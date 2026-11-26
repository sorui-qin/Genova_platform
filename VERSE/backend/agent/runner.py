"""One bounded ledger for streamed and ordinary Agent calls."""
import copy
import math
import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field, replace
from importlib.metadata import version

from pydantic_ai.messages import ModelMessagesTypeAdapter, RetryPromptPart, ToolCallPart
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.usage import RunUsage, UsageLimits


class RunFailure(Exception):
    def __init__(self, code, *, limit=None, allowed=None, used=None, scope=None):
        self.code = code
        self.details = {"limit": limit, "allowed": allowed, "used": used, "budget_scope": scope}
        super().__init__(code)


@dataclass(frozen=True)
class Budget:
    request_output: int = field(default_factory=lambda: int(os.getenv("AGENT_REQUEST_OUTPUT_TOKENS", "8192")))
    turn_output: int = field(default_factory=lambda: int(os.getenv("AGENT_TURN_OUTPUT_TOKENS", "32768")))
    requests: int = field(default_factory=lambda: int(os.getenv("AGENT_TURN_REQUESTS", "16")))
    tools: int = field(default_factory=lambda: int(os.getenv("AGENT_TURN_TOOLS", "24")))
    seconds: int = field(default_factory=lambda: int(os.getenv("AGENT_TURN_SECONDS", "240")))
    lease_seconds: int = field(default_factory=lambda: int(os.getenv("AGENT_TURN_LEASE_SECONDS", "300")))
    context_target_tokens: int = field(default_factory=lambda: int(os.getenv("AGENT_CONTEXT_TARGET_TOKENS", "98304")))
    context_max_input_tokens: int = field(default_factory=lambda: int(os.getenv("AGENT_CONTEXT_MAX_INPUT_TOKENS", "131072")))
    model_window: int = 0
    context_bytes: int = field(default_factory=lambda: int(os.getenv("AGENT_CONTEXT_BYTES", "2097152")))

    @classmethod
    def for_model(cls, window=None):
        budget = cls()
        cap = min(budget.context_max_input_tokens, window - budget.request_output - 1024 if window else 32768)
        return replace(budget, model_window=window or 0, context_max_input_tokens=cap,
                       context_target_tokens=min(budget.context_target_tokens, cap))

    def __post_init__(self):
        for name, ceiling in {"request_output": 8192, "turn_output": 32768, "requests": 16,
                              "tools": 24, "seconds": 3600, "lease_seconds": 3660,
                              "context_target_tokens": 1048576, "context_max_input_tokens": 1048576, "context_bytes": 16777216}.items():
            if not 0 < getattr(self, name) <= ceiling:
                raise ValueError(f"Invalid Agent budget: {name}")
        if self.lease_seconds < self.seconds + 60 or self.context_target_tokens > self.context_max_input_tokens:
            raise ValueError("Agent lease must include 60 seconds cleanup; context target must fit input limit")
        if self.model_window and self.model_window <= self.request_output + 1024:
            raise ValueError("Agent model window must fit output and safety margin")


