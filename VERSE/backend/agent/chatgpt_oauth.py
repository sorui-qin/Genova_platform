import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
import uuid
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx2 as httpx
import jwt
from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from backend.agent.user_settings import config_error, key_cipher, personal_proxy, public_client, selected_profile, AgentSettingsInput
from backend.config import settings
from backend.db import get_db, SessionLocal
from backend.deps import get_current_user
from backend.models import AgentLLMProfile, User
from backend.realtime import get_async_redis_client

ISSUER = "https://auth.openai.com"
AUTHORIZE_URL = ISSUER + "/api/accounts/authorize"
TOKEN_URL = ISSUER + "/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"
CALLBACK_URL = "http://127.0.0.1:18000/api/v1/agent/settings/chatgpt/callback"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_SCOPES = {"resource.invoke", "chatgpt.tokens.use.direct"}
TTL = 600
router = APIRouter(prefix="/agent/settings/chatgpt", tags=["agent"])
_discovery = None
_discovery_at = 0


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: uuid.UUID | None = None
    mode: Literal["local", "manual"] = "local"


class CompleteLoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attempt_id: uuid.UUID
    callback_url: str = Field(min_length=1, max_length=16384)


def credentials(profile):
    if not profile.encrypted_oauth_credentials:
        return {}
    try:
        return json.loads(key_cipher().decrypt(profile.encrypted_oauth_credentials.encode()))
    except InvalidToken:
        raise config_error("AGENT_CHATGPT_AUTH_REQUIRED", "Authorize ChatGPT again in Settings", 503) from None


def save_credentials(profile, value):
    profile.encrypted_oauth_credentials = key_cipher().encrypt(json.dumps(value).encode()).decode()


def connection_info(profile):
    try:
        value = credentials(profile)
    except HTTPException:
        return {"connection_status": "reauthorization_required", "account_label": None}
    connected = bool(value.get("access_token") and value.get("refresh_token"))
    return {"connection_status": "connected" if connected and PLAN_SCOPES <= set(value.get("scopes", []))
            else "plan_required" if connected else "disconnected",
            "account_label": value.get("email")}


def host_id():
    import fcntl
    directory = settings.data_root / ".auth"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(directory / "chatgpt-host-id", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "r+") as file:
        fcntl.flock(file, fcntl.LOCK_EX)
        value = file.read().strip()
        if not value:
            value = "urn:uuid:" + str(uuid.uuid4())
            file.write(value)
            file.flush()
        return value


def owned_profile(db, user_id, profile_id):
    profile = selected_profile(AgentSettingsInput(model="chatgpt", profile_id=profile_id), db, user_id)
    if profile.auth_type != "chatgpt":
        raise config_error("AGENT_INVALID_SETTINGS", "Select a ChatGPT configuration")
    return profile


async def discovery(*, proxy_url=None):
    global _discovery, _discovery_at
    if _discovery is None or time.time() - _discovery_at > 3600:
        value = await oauth_request("GET", ISSUER + "/.well-known/openid-configuration", proxy_url=proxy_url)
        if value.get("issuer") != ISSUER:
            raise config_error("AGENT_CHATGPT_OAUTH_INVALID", "Invalid OpenAI issuer", 502)
        for name in ("jwks_uri", "revocation_endpoint"):
            url = urlsplit(value[name])
            if url.scheme != "https" or url.hostname != "auth.openai.com":
                raise config_error("AGENT_CHATGPT_OAUTH_INVALID", "Invalid OpenAI endpoint", 502)
        _discovery, _discovery_at = value, time.time()
    return _discovery


