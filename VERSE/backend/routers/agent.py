"""Agent planning and user-controlled workflow APIs."""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.agent.catalog import CATALOG
from backend.agent.deps import AgentDeps
from backend.agent.errors import error_source_for, recovery_action_for
from backend.agent.knowledge import InMemoryKnowledgeProvider
from backend.agent.knowledge.base import KnowledgeProvider
from backend.agent.presentation import AgentPlanResponse, present_agent_response
from backend.agent.safety import PromptBlocked, normalize_and_check_prompt
from backend.agent.schemas import (
    AgentRequest,
    AgentResponse,
    AgentRuntimeOut,
    AgentPageContext,
    WorkflowApproveRequest,
    WorkflowInteractionRequest,
    WorkflowListItem,
    WorkflowOut,
    WorkflowPlan,
)
from backend.agent.service import AgentService
from backend.agent.user_settings import personal_config, personal_proxy, public_client
from backend.agent.runner import Budget
from backend.agent.skills import SkillRegistry
from backend.config import settings
from backend.db import SessionLocal, get_db
from backend.deps import get_current_user
from backend.models import User, WorkflowPlanningRequest
from backend.utils import utcnow
from backend.services.jobs import DomainValidationError, validate_protein_context_for_generation
from backend.services.workflows import (
    MAX_WORKFLOW_INTERACTIONS,
    RECENT_CONTEXT_INTERACTIONS,
    WorkflowError,
    approve_workflow,
    cancel_workflow,
    claim_planning_request,
    get_planning_request,
    link_planning_workflow,
    list_owner_workflows,
    mark_planning_failed,
    owned_workflow,
    planning_request_shape_is_valid,
    persist_workflow_preview,
    public_workflow_status,
    reconcile_stale_planning_requests,
    record_workflow_interaction,
    workflow_interaction_count,
    workflow_out,
)

router = APIRouter(prefix="/agent", tags=["agent"])
logger = logging.getLogger("backend-agent")

# Lazy singletons — created on first request, not at import time.
_knowledge: KnowledgeProvider | None = None
_skill_registry: SkillRegistry | None = None
_skill_registry_warning: str | None = None
_shielded_tasks: set[asyncio.Task[AgentPlanResponse]] = set()
_active_planning_requests: set[tuple[uuid.UUID, uuid.UUID]] = set()


def _get_skill_registry() -> SkillRegistry | None:
    """Return the singleton SkillRegistry, exposing initialization failure as a warning."""
    global _skill_registry, _skill_registry_warning
    if _skill_registry is None:
        from pathlib import Path
        skills_root = Path(__file__).resolve().parent.parent / "agent" / "skills"
        try:
            _skill_registry = SkillRegistry.from_directory(skills_root)
            if not _skill_registry.all_skills:
                _skill_registry_warning = "SKILL_REGISTRY_UNAVAILABLE"
            else:
                _skill_registry_warning = None
            logger.info("Skill registry loaded: %d skill(s)", len(_skill_registry.all_skills))
        except Exception as exc:
            _skill_registry_warning = "SKILL_REGISTRY_UNAVAILABLE"
            logger.warning("Failed to load skill registry: %s", exc)
            return None
    return _skill_registry


def _get_service(config, client) -> AgentService:
    registry = _get_skill_registry()
    startup_warnings = [_skill_registry_warning] if _skill_registry_warning else []
    return AgentService(**{"provider": "openai-compatible", **{key: value for key, value in config.items() if key != 'context_window'}}, http_client=client,
                        catalog=CATALOG, skill_registry=registry, startup_warnings=startup_warnings)


