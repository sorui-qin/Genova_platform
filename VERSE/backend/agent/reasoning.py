from typing import Annotated, Literal
from urllib.parse import urlsplit

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider


Effort = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")]
Protocol = Literal["auto", "chat_completions", "responses"]


class ReasoningSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    effort: Effort | None = None
    thinking: bool | None = Field(default=None, strict=True)
    budget_tokens: int | None = Field(default=None, ge=1, le=1_000_000, strict=True)


class ReasoningDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    effort_parameter: Literal["reasoning_effort", "reasoning.effort"] | None = None
    effort_levels: list[Effort] = Field(default_factory=list, max_length=16)
    default_effort: Effort | None = None
    thinking_parameter: Literal["thinking.type", "enable_thinking"] | None = None
    can_disable: bool = True
    budget_parameter: Literal["thinking_budget"] | None = None
    budget_min: int = Field(default=1, ge=1, le=1_000_000, strict=True)
    budget_max: int | None = Field(default=None, ge=1, le=1_000_000, strict=True)
    exclusive_effort_budget: bool = True

    @model_validator(mode="after")
    def check_controls(self):
        if bool(self.effort_parameter) != bool(self.effort_levels):
            raise ValueError("Declare both the effort parameter and its supported values")
        if len(self.effort_levels) != len(set(self.effort_levels)):
            raise ValueError("Effort values must be unique")
        if self.default_effort is not None and self.default_effort not in self.effort_levels:
            raise ValueError("Default effort must be a supported value")
        if self.budget_max is not None and self.budget_min > self.budget_max:
            raise ValueError("Minimum thinking budget exceeds maximum")
        if not self.can_disable and "none" in self.effort_levels:
            raise ValueError("A thinking-only model cannot support none effort")
        return self


class ReasoningCapability(ReasoningDeclaration):
    context_window: int | None = Field(default=None, ge=16384, le=16777216, strict=True)
    protocol: Literal["chat_completions", "responses"] = "chat_completions"
    source: Literal["metadata", "builtin", "user", "unknown"] = "unknown"
    warning: str | None = None
    manual_allowed: bool = True
    supported_protocols: list[Literal["chat_completions", "responses"]] = Field(default_factory=lambda: ["chat_completions", "responses"])


class ReasoningConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_protocol: Protocol = "auto"
    selection: ReasoningSelection = Field(default_factory=ReasoningSelection)
    manual: ReasoningDeclaration | None = None
    capability: ReasoningCapability | None = None


def builtin_capability(base_url, model, protocol="auto"):
    url = urlsplit(base_url)
    host, path = url.hostname or "", url.path.rstrip("/")
    values = {}
    preferred = "chat_completions"
    if host == "api.deepseek.com" and path in {"", "/v1"} and model in {"deepseek-flash", "deepseek-v4-pro"}:
        values = dict(effort_levels=["none", "low", "high", "max"], default_effort="high")
    elif host == "api.openai.com" and path == "/v1" and model == "gpt-6-luna":
        preferred = "responses"
        values = dict(effort_levels=["none", "low", "medium", "high", "xhigh", "max"], default_effort="medium")
    elif (host == "dashscope.aliyuncs.com" or host.endswith(".maas.aliyuncs.com")) and path == "/compatible-mode/v1" and model in {
            "qwen3.8-max", "qwen3.8-max-0902", "qwen3.8-flash", "qwen3.6-plus", "qwen3.5-plus"}:
        preferred = "responses" if model.startswith("qwen3.8-") else "chat_completions"
        if model.startswith("qwen3.8-") and protocol != "chat_completions":
            values = dict(effort_levels=["none", "low", "medium", "xhigh"], default_effort="xhigh")
        else:
            values = dict(thinking_parameter="enable_thinking", budget_parameter="thinking_budget")
    elif host in {"open.bigmodel.cn", "api.z.ai"} and path in {"/api/paas/v4", "/api/coding/paas/v4"} and model in {"glm-5.3", "glm-5.3-flash"}:
        values = dict(effort_levels=["low", "high", "max"], default_effort="max", can_disable=False)
    elif host in {"open.bigmodel.cn", "api.z.ai"} and path in {"/api/paas/v4", "/api/coding/paas/v4"} and model in {"glm-4.7", "glm-5", "glm-5.1"}:
        values = dict(thinking_parameter="thinking.type")
    resolved = preferred if protocol == "auto" else protocol
    if host in {"open.bigmodel.cn", "api.z.ai"} and values:
        values["supported_protocols"] = ["chat_completions"]
        if resolved != "chat_completions":
            raise ValueError("This GLM endpoint requires Chat Completions")
    if values.get("effort_levels"):
        values["effort_parameter"] = "reasoning.effort" if resolved == "responses" else "reasoning_effort"
    if values.get("budget_parameter"):
        from backend.agent.runner import Budget
        values["budget_max"] = Budget().request_output
    return ReasoningCapability(protocol=resolved, source="builtin" if values else "unknown", manual_allowed=not bool(values), **values)


def manual_capability(declaration, protocol):
    if protocol == "auto":
        protocol = "responses" if declaration.effort_parameter == "reasoning.effort" else "chat_completions"
    expected = "reasoning.effort" if protocol == "responses" else "reasoning_effort"
    if declaration.effort_parameter and declaration.effort_parameter != expected:
        raise ValueError("Effort parameter does not match the selected API protocol")
    values = declaration.model_dump()
    if declaration.budget_parameter:
        from backend.agent.runner import Budget
        values["budget_max"] = min(declaration.budget_max or Budget().request_output, Budget().request_output)
        if values["budget_min"] > values["budget_max"]:
            raise ValueError("Declared thinking budget does not fit the platform request budget")
    return ReasoningCapability(**values, protocol=protocol, source="user")