async def oauth_request(method, url, *, data=None, token=None, proxy_url=None):
    try:
        async with public_client(20, proxy_url=proxy_url) as client:
            response = await client.request(method, url, data=data,
                headers={"Authorization": "Bearer " + token} if token else None)
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = {}
            error = body.get("error") if isinstance(body, dict) else None
            upstream_code = error.get("code") if isinstance(error, dict) else error
            if response.status_code == 401 or upstream_code in {"invalid_grant", "invalid_client", "invalid_token", "unauthorized_client"}:
                raise config_error("AGENT_CHATGPT_AUTH_REQUIRED", "ChatGPT rejected authorization; sign in again", 503)
            from backend.agent.errors import provider_http_error
            code, message, upstream = provider_http_error(response.status_code, body)
            raise config_error(code, message, response.status_code, upstream_error_code=upstream)
        return response.json() if response.content else {}
    except httpx.TimeoutException:
        raise config_error("AGENT_CONNECTION_TIMEOUT", "OpenAI connection timed out", 504) from None
    except httpx.RequestError:
        raise config_error("AGENT_CONNECTION_ERROR", "Cannot connect to OpenAI", 502) from None
    except (ValueError, KeyError):
        raise config_error("AGENT_CHATGPT_OAUTH_INVALID", "Invalid OpenAI authorization response", 502) from None


async def validate_identity(tokens, client_id, nonce, *, proxy_url=None):
    metadata = await discovery(proxy_url=proxy_url)
    keys = await oauth_request("GET", metadata["jwks_uri"], proxy_url=proxy_url)
    try:
        header = jwt.get_unverified_header(tokens["id_token"])
        if header.get("alg") != "RS256":
            raise ValueError()
        key = next(item for item in keys["keys"] if item.get("kid") == header.get("kid"))
        identity = jwt.decode(tokens["id_token"], jwt.PyJWK.from_dict(key).key,
            algorithms=["RS256"], audience=client_id, issuer=ISSUER,
            options={"require": ["iss", "aud", "exp", "sub", "nonce"]})
        if not secrets.compare_digest(identity["nonce"], nonce):
            raise ValueError()
        return identity
    except (jwt.PyJWTError, KeyError, ValueError, TypeError, StopIteration):
        raise config_error("AGENT_CHATGPT_OAUTH_INVALID", "ChatGPT identity validation failed", 400) from None


def token_record(tokens, previous):
    try:
        if tokens["token_type"].lower() != "bearer" or not tokens["access_token"] or not tokens["refresh_token"]:
            raise ValueError()
        expires = int(tokens["expires_in"])
        if expires <= 0:
            raise ValueError()
        value = {**previous, "access_token": tokens["access_token"], "refresh_token": tokens["refresh_token"],
            "expires_at": time.time() + expires,
            "scopes": tokens["scope"].split() if "scope" in tokens else previous["scopes"]}
        if tokens.get("id_token"):
            value["id_token"] = tokens["id_token"]
        return value
    except (KeyError, ValueError, TypeError, AttributeError):
        raise config_error("AGENT_CHATGPT_OAUTH_INVALID", "Incomplete OpenAI token response", 502) from None


async def access_token(user_id, profile_id):
    async with get_async_redis_client() as redis:
        async with redis.lock("genova:chatgpt:credentials:" + str(profile_id), timeout=60, blocking_timeout=25):
            with SessionLocal() as db:
                profile = owned_profile(db, user_id, profile_id)
                value = credentials(profile)
                if not value.get("refresh_token") or not value.get("access_token"):
                    raise config_error("AGENT_CHATGPT_AUTH_REQUIRED", "Authorize ChatGPT in Settings", 503)
                if not PLAN_SCOPES <= set(value.get("scopes", [])):
                    raise config_error("AGENT_CHATGPT_PLAN_REQUIRED", "Allow this app to use your ChatGPT plan", 403)
                if value["expires_at"] - time.time() <= 300:
                    try:
                        tokens = await oauth_request("POST", TOKEN_URL, data={"grant_type": "refresh_token",
                            "client_id": value["client_id"], "refresh_token": value["refresh_token"], "resource": RESOURCE},
                            proxy_url=personal_proxy(db, user_id))
                    except HTTPException as exc:
                        if exc.detail["error_code"] == "AGENT_CHATGPT_AUTH_REQUIRED":
                            for key in ("access_token", "refresh_token", "id_token"):
                                value.pop(key, None)
                            save_credentials(profile, value)
                            db.commit()
                        raise
                    value = token_record(tokens, value)
                    save_credentials(profile, value)
                    db.commit()
                    if not PLAN_SCOPES <= set(value["scopes"]):
                        raise config_error("AGENT_CHATGPT_PLAN_REQUIRED", "Allow this app to use your ChatGPT plan", 403)
                return value["access_token"]


