"""AgentService — orchestrates PydanticAI for workflow planning, status, and results.

Runs PydanticAI with query tools and a draft-writing preview tool to produce
structured AgentResponse output; computation still requires approval.
"""
from __future__ import annotations

import logging
import asyncio
import time
from typing import Any, Literal

from pydantic_ai import Agent, ModelRetry, PromptedOutput, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.usage import UsageLimits
from pydantic_ai.messages import TextPart, TextPartDelta, PartStartEvent, PartDeltaEvent
from pydantic_core import from_json
from openai import APIConnectionError, APITimeoutError

from backend.agent.catalog import CATALOG, CapabilityCatalog
from backend.agent.context import prepare_context
from backend.agent.verifier import verify_response
from backend.agent.deps import AgentDeps
from backend.agent.errors import provider_http_error, exception_details
from backend.agent.runner import run_agent, initialize, RunFailure
from backend.agent.reasoning import create_model
from backend.agent.prompts import SYSTEM_PROMPT
from backend.agent.presentation import AgentPlanResponse
from backend.agent.schemas import AgentPageContext, AgentResponse
from backend.agent.skills import SkillRegistry
from backend.agent.tools import AGENT_TOOLS, prepare_tool


logger = logging.getLogger("backend-agent")


async def run_streamed(agent, prompt, deps, *, stage="planning"):
    async def events(ctx, stream):
        parts = {}
        last_emit = 0.0
        async for event in stream:
            if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                parts[event.index] = event.part.content
            elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                parts[event.index] = parts.get(event.index, "") + event.delta.content_delta
            else:
                continue
            now = time.monotonic()
            if now - last_emit < 0.25:
                continue
            text = "".join(parts[index] for index in sorted(parts)).lstrip()
            if text.startswith("```"):
                text = text.partition("\n")[2]
            try:
                partial = from_json(text, allow_partial="trailing-strings")
            except ValueError:
                continue
            researched = any(t.get('completed') and t['tool'] != 'read_skill' for t in deps.tool_audit)
            if not researched and isinstance(partial, dict) and isinstance(partial.get("message"), str):
                await deps.progress(message=partial["message"][:8000])
                last_emit = now
    result = await run_agent(agent, prompt, deps, stage=stage, event_handler=events)
    if not any(t.get('completed') and t['tool'] != 'read_skill' for t in deps.tool_audit):
        await deps.progress(message=result.output.message)
    return result


class AgentService:
    """Stateless service that runs PydanticAI planning."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        provider: str = "openai",
        base_url: str | None = None,
        reasoning: dict | None = None,
        catalog: CapabilityCatalog | None = None,
        skill_registry: SkillRegistry | None = None,
        http_client=None,
        startup_warnings: list[str] | None = None,
    ) -> None:
        self._catalog = catalog or CATALOG
        self._skill_registry = skill_registry
        self._startup_warnings = list(startup_warnings or [])
        self._model = self._resolve_model(model, provider, api_key, base_url, http_client, reasoning)
        self._agent = self._build_agent()

    @staticmethod
    def _resolve_model(model: str, provider: str, api_key: str, base_url: str | None = None, http_client=None, reasoning=None) -> Any:
        if provider == "chatgpt":
            from backend.agent.chatgpt_model import ChatGPTResponsesModel
            return ChatGPTResponsesModel(model, api_key, http_client, reasoning)
        if provider in ("openai", "deepseek", "openai-compatible"):
            return create_model(model, api_key, base_url, http_client, reasoning, provider)
        return f"{provider}:{model}"

    def _build_agent(self) -> Agent[AgentDeps, AgentResponse]:
        """Build the PydanticAI agent with tools and system prompt."""
        agent = Agent(
            self._model,
            system_prompt=SYSTEM_PROMPT,
            deps_type=AgentDeps,
            output_type=PromptedOutput(AgentResponse),
            retries=2,
            defer_model_check=True,
        )

        # Register tools
        for tool in AGENT_TOOLS:
            agent.tool(tool, prepare=prepare_tool)

        return agent

    async def plan(
        self,
        deps: AgentDeps,
        message: str,
        context: AgentPageContext | None = None,
        *,
        mode: Literal["plan", "modify", "explain"] = "plan",
    ) -> AgentResponse:
        """Run the planning agent.

        Args:
            deps: Agent dependencies (user_id, db, catalog, knowledge).
            message: User's natural language request.
            context: Optional frontend page context.

        Returns:
            AgentResponse with plan, validation status, and explanations.
        """
        deps.interaction_mode = mode
        deps.allow_plan_mutation = mode != "explain"
        deps.allowed_tools = frozenset(
            tool.__name__ for tool in AGENT_TOOLS
            if mode != "explain" or tool.__name__ != "preview_workflow"
        )
        deps.preview_candidates = []

        initialize(deps)
        started = time.monotonic()
        try:
            turn_context = await asyncio.wait_for(prepare_context(
                deps, message, context, mode=mode,
                skill_registry=self._skill_registry,
                startup_warnings=self._startup_warnings,
            ), timeout=max(0, deps.deadline - time.monotonic()))
        except (TimeoutError, asyncio.TimeoutError):
            return AgentResponse(message="The Agent turn timed out.", error_code="AGENT_TURN_TIMEOUT")
        if isinstance(turn_context, AgentResponse):
            return turn_context

        try:
            from backend.agent.research_safety import assess, require_task, check_reply
            if deps.safety_assessment is None:
                stopped = await assess(self, deps, message)
                if stopped:
                    return AgentResponse(**stopped)
            if mode != "explain":
                if deps.safety_assessment.get("answer_only"):
                    return AgentResponse(message="本轮可提供高层解释，请明确独立的正常研究目标后再创建方案。" if deps.safety_assessment.get("language") == "zh" else "I can offer high-level explanations; specify a distinct legitimate research objective before creating a plan.")
                require_task(deps.db, deps.research_task_id, deps.user_id, deps.safety_assessment["revision"])
            if deps.defer_preview_persistence:
                deps.db.rollback()
            async def run():
                if deps.progress:
                    return (await run_streamed(self._agent, turn_context.user_message, deps)).output
                result = await run_agent(self._agent, turn_context.user_message, deps, stage="planning")
                return result.output
            output = await asyncio.wait_for(run(), timeout=max(0, deps.deadline - time.monotonic()))
            output = verify_response(output, deps, turn_context, message)
            if deps.session_context:
                return output
            checked = await check_reply(self, deps, message, output.model_dump(mode="json"))
            return output.model_copy(update={"message": checked["message"], "diagnostic_notes": checked["diagnostic_notes"]})
        except Exception as exc:
            details = exception_details(exc)
            if isinstance(exc, ModelHTTPError):
                code, message, upstream = provider_http_error(exc.status_code, exc.body)
                return AgentPlanResponse(message=message, plan_valid=False, error_code=code,
                    error_source="provider_api", status_code=exc.status_code, upstream_status_code=exc.status_code, upstream_error_code=upstream)
            return AgentPlanResponse(message=details.get("error_message") or details["error_code"],
                plan_valid=False, error_code=details["error_code"], status_code=details.get("status_code"))