def _get_knowledge() -> KnowledgeProvider | None:
    """Return the singleton KnowledgeProvider, creating it on first call.

    Backend is selected by KNOWLEDGE_BACKEND env var:
      "memory"   — InMemoryKnowledgeProvider (test/dev, resets on restart)
      "postgres" — PostgresKnowledgeProvider (production, persists across restarts)
      "none"     — No RAG (knowledge=None, planning proceeds without RAG)
    """
    global _knowledge
    if _knowledge is None:
        backend = settings.knowledge_backend
        if backend == "postgres":
            from backend.db import SessionLocal
            from backend.agent.knowledge.postgres_provider import PostgresKnowledgeProvider
            _knowledge = PostgresKnowledgeProvider(SessionLocal)
            logger.info("Knowledge provider: PostgresKnowledgeProvider")
        elif backend == "memory":
            _knowledge = InMemoryKnowledgeProvider()
            logger.info("Knowledge provider: InMemoryKnowledgeProvider (no persistence)")
        elif backend == "none":
            logger.info("Knowledge provider: disabled")
            return None
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error_code": "AGENT_KNOWLEDGE_CONFIG_ERROR",
                    "error_source": "configuration",
                    "recovery_action": "contact_maintainer",
                    "message": "KNOWLEDGE_BACKEND must be memory, postgres, or none",
                },
            )
    return _knowledge


def _workflow_http_error(exc: WorkflowError) -> HTTPException:
    if exc.code == "RESOURCE_FORBIDDEN":
        exc = WorkflowError("RESOURCE_NOT_FOUND", "Workflow not found", 404)
    return HTTPException(
        status_code=exc.http_status,
        detail={"error_code": exc.code, "error_source": error_source_for(exc.code), "recovery_action": recovery_action_for(exc.code), "message": exc.message},
    )


def _prompt_http_error(exc: PromptBlocked) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"error_code": "PROMPT_BLOCKED", "error_source": "harness", "recovery_action": "revise_request", "category": exc.category, "message": exc.reason},
    )


async def _shielded(
    factory: Callable[[], Awaitable[AgentPlanResponse]],
    *,
    planning_key: tuple[uuid.UUID, uuid.UUID] | None = None,
) -> AgentPlanResponse:
    """Run planning + persistence even if the browser refreshes mid-request.

    A page refresh cancels the HTTP task; shield keeps the inner task alive so
    the step is still committed and appears in durable history.
    """
    task = asyncio.create_task(factory())
    _shielded_tasks.add(task)
    if planning_key is not None:
        _active_planning_requests.add(planning_key)
    client_disconnected = False

    def _finish(done: asyncio.Task) -> None:
        _shielded_tasks.discard(done)
        if planning_key is not None:
            _active_planning_requests.discard(planning_key)
        if done.cancelled():
            return
        exc = done.exception()
        if exc is not None and client_disconnected:
            logger.warning("Shielded agent run failed after client disconnect: %s", exc)

    task.add_done_callback(_finish)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        client_disconnected = True
        raise


def _planning_response(db: Session, row: WorkflowPlanningRequest) -> AgentPlanResponse:
    if not planning_request_shape_is_valid(row):
        raise WorkflowError(
            "PLANNING_INTEGRITY_ERROR",
            "The saved planning request is inconsistent and needs maintainer review",
            409,
        )
    if row.status == "linked" and row.workflow_id is not None:
        try:
            run = owned_workflow(db, row.workflow_id, row.owner_user_id)
            plan = WorkflowPlan.model_validate(run.plan_json)
        except (WorkflowError, ValueError) as exc:
            raise WorkflowError(
                "PLANNING_INTEGRITY_ERROR",
                "The saved planning request no longer has a valid workflow",
                409,
            ) from exc
        return present_agent_response(AgentResponse(
            message="This planning request already has a workflow.",
            plan=plan,
            normalized_plan=plan,
            plan_valid=True,
            workflow_id=run.id,
            plan_version=run.plan_version,
            plan_hash=run.plan_hash,
            interaction_type="plan",
            refinement_state=getattr(run, "refinement_state", None) or "awaiting_feedback",
            client_request_id=row.client_request_id,
            planning_status=public_workflow_status(run.status),
            attempt=row.attempt,
        ))

    interrupted = row.status == "interrupted"
    failed = row.status == "failed"
    return present_agent_response(AgentResponse(
        message=(
            "The previous planning attempt was interrupted and can be retried."
            if interrupted
            else "Planning failed. Retry this request or start a new one."
            if failed
            else "Planning is already in progress."
        ),
        error_code=row.last_error or ("PLANNING_FAILED" if failed else None),
        client_request_id=row.client_request_id,
        planning_status=row.status,
        attempt=row.attempt,
        retryable=interrupted or failed,
    ))