async def models_for(user_id, profile_id):
    with SessionLocal() as db:
        proxy_url = personal_proxy(db, user_id)
    value = await oauth_request("GET", RESOURCE + "/models", token=await access_token(user_id, profile_id), proxy_url=proxy_url)
    try:
        return [{"slug": item["slug"], "display_name": item["display_name"]}
                for item in value["models"] if item.get("visibility") == "list"]
    except (KeyError, TypeError):
        raise config_error("AGENT_MODEL_OUTPUT_INVALID", "Invalid ChatGPT model catalog", 502) from None


def require_manual_origin(request):
    try:
        configured = urlsplit(settings.public_base_url)
        configured.port
    except ValueError:
        raise config_error("AGENT_INVALID_SETTINGS", "Configure a valid HTTP(S) platform address", 400) from None
    if (configured.scheme not in {"http", "https"} or not configured.hostname or configured.username or configured.password
            or configured.query or configured.fragment
            or request.headers.get("origin") != f"{configured.scheme}://{configured.netloc}"):
        raise config_error("AGENT_INVALID_SETTINGS", "Remote ChatGPT authorization requires the configured HTTP(S) platform address", 400)


@router.post("/start")
async def start_login(data: LoginInput, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if data.mode == "manual":
        require_manual_origin(request)
    elif request.url.hostname not in {"127.0.0.1", "localhost", "testserver"}:
        raise config_error("AGENT_INVALID_SETTINGS", "ChatGPT authorization requires same-machine loopback access")
    value = credentials(owned_profile(db, user.id, data.profile_id)) if data.profile_id else {}
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    attempt_id = str(uuid.uuid4())
    pending = {"user_id": str(user.id), "profile_id": str(data.profile_id) if data.profile_id else None,
        "state": state, "nonce": nonce, "verifier": verifier, "attempt_id": attempt_id, "mode": data.mode,
        "client_id": value.get("client_id"), "subject": value.get("subject"), "redirect_uri": CALLBACK_URL,
        "proxy_url": personal_proxy(db, user.id)}
    async with get_async_redis_client() as redis:
        await redis.set("genova:chatgpt:pending:" + state, key_cipher().encrypt(json.dumps(pending).encode()).decode(), ex=TTL)
        await redis.set("genova:chatgpt:attempt:" + attempt_id,
            json.dumps({"user_id": str(user.id), "status": "pending"}), ex=TTL)
    params = {"client_id": value.get("client_id") or "dynamic_agent_client", "ext_agent_host_id": await asyncio.to_thread(host_id),
        "response_type": "code", "redirect_uri": CALLBACK_URL, "scope": SCOPES, "resource": RESOURCE,
        "state": state, "nonce": nonce, "code_challenge_method": "S256",
        "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")}
    if not value.get("client_id"):
        params["agent_name_hint"] = "Genova"
    # Keep authorization URLs free of retained ID tokens, which access logs could expose.
    return {"attempt_id": attempt_id, "authorization_url": AUTHORIZE_URL + "?" + urlencode(params)}


@router.get("/status/{attempt_id}")
async def login_status(attempt_id: uuid.UUID, user: User = Depends(get_current_user)):
    async with get_async_redis_client() as redis:
        raw = await redis.get("genova:chatgpt:attempt:" + str(attempt_id))
    if not raw:
        return {"status": "expired"}
    value = json.loads(raw)
    if value.pop("user_id") != str(user.id):
        raise config_error("AGENT_PROFILE_NOT_FOUND", "Authorization attempt not found", 404)
    return value


