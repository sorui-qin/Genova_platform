"""Stable Agent error contract shared by runtime, HTTP APIs, and UI."""
from __future__ import annotations

import re
from typing import Any, Literal

AgentErrorSource = Literal[
    "harness",
    "provider_api",
    "model_output",
    "workflow",
    "configuration",
    "domain",
    "internal",
]

RecoveryAction = Literal[
    "continue_turn",
    "revise_request",
    "check_api_key",
    "check_api_permissions",
    "check_model_endpoint",
    "wait_and_retry",
    "switch_model_or_thinking_mode",
    "check_network",
    "retry_once_then_switch_model",
    "reconfigure_agent",
    "refresh_workflow",
    "contact_maintainer",
]

_CODE_SOURCES: dict[str, AgentErrorSource] = {
    "CLARIFICATION_REQUIRED": "harness",
    "PROMPT_BLOCKED": "harness",
    "PROTEIN_CONTEXT_REQUIRED": "harness",
    "INVALID_UUID": "harness",
    "AGENT_AUTH_FAILED": "provider_api",
    "AGENT_ACCESS_DENIED": "provider_api",
    "AGENT_REGION_UNAVAILABLE": "provider_api",
    "AGENT_QUOTA_EXCEEDED": "provider_api",
    "AGENT_MODEL_NOT_FOUND": "provider_api",
    "AGENT_RATE_LIMITED": "provider_api",
    "AGENT_PROVIDER_UNAVAILABLE": "provider_api",
    "AGENT_REQUEST_REJECTED": "provider_api",
    "AGENT_THINKING_TOOL_CONFLICT": "provider_api",
    "AGENT_CONNECTION_TIMEOUT": "provider_api",
    "AGENT_CONNECTION_ERROR": "provider_api",
    "AGENT_MODEL_OUTPUT_INVALID": "model_output",
    "AGENT_DECISION_INVALID": "model_output",
    "AGENT_MODEL_RETRY_EXHAUSTED": "model_output",
    "PLAN_MODIFICATION_NOT_PRODUCED": "model_output",
    "AGENT_NOT_CONFIGURED": "configuration",
    "AGENT_CHATGPT_AUTH_REQUIRED": "configuration",
    "AGENT_CHATGPT_OAUTH_INVALID": "configuration",
    "AGENT_CHATGPT_PLAN_REQUIRED": "configuration",
    "AGENT_PROXY_INVALID": "configuration",
    "AGENT_PROXY_NOT_ALLOWED": "configuration",
    "AGENT_KEY_UNAVAILABLE": "configuration",
    "AGENT_KEY_REQUIRED": "configuration",
    "AGENT_INVALID_KEY": "configuration",
    "AGENT_INVALID_SETTINGS": "configuration",
    "AGENT_URL_BLOCKED": "configuration",
    "AGENT_DNS_ERROR": "configuration",
    "AGENT_KNOWLEDGE_CONFIG_ERROR": "configuration",
    "DEMO_EXECUTION_UNAVAILABLE": "configuration",
    "RESOURCE_NOT_FOUND": "workflow",
    "DIAGNOSTIC_SOURCE_MISSING": "domain",
    "DIAGNOSTIC_SOURCE_CHANGED": "domain",
    "RESOURCE_FORBIDDEN": "workflow",
    "INVALID_WORKFLOW_STATE": "workflow",
    "INVALID_JOB_STATE": "workflow",
    "JOB_NOT_FOUND": "workflow",
    "GENERATION_FAILED": "workflow",
    "POSTPROCESSING_FAILED": "workflow",
    "PLAN_INTEGRITY_ERROR": "workflow",
    "WORKFLOW_REQUIRED": "workflow",
    "USE_WORKFLOW_INTERACTIONS": "workflow",
    "WORKFLOW_ALREADY_STARTED": "workflow",
    "REFINEMENT_LIMIT_REACHED": "workflow",
    "PLAN_CHANGED": "workflow",
    "PLANNING_INTERRUPTED": "workflow",
    "PLANNING_FAILED": "workflow",
    "PLANNING_INTEGRITY_ERROR": "workflow",
    "PLANNING_RETRY_LIMIT": "workflow",
    "IDEMPOTENCY_KEY_REUSED": "workflow",
    "STALE_PLANNING_ATTEMPT": "workflow",
    "AGENT_USAGE_LIMIT": "internal",
    "AGENT_INTERNAL_ERROR": "internal",
    "UNKNOWN_MODULE": "model_output",
    "COMMAND_REQUIRED": "model_output",
    "INVALID_DECISION": "model_output",
    "KNOWLEDGE_UNAVAILABLE": "internal",
    "PROTOCOL_VERSION_NOT_FOUND": "configuration",
}

