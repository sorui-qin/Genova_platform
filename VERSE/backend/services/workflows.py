from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.agent.schemas import (
    WorkflowListItem,
    WorkflowOut,
    WorkflowInteractionOut,
    WorkflowPlan,
    WorkflowStepOut,
    calculate_plan_hash,
    canonicalize_workflow_plan,
)
from backend.models import (
    ActionProposal,
    AgentSession,
    Job,
    JobTask,
    ResearchTask,
    WorkflowInteraction,
    WorkflowPlanningRequest,
    WorkflowRun,
    WorkflowStep,
)
from backend.services.jobs import DomainValidationError, create_agent_source_job, create_postprocessing_job
from backend.utils import utcnow
from backend.workflows.contracts import digest


ACTIVE_JOB_STATUSES = {"pending", "queued", "running", "blocked"}
MAX_WORKFLOW_INTERACTIONS = 12
RECENT_CONTEXT_INTERACTIONS = 6
PLANNING_STALE_AFTER = timedelta(minutes=10)
PLANNING_IDENTITY_CONSTRAINT = "uq_workflow_planning_owner_client_request"
PLANNING_STATUSES = {"planning", "interrupted", "failed", "linked"}
MAX_PLANNING_ATTEMPTS = 1000
POSTPROCESSING_APPROVAL_PROTOCOL_VERSION = "tarpass-2026-09"