async def complete_authorization(pending, query, db, redis):
    result = {"user_id": pending["user_id"], "status": "failed"}
    try:
        if not secrets.compare_digest(query.get("state", ""), pending["state"]) or query.get("error"):
            raise config_error("AGENT_CHATGPT_OAUTH_INVALID", "ChatGPT authorization was canceled or rejected", 400)
        client_id = query.get("client_id") or pending["client_id"]
        if not client_id or client_id == "dynamic_agent_client" or (pending["client_id"] and client_id != pending["client_id"]):
            raise config_error("AGENT_CHATGPT_OAUTH_INVALID", "ChatGPT client registration did not match", 400)
        code = query.get("code")
        if not code or len(code) > 8192:
            raise config_error("AGENT_CHATGPT_OAUTH_INVALID", "Missing authorization code", 400)
        tokens = await oauth_request("POST", TOKEN_URL, data={"grant_type": "authorization_code", "client_id": client_id,
            "code": code, "code_verifier": pending["verifier"], "redirect_uri": pending["redirect_uri"], "resource": RESOURCE},
            proxy_url=pending["proxy_url"])
        identity = await validate_identity(tokens, client_id, pending["nonce"], proxy_url=pending["proxy_url"])
        if pending["subject"] and identity["sub"] != pending["subject"]:
            raise config_error("AGENT_CHATGPT_OAUTH_INVALID", "ChatGPT account did not match the selected configuration", 400)
        user_id = uuid.UUID(pending["user_id"])
        user = db.get(User, user_id)
        if not user or not user.is_active:
            raise config_error("AGENT_CHATGPT_OAUTH_INVALID", "Genova account is unavailable", 400)
        profile_id = pending["profile_id"] or str(uuid.uuid4())
        async with redis.lock("genova:chatgpt:credentials:" + profile_id, timeout=60, blocking_timeout=25):
            profile = owned_profile(db, user_id, uuid.UUID(profile_id)) if pending["profile_id"] else AgentLLMProfile(
                id=uuid.UUID(profile_id), user_id=user_id, name="ChatGPT · " + identity.get("email", "Account")[:54] + " · " + profile_id[:6],
                base_url=RESOURCE, model="", auth_type="chatgpt")
            value = token_record(tokens, {"client_id": client_id, "subject": identity["sub"], "issuer": ISSUER,
                "email": identity.get("email"), "scopes": []})
            save_credentials(profile, value)
            db.add(profile)
            db.commit()
        result.update(status="succeeded", profile_id=profile_id,
            connection_status="connected" if PLAN_SCOPES <= set(value["scopes"]) else "plan_required")
    except HTTPException as exc:
        db.rollback()
        result["error_code"] = exc.detail["error_code"]
    finally:
        await redis.set("genova:chatgpt:attempt:" + pending["attempt_id"], json.dumps(result), ex=TTL)
    return result