_RECOVERY_ACTIONS: dict[str, RecoveryAction] = {
    "DIAGNOSTIC_SOURCE_MISSING": "continue_turn",
    "DIAGNOSTIC_SOURCE_CHANGED": "continue_turn",
    "CLARIFICATION_REQUIRED": "revise_request",
    "PROMPT_BLOCKED": "revise_request",
    "PROTEIN_CONTEXT_REQUIRED": "revise_request",
    "INVALID_UUID": "revise_request",
    "AGENT_AUTH_FAILED": "check_api_key",
    "AGENT_ACCESS_DENIED": "check_api_permissions",
    "AGENT_REGION_UNAVAILABLE": "check_model_endpoint",
    "AGENT_QUOTA_EXCEEDED": "check_api_permissions",
    "AGENT_MODEL_NOT_FOUND": "check_model_endpoint",
    "AGENT_RATE_LIMITED": "wait_and_retry",
    "AGENT_PROVIDER_UNAVAILABLE": "wait_and_retry",
    "AGENT_REQUEST_REJECTED": "switch_model_or_thinking_mode",
    "AGENT_THINKING_TOOL_CONFLICT": "switch_model_or_thinking_mode",
    "AGENT_CONNECTION_TIMEOUT": "check_network",
    "AGENT_CONNECTION_ERROR": "check_network",
    "AGENT_MODEL_OUTPUT_INVALID": "retry_once_then_switch_model",
    "AGENT_DECISION_INVALID": "retry_once_then_switch_model",
    "AGENT_MODEL_RETRY_EXHAUSTED": "retry_once_then_switch_model",
    "PLAN_MODIFICATION_NOT_PRODUCED": "retry_once_then_switch_model",
    "AGENT_NOT_CONFIGURED": "reconfigure_agent",
    "AGENT_KEY_UNAVAILABLE": "reconfigure_agent",
    "AGENT_KEY_REQUIRED": "reconfigure_agent",
    "AGENT_INVALID_KEY": "reconfigure_agent",
    "AGENT_INVALID_SETTINGS": "reconfigure_agent",
    "AGENT_URL_BLOCKED": "reconfigure_agent",
    "AGENT_DNS_ERROR": "check_network",
    "AGENT_KNOWLEDGE_CONFIG_ERROR": "contact_maintainer",
    "DEMO_EXECUTION_UNAVAILABLE": "reconfigure_agent",
    "AGENT_USAGE_LIMIT": "revise_request",
    "UNKNOWN_MODULE": "retry_once_then_switch_model",
    "COMMAND_REQUIRED": "retry_once_then_switch_model",
    "INVALID_DECISION": "retry_once_then_switch_model",
    "KNOWLEDGE_UNAVAILABLE": "wait_and_retry",
    "PROTOCOL_VERSION_NOT_FOUND": "contact_maintainer",
    "AGENT_INTERNAL_ERROR": "contact_maintainer",
    "PLANNING_INTERRUPTED": "wait_and_retry",
    "PLANNING_FAILED": "wait_and_retry",
    "PLANNING_INTEGRITY_ERROR": "contact_maintainer",
    "PLANNING_RETRY_LIMIT": "revise_request",
    "IDEMPOTENCY_KEY_REUSED": "revise_request",
    "STALE_PLANNING_ATTEMPT": "refresh_workflow",
}