class WorkflowError(Exception):
    def __init__(self, code: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


@dataclass(frozen=True)
class PlanningClaim:
    request: WorkflowPlanningRequest
    should_run: bool


def planning_request_shape_is_valid(row: WorkflowPlanningRequest) -> bool:
    return (
        row.status in PLANNING_STATUSES
        and 1 <= row.attempt <= MAX_PLANNING_ATTEMPTS
        and (row.status == "linked") == (row.workflow_id is not None)
    )


def public_workflow_status(status: str) -> str:
    if status == "awaiting_approval":
        return "draft"
    if status == "superseded":
        return "canceled"
    return status


def _planning_request(
    db: Session,
    owner_user_id: uuid.UUID,
    client_request_id: uuid.UUID,
    *,
    lock: bool = False,
) -> WorkflowPlanningRequest | None:
    stmt = select(WorkflowPlanningRequest).where(
        WorkflowPlanningRequest.owner_user_id == owner_user_id,
        WorkflowPlanningRequest.client_request_id == client_request_id,
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return db.scalar(stmt)


def get_planning_request(
    db: Session,
    owner_user_id: uuid.UUID,
    client_request_id: uuid.UUID,
) -> WorkflowPlanningRequest:
    row = _planning_request(db, owner_user_id, client_request_id)
    if row is None:
        raise WorkflowError("RESOURCE_NOT_FOUND", "Planning request not found", 404)
    return row


def _validate_planning_identity(
    row: WorkflowPlanningRequest,
    *,
    message: str,
    protein_context_id: uuid.UUID,
) -> None:
    if row.message != message or row.protein_context_id != protein_context_id:
        raise WorkflowError(
            "IDEMPOTENCY_KEY_REUSED",
            "client_request_id is already bound to a different planning request",
            409,
        )


def _is_planning_identity_conflict(exc: IntegrityError) -> bool:
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    constraint_name = getattr(diag, "constraint_name", None)
    return constraint_name == PLANNING_IDENTITY_CONSTRAINT or PLANNING_IDENTITY_CONSTRAINT in str(exc.orig)


def claim_planning_request(
    db: Session,
    *,
    owner_user_id: uuid.UUID,
    client_request_id: uuid.UUID,
    message: str,
    protein_context_id: uuid.UUID,
    retry: bool = False,
) -> PlanningClaim:
    """Commit one durable identity before LLM work and arbitrate explicit retries."""
    existing = _planning_request(db, owner_user_id, client_request_id, lock=True)
    if existing is not None:
        _validate_planning_identity(existing, message=message, protein_context_id=protein_context_id)
        if not planning_request_shape_is_valid(existing):
            raise WorkflowError(
                "PLANNING_INTEGRITY_ERROR",
                "The saved planning request is inconsistent and needs maintainer review",
                409,
            )
        if retry and existing.status in {"failed", "interrupted"}:
            if existing.attempt >= MAX_PLANNING_ATTEMPTS:
                raise WorkflowError(
                    "PLANNING_RETRY_LIMIT",
                    "This planning request reached its retry limit; start a new request",
                    409,
                )
            existing.status = "planning"
            existing.attempt += 1
            existing.last_error = None
            existing.updated_at = utcnow()
            db.commit()
            return PlanningClaim(existing, True)
        return PlanningClaim(existing, False)

    now = utcnow()
    row = WorkflowPlanningRequest(
        owner_user_id=owner_user_id,
        client_request_id=client_request_id,
        message=message,
        protein_context_id=protein_context_id,
        status="planning",
        attempt=1,
        created_at=now,
        updated_at=now,
    )
    try:
        db.add(row)
        db.commit()
        return PlanningClaim(row, True)
    except IntegrityError as exc:
        db.rollback()
        if not _is_planning_identity_conflict(exc):
            raise
        existing = _planning_request(db, owner_user_id, client_request_id, lock=True)
        if existing is None:
            raise
        _validate_planning_identity(existing, message=message, protein_context_id=protein_context_id)
        return PlanningClaim(existing, False)


def link_planning_workflow(
    db: Session,
    *,
    owner_user_id: uuid.UUID,
    client_request_id: uuid.UUID,
    attempt: int,
    workflow_id: uuid.UUID,
) -> WorkflowPlanningRequest:
    row = _planning_request(db, owner_user_id, client_request_id, lock=True)
    if row is None:
        raise WorkflowError("RESOURCE_NOT_FOUND", "Planning request not found", 404)
    if row.status != "planning" or row.attempt != attempt:
        raise WorkflowError("STALE_PLANNING_ATTEMPT", "A newer planning attempt owns this request", 409)
    row.status = "linked"
    row.workflow_id = workflow_id
    row.last_error = None
    row.updated_at = utcnow()
    db.flush()
    return row


def mark_planning_failed(
    db: Session,
    *,
    owner_user_id: uuid.UUID,
    client_request_id: uuid.UUID,
    attempt: int,
    error_code: str,
) -> bool:
    row = _planning_request(db, owner_user_id, client_request_id, lock=True)
    if row is None or row.status != "planning" or row.attempt != attempt:
        return False
    row.status = "failed"
    row.last_error = error_code[:128]
    row.updated_at = utcnow()
    db.flush()
    return True


def reconcile_stale_planning_requests(
    db: Session,
    *,
    active_requests: set[tuple[uuid.UUID, uuid.UUID]],
    stale_after: timedelta = PLANNING_STALE_AFTER,
    now: datetime | None = None,
) -> int:
    """Mark orphaned planning rows retryable; never restart LLM work automatically."""
    current = now or utcnow()
    rows = db.scalars(
        select(WorkflowPlanningRequest)
        .where(
            WorkflowPlanningRequest.status == "planning",
            WorkflowPlanningRequest.workflow_id.is_(None),
            WorkflowPlanningRequest.updated_at < current - stale_after,
        )
        .with_for_update(skip_locked=True)
    ).all()
    changed = 0
    for row in rows:
        if (row.owner_user_id, row.client_request_id) in active_requests:
            continue
        row.status = "interrupted"
        row.last_error = "PLANNING_INTERRUPTED"
        row.updated_at = current
        changed += 1
    if changed:
        db.flush()
    return changed


def _workflow(db: Session, workflow_id: uuid.UUID, *, lock: bool = False, skip_locked: bool = False) -> WorkflowRun | None:
    stmt = select(WorkflowRun).where(WorkflowRun.id == workflow_id)
    if lock:
        stmt = stmt.with_for_update(skip_locked=skip_locked).execution_options(populate_existing=True)
    return db.scalar(stmt)


def owned_workflow(
    db: Session,
    workflow_id: uuid.UUID,
    owner_user_id: uuid.UUID,
    *,
    lock: bool = False,
) -> WorkflowRun:
    run = _workflow(db, workflow_id, lock=lock)
    if run is None:
        raise WorkflowError("RESOURCE_NOT_FOUND", "Workflow not found", 404)
    if run.owner_user_id != owner_user_id:
        raise WorkflowError("RESOURCE_FORBIDDEN", "Workflow belongs to another user", 403)
    return run


def workflow_steps(db: Session, workflow_id: uuid.UUID) -> list[WorkflowStep]:
    return list(
        db.scalars(
            select(WorkflowStep)
            .where(WorkflowStep.workflow_id == workflow_id)
            .order_by(WorkflowStep.step_index.asc())
        ).all()
    )


def recent_workflow_interactions(
    db: Session,
    workflow_id: uuid.UUID,
    *,
    limit: int = RECENT_CONTEXT_INTERACTIONS,
) -> list[WorkflowInteraction]:
    rows = list(
        db.scalars(
            select(WorkflowInteraction)
            .where(WorkflowInteraction.workflow_id == workflow_id)
            .order_by(WorkflowInteraction.created_at.desc(), WorkflowInteraction.id.desc())
            .limit(limit)
        ).all()
    )
    rows.reverse()
    return rows


def workflow_interaction_count(db: Session, workflow_id: uuid.UUID) -> int:
    return int(db.scalar(
        select(func.count()).select_from(WorkflowInteraction).where(WorkflowInteraction.workflow_id == workflow_id)
    ) or 0)


def list_owner_workflows(
    db: Session,
    owner_user_id: uuid.UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[WorkflowListItem]:
    """Durable history list — survives refresh/power loss; ordered newest first."""
    bounded_limit = min(max(limit, 1), 200)
    bounded_offset = max(offset, 0)
    window = bounded_offset + bounded_limit
    planning_rows = list(
        db.scalars(
            select(WorkflowPlanningRequest)
            .where(WorkflowPlanningRequest.owner_user_id == owner_user_id)
            .order_by(WorkflowPlanningRequest.updated_at.desc(), WorkflowPlanningRequest.id.desc())
            .limit(window)
        ).all()
    )
    linked_ids = [row.workflow_id for row in planning_rows if row.workflow_id is not None]
    linked_runs = {
        run.id: run
        for run in db.scalars(select(WorkflowRun).where(WorkflowRun.id.in_(linked_ids))).all()
    } if linked_ids else {}

    items: list[WorkflowListItem] = []
    for row in planning_rows:
        run = linked_runs.get(row.workflow_id) if row.workflow_id else None
        corrupt = (
            not planning_request_shape_is_valid(row)
            or (row.status == "linked" and run is None)
            or (run is not None and run.owner_user_id != row.owner_user_id)
        )
        if corrupt:
            run = None
            status = "failed"
        else:
            status = public_workflow_status(run.status) if run is not None else row.status
        items.append(
            WorkflowListItem(
                client_request_id=row.client_request_id,
                workflow_id=run.id if run is not None else None,
                status=status,
                template=run.template_key if run is not None else None,
                plan_version=run.plan_version if run is not None else None,
                refinement_state=(getattr(run, "refinement_state", None) or "awaiting_feedback") if run else None,
                title=row.message[:80],
                message=row.message,
                protein_context_id=row.protein_context_id,
                attempt=row.attempt if 1 <= row.attempt <= MAX_PLANNING_ATTEMPTS else None,
                retryable=not corrupt and status in {"failed", "interrupted"} and run is None,
                last_error="PLANNING_INTEGRITY_ERROR" if corrupt else row.last_error,
                updated_at=run.updated_at if run is not None else row.updated_at,
                created_at=row.created_at,
            )
        )
    items.sort(key=lambda item: (item.updated_at, str(item.workflow_id or item.client_request_id)), reverse=True)
    return items[bounded_offset:bounded_offset + bounded_limit]


def record_workflow_interaction(
    db: Session,
    *,
    run: WorkflowRun,
    interaction_type: str,
    user_message: str,
    assistant_message: str,
    base_plan_version: int,
) -> WorkflowInteraction:
    if interaction_type not in {"plan", "modify", "explain"}:
        raise ValueError("Unsupported workflow interaction type")
    row = WorkflowInteraction(
        workflow_id=run.id,
        interaction_type=interaction_type,
        user_message=user_message[:4000],
        assistant_message=assistant_message[:8000],
        base_plan_version=base_plan_version,
        resulting_plan_version=run.plan_version,
        resulting_plan_hash=run.plan_hash,
    )
    db.add(row)
    db.flush()
    return row


def workflow_out(db: Session, run: WorkflowRun, *, include_interactions: bool = False) -> WorkflowOut:
    return WorkflowOut(
        workflow_id=run.id,
        status=run.status,
        template=run.template_key,
        protocol_version=run.protocol_version,
        plan_version=run.plan_version,
        plan_hash=run.plan_hash,
        plan=WorkflowPlan.model_validate(run.plan_json),
        refinement_state=getattr(run, "refinement_state", None) or "awaiting_feedback",
        approved_version=run.approved_version,
        approved_hash=run.approved_hash,
        approved_at=run.approved_at,
        steps=[WorkflowStepOut.model_validate(step) for step in workflow_steps(db, run.id)],
        # UI history must be complete; LLM context stays bounded separately.
        interactions=[
            WorkflowInteractionOut.model_validate(row)
            for row in recent_workflow_interactions(db, run.id, limit=MAX_WORKFLOW_INTERACTIONS)
        ] if include_interactions else [],
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def workflow_step_error(step: WorkflowStep) -> dict[str, Any]:
    # Raw persisted diagnostics can contain paths/tracebacks; never send them to the LLM.
    return {"code": step.error_code,
            "message": "Generation failed" if step.step_key == "generation" else "Postprocessing failed"}


def workflow_status_dict(db: Session, run: WorkflowRun) -> dict[str, Any]:
    """Agent-facing workflow status payload — DB truth only, no paths or secrets."""
    steps = {step.step_key: step for step in workflow_steps(db, run.id)}

    def step_out(key: str) -> dict[str, Any]:
        step = steps.get(key)
        job = db.get(Job, step.job_id) if step and step.job_id else None
        return {
            "status": step.status if step else None,
            "job_id": str(step.job_id) if step and step.job_id else None,
            "finished_at": job.finished_at.isoformat() if job and job.finished_at else None,
        }

    error = None
    if run.status == "failed":
        failed = next((step for step in steps.values() if step.error_code), None)
        if failed is not None:
            error = workflow_step_error(failed)

    return {
        "workflow_id": str(run.id),
        "template": run.template_key,
        "status": run.status,
        "plan_version": run.plan_version,
        "plan_hash": run.plan_hash,
        "refinement_state": getattr(run, "refinement_state", None) or "awaiting_feedback",
        "generation": step_out("generation"),
        "postprocessing": step_out("postprocessing"),
        "error": error,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }


def persist_workflow_preview(
    db: Session,
    *,
    owner_user_id: uuid.UUID,
    plan: WorkflowPlan | dict[str, Any],
    workflow_id: uuid.UUID | None = None,
    expected_plan_version: int | None = None,
    domain_managed: bool = False,
    create_workflow_id: uuid.UUID | None = None,
) -> WorkflowRun:
    canonical = canonicalize_workflow_plan(plan)
    plan_hash = calculate_plan_hash(canonical)
    now = utcnow()

    if workflow_id is None:
        run = WorkflowRun(
            id=create_workflow_id or uuid.uuid4(),
            owner_user_id=owner_user_id,
            template_key=canonical["template"],
            protocol_version=canonical["protocol_version"],
            plan_json=canonical,
            plan_version=1,
            plan_hash=plan_hash,
            refinement_state="awaiting_feedback",
            status="awaiting_approval",
            created_at=now,
            updated_at=now,
        )
        db.add(run)
        db.flush()
        db.add_all(
            [
                WorkflowStep(workflow_id=run.id, step_key="generation", step_index=0, status="pending"),
                WorkflowStep(workflow_id=run.id, step_key="postprocessing", step_index=1, status="pending"),
            ]
        )
        db.flush()
        return run

    run = owned_workflow(db, workflow_id, owner_user_id, lock=True)
    if expected_plan_version is not None and run.plan_version != expected_plan_version:
        raise WorkflowError("PLAN_CHANGED", "The workflow plan changed; revise the current version", 409)
    if getattr(run, "action_proposal_id", None) and not domain_managed:
        raise WorkflowError("USE_WORKFLOW_COMMANDS", "Use the versioned workflow command endpoint for this draft", 409)
    steps = workflow_steps(db, run.id)
    if run.status != "awaiting_approval" or any(step.job_id for step in steps):
        raise WorkflowError("WORKFLOW_ALREADY_STARTED", "A started workflow cannot be revised", 409)
    if run.plan_hash == plan_hash:
        return run

    run.template_key = canonical["template"]
    run.protocol_version = canonical["protocol_version"]
    run.plan_json = canonical
    run.plan_version += 1
    run.plan_hash = plan_hash
    run.refinement_state = "awaiting_feedback"
    run.status = "awaiting_approval"
    run.approved_version = None
    run.approved_hash = None
    run.approved_at = None
    run.updated_at = now
    for step in steps:
        step.status = "pending"
        step.error_code = None
        step.error_message = None
        step.updated_at = now
    db.flush()
    return run


def approve_workflow(
    db: Session,
    *,
    workflow_id: uuid.UUID,
    owner_user_id: uuid.UUID,
    plan_version: int,
    plan_hash: str,
) -> WorkflowRun:
    run = owned_workflow(db, workflow_id, owner_user_id)
    from backend.agent.research_safety import require_task
    require_task(db, run.research_task_id, owner_user_id)
    run = owned_workflow(db, workflow_id, owner_user_id, lock=True)
    if getattr(run, "execution_binding", None) or getattr(run, "action_proposal_id", None):
        from backend.workflows.bindings import workflow_binding
        workflow_binding(db, run)
    try:
        stored_hash = calculate_plan_hash(run.plan_json)
    except ValueError as exc:
        raise WorkflowError("PLAN_INTEGRITY_ERROR", "The stored workflow plan failed integrity validation", 409) from exc
    if stored_hash != run.plan_hash:
        raise WorkflowError("PLAN_INTEGRITY_ERROR", "The stored workflow plan failed integrity validation", 409)
    if plan_version != run.plan_version or plan_hash != run.plan_hash:
        raise WorkflowError("PLAN_CHANGED", "The workflow plan changed; approve the current version and hash", 409)
    if run.status == "approved" and run.approved_version == plan_version and run.approved_hash == plan_hash:
        return run
    if run.status in {"running", "succeeded", "failed", "canceled", "superseded"}:
        raise WorkflowError("WORKFLOW_ALREADY_STARTED", "The workflow has already started or finished", 409)
    if run.status != "awaiting_approval":
        raise WorkflowError("INVALID_WORKFLOW_STATE", f"Workflow cannot be approved from state '{run.status}'", 409)

    run.approved_version = run.plan_version
    run.approved_hash = run.plan_hash
    run.approved_at = utcnow()
    run.status = "approved"
    run.refinement_state = "approved"
    run.updated_at = run.approved_at
    db.flush()
    return run


def cancel_workflow(db: Session, *, workflow_id: uuid.UUID, owner_user_id: uuid.UUID) -> WorkflowRun:
    run = owned_workflow(db, workflow_id, owner_user_id, lock=True)
    if run.status == "canceled":
        return run
    if run.status in {"succeeded", "failed", "superseded"}:
        raise WorkflowError("INVALID_WORKFLOW_STATE", f"Workflow cannot be canceled from state '{run.status}'", 409)

    now = utcnow()
    steps = workflow_steps(db, run.id)
    active = any(step.job_id and db.get(Job, step.job_id).status in ACTIVE_JOB_STATUSES for step in steps)
    run.status = "cancel_requested" if active else "canceled"
    run.refinement_state = "closed"
    run.updated_at = now
    for step in steps:
        if step.job_id is None:
            step.status = "canceled"
            step.updated_at = now
    db.flush()
    return run


def _fail(run: WorkflowRun, step: WorkflowStep, code: str, message: str) -> None:
    now = utcnow()
    step.status = "failed"
    step.error_code = code
    step.error_message = message[:2000]
    step.updated_at = now
    run.status = "failed"
    run.refinement_state = "closed"
    run.updated_at = now


def _job_error(db: Session, job_id: uuid.UUID) -> str:
    task = db.scalar(select(JobTask).where(JobTask.job_id == job_id).order_by(JobTask.created_at.desc()))
    return str(task.error_message or "Job failed") if task is not None else "Job failed"


def _postprocessing_proposal(db: Session, run: WorkflowRun) -> ActionProposal | None:
    return db.scalar(select(ActionProposal).where(
        ActionProposal.workflow_id == run.id,
        ActionProposal.kind == "postprocessing",
        ActionProposal.status == "approved",
    ).order_by(ActionProposal.created_at.desc()).limit(1))


def _agent_generation_binding_is_current(db: Session, run: WorkflowRun) -> bool:
    if not run.action_proposal_id:
        return True
    session = db.scalar(select(AgentSession).where(
        AgentSession.owner_user_id == run.owner_user_id,
        AgentSession.research_task_id == run.research_task_id,
        AgentSession.active_workflow_id == run.id,
    ).order_by(AgentSession.updated_at.desc()).limit(1))
    binding = run.execution_binding or {}
    if session is None or not binding.get("inputs") or not binding.get("payload"):
        return False
    try:
        from backend.workflows.commands import design
        from backend.workflows.bindings import snapshot_inputs
        draft = design(db, session)
        current = snapshot_inputs(
            db, session.owner_user_id, draft.assets, draft.values,
            session.input_revision, binding["payload"],
        )
    except (DomainValidationError, WorkflowError, KeyError, TypeError, ValueError):
        return False
    return current == binding["inputs"]


def _supersede_unbound_workflow(run: WorkflowRun, generation: WorkflowStep, postprocessing: WorkflowStep) -> None:
    now = utcnow()
    generation.status = "canceled"
    generation.error_code = "WORKFLOW_SUPERSEDED"
    generation.error_message = "The approved Agent workflow is no longer bound to the active session"
    generation.updated_at = now
    postprocessing.status = "canceled"
    postprocessing.updated_at = now
    run.status = "superseded"
    run.refinement_state = "closed"
    run.updated_at = now


def dispatch_postprocessing_proposal(db: Session, run: WorkflowRun, proposal: ActionProposal, generation_job: Job) -> Job:
    payload = proposal.payload or {}
    if payload.get("source_workflow_id") != str(run.id) or payload.get("generation_plan_version") != run.plan_version or payload.get("generation_plan_hash") != run.plan_hash:
        proposal.status = "stale"
        raise WorkflowError("ACTION_STALE", "Postprocessing approval no longer matches the generation plan", 409)
    if payload.get("runtime_config_version") != POSTPROCESSING_APPROVAL_PROTOCOL_VERSION:
        proposal.status = "stale"
        raise WorkflowError("ACTION_STALE", "Postprocessing protocol changed; approve a new proposal", 409)
    generation_step = db.scalar(select(WorkflowStep).where(
        WorkflowStep.workflow_id == run.id, WorkflowStep.step_key == "generation"))
    if (generation_step is None or generation_step.job_id != generation_job.id
            or generation_step.status != "succeeded"
            or generation_job.owner_user_id != run.owner_user_id):
        proposal.status = "stale"
        raise WorkflowError("ACTION_STALE", "Generation source is not bound to this workflow", 409)
    post_hash = digest({"config": payload.get("postprocessing"), "protocol_version": POSTPROCESSING_APPROVAL_PROTOCOL_VERSION})
    if payload.get("postprocessing_hash") != post_hash:
        proposal.status = "stale"
        raise WorkflowError("ACTION_STALE", "Postprocessing parameters changed; approve a new proposal", 409)
    if generation_job.status != "succeeded":
        raise WorkflowError("SOURCE_NOT_READY", "Generation has not succeeded", 409)
    if proposal.execution.get("job_id"):
        return db.get(Job, uuid.UUID(proposal.execution["job_id"]))
    session = db.get(AgentSession, proposal.session_id)
    if session is None or session.active_workflow_id != run.id:
        proposal.status = "stale"
        raise WorkflowError("ACTION_STALE", "The postprocessing session is no longer active", 409)
    from backend.workflows.commands import design
    from backend.workflows.bindings import snapshot_inputs
    draft = design(db, session)
    current_inputs = snapshot_inputs(db, session.owner_user_id, draft.assets, draft.values, session.input_revision, payload)
    if current_inputs != proposal.input_fingerprint:
        proposal.status = "stale"
        raise WorkflowError("INPUT_CHANGED", "Inputs changed; create and approve a new postprocessing proposal", 409)
    config = dict(payload.get("postprocessing") or {})
    config["source_job_id"] = str(generation_job.id)
    config["protein_context_id"] = config.get("protein_context_id") or str(run.plan_json["protein_context_id"])
    job = create_postprocessing_job(db, owner_user_id=run.owner_user_id, params={
        "postprocessing": config,
        "job_name": f"Workflow {str(run.id)[:8]} TarPass",
    })
    proposal.execution = {
        **(proposal.execution or {}),
        "authorized": True,
        "workflow_id": str(run.id),
        "source_job_id": str(generation_job.id),
        "job_id": str(job.id),
        "postprocessing_hash": payload["postprocessing_hash"],
    }
    db.flush()
    return job


def _advance_locked_workflow(db: Session, run: WorkflowRun) -> None:
    """Advance one already row-locked workflow by at most one submission."""
    if run.status == "cancel_requested":
        if all(not step.job_id or db.get(Job, step.job_id).status not in ACTIVE_JOB_STATUSES for step in workflow_steps(db, run.id)):
            run.status = "canceled"
        return
    if run.status not in {"approved", "running"}:
        return
    from backend.agent.research_safety import require_task
    require_task(db, run.research_task_id, run.owner_user_id)
    # Keep limited worker batches fair while active Jobs are only being observed.
    run.updated_at = utcnow()
    steps = {step.step_key: step for step in workflow_steps(db, run.id)}
    generation = steps["generation"]
    postprocessing = steps["postprocessing"]
    try:
        plan = WorkflowPlan.model_validate(run.plan_json)
    except ValueError:
        _fail(run, generation, "PLAN_INTEGRITY_ERROR", "The approved workflow plan is invalid")
        return
    if run.approved_version != run.plan_version or run.approved_hash != run.plan_hash:
        _fail(run, generation, "PLAN_INTEGRITY_ERROR", "The approved workflow plan failed integrity validation")
        return

    if generation.job_id is None:
        from backend.services.task_plans import can_submit
        if not can_submit(db, run):
            return
        if not _agent_generation_binding_is_current(db, run):
            _supersede_unbound_workflow(run, generation, postprocessing)
            db.flush()
            return
        try:
            if getattr(run, "execution_binding", None) or getattr(run, "action_proposal_id", None):
                from backend.workflows.bindings import workflow_binding
                binding = workflow_binding(db, run)
            else:
                binding = None
            job = create_agent_source_job(
                db,
                owner_user_id=run.owner_user_id,
                protein_context_id=uuid.UUID(plan.protein_context_id),
                generation=(binding["effective_generation"] if binding else {
                    **plan.generation.model_dump(mode="json"),
                    **({"seed_source": plan.seed_source, "ligand_dataset_id": plan.seed_source["dataset_id"]} if plan.seed_source else {}),
                }),
                workflow_id=run.id,
            )
        except (DomainValidationError, WorkflowError) as exc:
            _fail(run, generation, exc.code, exc.message)
            return
        generation.job_id = job.id
        generation.status = "submitted"
        generation.updated_at = utcnow()
        run.status = "running"
        run.refinement_state = "running"
        run.updated_at = generation.updated_at
        db.flush()
        return

    generation_job = db.get(Job, generation.job_id)
    if generation_job is None:
        _fail(run, generation, "JOB_NOT_FOUND", "Generation Job is missing")
        return
    if generation_job.status in ACTIVE_JOB_STATUSES:
        return
    if generation_job.status == "failed":
        _fail(run, generation, "GENERATION_FAILED", _job_error(db, generation_job.id))
        return
    if generation_job.status == "canceled":
        now = utcnow()
        generation.status = "canceled"
        generation.updated_at = now
        postprocessing.status = "canceled"
        postprocessing.updated_at = now
        run.status = "canceled"
        run.refinement_state = "closed"
        run.updated_at = now
        return
    if generation_job.status != "succeeded":
        _fail(run, generation, "INVALID_JOB_STATE", f"Unexpected generation Job state '{generation_job.status}'")
        return

    generation.status = "succeeded"
    generation.updated_at = utcnow()
    task = db.get(ResearchTask, run.research_task_id) if run.research_task_id else None
    choice = ((task.workflow_preferences or {}).get("postprocessing") or {}).get("choice") if task else None
    if postprocessing.job_id is None and (postprocessing.status == "skipped" or choice == "skip"):
        postprocessing.status = "skipped"
        postprocessing.updated_at = generation.updated_at
        run.status = "succeeded"
        run.refinement_state = "closed"
        run.updated_at = generation.updated_at
        return

    if postprocessing.job_id is None:
        from backend.services.task_plans import can_submit
        if not can_submit(db, run):
            return
        try:
            proposal = _postprocessing_proposal(db, run)
            if proposal is None:
                postprocessing.status = "awaiting_approval"
                postprocessing.updated_at = generation.updated_at
                run.updated_at = generation.updated_at
                db.flush()
                return
            job = dispatch_postprocessing_proposal(db, run, proposal, generation_job)
        except WorkflowError as exc:
            if exc.code in {"ACTION_STALE", "INPUT_CHANGED"}:
                postprocessing.status = "awaiting_approval"
                postprocessing.updated_at = utcnow()
                run.updated_at = postprocessing.updated_at
                db.flush()
                return
            _fail(run, postprocessing, exc.code, exc.message)
            return
        except DomainValidationError as exc:
            _fail(run, postprocessing, exc.code, exc.message)
            return
        postprocessing.job_id = job.id
        postprocessing.status = "submitted"
        postprocessing.updated_at = utcnow()
        run.updated_at = postprocessing.updated_at
        db.flush()
        return

    post_job = db.get(Job, postprocessing.job_id)
    if post_job is None:
        _fail(run, postprocessing, "JOB_NOT_FOUND", "Postprocessing Job is missing")
        return
    if post_job.status in ACTIVE_JOB_STATUSES:
        return
    if post_job.status == "failed":
        _fail(run, postprocessing, "POSTPROCESSING_FAILED", _job_error(db, post_job.id))
        return
    if post_job.status == "canceled":
        now = utcnow()
        postprocessing.status = "canceled"
        postprocessing.updated_at = now
        run.status = "canceled"
        run.refinement_state = "closed"
        run.updated_at = now
        return
    if post_job.status != "succeeded":
        _fail(run, postprocessing, "INVALID_JOB_STATE", f"Unexpected postprocessing Job state '{post_job.status}'")
        return

    now = utcnow()
    postprocessing.status = "succeeded"
    postprocessing.updated_at = now
    run.status = "succeeded"
    run.refinement_state = "closed"
    run.updated_at = now


def lock_workflow_for_tick(db: Session, workflow_id: uuid.UUID) -> WorkflowRun | None:
    from backend.models import ResearchTask
    current = _workflow(db, workflow_id)
    if current and current.research_task_id:
        task = db.scalar(select(ResearchTask).where(ResearchTask.id == current.research_task_id).with_for_update(skip_locked=True).execution_options(populate_existing=True))
        if task is None or task.pending_turn_id or (task.state != "allowed" and current.status != "cancel_requested"):
            return None
    return _workflow(db, workflow_id, lock=True, skip_locked=True)


def advance_locked_workflow(db: Session, run: WorkflowRun) -> None:
    from backend.workflows.commands import emit
    before = run.status
    _advance_locked_workflow(db, run)
    if run.status != before:
        emit(db, run.id, run.plan_version, "workflow_" + run.status,
             f"workflow:{run.id}:{run.plan_version}:{run.status}", {"status": run.status})
