import asyncio
import base64
import ipaddress
import socket
from urllib.parse import urlsplit
from uuid import UUID
from functools import partial
from typing import Literal

import httpx2 as httpx
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import APIRouter, Depends, HTTPException
from openai import AsyncOpenAI, APIConnectionError, APIStatusError, APITimeoutError
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_ai.exceptions import ModelHTTPError
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agent.errors import error_source_for, provider_http_error, recovery_action_for
from backend.agent.reasoning import ReasoningConfig, ReasoningCapability, builtin_capability, manual_capability, metadata_capability, validate_selection, create_model
from backend.config import settings, validate_proxy_url
from backend.db import get_db
from backend.deps import get_current_user
from backend.models import AgentLLMProfile, AgentUserSettings, AgentProxySettings, AgentWorkPreference, User
from backend.utils import utcnow


DEFAULT_BASE_URL = "https://api.openai.com/v1"
router = APIRouter(prefix="/agent/settings", tags=["agent"])


def config_error(code, message, status=422, *, source=None, upstream_status_code=None, upstream_error_code=None):
    detail = {
        "error_code": code,
        "error_source": source or error_source_for(code),
        "recovery_action": recovery_action_for(code),
        "message": message,
        "status_code": status,
    }
    if upstream_status_code is not None:
        detail["upstream_status_code"] = upstream_status_code
    if upstream_error_code is not None:
        detail["upstream_error_code"] = upstream_error_code
    return HTTPException(status, detail)


def validate_url(value):
    value = value.strip().rstrip("/")
    try:
        url = urlsplit(value)
        if (url.scheme != "https" or not url.hostname or url.username is not None
                or url.password is not None or url.query or url.fragment or "\\" in value
                or any(ord(c) < 33 for c in value) or url.port == 0):
            raise ValueError()
        if ":" in url.hostname or url.hostname.replace(".", "").isdigit():
            if not public_ip(url.hostname):
                raise ValueError()
    except ValueError:
        raise ValueError("Use a public HTTPS API base URL without credentials, query or fragment") from None
    return value


def public_ip(value):
    ip = ipaddress.ip_address(value)
    return (ip.is_global and not ip.is_multicast and not ip.is_reserved
            and not (isinstance(ip, ipaddress.IPv6Address) and (ip.ipv4_mapped or ip.sixtofour or ip.teredo)))


async def public_addresses(host, port):
    try:
        answers = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM), timeout=5)
    except (OSError, asyncio.TimeoutError):
        raise config_error("AGENT_DNS_ERROR", "Cannot resolve the API hostname", 502) from None
    addresses = list(dict.fromkeys(item[4][0] for item in answers))
    if not addresses or any(not public_ip(ip) for ip in addresses):
        raise config_error("AGENT_URL_BLOCKED", "Only public HTTPS API addresses are allowed")
    return addresses


class PublicAPITransport(httpx.AsyncBaseTransport):
    def __init__(self, proxy_url=None):
        self.proxy_url = allowed_proxy(proxy_url)
        self.transport = httpx.AsyncHTTPTransport(trust_env=False, retries=0,
            **({"proxy": self.proxy_url} if self.proxy_url else {}))

    async def handle_async_request(self, request):
        validate_url(str(request.url))
        if self.proxy_url:
            allowed_proxy(self.proxy_url)
            # Approved proxies resolve the original hostname so CONNECT retains TLS identity.
            return await self.transport.handle_async_request(request)
        addresses = await public_addresses(request.url.host, request.url.port or 443)
        # Pin the checked address while retaining the original Host and TLS identity.
        pinned = httpx.Request(request.method, request.url.copy_with(host=addresses[0]),
                               headers=request.headers, stream=request.stream,
                               extensions={**request.extensions, "sni_hostname": request.url.host})
        return await self.transport.handle_async_request(pinned)

    async def aclose(self):
        await self.transport.aclose()


def public_client(timeout=60, *, proxy_url=None):
    return httpx.AsyncClient(transport=PublicAPITransport(proxy_url), trust_env=False,
                            follow_redirects=False, timeout=timeout)


def allowed_proxy(value):
    if value is None:
        return None
    try:
        value = validate_proxy_url(value)
    except ValueError:
        raise config_error("AGENT_PROXY_INVALID", "Use an unauthenticated HTTP(S) proxy address") from None
    if value not in settings.agent_proxy_allowed_urls:
        raise config_error("AGENT_PROXY_NOT_ALLOWED", "The deployment administrator has not allowed this proxy address")
    return value