for _code in ("AGENT_USAGE_UNKNOWN", "AGENT_CONTEXT_TOO_LARGE", "AGENT_OUTPUT_LIMIT", "AGENT_REQUEST_LIMIT", "AGENT_TOOL_LIMIT", "AGENT_TOOL_LOOP", "AGENT_TURN_TIMEOUT"):
    _CODE_SOURCES[_code] = "harness"
    _RECOVERY_ACTIONS[_code] = "contact_maintainer" if _code == "AGENT_CONTEXT_TOO_LARGE" else "continue_turn"
_CODE_SOURCES["AGENT_OUTPUT_TRUNCATED"] = "model_output"
_CODE_SOURCES["AGENT_EVALUATION_LIMIT"] = "harness"
_RECOVERY_ACTIONS["AGENT_EVALUATION_LIMIT"] = "contact_maintainer"
_RECOVERY_ACTIONS["AGENT_OUTPUT_TRUNCATED"] = "retry_once_then_switch_model"
_RECOVERY_ACTIONS["AGENT_USAGE_LIMIT"] = "contact_maintainer"
_RECOVERY_ACTIONS["AGENT_TURN_TIMEOUT"] = "continue_turn"


_CODE_SOURCES["SAFETY_CHECK_UNAVAILABLE"] = "harness"
_RECOVERY_ACTIONS["SAFETY_CHECK_UNAVAILABLE"] = "wait_and_retry"

_UPSTREAM_CODE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")


def error_source_for(code: str | None) -> AgentErrorSource | None:
    """Return a stable component/source classification for a public error code."""
    if not code:
        return None
    if code in _CODE_SOURCES:
        return _CODE_SOURCES[code]
    if code.startswith(("WORKFLOW_", "PLAN_", "PLANNING_", "REFINEMENT_", "RESOURCE_")):
        return "workflow"
    if code.startswith("AGENT_"):
        return "internal"
    return "domain"


def recovery_action_for(code: str | None) -> RecoveryAction | None:
    """Return the simplest safe user action for a public error code."""
    if not code:
        return None
    if code in _RECOVERY_ACTIONS:
        return _RECOVERY_ACTIONS[code]
    source = error_source_for(code)
    if source == "workflow":
        return "refresh_workflow"
    if source == "provider_api":
        return "retry_once_then_switch_model"
    if source == "model_output":
        return "retry_once_then_switch_model"
    if source == "configuration":
        return "reconfigure_agent"
    if source in {"domain", "harness"}:
        return "revise_request"
    return "contact_maintainer"


