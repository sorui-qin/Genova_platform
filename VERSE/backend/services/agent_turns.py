"""Durable conversation turns shared by the HTTP API and workflow worker."""
import asyncio
import logging
import time
import uuid
import redis
from datetime import timedelta, timezone

from sqlalchemy import select
from pydantic_ai.usage import RunUsage

from backend.agent.language import interface_text, session_interface_language
from backend.agent.errors import exception_details, failure_details, log_failure
from backend.agent.catalog import CATALOG
from backend.agent.deps import AgentDeps
from backend.agent.runner import diagnostic, Budget
from backend.agent.presentation import present_agent_response
from backend.agent.schemas import AgentPageContext, WorkflowPlan, AgentResponse
from backend.agent.session_schemas import SessionTurnRequest, SessionDecision
from backend.agent.session_chat import answer
from backend.agent.user_settings import personal_config, personal_proxy, public_client
from backend.config import settings
from backend.db import SessionLocal
from backend.models import AgentSession, AgentTurn, DatasetFile, ResearchTask, ActionProposal
from backend.routers.agent import _get_service, _get_knowledge
from backend.services import agent_sessions as service
from backend.services.jobs import DomainValidationError, validate_protein_context_for_generation
from backend.services.results import ResultServiceError
from backend.services.workflows import (WorkflowError, owned_workflow, persist_workflow_preview,
    record_workflow_interaction, claim_planning_request, link_planning_workflow, mark_planning_failed)
from backend.realtime import publish_user_event_sync
from backend.utils import utcnow

logger = logging.getLogger("backend-agent")


def publish_turn(user_id, turn):
    try:
        with redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1) as client:
            publish_user_event_sync(user_id, {"event": "agent.turn.updated", "object": turn}, redis_client=client)
        return True
    except Exception:
        logger.warning("Agent event unavailable; clients recover from persisted turns")
        return False


def _merge_committed_effects(*collections):
    merged = []
    for collection in collections:
        for effect in collection or []:
            if effect not in merged:
                merged.append(effect)
    return merged


def _failed_turn_response(turn, deps, details, *, stage, turn_id, attempt, sequence, partial_reply):
    committed_effects = _merge_committed_effects(
        turn.audit.get("committed_effects", []), deps.committed_effects if deps else [])
    if deps:
        deps.committed_effects = committed_effects
    response = {**partial_reply, **details,
        "error_stage": deps.stages[-1]["stage"] if stage == 'model' and deps and deps.stages else stage,
        "trace_id": deps.trace_id if deps else f"{turn_id}:{attempt}",
        "committed_effects": committed_effects,
        "stream_seq": sequence + 1}
    if deps and deps.safety_assessment:
        response["safety_decision"] = deps.safety_assessment["decision"]
    module_side = bool(deps and ((deps.session_context or {}).get("assets") or {}).get("module_assistant"))
    if module_side and not response.get("message"):
        # The side assistant shows `message` as the reply and the error below it: a failed turn still says what to do next.
        language = deps.interface_language or (turn.request or {}).get("interface_language")
        response["message"] = ("这一轮没有完成，当前页面和对话不受影响。请点「重试」，或换个说法再问一次。" if language == "zh" else
                               "This reply did not finish; the page and conversation are unchanged. Retry, or ask again in different words.")
    return response


_PREREQUISITES = {
    "prepared_context": ("请先上传并准备蛋白，或选择已准备好的蛋白和结合位点。",
                         "Upload and prepare a protein, or choose an existing prepared protein and binding site."),
    "pending_plan": ("请先创建方案，再选择要修改的设置。", "Create a plan first, then choose which settings to change."),
}


def prerequisite_reply(requirement, zh):
    """The fixed prompt for a plan or modify request that lacks its prerequisite, in the page language when the page sent one."""
    return {"message": _PREREQUISITES[requirement][0 if zh else 1], "missing_requirements": [requirement]}


def stated_choices(decision, intent, reply):
    """A follow-up question that also records generation or ranking choices the user already confirmed in the conversation."""
    return bool(decision and intent == 'ask' and reply.get('missing_requirements') and (decision.generation_request or decision.future_selection))


def record_generation_choices(preferences, decision, future, *, stated, plan_version, optimization_seed):
    """Save the method, count and later ranking a decision states. A follow-up question keeps only what the user actually said."""
    if decision.generation_request:
        preferences['generation']=future.generation.model_dump(mode='json') if future else decision.generation_request.model_dump(mode='json', exclude_unset=stated)
        preferences['generation_source']='agent_turn'
        preferences['generation_source_version']=plan_version
        if future and future.seed_source:
            preferences['seed_source']=future.seed_source
        elif preferences['generation'].get('engine') in {'delete','epso'} and optimization_seed:
            preferences['seed_source']=optimization_seed
    future_selection=decision.future_selection or decision.selection
    if future_selection:
        preferences['selection']=future_selection.model_dump(mode='json')


def claim_next_turn():
    with SessionLocal() as db:
        candidates = list(db.scalars(select(AgentTurn).where(AgentTurn.status == "queued")
            .order_by(AgentTurn.audit["trigger"].as_string().is_not(None), AgentTurn.created_at).limit(20)))
        for candidate in candidates:
            session = db.scalar(select(AgentSession).where(AgentSession.id == candidate.session_id).with_for_update(skip_locked=True))
            if session is None:
                db.rollback()
                continue
            service.reconcile_session(db, session)
            row = db.get(AgentTurn, candidate.id, populate_existing=True)
            if row.audit.get('trigger') in {'task_plan', 'reading'}:
                from backend.models import ResearchTask
                task = db.get(ResearchTask, row.research_task_id)
                if task and task.task_plan and task.task_plan['state'] in {'paused', 'pause_requested'}:
                    db.commit()
                    continue
            running = db.scalar(select(AgentTurn.id).where(AgentTurn.session_id == session.id, AgentTurn.status == "running"))
            if row.status != "queued" or running:
                db.commit()
                continue
            if row.audit.get("trigger") and ((session.phase in {"canceled", "cancel_requested", "archived"} or (session.phase == "failed" and row.audit.get("trigger") != "reading"))
                    or (row.audit.get("execution_revision") != session.input_revision and not (row.audit.get("trigger") == "reading" and row.request["intent"] == "ask"))):
                row.status = "completed"
                row.response = {"message": interface_text(session_interface_language(db, session), "会话状态已改变，已停止原目标的自动续接。", "The session state changed. Automatic continuation of the previous goal has stopped.")}
                db.commit()
                continue
            row.status = "running"
            row.lease_until = utcnow() + timedelta(seconds=Budget().lease_seconds)
            result = (session.id, row.id, session.owner_user_id, row.attempt)
            db.commit()
            return result
    return None