@router.get("/callback", response_class=HTMLResponse)
async def callback(request: Request, db: Session = Depends(get_db)):
    query = request.query_params
    request.scope["query_string"] = b""  # Do not put authorization codes in access logs.
    state = query.get("state", "")
    async with get_async_redis_client() as redis:
        raw = await redis.getdel("genova:chatgpt:pending:" + state) if len(state) <= 128 else None
        if not raw:
            return HTMLResponse("<p>Authorization expired or already used. Return to Genova Settings.</p>", status_code=400,
                headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
        pending = json.loads(key_cipher().decrypt(raw.encode()))
        result = await complete_authorization(pending, query, db, redis)
    message = "Authorization completed. Return to Genova Settings to select a model and save." if result["status"] == "succeeded" else (
        "Authorization failed (" + result["error_code"] + "). Return to Genova Settings to view the error.")
    return HTMLResponse("<p>" + message + "</p>",
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.post("/complete")
async def complete_login(data: CompleteLoginInput, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_manual_origin(request)
    pasted = data.callback_url.strip()
    expected = urlsplit(CALLBACK_URL)
    try:
        address = urlsplit(pasted)
        pairs = parse_qsl(address.query, keep_blank_values=True, max_num_fields=20)
        query = dict(pairs)
        if (any(ord(ch) < 33 for ch in pasted) or address.fragment
                or (address.scheme, address.netloc, address.path) != (expected.scheme, expected.netloc, expected.path)
                or any(sum(key == field for key, _ in pairs) > 1 for field in ("state", "code", "client_id", "error"))
                or not query.get("state") or len(query["state"]) > 128
                or (not query.get("error") and (not query.get("code") or len(query["code"]) > 8192))):
            raise ValueError()
    except ValueError:
        raise config_error("AGENT_CHATGPT_OAUTH_INVALID", "Paste the complete callback address from this authorization window", 400) from None
    async with get_async_redis_client() as redis:
        attempt = await redis.get("genova:chatgpt:attempt:" + str(data.attempt_id))
        if not attempt or json.loads(attempt)["user_id"] != str(user.id):
            raise config_error("AGENT_PROFILE_NOT_FOUND", "Authorization attempt not found or expired", 404)
        key = "genova:chatgpt:pending:" + query["state"]
        raw = await redis.get(key)
        if not raw:
            raise config_error("AGENT_CHATGPT_OAUTH_INVALID", "Authorization expired or already used; start again", 400)
        pending = json.loads(key_cipher().decrypt(raw.encode()))
        if (pending["user_id"] != str(user.id) or pending["attempt_id"] != str(data.attempt_id)
                or pending["mode"] != "manual" or pending["redirect_uri"] != CALLBACK_URL
                or not secrets.compare_digest(query["state"], pending["state"])):
            raise config_error("AGENT_CHATGPT_OAUTH_INVALID", "Callback does not match this authorization attempt", 400)
        client_id = query.get("client_id") or pending["client_id"]
        if not query.get("error") and (not client_id or client_id == "dynamic_agent_client"
                or (pending["client_id"] and client_id != pending["client_id"])):
            raise config_error("AGENT_CHATGPT_OAUTH_INVALID", "Paste the complete callback address for the selected ChatGPT account", 400)
        if not await redis.getdel(key):
            raise config_error("AGENT_CHATGPT_OAUTH_INVALID", "Authorization expired or already used; start again", 400)
        result = await complete_authorization(pending, query, db, redis)
    return {key: value for key, value in result.items() if key != "user_id"}


@router.get("/models")
async def list_models(profile_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    owned_profile(db, user.id, profile_id)
    return {"models": await models_for(user.id, profile_id)}


async def disconnect_profile(profile, db):
    async with get_async_redis_client() as redis:
        async with redis.lock("genova:chatgpt:credentials:" + str(profile.id), timeout=60, blocking_timeout=25):
            db.refresh(profile)
            value = credentials(profile)
            revoked = True
            if value.get("refresh_token"):
                try:
                    proxy_url = personal_proxy(db, profile.user_id)
                    metadata = await discovery(proxy_url=proxy_url)
                    await oauth_request("POST", metadata["revocation_endpoint"], data={"token": value["refresh_token"],
                        "token_type_hint": "refresh_token", "client_id": value["client_id"]}, proxy_url=proxy_url)
                except HTTPException:
                    revoked = False
            for key in ("access_token", "refresh_token", "id_token"):
                value.pop(key, None)
            save_credentials(profile, value)
            db.commit()
            return revoked


@router.post("/disconnect")
async def disconnect(data: LoginInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if data.profile_id is None:
        raise config_error("AGENT_INVALID_SETTINGS", "Select a ChatGPT configuration")
    return {"revocation_confirmed": await disconnect_profile(owned_profile(db, user.id, data.profile_id), db)}