def estimate_tokens(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    # ponytail: conservative local estimate; use a verified tokenizer when provider metadata supplies one.
    return math.ceil(sum(1 if ord(c) < 128 else 3 for c in text) / 3)


def compact_messages(messages, target, session_id=None, investigation=None, byte_target=None):
    messages = copy.deepcopy(messages)
    def oversized():
        serialized = ModelMessagesTypeAdapter.dump_json(messages)
        return estimate_tokens(serialized.decode()) > target or (byte_target is not None and len(serialized) > byte_target)
    from pydantic_ai.messages import ToolReturnPart, TextPart, UserPromptPart, ModelRequest, ModelResponse
    if session_id and messages:
        for part in messages[0].parts:
            if not isinstance(part, UserPromptPart) or not isinstance(part.content, str):
                continue
            try:
                prompt = json.loads(part.content)
            except ValueError:
                continue
            if not isinstance(prompt, dict) or not {'question', 'session'} <= prompt.keys() or prompt.keys() - {'question', 'session', 'available_skills', 'available_protein_files'}:
                continue
            state = prompt['session']
            if not isinstance(state, dict) or state.get('id') != session_id:
                continue
            if investigation:
                state['diagnostic_investigation'] = copy.deepcopy(investigation)
                part.content = json.dumps(prompt, ensure_ascii=False)
            # Only backend-packaged historical turns are removable; the current
            # question and authoritative scientific snapshot remain intact.
            while state.get('turns') and oversized():
                state['turns'].pop(0)
                part.content = json.dumps(prompt, ensure_ascii=False)
    for message in messages[1:-1]:
        for part in message.parts:
            if not oversized():
                return messages
            if isinstance(part, ToolReturnPart) and estimate_tokens(part.content) > 512:
                if part.tool_name == "query_results" and isinstance(part.content, dict) and "summary" in part.content:
                    part.content = {**part.content, "rows": part.content["rows"][:1],
                        "rows_preview_count": min(1, len(part.content["rows"])),
                        "rows_preview_truncated": part.content["returned_count"] > 1}
                elif part.tool_name in {"get_job_diagnostics", "read_job_diagnostic", "read_task_source"} and isinstance(part.content, dict):
                    tasks = part.content.get("tasks")
                    part.content = {key: value for key, value in part.content.items()
                        if key not in {"lines", "tasks"}}
                    if isinstance(tasks, list):
                        # A failed task's reason stays: its code and the last line of its error.
                        part.content["tasks"] = [{key: task.get(key) for key in ("task_code", "status", "error_code", "error_last_line", "ref")}
                                                 for task in tasks if isinstance(task, dict)]
                    part.content.update(compacted=True, note="Re-read the source and line range for original evidence.")
                else:
                    payload = json.dumps(part.content, ensure_ascii=False, default=str)
                    part.content = {"compacted": True, "tool_call_id": part.tool_call_id,
                        "excerpt": payload[:768], "note": "Historical tool data only; re-read current resource before mutation."}
            elif isinstance(part, TextPart) and estimate_tokens(part.content) > 512:
                part.content = part.content[:768] + " [Historical assistant text compacted; not authoritative state.]"
    index = 1
    while index < len(messages) - 3 and oversized():
        response, request = messages[index:index + 2]
        if isinstance(response, ModelResponse) and isinstance(request, ModelRequest):
            calls = [p.tool_call_id for p in response.parts if isinstance(p, ToolCallPart)]
            returns = [p.tool_call_id for p in request.parts if isinstance(p, ToolReturnPart)]
            if calls and sorted(calls) == sorted(returns) and len(returns) == len(request.parts):
                # Drop only a completed exchange, including its reasoning as a
                # whole. Never edit signed reasoning or leave orphaned tools.
                del messages[index:index + 2]
                continue
        index += 1
    # Keep the original request and latest exchange. Oversize protected data fails closed.
    return messages


def usage_snapshot(usage):
    return {key: getattr(usage, key) for key in ("requests", "tool_calls", "input_tokens", "output_tokens")}


def initialize(deps):
    if deps.usage is None:
        deps.usage = RunUsage()
    if deps.deadline is None:
        deps.deadline = time.monotonic() + deps.budget.seconds
    if not hasattr(deps, "unknown_output_reserved"):
        deps.unknown_output_reserved = 0


def evidence_reserve(deps):
    return (min(1, deps.budget.requests - 1),
            min(2048, deps.budget.request_output, deps.budget.turn_output // 4),
            min(30, deps.budget.seconds / 4))


def presentation_available(deps):
    requests, tokens, seconds = evidence_reserve(deps)
    return (deps.usage.requests < deps.budget.requests - requests - 1
            and deps.usage.output_tokens + deps.unknown_output_reserved + tokens + 2048 < deps.budget.turn_output
            and deps.deadline - time.monotonic() > seconds + 15)


def diagnostic(deps):
    requests = [r for s in deps.stages for r in s["requests"]]
    ledger = usage_snapshot(deps.usage)
    ledger["requests"] = max(ledger["requests"], getattr(deps, "previous_ledger", {}).get("requests", 0) + sum(r.get("sent", False) for r in requests))
    for key in ("input_tokens", "output_tokens"):
        ledger[key] = max(ledger[key], getattr(deps, "previous_ledger", {}).get(key, 0) + sum(r.get(key) or (r.get("partial_output_tokens", 0) if key == "output_tokens" else 0) for r in requests))
    usage = dict(ledger)
    for key in ("input_tokens", "output_tokens"):
        previous = getattr(deps, "previous_usage", {}).get(key, 0)
        usage[key] = (previous + sum(r[key] for r in requests) if previous is not None and all(r.get(key) is not None for r in requests) else None) if requests else getattr(deps, "previous_usage", {}).get(key)
    return {"trace_id": deps.trace_id, "stages": deps.stages, "usage": usage,
            "ledger": ledger,
            "warnings": sorted({s["warning"] for s in deps.stages if s.get("warning")} | {r["warning"] for r in requests if r.get("warning")}),
            "active_elapsed_ms": getattr(deps, "previous_elapsed_ms", 0) + round((time.monotonic() - getattr(deps, "attempt_started", time.monotonic())) * 1000),
            "unknown_output_reserved": getattr(deps, "unknown_output_reserved", 0) + sum(r.get("output_allowance", 0) for r in requests if r.get("sent") and "elapsed_ms" not in r),
            "provider_output_overrun": getattr(deps, "provider_output_overrun", None),
            "contract_version": "agent-run-v1",
            "tools": deps.tool_audit, "committed_effects": deps.committed_effects,
            "budget": asdict(deps.budget), "runtime_version": version("pydantic-ai-slim"),
            "tool_attempts": getattr(deps, "tool_attempts", 0),
            "tool_completed": sum(bool(t.get("completed")) for t in deps.tool_audit),
            "output_validation_retries": sum(max((r["validation_retries"] for r in s["requests"]), default=0) for s in deps.stages)}


class StageLimits(UsageLimits):
    def _check(self, name, used, *, inclusive=False):
        if name == "output_tokens_limit":
            overrun = getattr(self.deps, "provider_output_overrun", None)
            if overrun:
                raise RunFailure("AGENT_OUTPUT_LIMIT", limit="request_output_tokens", scope="provider_request", **overrun)
            used += self.deps.unknown_output_reserved
        allowed = getattr(self, name)
        if allowed is not None and (used >= allowed if inclusive else used > allowed):
            code = {"request_limit": "AGENT_REQUEST_LIMIT", "tool_calls_limit": "AGENT_TOOL_LIMIT",
                    "output_tokens_limit": "AGENT_OUTPUT_LIMIT"}[name]
            if name == "output_tokens_limit" and self.deps.unknown_output_reserved:
                code = "AGENT_USAGE_UNKNOWN"
            total = {"request_limit": self.deps.budget.requests, "tool_calls_limit": self.deps.budget.tools,
                     "output_tokens_limit": self.deps.budget.turn_output}[name]
            raise RunFailure(code, limit=name, allowed=allowed, used=used, scope="turn" if allowed == total else "stage")

    def check_before_request(self, usage):
        if getattr(self.deps, "chatgpt_client_budget", False) and getattr(self.deps, "provider_output_overrun", None):
            raise RunFailure("AGENT_OUTPUT_LIMIT", **self.deps.provider_output_overrun)
        self._check("request_limit", usage.requests, inclusive=True)
        self._check("output_tokens_limit", usage.output_tokens, inclusive=True)

    def check_tokens(self, usage):
        # Validate an already returned final answer; further requests and tools remain blocked.
        if usage.output_tokens > self.deps.budget.turn_output:
            self.deps.budget_exceeded = True

    def check_before_tool_call(self, projected_usage):
        if getattr(self.deps, "chatgpt_client_budget", False) and getattr(self.deps, "provider_output_overrun", None):
            raise RunFailure("AGENT_OUTPUT_LIMIT", **self.deps.provider_output_overrun)
        self._check("output_tokens_limit", projected_usage.output_tokens, inclusive=True)
        if getattr(self.deps, "tool_attempts", 0) > self.deps.budget.tools:
            raise RunFailure("AGENT_TOOL_LIMIT", allowed=self.deps.budget.tools, used=self.deps.tool_attempts)
        self._check("tool_calls_limit", projected_usage.tool_calls)


class AuditedModel(WrapperModel):
    def __init__(self, model, deps, stage, limits):
        super().__init__(model)
        self.deps, self.stage, self.limits = deps, stage, limits

    def request_messages(self, messages, parameters):
        fixed_payload = {"tools": [{"name": t.name, "description": t.description, "schema": t.parameters_json_schema} for t in parameters.function_tools],
            "output": {"object": parameters.output_object.json_schema if parameters.output_object else None,
                "tools": [{"name": t.name, "description": t.description, "schema": t.parameters_json_schema} for t in parameters.output_tools]},
            "instructions": parameters.instruction_parts}
        fixed = estimate_tokens(fixed_payload)
        fixed_bytes = sum(len(json.dumps(value, ensure_ascii=False, default=str).encode()) for value in fixed_payload.values())
        cap = min(self.deps.budget.context_target_tokens, self.deps.budget.context_max_input_tokens)
        if self.deps.budget.model_window:
            cap = min(cap, self.deps.budget.model_window - self.deps.budget.request_output - 1024)
        investigating = any(s.metadata.name == 'failure-triage' for s in self.deps.active_skills) or any(
            t['tool'] in {'get_job_diagnostics', 'read_job_diagnostic'} for t in self.deps.tool_audit)
        packed = compact_messages(messages, max(0, cap - fixed), (getattr(self.deps, 'session_context', None) or {}).get('id'),
                                self.deps.diagnostic_state if investigating else None,
                                max(0, self.deps.budget.context_bytes - fixed_bytes))

        self.stage['context_compaction'] = {'before_bytes': len(ModelMessagesTypeAdapter.dump_json(messages)),
            'after_bytes': len(ModelMessagesTypeAdapter.dump_json(packed))}
        return packed

    async def checkpoint(self, row):
        row["sent"] = True
        callback = getattr(self.deps, "checkpoint_usage", None)
        if callback:
            try:
                await callback()
            except BaseException:
                row["sent"], row["generation_rejected"] = False, True
                raise

    def begin(self, messages, settings, parameters):
        self.limits.check_before_request(self.deps.usage)
        if getattr(self.deps, "tool_attempts", 0) > self.deps.budget.tools:
            raise RunFailure("AGENT_TOOL_LIMIT", allowed=self.deps.budget.tools, used=self.deps.tool_attempts)
        sizes = {"messages": len(ModelMessagesTypeAdapter.dump_json(messages)),
                 "tools": len(json.dumps([{"name": t.name, "description": t.description, "schema": t.parameters_json_schema} for t in parameters.function_tools], ensure_ascii=False).encode()),
                 "output": len(json.dumps({"object": parameters.output_object.json_schema if parameters.output_object else None,
                     "tools": [{"name": t.name, "description": t.description, "schema": t.parameters_json_schema} for t in parameters.output_tools]}, ensure_ascii=False).encode()),
                 "instructions": len(json.dumps(parameters.instruction_parts, default=str, ensure_ascii=False).encode())}
        retries = sum(isinstance(p, RetryPromptPart) for m in messages for p in m.parts)
        row = {"request_id": str(uuid.uuid4()), "sequence": len(self.stage["requests"]) + 1, "model": self.model_name, "provider": self.system,
               "prompt_bytes": sizes, "input_tokens": None, "output_tokens": None,
               "validation_retries": retries, "finish_reason": None, "output_tool_names": [t.name for t in parameters.output_tools]}
        self.stage["requests"].append(row)
        if sum(sizes.values()) > self.deps.budget.context_bytes:
            raise RunFailure("AGENT_CONTEXT_TOO_LARGE", limit="context_bytes", allowed=self.deps.budget.context_bytes, used=sum(sizes.values()))
        remaining = self.limits.output_tokens_limit - self.deps.usage.output_tokens - self.deps.unknown_output_reserved
        if remaining <= 0:
            raise RunFailure("AGENT_OUTPUT_LIMIT", limit="output_tokens_limit", allowed=self.limits.output_tokens_limit, used=self.deps.usage.output_tokens + self.deps.unknown_output_reserved)
        row["output_allowance"] = min(self.deps.budget.request_output, remaining)
        serialized = ModelMessagesTypeAdapter.dump_json(messages).decode()
        estimated = estimate_tokens(serialized) + math.ceil(sum(v for k, v in sizes.items() if k != "messages") / 3)
        cap = self.deps.budget.context_max_input_tokens
        if self.deps.budget.model_window:
            cap = min(cap, self.deps.budget.model_window - row["output_allowance"] - 1024)
        row.update(input_estimate=estimated, input_estimate_state="estimated", input_limit=cap,
                   model_window_verified=bool(self.deps.budget.model_window))
        if estimated > cap:
            raise RunFailure("AGENT_CONTEXT_TOO_LARGE", limit="input_tokens_estimated", allowed=cap, used=estimated)
        settings = settings or {}
        extra = settings.get("extra_body", {})
        row["reasoning"] = {"effort": settings.get("openai_reasoning_effort"),
            "thinking": extra.get("thinking", extra.get("enable_thinking")),
            "budget_tokens": extra.get("thinking_budget")}
        return row, {**settings, "max_tokens": row["output_allowance"]}

    def finish(self, row, response, started):
        if response is not None:
            row.update(cache_read_tokens=response.usage.cache_read_tokens, cache_write_tokens=response.usage.cache_write_tokens)
        if "elapsed_ms" in row:
            if response is not None:
                for key in ("input_tokens", "output_tokens"):
                    value = getattr(response.usage, key, 0)
                    if row.get(key) is None and value:
                        row[key], row[key + "_state"] = value, "observed"
                        settled = max(0, value - row.get("partial_output_tokens", 0)) if key == "output_tokens" else value
                        setattr(self.deps.usage, key, getattr(self.deps.usage, key) + settled)
                        if key == "output_tokens":
                            self.deps.unknown_output_reserved -= row.pop("reserved_output", 0)
                            if value > row["output_allowance"]:
                                row["warning"] = "provider_usage_mismatch"
                                self.deps.provider_output_overrun = {"allowed": row["output_allowance"], "used": value}
                                self.deps.budget_exceeded = True
            return
        row["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        for key in ("input_tokens", "output_tokens"):
            value = getattr(response.usage, key, 0) if response else 0
            if key == "output_tokens" and row.get("interrupted"):
                row["partial_output_tokens"] = value
                value = 0
            row[key] = value if value else None
            row[key + "_state"] = "observed" if value else "unknown"
        if row["output_tokens"] is None and not row.get("generation_rejected"):
            row["reserved_output"] = max(0, row["output_allowance"] - row.get("partial_output_tokens", 0))
            self.deps.unknown_output_reserved += row["reserved_output"]
        if response is not None:
            row["finish_reason"] = response.finish_reason
            row["reasoning_tokens"] = response.usage.details.get("reasoning_tokens")
            row["usage_source"] = "sdk_normalized_provider"
            row["tool_attempts"] = sum(isinstance(part, ToolCallPart) and part.tool_name not in row.get("output_tool_names", []) for part in response.parts)
            if (row["output_tokens"] or 0) > row["output_allowance"]:
                row["warning"] = "provider_usage_mismatch"
                self.deps.provider_output_overrun = {"allowed": row["output_allowance"], "used": row["output_tokens"]}
                self.deps.budget_exceeded = True
            self.deps.tool_attempts = getattr(self.deps, "tool_attempts", 0) + row["tool_attempts"]

    async def request(self, messages, model_settings, model_request_parameters):
        messages = self.request_messages(messages, model_request_parameters)
        row, settings = self.begin(messages, model_settings, model_request_parameters)
        started, response = time.monotonic(), None
        try:
            await self.checkpoint(row)
            response = await self.wrapped.request(messages, settings, model_request_parameters)
            if any(isinstance(p, ToolCallPart) and p.tool_name in getattr(self.deps, "stalled_tools", set()) for p in response.parts):
                raise RunFailure("AGENT_TOOL_LOOP")
            if response.finish_reason == "length":
                raise RunFailure("AGENT_OUTPUT_TRUNCATED")
            return response
        except Exception as exc:
            if response is not None:
                # The SDK cannot account for a response rejected before it returns.
                self.deps.usage.requests += 1
                self.deps.usage.incr(response.usage)
            if getattr(exc, "status_code", None) in {400, 401, 403, 404, 422}:
                row["generation_rejected"] = True
            raise
        finally:
            self.finish(row, response, started)

    @asynccontextmanager
    async def request_stream(self, messages, model_settings, model_request_parameters, run_context=None):
        messages = self.request_messages(messages, model_request_parameters)
        row, settings = self.begin(messages, model_settings, model_request_parameters)
        started, stream = time.monotonic(), None
        try:
            await self.checkpoint(row)
            async with self.wrapped.request_stream(messages, settings, model_request_parameters, run_context) as stream:
                yield stream
        except BaseException as exc:
            row["interrupted"] = True
            if getattr(exc, "status_code", None) in {400, 401, 403, 404, 422}:
                row["generation_rejected"] = True
            raise
        finally:
            response = stream.get() if stream else None
            self.finish(row, response, started)
            if response and any(isinstance(p, ToolCallPart) and p.tool_name in getattr(self.deps, "stalled_tools", set()) for p in response.parts):
                raise RunFailure("AGENT_TOOL_LOOP")
            if response and response.finish_reason == "length":
                raise RunFailure("AGENT_OUTPUT_TRUNCATED")


async def run_agent(agent, prompt, deps, *, stage, event_handler=None):
    initialize(deps)
    before = usage_snapshot(deps.usage)
    final_check = stage.startswith('output_evidence')
    reserve_requests, reserve_tokens, reserve_seconds = (0, 0, 0) if final_check else evidence_reserve(deps)
    limits = StageLimits(request_limit=deps.budget.requests - reserve_requests,
        tool_calls_limit=deps.budget.tools, output_tokens_limit=deps.budget.turn_output - reserve_tokens)
    limits.deps = deps
    record = {"stage": stage, "id": str(uuid.uuid4()), "before": before, "requests": [], "prompt_composition_bytes": getattr(deps, "prompt_composition", {}),
              "limits": {k: getattr(limits, k) for k in ("request_limit", "tool_calls_limit", "output_tokens_limit")}}
    from backend.agent.chatgpt_model import ChatGPTResponsesModel
    if isinstance(agent.model, ChatGPTResponsesModel):
        deps.chatgpt_client_budget = True
        record["output_limit_enforcement"] = "client_only"
    deps.stages.append(record)
    started = time.monotonic()
    try:
        result = await asyncio.wait_for(agent.run(prompt, deps=deps, usage=deps.usage,
            model=AuditedModel(agent.model, deps, record, limits), usage_limits=limits,
            event_stream_handler=event_handler), timeout=max(0, deps.deadline - time.monotonic() - reserve_seconds))
        if getattr(deps, "budget_exceeded", False):
            record["warning"] = "budget_exceeded_after_completion"
        return result
    except BaseException as exc:
        from backend.agent.errors import exception_details
        record["failure"] = exception_details(exc)
        if any(r.get("finish_reason") == "length" for r in record["requests"]):
            record["failure"] = {"error_code": "AGENT_OUTPUT_TRUNCATED"}
            raise RunFailure("AGENT_OUTPUT_TRUNCATED") from exc
        raise
    finally:
        record["after"] = usage_snapshot(deps.usage)
        record["delta"] = {k: record["after"][k] - before[k] for k in before}
        for key in ("input_tokens", "output_tokens"):
            if any(r.get(key) is None for r in record["requests"]):
                record["delta"][key] = None
        record["soft_target"] = 8192 if stage == "decision" else 12288
        record["soft_target_exceeded"] = (record["delta"].get("output_tokens") or 0) > record["soft_target"]
        record["elapsed_ms"] = round((time.monotonic() - started) * 1000)


if __name__ == "__main__":
    import hashlib
    from pathlib import Path
    print(json.dumps({"budget": asdict(Budget()), "runtime_version": version("pydantic-ai-slim"),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}, indent=2))