async def run_turn(session_id, turn_id, user_id, attempt, config=None):
    planning_attempt = None
    planning_request_id = None
    command_turn_id = turn_id
    sequence = 0
    last_checkpoint = 0.0
    events_available = True
    partial_reply = {"message": "", "tools": []}
    stage = "model"
    deps = None
    attempt_started = time.monotonic()
    deadline = attempt_started + Budget().seconds

    async def progress(*, message=None, tool=None, status=None, details=None, force=False):
        nonlocal sequence, last_checkpoint, events_available
        sequence += 1
        # Only verified final text is published; tool progress remains immediate.
        message = None
        if tool:
            blocks = list(partial_reply["tools"])
            if status == "running":
                blocks.append({"tool": tool, "status": status})
            else:
                for item in reversed(blocks):
                    if item["tool"] == tool and item["status"] == "running":
                        item["status"] = status
                        item.update(details or {})
                        break
            partial_reply["tools"] = blocks
        partial_reply["stream_seq"] = sequence
        now = time.monotonic()
        if force or tool or now - last_checkpoint >= 1:
            with SessionLocal() as db:
                service.owned_session(db, session_id, user_id, lock=True)
                turn = db.get(AgentTurn, turn_id)
                if turn.attempt != attempt or turn.status != "running" or turn.lease_until.replace(tzinfo=timezone.utc) <= utcnow():
                    raise WorkflowError("TURN_INTERRUPTED", "This turn is no longer active", 409)
                turn.response = dict(partial_reply)
                if deps:
                    turn.audit = {**turn.audit, "tools": list(deps.tool_audit), "diagnostic": diagnostic(deps),
                                  "diagnostic_state": deps.diagnostic_state, "source_read_state": deps.source_read_state}
                db.commit()
            last_checkpoint = now
        if events_available:
            events_available = publish_turn(user_id, {"session_id": str(session_id), "id": str(turn_id), "attempt": attempt,
                "status": "running", "response": dict(partial_reply)})

    async def run():
        nonlocal planning_attempt, planning_request_id, stage, deps, deadline, command_turn_id
        with SessionLocal() as db:
            session = service.owned_session(db, session_id, user_id)
            turn = db.get(AgentTurn, turn_id)
            if turn.attempt != attempt or turn.status != "running":
                return
            if turn.lease_until.replace(tzinfo=timezone.utc) <= utcnow():
                service.interrupt_turn(db, session, turn)
                db.commit()
                return
            from backend.agent.research_safety import bind_legacy_turn
            bind_legacy_turn(db,session,turn)
            command_turn_id = uuid.UUID(turn.audit.get("command_turn_id", str(turn.id)))
            checkpoint = turn.audit.get("checkpoint")
            pending_review = turn.audit.get('pending_review')
            request = SessionTurnRequest.model_validate(turn.request)
            if request.intent != "new_task" and turn.research_task_id and session.research_task_id and turn.research_task_id != session.research_task_id:
                raise WorkflowError("INPUT_CHANGED", "The turn belongs to another research task", 409)
            autonomous = request.intent == "auto"
            revision = session.input_revision
            state = service.snapshot(db, session, model_view=True)
            if request.module_context is not None:
                state['module_context'] = request.module_context.model_dump(mode='json')
            previous_diagnostic = db.scalar(select(AgentTurn).where(AgentTurn.session_id == session.id,
                AgentTurn.id != turn.id, AgentTurn.research_task_id == session.research_task_id, AgentTurn.audit['diagnostic_state'].is_not(None), AgentTurn.audit['diagnostic_state'] != {})
                .order_by(AgentTurn.created_at.desc()).limit(1))
            if previous_diagnostic:
                state['diagnostic_investigation'] = previous_diagnostic.audit.get('diagnostic_state') or {}
            state["turns"] = [{"id": item["id"], "intent": item["intent"], "message": item["message"],
                "status": item["status"], "response": item["response"] if item["status"] in {"completed", "needs_input"} else {"message": "", "error_code": item["response"].get("error_code")}}
                for item in state["turns"] if item["id"] != str(turn_id) and item.get("research_task_id") == (str(session.research_task_id) if session.research_task_id else None)]
            previous_task = db.scalar(select(AgentTurn).where(AgentTurn.session_id == session.id, AgentTurn.research_task_id == session.research_task_id, AgentTurn.id != turn.id,
                (AgentTurn.audit["resolved_intent"].as_string() != "ask") | (AgentTurn.status == "needs_input") |
                AgentTurn.audit["trigger"].as_string().is_not(None)).order_by(AgentTurn.created_at.desc()).limit(1))
            state["continuation"] = turn.audit.get("continuation") if turn.audit.get("trigger") else previous_task.audit.get("continuation") if previous_task else None
            if turn.audit.get("trigger") and state["continuation"]:
                request = request.model_copy(update={"message": state["continuation"]["goal"]})
            state["attachment_files"] = [{"dataset_id": str(f.dataset_id), "file_id": str(f.id), "name": f.original_filename}
                for f in db.scalars(select(DatasetFile).where(DatasetFile.dataset_id.in_(
                    [uuid.UUID(value) for key, value in session.assets.items()
                     if value and (key.endswith('_dataset_id') or key in {'protein_context_id', 'prepared_receptor_id'})])))]
            snapshot_error = None
            try:
                scientific_snapshot = service.fingerprint(db, session) if request.intent not in {"ask", "new_task"} else None
            except (WorkflowError, DomainValidationError) as exc:
                if not autonomous:
                    raise
                scientific_snapshot, snapshot_error = None, exc
            config_value = config if config is not None else personal_config(db, user_id)
            proxy_url = personal_proxy(db, user_id)
            workflow_id = session.active_workflow_id
            context_id = session.assets.get("protein_context_id")
            previous = turn.audit.get("diagnostic", {}) if attempt > 1 and not pending_review else {}
            deadline -= previous.get("active_elapsed_ms", 0) / 1000
            deps = AgentDeps(user_id=user_id, db=db, catalog=CATALOG, knowledge=_get_knowledge(), research_task_id=turn.research_task_id or session.research_task_id,
                workflow_id=workflow_id, protein_context_id=uuid.UUID(context_id) if context_id else None,
                interface_language=request.interface_language or session_interface_language(db, session),
                defer_preview_persistence=True, postprocessing_options=service.session_values(session),
                progress=progress, usage=RunUsage(**previous.get("ledger", {})), session_context=state,
                deadline=deadline, trace_id=f"{turn_id}:{attempt}", budget=Budget.for_model(config_value.get("context_window")))
            deps.checkpoint_usage = lambda: progress(force=True)
            from copy import deepcopy
            deps.diagnostic_state = deepcopy(state.get('diagnostic_investigation') or {})
            previous_source = db.scalar(select(AgentTurn).where(AgentTurn.session_id == session.id,
                AgentTurn.research_task_id == session.research_task_id, AgentTurn.id != turn.id,
                AgentTurn.audit['source_read_state'].is_not(None), AgentTurn.audit['source_read_state'] != {})
                .order_by(AgentTurn.created_at.desc()).limit(1))
            deps.source_read_state = deepcopy(turn.audit.get('source_read_state') or
                ((previous_source.audit or {}).get('source_read_state') if previous_source else {}) or {})
            state['source_read_state'] = deps.source_read_state

            deps.tool_attempts = previous.get("tool_attempts", 0)
            deps.previous_tool_executions = previous.get("tool_attempts", 0)
            deps.previous_usage = previous.get("usage", {})
            deps.previous_ledger = previous.get("ledger", {})
            deps.unknown_output_reserved = previous.get("unknown_output_reserved", 0)
            deps.provider_output_overrun = previous.get("provider_output_overrun")
            deps.previous_elapsed_ms = previous.get("active_elapsed_ms", 0)
            deps.attempt_started = attempt_started
            deps.committed_effects = list(turn.audit.get("committed_effects", []))
            trigger = turn.audit.get("trigger")
            audit = dict(turn.audit)
            db.rollback()
            from backend.agent.research_safety import assess, require_task, check_reply
            if turn.audit.get('trigger') == 'task_plan' and request.intent == 'ask':
                from backend.services.task_plans import approved_analysis
                deps.safety_assessment = approved_analysis(db, session, turn)
                stopped_reply = None
            else:
                async with public_client(proxy_url=proxy_url) as client:
                    stopped_reply = await assess(_get_service(config_value, client), deps, request.message,
                        session=session, turn=turn, new=request.intent == "new_task")
            audit.update(db.get(AgentTurn, turn_id).audit)
            db.rollback()
            session = service.owned_session(db, session_id, user_id, lock=True)
            turn = db.get(AgentTurn, turn_id, populate_existing=True)
            check_turn(session, turn, attempt, None)
            if stopped_reply is not None:
                turn = db.get(AgentTurn, turn_id)
                audit["resolved_intent"] = "ask"
                audit["diagnostic"] = diagnostic(deps)
                stopped_reply["safety_decision"] = deps.safety_assessment["decision"]
                turn.response = {**stopped_reply, "stream_seq": sequence + 1}
                turn.status = 'needs_input' if stopped_reply.get('missing_requirements') else 'completed'
                if session.research_task_id == turn.research_task_id and stopped_reply.get('missing_requirements'):
                    session.pending_requirements = stopped_reply['missing_requirements']
                    session.phase = 'waiting_input'
                elif session.research_task_id == turn.research_task_id and stopped_reply['safety_decision'] == 'refuse':
                    session.pending_requirements = []
                    session.phase = 'cancel_requested'
                turn.audit = {k: v for k, v in audit.items() if k not in {"checkpoint", "continuation", "pending_review"}}
                db.commit()
                return
            if state.get('research_task_id') != (str(session.research_task_id) if session.research_task_id else None):
                state = service.snapshot(db, session, model_view=True)
                state['turns'] = [t for t in state['turns'] if t['id'] != str(turn_id)]
                if request.module_context is not None:
                    state['module_context'] = request.module_context.model_dump(mode='json')
                deps.session_context = state
                deps.diagnostic_state = {}
                deps.source_read_state = {}
            if request.intent == "new_task":
                session = service.owned_session(db, session_id, user_id, lock=True)
                require_task(db, deps.research_task_id, user_id, deps.safety_assessment["revision"])
                from backend.workflows.commands import design
                draft = design(db, session)
                session.research_task_id = deps.research_task_id
                session.goal = request.message
                session.active_workflow_id = None
                session.preparation_job_id = None
                session.assets, session.confirmed_fields, session.pending_requirements = {}, {}, []
                session.last_error = None
                session.input_revision += 1
                session.phase = "awaiting_upload"
                draft.assets, draft.values, draft.revision = {}, {}, session.input_revision
                turn = db.get(AgentTurn, turn_id)
                turn.audit = {**turn.audit, "resolved_intent": "new_task"}
                turn.response = {"message": interface_text(deps.interface_language, "已新建研究任务。", "New research task created."), "research_task_id": str(deps.research_task_id), "safety_decision": "allow", "stream_seq": sequence + 1}
                turn.status = "completed"
                db.commit()
                return
            if request.attachments and not pending_review:
                session = service.owned_session(db, session_id, user_id, lock=True)
                turn = db.get(AgentTurn, turn_id)
                service.change_inputs(db, session, turn, request.model_copy(update={"intent": "bind", "values": request.attachments}))
                if request.values.get("protein_file_id"):
                    service.change_inputs(db, session, turn, request.model_copy(update={"intent": "select_context", "values": {"protein_file_id": request.values["protein_file_id"]}}))
                deps.committed_effects = _merge_committed_effects(
                    turn.audit.get("committed_effects", []), deps.committed_effects)
                audit.update(execution_revision=session.input_revision,
                    committed_effects=list(deps.committed_effects))
                turn.audit = {**turn.audit, **audit}
                revision = session.input_revision
                scientific_snapshot = service.fingerprint(db, session)
                deps.session_context = state = service.snapshot(db, session, model_view=True)
                context_id = session.assets.get("protein_context_id")
                workflow_id = session.active_workflow_id
                deps.workflow_id = workflow_id
                deps.protein_context_id = uuid.UUID(context_id) if context_id else None
                db.commit()
            db.rollback()
            reply, response, decision = {}, None, None
            if pending_review:
                stage = 'candidate_validation'
                if (pending_review['revision'] != revision or pending_review['fingerprint'] != scientific_snapshot
                        or pending_review['research_task_id'] != str(deps.research_task_id)):
                    raise WorkflowError('INPUT_CHANGED', 'Candidate inputs changed; send a new message', 409)
                saved_workflow = pending_review.get('workflow')
                task = db.get(ResearchTask, deps.research_task_id)
                if (pending_review['preferences'] != (task.workflow_preferences or {})
                        or (saved_workflow['id'] if saved_workflow else None) != (str(session.active_workflow_id) if session.active_workflow_id else None)):
                    raise WorkflowError('INPUT_CHANGED', 'Scientific choices or active workflow changed; send a new message', 409)
                if saved_workflow:
                    current = owned_workflow(db, uuid.UUID(saved_workflow['id']), user_id)
                    if current.plan_version != saved_workflow['version'] or current.plan_hash != saved_workflow['hash']:
                        raise WorkflowError('PLAN_CHANGED', 'Candidate plan changed; send a new message', 409)
                request = SessionTurnRequest.model_validate(pending_review['request'])
                decision = SessionDecision.model_validate(pending_review['decision']) if pending_review.get('decision') else None
                response = AgentResponse.model_validate(pending_review['response']) if pending_review.get('response') else None
                reply = deepcopy(pending_review['reply'])
                deps.response_facts = deepcopy(pending_review['facts'])
                deps.reference_content = deepcopy(pending_review['references'])
                deps.base_plan_version = pending_review['base_plan_version']
                audit['resolved_intent'] = request.intent
                if response and response.plan_valid and request.intent == 'plan':
                    claim = claim_planning_request(db, owner_user_id=user_id, client_request_id=command_turn_id,
                        message=request.message, protein_context_id=uuid.UUID(context_id), retry=True)
                    if not claim.should_run:
                        raise WorkflowError('PLANNING_ALREADY_CLAIMED', 'The planning request is already active', 409)
                    planning_attempt, planning_request_id = claim.request.attempt, claim.request.id
                    claim.request.research_task_id = deps.research_task_id
                    db.get(AgentTurn, turn_id).planning_request_id = planning_request_id
                    db.commit()
            if checkpoint and not pending_review:
                stage = 'checkpoint_validation'
                if checkpoint["revision"] != revision or checkpoint["fingerprint"] != scientific_snapshot:
                    raise WorkflowError("INPUT_CHANGED", "Checkpoint inputs changed; send a new message", 409)
                saved_workflow = checkpoint.get("workflow")
                if saved_workflow:
                    current = owned_workflow(db, uuid.UUID(saved_workflow["id"]), user_id)
                    if current.plan_version != saved_workflow["version"] or current.plan_hash != saved_workflow["hash"]:
                        raise WorkflowError("PLAN_CHANGED", "Checkpoint plan changed; send a new message", 409)
                request = SessionTurnRequest.model_validate(checkpoint["request"])
                decision = SessionDecision.model_validate(checkpoint["decision"])
                error = decision.instruction_error(request.message, trusted_completion=bool(trigger),
                    action_requested=(deps.safety_assessment or {}).get('answer_only') is False)
                if error:
                    raise WorkflowError(error, "Checkpoint instruction is no longer valid", 422)
                audit["resolved_intent"] = decision.operation
                reply = decision.model_dump(mode="json")
            if not checkpoint and not pending_review and request.intent in {"auto", "ask"}:
                async with public_client(proxy_url=proxy_url) as client:
                    if autonomous:
                        reply, model_audit = await answer(_get_service(config_value, client), deps, request.message, state, autonomous=True, trusted_completion=bool(trigger))
                    else:
                        reply, model_audit = await answer(_get_service(config_value, client), deps, request.message, state)
                audit.update(model_audit)
                if autonomous and not reply.get("error_code"):
                    decision = SessionDecision.model_validate(model_audit.get("model_decision") or
                        {k: v for k, v in reply.items() if k in SessionDecision.model_fields})
                    decision_error = decision.instruction_error(request.message, trusted_completion=bool(trigger),
                        action_requested=(deps.safety_assessment or {}).get('answer_only') is False)
                    if decision_error:
                        raise WorkflowError(decision_error, "Model decision did not satisfy the instruction contract", 422)
                    request = request.model_copy(update={"intent": decision.operation, "values": decision.values,
                        "selection": decision.selection, "task_plan": decision.task_plan})
                    audit["resolved_intent"] = decision.operation
            if decision and decision.operation == "retry_postprocessing" and session.active_workflow_id:
                operation = service.postprocessing_operation(db, session)
                decision = decision.model_copy(update={"operation": operation})
                request = request.model_copy(update={"intent": operation})
                audit["resolved_intent"] = operation
            stage = "decision"
            if decision and getattr(deps, "budget_exceeded", False) and (decision.assets or decision.values or request.intent not in {"ask", "plan", "modify", "prepare", "retry_postprocessing"}):
                raise WorkflowError("AGENT_OUTPUT_LIMIT", "Completed output exceeded budget; no scientific change was applied", 409)
            if deps.safety_assessment.get("answer_only") and request.intent not in {"ask", "auto"}:
                raise WorkflowError("RESEARCH_TASK_READ_ONLY", "Only safe explanatory help is available for this request", 409)
            if decision and request.intent != "ask" and not checkpoint and not pending_review:
                if snapshot_error:
                    raise snapshot_error
                db.rollback()
                session = service.owned_session(db, session_id, user_id, lock=True)
                turn = db.get(AgentTurn, turn_id, populate_existing=True)
                check_turn(session, turn, attempt, revision)
                if service.fingerprint(db, session) != scientific_snapshot:
                    raise WorkflowError("INPUT_CHANGED", "Session inputs changed during this turn", 409)
                if session.phase in {"cancel_requested", "canceled", "archived"}:
                    raise WorkflowError("SESSION_BUSY", "Wait for the running task before changing its inputs", 409)
                require_task(db, deps.research_task_id, user_id, deps.safety_assessment["revision"])
                stage = 'input_binding'
                if decision.assets:
                    service.change_inputs(db, session, turn, request.model_copy(update={"intent": "bind", "values": decision.model_dump(mode="json")["assets"]}))
                    deps.committed_effects = _merge_committed_effects(
                        turn.audit.get("committed_effects", []), deps.committed_effects)
                    audit.update(execution_revision=session.input_revision,
                        committed_effects=list(deps.committed_effects))
                    turn.audit = {**turn.audit, **audit}
                if request.values and request.intent != "select_context":
                    service.change_inputs(db, session, turn, request.model_copy(update={"intent": "select_context"}))
                    deps.committed_effects = _merge_committed_effects(
                        turn.audit.get("committed_effects", []), deps.committed_effects)
                    audit.update(execution_revision=session.input_revision,
                        committed_effects=list(deps.committed_effects))
                    turn.audit = {**turn.audit, **audit}
                revision = session.input_revision
                scientific_snapshot = service.fingerprint(db, session)
                context_id = session.assets.get("protein_context_id")
                workflow_id = session.active_workflow_id
                deps.protein_context_id = uuid.UUID(context_id) if context_id else None
                deps.workflow_id = workflow_id
                deps.postprocessing_options = service.session_values(session)
                deps.committed_effects = list(turn.audit.get("committed_effects", deps.committed_effects))
                checkpoint = {"request": request.model_dump(mode="json"), "decision": decision.model_dump(mode="json"),
                    "revision": revision, "fingerprint": scientific_snapshot}
                if workflow_id:
                    current = owned_workflow(db, workflow_id, user_id)
                    checkpoint["workflow"] = {"id": str(current.id), "version": current.plan_version, "hash": current.plan_hash}
                audit.update(checkpoint=checkpoint, execution_revision=revision, committed_effects=list(deps.committed_effects))
                audit["diagnostic"] = diagnostic(deps)
                turn.audit = dict(audit)
                db.commit()
                deps.session_context = service.snapshot(db, session, model_view=True)
            if not pending_review and request.intent in {"plan", "modify"}:
                stage = "planning"
                current_plan = WorkflowPlan.model_validate(owned_workflow(db, workflow_id, user_id).plan_json) if request.intent == "modify" and workflow_id else None
                zh = deps.interface_language == "zh"
                if not context_id:
                    reply = prerequisite_reply("prepared_context", zh)
                elif request.intent == "modify" and not workflow_id:
                    reply = prerequisite_reply("pending_plan", zh)
                else:
                    validate_protein_context_for_generation(db, user_id, uuid.UUID(context_id))
                    if request.intent == "plan":
                        deps.workflow_id = None
                        claim = claim_planning_request(db, owner_user_id=user_id, client_request_id=command_turn_id,
                            message=request.message, protein_context_id=uuid.UUID(context_id), retry=attempt > 1 or bool(audit.get("recovery_of")))
                        if not claim.should_run:
                            raise WorkflowError("PLANNING_ALREADY_CLAIMED", "The planning request is already active", 409)
                        planning_attempt, planning_request_id = claim.request.attempt, claim.request.id
                        claim.request.research_task_id = deps.research_task_id
                        db.get(AgentTurn, turn_id).planning_request_id = planning_request_id
                        db.commit()
                    else:
                        run_state = owned_workflow(db, workflow_id, user_id)
                        deps.base_plan_version = run_state.plan_version
                    db.rollback()
                    if decision and decision.quantity_patch is not None:
                        from backend.workflows.commands import patch_plan
                        field = "target_num_molecules" if current_plan.generator == "ecloudgen" else "num_molecules"
                        patched = patch_plan(current_plan.model_dump(mode="json"), {"generation": {field: decision.quantity_patch}})
                        from backend.agent.schemas import calculate_plan_hash
                        patched_hash = calculate_plan_hash(patched)
                        reuse = run_state.status == "awaiting_approval"
                        response = AgentResponse(message=decision.message, plan_valid=True, normalized_plan=patched,
                            workflow_id=run_state.id if reuse else uuid.uuid4(),
                            plan_version=run_state.plan_version + (patched_hash != run_state.plan_hash) if reuse else 1,
                            plan_hash=patched_hash)
                    else:
                        async with public_client(proxy_url=proxy_url) as client:
                            response = await _get_service(config_value, client).plan(deps, request.message,
                                AgentPageContext(page="protein_context", protein_context_id=context_id,
                                    workflow_id=str(deps.workflow_id) if deps.workflow_id else None), mode=request.intent)
                    plan_reply = present_agent_response(response).model_dump(mode="json")
                    reply = plan_reply
            if decision and decision.future_selection and response and response.plan_valid and response.normalized_plan:
                from backend.agent.schemas import ResultSelection,calculate_plan_hash
                selected=ResultSelection(**{key:value for key,value in decision.future_selection.model_dump().items()
                    if key in ResultSelection.model_fields})
                selected_plan=response.normalized_plan.model_copy(update={'selection':selected})
                response=response.model_copy(update={'normalized_plan':selected_plan,'plan':selected_plan,
                    'plan_hash':calculate_plan_hash(selected_plan)})
                reply=present_agent_response(response).model_dump(mode='json')
            if deps.model_decision:
                audit['model_decision'] = deps.model_decision
            if deps.decision_validation_errors:
                audit['decision_validation_errors'] = deps.decision_validation_errors
            if reply.get('error_code'):
                reply.setdefault('error_stage', 'decision' if request.intent in {'auto', 'ask'} else stage)
            if request.intent != 'ask' and not reply.get('error_code'):
                session = service.owned_session(db, session_id, user_id, lock=True)
                turn = db.get(AgentTurn, turn_id, populate_existing=True)
                check_turn(session, turn, attempt, revision)
                if service.fingerprint(db, session) != scientific_snapshot:
                    raise WorkflowError('INPUT_CHANGED', 'Inputs changed before candidate review', 409)
                current = owned_workflow(db, session.active_workflow_id, user_id) if session.active_workflow_id else None
                task = db.get(ResearchTask, deps.research_task_id)
                from backend.agent.sources import bounded_facts
                audit['pending_review'] = {'revision': revision, 'fingerprint': scientific_snapshot,
                    'research_task_id': str(deps.research_task_id), 'request': request.model_dump(mode='json'),
                    'preferences': deepcopy(task.workflow_preferences or {}),
                    'decision': decision.model_dump(mode='json') if decision else None,
                    'response': response.model_dump(mode='json') if response else None, 'reply': reply,
                    'facts': bounded_facts(deps.response_facts), 'references': deps.reference_content,
                    'base_plan_version': deps.base_plan_version,
                    'workflow': {'id': str(current.id), 'version': current.plan_version, 'hash': current.plan_hash} if current else None}
                turn.audit = {**turn.audit, **audit}
                db.commit()
            stage = 'output_evidence'
            if decision and not deps.safety_assessment.get('answer_only'):
                reply['_candidate_decision'] = decision.model_dump(mode='json')
            async with public_client(proxy_url=proxy_url) as client:
                reply = await check_reply(_get_service(config_value, client), deps, request.message, reply)
                correction = reply.pop('_plan_correction', None)
                if correction and decision:
                    from backend.agent.preparation import repair_stage_decision
                    if correction.get('site_request') and response and response.plan_valid and decision.generation_request is None:
                        decision.generation_request = response.normalized_plan.generation
                    decision = repair_stage_decision(deps, decision, correction, request.message)
                    decision.message = reply['message']
                    if response and response.plan_valid:
                        if decision.operation == 'ask':
                            response = None
                            reply.pop('normalized_plan', None)
                            reply['plan_valid'] = False
                        else:
                            from backend.workflows.commands import patch_plan
                            from backend.agent.schemas import calculate_plan_hash
                            changes = {}
                            if 'prefilter_request' in correction:
                                changes['postprocessing'] = {'prefilters': correction['prefilter_request']}
                            if correction.get('generation_request'):
                                changes.update(generator=correction['generation_request']['engine'], generation=correction['generation_request'])
                            revised = patch_plan(response.normalized_plan.model_dump(mode='json'), changes)
                            response = response.model_copy(update={'normalized_plan': revised, 'plan': revised, 'plan_hash': calculate_plan_hash(revised)})
                            reply.update(normalized_plan=revised.model_dump(mode='json'), plan_hash=response.plan_hash)
                    error = decision.instruction_error(request.message, trusted_completion=bool(trigger),
                        action_requested=deps.safety_assessment.get('answer_only') is False)
                    if error:
                        raise WorkflowError(error, 'The revised draft requires a valid decision', 422)
                    request = request.model_copy(update={'intent': decision.operation, 'values': decision.values,
                        'task_plan': decision.task_plan, 'selection': decision.selection})
                    audit['model_decision'] = decision.model_dump(mode='json')
                    audit['resolved_intent'] = decision.operation
                    deps.model_decision = audit['model_decision']
                    if audit.get('checkpoint'):
                        audit['checkpoint'] = {**audit['checkpoint'], 'request': request.model_dump(mode='json'),
                            'decision': decision.model_dump(mode='json')}
                    reply.update(decision.model_dump(mode='json'))
                    reply['_candidate_decision'] = decision.model_dump(mode='json')
                    reply = await check_reply(_get_service(config_value, client), deps, request.message, reply)
                    if reply.pop('_plan_correction', None):
                        raise WorkflowError('AGENT_DECISION_INVALID', 'The draft still conflicts with the requested settings', 422)
            reply.pop('_candidate_decision', None)
            if reply.get('message') and not reply.get('error_code'):
                # After the last reply check, which may replace the message; before it is copied into the saved plan response.
                from backend.agent.reply_guards import final_guards
                reply['message'] = final_guards(reply['message'], deps, decision=decision, response=response,
                                                user_message=request.message, trigger=trigger)
                if ((deps.session_context or {}).get('assets') or {}).get('module_assistant'):
                    # A side-assistant reply that states values for editable fields carries them as fill-in cards.
                    from backend.agent.module_assistant import complete_suggestions
                    async with public_client(proxy_url=proxy_url) as client:
                        added = await complete_suggestions(_get_service(config_value, client), deps, request.message, reply)
                    if added:
                        reply['module_suggestions'] = added
                        audit['suggestion_pass'] = {'added': len(added)}
            if response:
                response = response.model_copy(update={"message": reply["message"], "diagnostic_notes": reply["diagnostic_notes"]})
            db.rollback()
            stage = 'persistence'
            session = service.owned_session(db, session_id, user_id, lock=True)
            turn = db.get(AgentTurn, turn_id, populate_existing=True)
            stated = stated_choices(decision, request.intent, reply)
            mutating_settings = decision and (decision.site_request is not None or decision.prefilter_request is not None or stated)
            check_turn(session, turn, attempt, revision if request.intent != "ask" or mutating_settings else None)
            require_task(db, deps.research_task_id, user_id, deps.safety_assessment["revision"], read_only=request.intent == "ask" and deps.safety_assessment.get("answer_only", False))
            if (request.intent != "ask" or mutating_settings) and (session.phase in {"canceled", "cancel_requested", "archived"} or service.fingerprint(db, session) != scientific_snapshot):
                raise WorkflowError("INPUT_CHANGED", "Session inputs changed during this turn", 409)
            if time.monotonic() >= deadline:
                raise TimeoutError("Turn deadline expired before persistence")
            if getattr(deps, "budget_exceeded", False) and request.intent not in {"ask", "plan", "modify", "prepare", "retry_postprocessing"}:
                raise WorkflowError("AGENT_OUTPUT_LIMIT", "Completed output exceeded budget; no scientific change was applied", 409)
            if request.intent != "ask":
                if deps.safety_assessment.get("answer_only"):
                    raise WorkflowError("RESEARCH_TASK_READ_ONLY", "Only safe explanatory help is available", 409)
                require_task(db, deps.research_task_id, user_id, deps.safety_assessment["revision"])
            if decision and decision.postprocessing_choice and not turn.audit.get("postprocessing_choice"):
                if deps.safety_assessment.get('answer_only'):
                    raise WorkflowError('RESEARCH_TASK_READ_ONLY', 'An explanation cannot change postprocessing preferences', 409)
                audit["postprocessing_choice"] = service.record_postprocessing_choice(
                    db, session, turn, decision.postprocessing_choice, decision.postprocessing_evidence
                )
            if decision and decision.preference_request and not turn.audit.get("preferences_saved"):
                from backend.agent.user_settings import save_work_preferences
                saved, skipped = save_work_preferences(db, user_id, [item.text for item in decision.preference_request])
                audit["preferences_saved"] = saved
                if saved:
                    deps.committed_effects = _merge_committed_effects(deps.committed_effects, [{"kind": "work_preferences_saved", "count": len(saved)}])
                if skipped:
                    zh = deps.interface_language == "zh"
                    note = ("未保存：已达到 20 条偏好上限，请先在设置里删除不需要的偏好。" if zh
                        else "Not saved: the limit of 20 saved preferences is reached. Delete one in Settings first.")
                    reply["message"] = f"{reply['message']}\n\n{note}" if saved else note
            if decision and (decision.site_request is not None or decision.prefilter_request is not None or stated or request.intent != 'ask' and (decision.generation_request or decision.future_selection)):
                if deps.safety_assessment.get('answer_only'):
                    raise WorkflowError('RESEARCH_TASK_READ_ONLY', 'An explanation cannot change draft parameters', 409)
                task=db.get(ResearchTask,deps.research_task_id)
                future=decision.task_plan.workflow if decision.task_plan else None
                preferences=dict(task.workflow_preferences or {})
                if decision.site_request is not None:
                    from backend.services.task_plans import require_editable
                    require_editable(db, session, turn)
                    preferences['site_request'] = decision.site_request.model_dump(mode='json')
                    session.pending_requirements = list(dict.fromkeys([*session.pending_requirements, 'site']))
                    if request.intent == 'ask' and any(session.assets.get(key) for key in ('protein_context_id', 'prepared_receptor_id')):
                        session.phase = 'awaiting_site'
                        if task.task_plan and task.task_plan['state'] in {'awaiting_approval', 'paused', 'blocked'}:
                            task.task_plan = {**task.task_plan, 'state': 'canceled'}
                            for proposal in db.scalars(select(ActionProposal).where(ActionProposal.session_id == session.id, ActionProposal.status == 'pending')):
                                proposal.status = 'stale'
                if decision.prefilter_request is not None:
                    preferences['postprocessing'] = {**preferences.get('postprocessing', {}),
                        'prefilters': [rule.model_dump(mode='json') for rule in decision.prefilter_request]}
                record_generation_choices(preferences, decision, future, stated=stated,
                    plan_version=(task.task_plan or {}).get('version', 0), optimization_seed=session.assets.get('optimization_seed'))
                task.workflow_preferences=preferences
            if response and response.plan_valid and response.normalized_plan:
                from backend.workflows.commands import save_plan
                saved = save_plan(db, session, turn, response.normalized_plan,
                    expected_plan_version=deps.base_plan_version or None, new=request.intent == "plan",
                    create_workflow_id=response.workflow_id)
                draft = owned_workflow(db, uuid.UUID(saved["workflow_id"]), user_id)
                record_workflow_interaction(db, run=draft, interaction_type=request.intent, user_message=request.message,
                    assistant_message=response.message, base_plan_version=deps.base_plan_version)
                if planning_attempt:
                    link_planning_workflow(db, owner_user_id=user_id, client_request_id=command_turn_id, attempt=planning_attempt, workflow_id=draft.id)
                    turn.planning_request_id = planning_request_id
                reply.update(saved, plan_hash=draft.plan_hash, message=response.message)
            elif planning_attempt:
                mark_planning_failed(db, owner_user_id=user_id, client_request_id=command_turn_id, attempt=planning_attempt,
                    error_code=reply.get("error_code") or "PLANNING_INCOMPLETE")
            elif request.intent not in {"ask", "plan", "modify", "auto"}:
                action_request = request.model_copy(update={"values": decision.model_dump(mode="json")["assets"]}) if decision and request.intent == "bind" else request
                stage = "action"
                result = service.execute_action(db, session, turn, action_request)
                explanation = reply.get("message", "")
                reply = {**reply, **result, "message": result["message"] + ("\n\n" + explanation if explanation else "")}
                deps.committed_effects = list(turn.audit.get("committed_effects", deps.committed_effects))
            stopped = service.continuation_stopped(db, session.id, turn.created_at, research_task_id=deps.research_task_id)
            if decision and decision.remaining_goal and not deps.safety_assessment.get('answer_only') and not stopped and not getattr(deps, "budget_exceeded", False) and (request.intent != "ask" or reply.get("missing_requirements")):
                audit["continuation"] = {"goal": decision.remaining_goal, "source_turn_id": str(turn_id), "revision": session.input_revision}
            elif trigger or stopped:
                audit.pop("continuation", None)
            audit["committed_effects"] = list(deps.committed_effects)
            audit.pop('pending_review', None)
            audit["execution_revision"] = session.input_revision
            audit["tools"] = deps.tool_audit
            audit["diagnostic"] = diagnostic(deps)
            audit['diagnostic_state'] = deps.diagnostic_state
            audit['source_read_state'] = deps.source_read_state
            from backend.agent.research_safety import diagnostic_notes
            reply["diagnostic_notes"] = diagnostic_notes(deps)
            reply["warnings"] = [w for w in diagnostic(deps)["warnings"] if not reply.get("error_code") or w != "budget_exceeded_after_completion"]
            reply = {k: v for k, v in reply.items() if k not in {"operation", "command_evidence", "values", "assets", "remaining_goal", "quantity_patch", "postprocessing_choice", "postprocessing_evidence", "preparation_request", "generation_request", "future_selection", "site_request", "prefilter_request", "preference_request"}}
            if reply.get("error_code"):
                reply = {**failure_details(reply["error_code"]), **reply, "error_stage": reply.get('error_stage') or stage, "trace_id": deps.trace_id, "committed_effects": deps.committed_effects}
                failure = deps.stages[-1].get("failure", {}) if deps.stages else {}
                if failure.get("error_code") == reply["error_code"]:
                    reply.update(failure)
            from backend.agent.clarification import presentation_fields
            reply["clarification_fields"] = presentation_fields(reply.get("missing_requirements", []), reply.get("clarification_fields", []))
            if deps.safety_assessment.get('task_state') == 'blocked':
                for key in ('missing_requirements', 'clarification_fields', 'module_suggestions', 'input_query'):
                    reply.pop(key, None)
            turn.response = {**reply, "safety_decision": deps.safety_assessment["decision"], "stream_seq": sequence + 1, "tools": partial_reply["tools"]}
            turn.audit = audit
            turn.status = "needs_input" if reply.get("missing_requirements") else "failed" if reply.get("error_code") else "completed"
            if request.intent != "ask" or reply.get("missing_requirements"):
                session.pending_requirements = reply.get("missing_requirements", [])
            session.updated_at = utcnow()
            if session.phase == 'ready_for_planning':
                db.flush()
                service.reconcile_session(db, session)
            db.commit()

    async def watch_stop():
        while True:
            await asyncio.sleep(0.5)
            with SessionLocal() as db:
                current = db.execute(select(AgentTurn.status, AgentTurn.attempt).where(AgentTurn.id == turn_id)).one_or_none()
                if current is None or current.status != "running" or current.attempt != attempt:
                    raise WorkflowError("TURN_INTERRUPTED", "This turn is no longer active", 409)

    tasks = [asyncio.create_task(run()), asyncio.create_task(watch_stop())]
    try:
        try:
            done, _ = await asyncio.wait(tasks, timeout=max(0, deadline - time.monotonic()), return_when=asyncio.FIRST_COMPLETED)
            if not done:
                raise TimeoutError("Turn deadline expired")
            for task in done:
                task.result()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as exc:
        if not (isinstance(exc, WorkflowError) and exc.code == "TURN_INTERRUPTED"):
            log_failure(logger, exc, session_id=str(session_id), turn_id=str(turn_id), attempt=attempt, stage=stage)
        with SessionLocal() as db:
            session = service.owned_session(db, session_id, user_id, lock=True)
            turn = db.get(AgentTurn, turn_id)
            if turn.attempt == attempt and turn.status == "running":
                details = exception_details(exc)
                code = details["error_code"]
                turn.response = _failed_turn_response(turn, deps, details, stage=stage,
                    turn_id=turn_id, attempt=attempt, sequence=sequence, partial_reply=partial_reply)
                committed_effects = turn.response["committed_effects"]
                for step in partial_reply["tools"]:
                    if step["status"] == "running":
                        step.update(status="failed", **details)
                turn.response = {**turn.response, "tools": partial_reply["tools"]}
                if deps:
                    deps.committed_effects = committed_effects
                    turn.audit = {**turn.audit, "tools": list(deps.tool_audit),
                                  'model_decision': deps.model_decision or turn.audit.get('model_decision'),
                                  'decision_validation_errors': deps.decision_validation_errors,
                                  "committed_effects": committed_effects,
                                  "diagnostic": diagnostic(deps), "diagnostic_state": deps.diagnostic_state, "source_read_state": deps.source_read_state}
                    if deps.decision_validation_errors:
                        turn.response = {**turn.response, 'validation_errors': deps.decision_validation_errors}
                turn.status = "failed"
                if turn.audit.get('pending_review') and stage == 'output_evidence':
                    turn.response = {**turn.response, 'review_pending': True, 'retryable': True,
                        'recovery_action': 'retry_once_then_switch_model',
                        'message': ('候选方案已保留，最终检查未完成。请重试检查；当前尚未提交可审批方案。'
                            if deps.interface_language == 'zh'
                            else 'The candidate draft is preserved, but the final check is incomplete. Retry the check; no approvable plan has been submitted.')}
                investigating = deps and (any(s.metadata.name == 'failure-triage' for s in deps.active_skills) or any(
                    t['tool'] in {'get_job_diagnostics', 'read_job_diagnostic'} for t in deps.tool_audit))
                if deps and (investigating and deps.diagnostic_state or deps.source_read_state) and not deps.committed_effects and stage in {'model', 'decision'} and code in {
                    'AGENT_TOOL_LIMIT', 'AGENT_REQUEST_LIMIT', 'AGENT_OUTPUT_LIMIT', 'AGENT_TURN_TIMEOUT', 'AGENT_CONTEXT_TOO_LARGE', 'AGENT_USAGE_UNKNOWN'}:
                    from backend.agent.diagnostics import paused_reply
                    turn.response = {**paused_reply(deps, code), 'stream_seq': sequence + 1}
                    turn.status = 'completed'
                if planning_attempt:
                    mark_planning_failed(db, owner_user_id=user_id, client_request_id=command_turn_id, attempt=planning_attempt, error_code=code)
                db.commit()
    with SessionLocal() as db:
        turn = db.get(AgentTurn, turn_id)
        if turn and turn.attempt == attempt:
            publish_turn(user_id, {**service.turn_out(turn), "session_id": str(session_id)})


def check_turn(session, turn, attempt, revision):
    if turn.attempt != attempt or turn.status != "running" or turn.lease_until.replace(tzinfo=timezone.utc) <= utcnow():
        raise WorkflowError("TURN_INTERRUPTED", "This turn is no longer active", 409)
    if revision is not None and session.input_revision != revision:
        raise WorkflowError("INPUT_CHANGED", "Session inputs changed during this turn", 409)