def _upstream_error(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {}
    value = body.get("error", body)
    return value if isinstance(value, dict) else {}


def upstream_error_code(body: Any) -> str | None:
    value = _upstream_error(body).get("code")
    return value if isinstance(value, str) and _UPSTREAM_CODE_RE.fullmatch(value) else None


def provider_http_error(status_code: int, body: Any = None) -> tuple[str, str, str | None]:
    """Map one upstream model HTTP failure without exposing arbitrary provider text."""
    body_text = str(body).lower()
    upstream = upstream_error_code(body)
    if upstream in {"subscription_sharing_usage_limit_exceeded", "subscription_sharing_usage_unavailable"}:
        return "AGENT_QUOTA_EXCEEDED", "ChatGPT plan usage is unavailable or its app limit has been reached. Check ChatGPT Settings > Usage.", upstream
    if status_code == 403 and (upstream in {"unsupported_country", "unsupported_country_region_territory"}
            or _upstream_error(body).get("message") == "This model is not available in your region."):
        return "AGENT_REGION_UNAVAILABLE", "This model is not available in the server's region.", upstream_error_code(body)
    if status_code == 400 and "thinking" in body_text and (
        "tool_choice" in body_text or "tool choice" in body_text
    ):
        return (
            "AGENT_THINKING_TOOL_CONFLICT",
            "The model's thinking mode conflicts with tool calling. "
            "Use a compatible configuration; retrying unchanged will not help.",
            upstream_error_code(body),
        )
    mapping = {
        401: ("AGENT_AUTH_FAILED", "The API key was rejected. Check your Agent API settings."),
        402: ("AGENT_QUOTA_EXCEEDED", "The model provider has insufficient credits or the key's spending limit was reached."),
        403: ("AGENT_ACCESS_DENIED", "API access was denied. Check your model permissions."),
        404: ("AGENT_MODEL_NOT_FOUND", "The model or API endpoint was not found. Check your Agent API settings."),
        429: ("AGENT_RATE_LIMITED", "API quota or rate limit exceeded. Check your quota or try again later."),
    }
    if status_code in mapping:
        code, message = mapping[status_code]
    elif status_code >= 500:
        code, message = "AGENT_PROVIDER_UNAVAILABLE", "The model service is unavailable. Try again later."
    else:
        code, message = (
            "AGENT_REQUEST_REJECTED",
            "The model API rejected the request. Check model support and request compatibility.",
        )
    return code, message, upstream_error_code(body)


def failure_details(code: str, message: str = "") -> dict:
    if not message:
        message = {
            "AGENT_CONNECTION_TIMEOUT": "The model request exceeded the local timeout.",
            "AGENT_CONNECTION_ERROR": "Cannot connect to the model provider. Check DNS, network and TLS connectivity.",
            "AGENT_PROVIDER_UNAVAILABLE": "The model provider is unavailable. Try again later.",
            "AGENT_MODEL_OUTPUT_INVALID": "The model response does not match the expected output format.",
            "AGENT_DECISION_INVALID": "The model could not fill the plan fields correctly. Existing inputs are preserved; retry this request.",
            "AGENT_INTERNAL_ERROR": "An internal Agent error occurred. Contact the maintainer with the trace ID.",
            "AGENT_CHATGPT_AUTH_REQUIRED": "Authorize ChatGPT again in Genova Settings.",
            "AGENT_CHATGPT_OAUTH_INVALID": "ChatGPT authorization failed validation. Start a new sign-in from Settings.",
            "AGENT_CHATGPT_PLAN_REQUIRED": "Allow Genova to use your ChatGPT plan in ChatGPT Settings.",
            "AGENT_QUOTA_EXCEEDED": "Provider usage allowance has been reached. Check your account or ChatGPT app limits.",
        }.get(code, "")
    if not message and code == "AGENT_DNS_ERROR":
        message = "Cannot resolve the API hostname."
    elif not message and code == "AGENT_USAGE_UNKNOWN":
        message = "This turn has reached its available budget. Send a follow-up to continue."
    elif not message and code in {"AGENT_OUTPUT_LIMIT", "AGENT_REQUEST_LIMIT", "AGENT_TOOL_LIMIT", "AGENT_TURN_TIMEOUT"}:
        message = "This turn paused. Send a follow-up to continue from the saved checkpoint."
    recovery = recovery_action_for(code)
    status = {"AGENT_AUTH_FAILED":401, "AGENT_ACCESS_DENIED":403, "AGENT_REGION_UNAVAILABLE":403,
        "AGENT_QUOTA_EXCEEDED":402, "AGENT_MODEL_NOT_FOUND":404, "AGENT_RATE_LIMITED":429,
        "AGENT_CONNECTION_TIMEOUT":504, "AGENT_TURN_TIMEOUT":504, "AGENT_CONNECTION_ERROR":502,
        "AGENT_PROVIDER_UNAVAILABLE":502, "AGENT_MODEL_OUTPUT_INVALID":502, "AGENT_DECISION_INVALID":422,
        "AGENT_MODEL_RETRY_EXHAUSTED":502, "AGENT_INTERNAL_ERROR":500, "SAFETY_CHECK_UNAVAILABLE":503,
        "SAFETY_ASSESSMENT_REQUIRED":409,"RESEARCH_TASK_BLOCKED":409,"RESEARCH_TASK_READ_ONLY":409}.get(code)
    return {"error_code": code, "status_code": status, "error_source": error_source_for(code),
            "error_message": message, "recovery_action": recovery,
            "retryable": recovery in {"wait_and_retry", "check_network", "retry_once_then_switch_model"}}


def exception_details(exc: Exception) -> dict:
    import asyncio
    from fastapi import HTTPException
    from pydantic import ValidationError
    from pydantic_ai import UsageLimitExceeded, UnexpectedModelBehavior, ModelRetry
    from pydantic_ai.exceptions import ModelHTTPError, ModelAPIError
    from openai import APIConnectionError, APITimeoutError, APIStatusError
    from backend.services.workflows import WorkflowError
    from backend.services.jobs import DomainValidationError
    from backend.services.results import ResultServiceError
    from backend.agent.runner import RunFailure
    if isinstance(exc, RunFailure):
        result = {**failure_details(exc.code), **exc.details}
        if exc.details.get("budget_scope") == "turn":
            result.update(retryable=False, recovery_action="continue_turn")
        return result
    if isinstance(exc, (WorkflowError, DomainValidationError, ResultServiceError)):
        return {**failure_details(exc.code, exc.message), 'status_code': exc.http_status}
    if isinstance(exc, ModelHTTPError):
        code, message, upstream = provider_http_error(exc.status_code, exc.body)
        return {**failure_details(code, message), "status_code": exc.status_code,
                "upstream_status_code": exc.status_code, "upstream_error_code": upstream}
    if isinstance(exc, ModelAPIError):
        if isinstance(exc.__cause__, APIStatusError):
            cause = exc.__cause__
            code, message, upstream = provider_http_error(cause.status_code, cause.body)
            return {**failure_details(code, message), "status_code": cause.status_code,
                    "upstream_status_code": cause.status_code, "upstream_error_code": upstream}
        if isinstance(exc.__cause__, APITimeoutError):
            return failure_details("AGENT_CONNECTION_TIMEOUT")
        return failure_details("AGENT_CONNECTION_ERROR" if isinstance(exc.__cause__, APIConnectionError)
            else "AGENT_PROVIDER_UNAVAILABLE")
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return failure_details("AGENT_TURN_TIMEOUT")
    if isinstance(exc, APITimeoutError):
        return failure_details("AGENT_CONNECTION_TIMEOUT")
    if isinstance(exc, (APIConnectionError, ConnectionError)):
        return failure_details("AGENT_CONNECTION_ERROR")
    if isinstance(exc, UsageLimitExceeded):
        text = str(exc)
        code = next((code for name, code in (("output_tokens_limit", "AGENT_OUTPUT_LIMIT"),
            ("request_limit", "AGENT_REQUEST_LIMIT"), ("tool_calls_limit", "AGENT_TOOL_LIMIT"),
            ("input_tokens_limit", "AGENT_CONTEXT_TOO_LARGE")) if name in text), "AGENT_USAGE_LIMIT")
        return failure_details(code)
    if isinstance(exc, (UnexpectedModelBehavior, ValidationError)):
        details=failure_details("AGENT_MODEL_OUTPUT_INVALID")
        issues=validation_issues(exc)
        if issues:
            details['validation_errors']=issues
        return details
    if isinstance(exc, ModelRetry):
        return failure_details("AGENT_MODEL_RETRY_EXHAUSTED")
    if isinstance(exc, HTTPException):
        code = exc.detail.get("error_code") if isinstance(exc.detail, dict) else None
        if isinstance(code, str) and code in _CODE_SOURCES:
            return {**failure_details(code), "status_code": exc.status_code}
        code = {400: "INVALID_INPUT", 403: "RESOURCE_FORBIDDEN", 404: "RESOURCE_NOT_FOUND",
                409: "INPUT_CHANGED", 422: "INVALID_INPUT"}.get(exc.status_code, "AGENT_INTERNAL_ERROR")
        return {**failure_details(code), "status_code": exc.status_code}
    return failure_details("AGENT_INTERNAL_ERROR")


def validation_issues(exc):
    from pydantic import ValidationError
    issues=[]
    seen=set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc,ValidationError):
            issues.extend({'path':'.'.join(str(part) for part in error['loc']), 'type':error['type']}
                for error in exc.errors(include_input=False,include_context=False,include_url=False))
            break
        exc=exc.__cause__
    return issues[:20]


def log_failure(logger, exc: Exception, **context):
    import traceback
    # Only code locations, never exception bodies, source lines or local variables.
    frames = [(frame.filename, frame.lineno, frame.name) for frame in traceback.extract_tb(exc.__traceback__)]
    logger.error("Agent failure context=%s type=%s frames=%s validation=%s", context, type(exc).__name__, frames, validation_issues(exc))