def personal_proxy(db, user_id):
    row = db.get(AgentProxySettings, user_id)
    return allowed_proxy(row.proxy_url) if row else None


MAX_WORK_PREFERENCES = 20


def list_work_preferences(db, user_id):
    rows = db.scalars(select(AgentWorkPreference).where(AgentWorkPreference.user_id == user_id)
        .order_by(AgentWorkPreference.created_at, AgentWorkPreference.id))
    return [{"id": str(row.id), "text": row.text} for row in rows]


def save_work_preferences(db, user_id, texts):
    """Add standing preferences for the user. Returns (saved, skipped): a text already stored counts as saved; the 20-item cap skips the rest."""
    db.scalar(select(User).where(User.id == user_id).with_for_update())
    known = {item["text"] for item in list_work_preferences(db, user_id)}
    saved, skipped = [], []
    for text in dict.fromkeys(item.strip()[:500] for item in texts if item.strip()):
        if text not in known and len(known) >= MAX_WORK_PREFERENCES:
            skipped.append(text)
            continue
        if text not in known:
            db.add(AgentWorkPreference(user_id=user_id, text=text))
            known.add(text)
        saved.append(text)
    db.flush()
    return saved, skipped


class AgentProxyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    proxy_url: str | None = Field(max_length=2048)


class AgentProxyOut(AgentProxyInput):
    allowed_proxy_urls: list[str]