def metadata_capability(body, model, fallback):
    if not isinstance(body, dict):
        raise ValueError("Model list must be an object")
    rows = body.get("data", body.get("models", []))
    if not isinstance(rows, list):
        raise ValueError("Model list must contain an array")
    item = next((r for r in rows if isinstance(r, dict) and (r.get("id") or r.get("slug")) == model), None)
    if item is None:
        return fallback
    window = item.get("context_window")
    if window is not None:
        fallback = ReasoningCapability.model_validate({**fallback.model_dump(), "context_window": window})
    effort = item.get("effort")
    if isinstance(effort, dict) and "supported_levels" in effort:
        levels, default = effort["supported_levels"], effort.get("default_level")
        # DeepSeek lists only enabled-thinking levels; its documented none switch remains available.
        if isinstance(levels, list) and "none" in fallback.effort_levels and "none" not in levels:
            levels = ["none", *levels]
    elif "supported_reasoning_levels" in item:
        levels = [r["effort"] for r in item["supported_reasoning_levels"]]
        default = item.get("default_reasoning_level")
    else:
        return fallback
    result = fallback.model_dump()
    result.update(effort_parameter="reasoning.effort" if fallback.protocol == "responses" else "reasoning_effort",
                  effort_levels=levels, default_effort=default, source="metadata")
    return ReasoningCapability.model_validate(result)


def validate_selection(config, capability, base_url, model):
    selection = config.selection
    if selection.effort is not None and selection.effort not in capability.effort_levels:
        raise ValueError("Selected reasoning effort is not supported by this endpoint and model")
    if selection.thinking is not None and not capability.thinking_parameter:
        raise ValueError("This model does not expose a thinking toggle")
    if selection.thinking is False and not capability.can_disable:
        raise ValueError("Thinking cannot be disabled for this model")
    if selection.budget_tokens is not None:
        if not capability.budget_parameter:
            raise ValueError("This model does not expose a thinking budget")
        if selection.budget_tokens < capability.budget_min or (capability.budget_max is not None and
                selection.budget_tokens > capability.budget_max):
            raise ValueError(f"Thinking budget must be between {capability.budget_min} and {capability.budget_max or 1_000_000} tokens (model and platform limits)")
    if capability.exclusive_effort_budget and selection.effort is not None and selection.budget_tokens is not None:
        raise ValueError("Reasoning effort and thinking budget cannot be set together")
    if selection.thinking is False and (selection.budget_tokens is not None or selection.effort not in {None, "none"}):
        raise ValueError("Disabled thinking conflicts with reasoning effort or budget")
    if selection.thinking is True and selection.effort == "none":
        raise ValueError("Enabled thinking conflicts with none reasoning effort")
    if urlsplit(base_url).hostname == "api.openai.com" and model == "gpt-6-luna" and capability.protocol == "chat_completions":
        if selection.effort != "none":
            raise ValueError("GPT-6 Luna needs Responses for reasoning with tools; Chat Completions requires none")
    return config.model_copy(update={"capability": capability})


def request_settings(reasoning):
    if not reasoning:
        return {}
    config = ReasoningConfig.model_validate(reasoning)
    selection, capability = config.selection, config.capability
    if capability is None:
        if any(value is not None for value in selection.model_dump().values()):
            raise ValueError("Reasoning selection requires a validated capability")
        return {}
    result, extra = {}, {}
    if selection.effort is not None:
        result["openai_reasoning_effort"] = selection.effort
    thinking = selection.thinking
    if selection.budget_tokens is not None:
        extra["thinking_budget"] = selection.budget_tokens
        if thinking is None and capability.thinking_parameter:
            thinking = True
    if thinking is not None:
        if capability.thinking_parameter == "thinking.type":
            extra["thinking"] = {"type": "enabled" if thinking else "disabled"}
        elif capability.thinking_parameter == "enable_thinking":
            extra["enable_thinking"] = thinking
    if extra:
        result["extra_body"] = extra
    return result


def create_model(model, api_key, base_url=None, http_client=None, reasoning=None, provider_name="openai-compatible"):
    if provider_name == "deepseek":
        base_url = base_url or "https://api.deepseek.com"
    host = urlsplit(base_url or "https://api.openai.com/v1").hostname
    config = ReasoningConfig.model_validate(reasoning) if reasoning else ReasoningConfig()
    capability = config.capability or builtin_capability(base_url or "https://api.openai.com/v1", model, config.api_protocol)
    options = {}
    params = request_settings(reasoning)
    if params:
        options["settings"] = params
    if capability.protocol == "chat_completions" and (provider_name == "deepseek" or host in {"api.deepseek.com", "open.bigmodel.cn", "api.z.ai", "dashscope.aliyuncs.com"}
            or (host and host.endswith(".maas.aliyuncs.com"))):
        options["profile"] = OpenAIModelProfile(openai_chat_supports_max_completion_tokens=False,
            openai_chat_thinking_field="reasoning_content", openai_chat_send_back_thinking_parts="field")
    elif capability.protocol == "chat_completions" and capability.source in {"metadata", "user"}:
        options["profile"] = OpenAIModelProfile(openai_chat_thinking_field="reasoning_content",
            openai_chat_send_back_thinking_parts="field")
    model_class = OpenAIResponsesModel if capability.protocol == "responses" else OpenAIChatModel
    provider = OpenAIProvider(openai_client=AsyncOpenAI(api_key=api_key, base_url=base_url,
        http_client=http_client, max_retries=0)) if http_client is not None else OpenAIProvider(api_key=api_key, base_url=base_url)
    return model_class(model, provider=provider, **options)