def _domain_http_error(exc: DomainValidationError) -> HTTPException:
    return HTTPException(
        status_code=exc.http_status,
        detail={"error_code": exc.code, "error_source": error_source_for(exc.code), "recovery_action": recovery_action_for(exc.code), "message": exc.message},
    )


@router.get("/runtime", response_model=AgentRuntimeOut)
def runtime_capabilities(current_user: User = Depends(get_current_user)) -> AgentRuntimeOut:
    del current_user
    return AgentRuntimeOut(
        max_interactions=MAX_WORKFLOW_INTERACTIONS,
        recent_context_interactions=RECENT_CONTEXT_INTERACTIONS,
    )


@router.post("/plan", response_model=AgentPlanResponse)
async def plan(
    request: AgentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentPlanResponse:
    """Run the planning agent on a user message.

    Returns a structured AgentResponse with an optional WorkflowPlan,
    validation status, missing requirements, and warnings.

    Returns 503 AGENT_NOT_CONFIGURED if the user has not configured an API.
    """
    try:
        message = normalize_and_check_prompt(request.message)
    except PromptBlocked as exc:
        raise _prompt_http_error(exc) from exc

    config = personal_config(db, current_user.id)
    proxy_url = personal_proxy(db, current_user.id)

    if request.context is None or not request.context.protein_context_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "PROTEIN_CONTEXT_REQUIRED",
                "error_source": "harness",
                "recovery_action": "revise_request",
                "message": "Select a prepared Protein Context before planning.",
            },
        )
    try:
        protein_context_id = uuid.UUID(request.context.protein_context_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "INVALID_UUID", "error_source": "harness", "recovery_action": "revise_request", "message": "protein_context_id is not a valid UUID"},
        ) from exc

    if request.context.workflow_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "USE_WORKFLOW_INTERACTIONS",
                "error_source": "workflow",
                "recovery_action": "refresh_workflow",
                "message": "Use the workflow interaction endpoint for questions or plan modifications.",
            },
        )

    try:
        validate_protein_context_for_generation(db, current_user.id, protein_context_id)
    except DomainValidationError as exc:
        raise _domain_http_error(exc) from exc

    knowledge = _get_knowledge()
    user_id = current_user.id
    page_context = request.context
    client_request_id = request.client_request_id
    planning_key = (user_id, client_request_id)

    with SessionLocal() as planning_session:
        reconcile_stale_planning_requests(
            planning_session,
            active_requests=_active_planning_requests,
        )
        planning_session.commit()
        try:
            claim = claim_planning_request(
                planning_session,
                owner_user_id=user_id,
                client_request_id=client_request_id,
                message=message,
                protein_context_id=protein_context_id,
                retry=request.retry,
            )
            if not claim.should_run:
                return _planning_response(planning_session, claim.request)
            attempt = claim.request.attempt
        except WorkflowError as exc:
            planning_session.rollback()
            raise _workflow_http_error(exc) from exc

    async def _run_plan() -> AgentPlanResponse:
        # Own session: request teardown on refresh must not roll back progress.
        with SessionLocal() as session:
            try:
                deps = AgentDeps(
                    user_id=user_id,
                    db=session,
                    catalog=CATALOG,
                    workflow_id=None,
                    knowledge=knowledge,
                    protein_context_id=protein_context_id,
                    defer_preview_persistence=True,
                    planning_request_id=claim.request.id,
                    budget=Budget.for_model(config.get("context_window")),
                )
                async with public_client(proxy_url=proxy_url) as client:
                    response = await _get_service(config, client).plan(deps, message, page_context, mode="plan")
                if response.plan_valid and response.workflow_id is not None:
                    from backend.agent.research_safety import require_task
                    require_task(session, deps.research_task_id, user_id, deps.safety_assessment["revision"])
                    if deps.preview_candidates:
                        draft = persist_workflow_preview(
                            session, owner_user_id=user_id, plan=deps.preview_candidates[-1],
                            create_workflow_id=response.workflow_id,
                        )
                        draft.research_task_id = deps.research_task_id
                        response = response.model_copy(update={
                            "workflow_id": draft.id, "plan_version": draft.plan_version,
                            "plan_hash": draft.plan_hash,
                        })
                    run = owned_workflow(session, response.workflow_id, user_id)
                    record_workflow_interaction(
                        session,
                        run=run,
                        interaction_type="plan",
                        user_message=message,
                        assistant_message=response.message,
                        base_plan_version=0,
                    )
                    link_planning_workflow(
                        session,
                        owner_user_id=user_id,
                        client_request_id=client_request_id,
                        attempt=attempt,
                        workflow_id=run.id,
                    )
                    response = response.model_copy(update={
                        "client_request_id": client_request_id,
                        "planning_status": public_workflow_status(run.status),
                        "attempt": attempt,
                        "retryable": False,
                    })
                    session.commit()
                else:
                    session.rollback()
                    marked = mark_planning_failed(
                        session,
                        owner_user_id=user_id,
                        client_request_id=client_request_id,
                        attempt=attempt,
                        error_code=response.error_code or "PLANNING_FAILED",
                    )
                    if not marked:
                        session.rollback()
                        return _planning_response(
                            session,
                            get_planning_request(session, user_id, client_request_id),
                        )
                    session.commit()
                    response = response.model_copy(update={
                        "client_request_id": client_request_id,
                        "planning_status": "failed",
                        "attempt": attempt,
                        "retryable": True,
                    })
            except WorkflowError as exc:
                session.rollback()
                if exc.code == "STALE_PLANNING_ATTEMPT":
                    return _planning_response(
                        session,
                        get_planning_request(session, user_id, client_request_id),
                    )
                marked = mark_planning_failed(
                    session,
                    owner_user_id=user_id,
                    client_request_id=client_request_id,
                    attempt=attempt,
                    error_code=exc.code,
                )
                if not marked:
                    session.rollback()
                    return _planning_response(
                        session,
                        get_planning_request(session, user_id, client_request_id),
                    )
                session.commit()
                raise _workflow_http_error(exc) from exc
            except Exception:
                session.rollback()
                try:
                    mark_planning_failed(
                        session,
                        owner_user_id=user_id,
                        client_request_id=client_request_id,
                        attempt=attempt,
                        error_code="PLANNING_FAILED",
                    )
                    session.commit()
                except Exception:
                    session.rollback()
                    logger.exception("Could not record failed planning request %s", client_request_id)
                raise
            return present_agent_response(response)

    return await _shielded(_run_plan, planning_key=planning_key)