@router.get("/proxy", response_model=AgentProxyOut)
def read_proxy(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.get(AgentProxySettings, user.id)
    return AgentProxyOut(proxy_url=row.proxy_url if row else None,
        allowed_proxy_urls=settings.agent_proxy_allowed_urls)


@router.put("/proxy", response_model=AgentProxyOut)
def save_proxy(data: AgentProxyInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    proxy_url = allowed_proxy(data.proxy_url)
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    row = db.get(AgentProxySettings, user.id)
    if row is None:
        row = AgentProxySettings(user_id=user.id)
        db.add(row)
    row.proxy_url = proxy_url
    db.commit()
    return read_proxy(db, user)


class WorkPreferenceOut(BaseModel):
    id: str
    text: str


@router.get("/preferences", response_model=list[WorkPreferenceOut])
def read_work_preferences(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return list_work_preferences(db, user.id)


@router.delete("/preferences/{preference_id}", status_code=204)
def delete_work_preference(preference_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.scalar(select(AgentWorkPreference).where(AgentWorkPreference.id == preference_id, AgentWorkPreference.user_id == user.id))
    if row is None:
        raise HTTPException(404, "Preference not found")
    db.delete(row)
    db.commit()


def key_cipher():
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
               info=b"genova-agent-api-key-v1").derive(settings.jwt_secret.encode())
    return Fernet(base64.urlsafe_b64encode(key))


class AgentSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)
    base_url: str = Field(default=DEFAULT_BASE_URL, min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=256)
    api_key: SecretStr | None = None
    profile_id: UUID | None = None
    profile_name: str | None = Field(default=None, min_length=1, max_length=80)
    auth_type: Literal["api_key", "chatgpt"] = "api_key"
    reasoning: ReasoningConfig | None = None
    context_window: int | None = Field(default=None, ge=16384, le=16777216, strict=True)

    @field_validator("base_url")
    @classmethod
    def check_url(cls, value):
        return validate_url(value)

    @model_validator(mode="after")
    def check_protocol(self):
        protocol = self.reasoning.api_protocol if self.reasoning else "auto"
        if self.auth_type == "chatgpt" and protocol == "chat_completions":
            raise ValueError("ChatGPT OAuth requires Responses")
        builtin_capability(self.base_url, self.model, protocol)
        return self


class AgentProfileOut(BaseModel):
    id: UUID
    name: str
    base_url: str
    model: str
    context_window: int | None = None
    has_api_key: bool
    auth_type: Literal["api_key", "chatgpt"] = "api_key"
    reasoning: ReasoningConfig | None = None
    connection_status: str | None = None
    account_label: str | None = None


class AgentSettingsOut(BaseModel):
    base_url: str = DEFAULT_BASE_URL
    model: str = ""
    context_window: int | None = None
    has_api_key: bool = False
    active_profile_id: UUID | None = None
    profiles: list[AgentProfileOut] = Field(default_factory=list)
    reasoning: ReasoningConfig | None = None


def selected_profile(data, db, user_id):
    if data.profile_id is None:
        return None
    profile = db.scalar(select(AgentLLMProfile).where(
        AgentLLMProfile.id == data.profile_id, AgentLLMProfile.user_id == user_id))
    if profile is None:
        raise config_error("AGENT_PROFILE_NOT_FOUND", "Saved API configuration not found", 404)
    return profile


def settings_out(db, user_id, row):
    from backend.agent.chatgpt_oauth import connection_info
    profiles = [AgentProfileOut(id=p.id, name=p.name, base_url=p.base_url, model=p.model, context_window=p.context_window,
        has_api_key=bool(p.encrypted_api_key), reasoning=p.reasoning, auth_type=p.auth_type,
        **(connection_info(p) if p.auth_type == "chatgpt" else {})) for p in db.scalars(select(AgentLLMProfile).where(
            AgentLLMProfile.user_id == user_id).order_by(AgentLLMProfile.updated_at.desc(), AgentLLMProfile.id))]
    return AgentSettingsOut(base_url=row.base_url, model=row.model, has_api_key=bool(row.encrypted_api_key), reasoning=row.reasoning,
        active_profile_id=row.active_profile_id, context_window=next((p.context_window for p in profiles if p.id == row.active_profile_id), None), profiles=profiles) if row else AgentSettingsOut(profiles=profiles)


def personal_config(db, user_id):
    row = db.get(AgentUserSettings, user_id)
    if row is None:
        raise config_error("AGENT_NOT_CONFIGURED", "Configure your Agent API in Settings", 503)
    profile = None
    if row.active_profile_id:
        profile = selected_profile(AgentSettingsInput(model=row.model, profile_id=row.active_profile_id), db, user_id)
        if profile.auth_type == "chatgpt":
            from backend.agent.chatgpt_oauth import access_token, connection_info
            info = connection_info(profile)
            if info["connection_status"] != "connected":
                raise config_error("AGENT_CHATGPT_AUTH_REQUIRED", "Authorize ChatGPT and allow plan usage in Settings", 503)
            return {"base_url": DEFAULT_BASE_URL, "model": row.model, "provider": "chatgpt",
                    "api_key": partial(access_token, user_id, profile.id), "reasoning": row.reasoning, "context_window": profile.context_window}
    try:
        secret = key_cipher().decrypt(row.encrypted_api_key.encode()).decode()
    except InvalidToken:
        raise config_error("AGENT_KEY_UNAVAILABLE", "Re-enter your Agent API key in Settings", 503) from None
    return {"base_url": row.base_url, "model": row.model, "api_key": secret, "reasoning": row.reasoning,
            "context_window": profile.context_window if profile else None}


def resolve_input(data, db, user_id):
    profile = selected_profile(data, db, user_id)
    row = profile if "profile_id" in data.model_fields_set else db.get(AgentUserSettings, user_id)
    if data.auth_type == "chatgpt":
        if profile is None or profile.auth_type != "chatgpt" or data.base_url != DEFAULT_BASE_URL or data.api_key is not None:
            raise config_error("AGENT_INVALID_SETTINGS", "Select an authorized ChatGPT configuration without an API key")
        from backend.agent.chatgpt_oauth import access_token
        return {"base_url": DEFAULT_BASE_URL, "model": data.model, "provider": "chatgpt",
                "api_key": partial(access_token, user_id, profile.id), "encrypted_api_key": None,
                "reasoning": data.reasoning.model_dump(mode="json") if data.reasoning else None}
    if (profile and profile.auth_type != "api_key") or (row and row.encrypted_api_key is None):
        raise config_error("AGENT_INVALID_SETTINGS", "Select the matching configuration type")
    secret = data.api_key.get_secret_value().strip() if data.api_key else ""
    if secret:
        if len(secret) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in secret):
            raise config_error("AGENT_INVALID_KEY", "API key contains invalid characters or is too long")
    else:
        if row is None or row.base_url != data.base_url:
            raise config_error("AGENT_KEY_REQUIRED", "Enter an API key for this API base URL")
        try:
            secret = key_cipher().decrypt(row.encrypted_api_key.encode()).decode()
        except InvalidToken:
            raise config_error("AGENT_KEY_UNAVAILABLE", "Re-enter your Agent API key in Settings", 503) from None
    return {"base_url": data.base_url, "model": data.model, "api_key": secret,
        "reasoning": data.reasoning.model_dump(mode="json") if data.reasoning else None,
        "encrypted_api_key": key_cipher().encrypt(secret.encode()).decode() if data.api_key and data.api_key.get_secret_value().strip() else row.encrypted_api_key}


@router.get("", response_model=AgentSettingsOut)
def read_settings(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.get(AgentUserSettings, user.id)
    return settings_out(db, user.id, row)


async def resolve_capability(data, db, user_id, *, fetch_metadata=True, secret=None):
    options = data.reasoning or ReasoningConfig()
    capability = builtin_capability(data.base_url, data.model, options.api_protocol)
    if options.manual:
        if capability.source == "builtin":
            raise config_error("AGENT_INVALID_SETTINGS", "Official model capabilities cannot be overridden manually")
        try:
            return manual_capability(options.manual, "responses" if data.auth_type == "chatgpt" else options.api_protocol)
        except ValueError as exc:
            raise config_error("AGENT_INVALID_SETTINGS", str(exc)) from None
    if data.auth_type == "chatgpt":
        capability = capability.model_copy(update={"protocol": "responses", "supported_protocols": ["responses"]})
    if not fetch_metadata:
        return capability
    if secret is None:
        try:
            secret = resolve_input(data, db, user_id)["api_key"]
        except HTTPException as exc:
            if exc.detail["error_code"] != "AGENT_KEY_REQUIRED":
                raise
            return capability
    if callable(secret):
        secret = await secret()
    try:
        async with public_client(10, proxy_url=personal_proxy(db, user_id)) as client:
            response = await client.get(data.base_url + "/models", headers={"Authorization": "Bearer " + secret})
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = {}
            code, _, _ = provider_http_error(response.status_code, body)
            return capability.model_copy(update={"warning": code})
        return metadata_capability(response.json(), data.model, capability)
    except HTTPException:
        raise
    except httpx.TimeoutException:
        return capability.model_copy(update={"warning": "AGENT_CONNECTION_TIMEOUT"})
    except httpx.RequestError:
        return capability.model_copy(update={"warning": "AGENT_CONNECTION_ERROR"})
    except (ValueError, KeyError, TypeError):
        return capability.model_copy(update={"warning": "AGENT_INVALID_SETTINGS"})


@router.post("/capabilities", response_model=ReasoningCapability)
async def read_capability(data: AgentSettingsInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    selected_profile(data, db, user.id)
    return await resolve_capability(data, db, user.id)


async def prepare_reasoning(data, config, db, user_id):
    if data.reasoning is None:
        data = data.model_copy(update={"reasoning": ReasoningConfig()})
    profile = selected_profile(data, db, user_id)
    stored = ReasoningConfig.model_validate(profile.reasoning) if profile and profile.reasoning else None
    # Only a server-stored snapshot can avoid revalidation; never trust one supplied by a client.
    if (stored and stored.capability and stored.capability.context_window and profile.base_url == data.base_url and profile.model == data.model
            and stored.api_protocol == data.reasoning.api_protocol and stored.manual == data.reasoning.manual
            and stored.capability == data.reasoning.capability and not (data.api_key and data.api_key.get_secret_value().strip())):
        capability = stored.capability
    else:
        capability = await resolve_capability(data, db, user_id,
            fetch_metadata=True,
            secret=config["api_key"])
    try:
        validated = validate_selection(data.reasoning, capability, data.base_url, data.model)
    except ValueError as exc:
        raise config_error("AGENT_INVALID_SETTINGS", str(exc)) from None
    config["reasoning"] = validated.model_dump(mode="json")
    config["context_window"] = capability.context_window or data.context_window


@router.put("", response_model=AgentSettingsOut)
async def save_settings(data: AgentSettingsInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if data.auth_type == "chatgpt":
        resolve_input(data, db, user.id)
        from backend.agent.chatgpt_oauth import models_for
        available = await models_for(user.id, data.profile_id)
        if data.model not in {item["slug"] for item in available}:
            raise config_error("AGENT_MODEL_NOT_FOUND", "Select a model available to this ChatGPT account", 404)
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    config = resolve_input(data, db, user.id)
    await prepare_reasoning(data, config, db, user.id)
    url = urlsplit(config["base_url"])
    if not personal_proxy(db, user.id):
        await public_addresses(url.hostname, url.port or 443)
    row = db.get(AgentUserSettings, user.id)
    profile = selected_profile(data, db, user.id)
    if "profile_id" not in data.model_fields_set and row and row.base_url == data.base_url and row.active_profile_id:
        profile = db.get(AgentLLMProfile, row.active_profile_id)
    if profile is None:
        profile = AgentLLMProfile(user_id=user.id, name=data.profile_name or url.hostname[:80])
        db.add(profile)
    elif data.profile_name is not None:
        profile.name = data.profile_name
    profile.updated_at = utcnow()
    profile.base_url, profile.model = config["base_url"], config["model"]
    profile.encrypted_api_key = config["encrypted_api_key"]
    profile.reasoning = config["reasoning"]
    profile.context_window = config["context_window"]
    db.flush()
    if row is None:
        row = AgentUserSettings(user_id=user.id)
        db.add(row)
    row.base_url, row.model = config["base_url"], config["model"]
    row.encrypted_api_key = profile.encrypted_api_key
    row.reasoning = profile.reasoning
    row.active_profile_id = profile.id
    db.commit()
    return settings_out(db, user.id, row)


@router.delete("", status_code=204)
async def clear_settings(profile_id: UUID | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.get(AgentUserSettings, user.id)
    target = profile_id or (row.active_profile_id if row else None)
    if target:
        profile = selected_profile(AgentSettingsInput(model="delete", profile_id=target), db, user.id)
        if profile.auth_type == "chatgpt":
            from backend.agent.chatgpt_oauth import disconnect_profile
            if not await disconnect_profile(profile, db):
                raise config_error("AGENT_CONNECTION_ERROR", "Tokens cleared locally; remote revocation was not confirmed. Disconnect in ChatGPT Settings before deleting", 502)
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    if target:
        db.delete(profile)
    if row is not None and (profile_id is None or row.active_profile_id == target):
        db.delete(row)
    db.commit()


@router.post("/test")
async def test_connection(data: AgentSettingsInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    config = resolve_input(data, db, user.id)
    await prepare_reasoning(data, config, db, user.id)
    try:
        from pydantic_ai.messages import ModelRequest, UserPromptPart
        from pydantic_ai.models import ModelRequestParameters
        from backend.agent.runner import Budget
        async with public_client(60, proxy_url=personal_proxy(db, user.id)) as client:
            if data.auth_type == "chatgpt":
                from backend.agent.chatgpt_model import ChatGPTResponsesModel
                model = ChatGPTResponsesModel(config["model"], config["api_key"], client, config["reasoning"])
            else:
                model = create_model(config["model"], config["api_key"], config["base_url"], client, config["reasoning"])
            response = await asyncio.wait_for(model.request([ModelRequest(parts=[UserPromptPart("Reply with OK.")])],
                {"max_tokens": Budget().request_output}, ModelRequestParameters()), timeout=60)
            if not response.parts:
                raise config_error("AGENT_MODEL_OUTPUT_INVALID", "The API returned no completion", 502, source="model_output")
    except HTTPException:
        raise
    except (asyncio.TimeoutError, APITimeoutError):
        raise config_error("AGENT_CONNECTION_TIMEOUT", "API connection timed out", 504, source="provider_api") from None
    except (APIStatusError, ModelHTTPError) as exc:
        code, message, upstream_code = provider_http_error(exc.status_code, getattr(exc, "body", getattr(exc, "response", None)))
        raise config_error(
            code,
            message,
            exc.status_code if 400 <= exc.status_code <= 599 else 502,
            source="provider_api",
            upstream_status_code=exc.status_code,
            upstream_error_code=upstream_code,
        ) from None
    except APIConnectionError:
        raise config_error(
            "AGENT_CONNECTION_ERROR",
            "Cannot connect to the configured API",
            502,
            source="provider_api",
        ) from None
    except Exception:
        raise config_error(
            "AGENT_INTERNAL_ERROR",
            "An unexpected backend error occurred while testing the Agent API configuration",
            500,
            source="internal",
        ) from None
    return {"ok": True}