@router.post("/workflows/{workflow_id}/interactions", response_model=AgentPlanResponse)
async def interact(
    workflow_id: uuid.UUID,
    request: WorkflowInteractionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentPlanResponse:
    try:
        message = normalize_and_check_prompt(request.message)
    except PromptBlocked as exc:
        raise _prompt_http_error(exc) from exc
    config = personal_config(db, current_user.id)
    proxy_url = personal_proxy(db, current_user.id)

    try:
        run = owned_workflow(db, workflow_id, current_user.id)
        if run.status != "awaiting_approval":
            raise WorkflowError("WORKFLOW_ALREADY_STARTED", "An approved or started workflow cannot be refined", 409)
        if workflow_interaction_count(db, run.id) >= MAX_WORKFLOW_INTERACTIONS:
            raise WorkflowError(
                "REFINEMENT_LIMIT_REACHED",
                f"This planning session is limited to {MAX_WORKFLOW_INTERACTIONS} interactions",
                409,
            )
        try:
            plan_value = WorkflowPlan.model_validate(run.plan_json)
            protein_context_id = uuid.UUID(plan_value.protein_context_id)
        except (ValueError, TypeError) as exc:
            raise WorkflowError("PLAN_INTEGRITY_ERROR", "The stored workflow plan is invalid", 409) from exc
        if request.intent == "modify":
            validate_protein_context_for_generation(db, current_user.id, protein_context_id)
        base_plan_version = run.plan_version
        # Save the user interaction time and release the workflow row lock before Agent/LLM execution. The LLM
        # call is external and may take a long time; persistence later uses
        # version checking to resolve concurrent refinements safely.
        run.updated_at = utcnow()
        db.commit()
    except WorkflowError as exc:
        raise _workflow_http_error(exc) from exc
    except DomainValidationError as exc:
        raise _domain_http_error(exc) from exc

    user_id = current_user.id
    intent = request.intent
    knowledge = _get_knowledge()

    async def _run_interact() -> AgentPlanResponse:
        with SessionLocal() as session:
            deps = AgentDeps(
                user_id=user_id,
                db=session,
                catalog=CATALOG,
                workflow_id=workflow_id,
                knowledge=knowledge,
                protein_context_id=protein_context_id,
                base_plan_version=base_plan_version,
                defer_preview_persistence=True,
                budget=Budget.for_model(config.get("context_window")),
            )
            context = AgentPageContext(
                page="protein_context",
                protein_context_id=str(protein_context_id),
                workflow_id=str(workflow_id),
            )
            async with public_client(proxy_url=proxy_url) as client:
                response = await _get_service(config, client).plan(deps, message, context, mode=intent)
            try:
                response_workflow_id = uuid.UUID(str(response.workflow_id))
            except (ValueError, TypeError, AttributeError):
                response_workflow_id = None
            if response.plan_valid:
                from backend.agent.research_safety import require_task
                require_task(session, deps.research_task_id, user_id, deps.safety_assessment["revision"])
            if not response.plan_valid or response_workflow_id != workflow_id:
                session.rollback()
                response = response.model_copy(update={
                    "plan_valid": False,
                    "plan_changed": False,
                    "plan": None,
                    "normalized_plan": None,
                    "workflow_id": None,
                    "plan_version": None,
                    "plan_hash": None,
                    "interaction_type": intent,
                    "error_code": response.error_code or (
                        "PLAN_MODIFICATION_NOT_PRODUCED" if intent == "modify" else "PLAN_CHANGED"
                    ),
                })
                # Re-read committed truth; do not burn refinement budget on failures.
                try:
                    actual = owned_workflow(session, workflow_id, user_id)
                    actual_plan = WorkflowPlan.model_validate(actual.plan_json)
                    response = response.model_copy(update={
                        "plan_valid": False,
                        "plan": actual_plan,
                        "normalized_plan": actual_plan,
                        "workflow_id": actual.id,
                        "plan_version": actual.plan_version,
                        "plan_hash": actual.plan_hash,
                        "interaction_type": intent,
                        "error_code": response.error_code or (
                            "PLAN_MODIFICATION_NOT_PRODUCED" if intent == "modify" else None
                        ),
                    })
                except Exception:
                    session.rollback()
                return present_agent_response(response)

            try:
                candidate_plan = response.normalized_plan or response.plan
                if candidate_plan is None:
                    raise WorkflowError(
                        "PLAN_MODIFICATION_NOT_PRODUCED",
                        "The agent did not produce a valid workflow plan",
                        409,
                    )
                current = persist_workflow_preview(
                    session,
                    owner_user_id=user_id,
                    plan=candidate_plan,
                    workflow_id=workflow_id,
                    expected_plan_version=base_plan_version,
                )
                if workflow_interaction_count(session, current.id) >= MAX_WORKFLOW_INTERACTIONS:
                    raise WorkflowError(
                        "REFINEMENT_LIMIT_REACHED",
                        f"This planning session is limited to {MAX_WORKFLOW_INTERACTIONS} interactions",
                        409,
                    )
                record_workflow_interaction(
                    session,
                    run=current,
                    interaction_type=intent,
                    user_message=message,
                    assistant_message=response.message,
                    base_plan_version=base_plan_version,
                )
                current.refinement_state = "awaiting_feedback"
                current_plan = WorkflowPlan.model_validate(current.plan_json)
                response = response.model_copy(update={
                    "plan": current_plan,
                    "normalized_plan": current_plan,
                    "workflow_id": current.id,
                    "plan_version": current.plan_version,
                    "plan_hash": current.plan_hash,
                    "plan_changed": current.plan_version != base_plan_version,
                    "previous_plan_version": base_plan_version,
                    "refinement_state": current.refinement_state,
                })
                session.commit()
            except WorkflowError as exc:
                session.rollback()
                raise _workflow_http_error(exc) from exc
            return present_agent_response(response)

    return await _shielded(_run_interact)


@router.post("/workflows/{workflow_id}/approve", response_model=WorkflowOut)
async def approve(
    workflow_id: uuid.UUID,
    request: WorkflowApproveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowOut:
    try:
        from backend.agent.research_safety import assess_existing
        current = owned_workflow(db, workflow_id, current_user.id)
        await assess_existing(db, current_user.id, workflow=current)
        run = approve_workflow(
            db,
            workflow_id=workflow_id,
            owner_user_id=current_user.id,
            plan_version=request.plan_version,
            plan_hash=request.plan_hash,
        )
        db.commit()
        return workflow_out(db, run, include_interactions=True)
    except WorkflowError as exc:
        db.rollback()
        raise _workflow_http_error(exc) from exc


@router.get("/workflows", response_model=list[WorkflowListItem])
def list_workflows(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[WorkflowListItem]:
    """Durable history list — restore any session after refresh or crash."""
    reconcile_stale_planning_requests(db, active_requests=_active_planning_requests)
    db.commit()
    return list_owner_workflows(db, current_user.id, limit=limit, offset=offset)


@router.get("/workflows/{workflow_id}", response_model=WorkflowOut)
def get_workflow(
    workflow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowOut:
    try:
        return workflow_out(db, owned_workflow(db, workflow_id, current_user.id), include_interactions=True)
    except WorkflowError as exc:
        raise _workflow_http_error(exc) from exc


@router.post("/workflows/{workflow_id}/cancel", response_model=WorkflowOut)
def cancel(
    workflow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowOut:
    try:
        run = cancel_workflow(db, workflow_id=workflow_id, owner_user_id=current_user.id)
        db.commit()
        return workflow_out(db, run, include_interactions=True)
    except WorkflowError as exc:
        db.rollback()
        raise _workflow_http_error(exc) from exc


@router.delete("/workflows/{workflow_id}", status_code=204)
def delete_workflow(workflow_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from fastapi import Response
    from backend.services.agent_history import delete_workflow as remove
    try:
        remove(db, workflow_id, current_user.id)
        db.commit()
        return Response(status_code=204)
    except WorkflowError as exc:
        db.rollback()
        raise _workflow_http_error(exc) from exc


@router.delete("/planning-requests/{client_request_id}", status_code=204)
def delete_planning_request(client_request_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from fastapi import Response
    from backend.services.agent_history import delete_planning_request as remove
    try:
        remove(db, client_request_id, current_user.id)
        db.commit()
        return Response(status_code=204)
    except WorkflowError as exc:
        db.rollback()
        raise _workflow_http_error(exc) from exc
