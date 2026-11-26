"""Delete inactive Agent history while retaining datasets, jobs and results."""
from sqlalchemy import delete, select, update

from backend.models import AgentSession, AgentTurn, ActionProposal, CandidateSet, Job, WorkflowRun, WorkflowStep, WorkflowInteraction, WorkflowPlanningRequest, DesignDraft, EditSession, WorkflowCommand, WorkflowEvent, ResearchTask
from backend.services.agent_sessions import owned_session, reconcile_session
from backend.services.jobs import DomainValidationError
from backend.services.workflows import ACTIVE_JOB_STATUSES, WorkflowError, owned_workflow


def delete_workflow(db, workflow_id, user_id, *, session_id=None):
    owned_workflow(db, workflow_id, user_id)
    # Session operations lock the session before the workflow; keep that order.
    linked = set(db.scalars(select(AgentSession.id).where(AgentSession.active_workflow_id == workflow_id)))
    linked.update(db.scalars(select(ActionProposal.session_id).where(ActionProposal.workflow_id == workflow_id)))
    if linked - {session_id}:
        raise WorkflowError("WORKFLOW_SESSION_LINKED", "Delete the associated Agent session first", 409)
    run = owned_workflow(db, workflow_id, user_id, lock=True)
    if run.status in {"approved", "running"}:
        raise WorkflowError("HISTORY_BUSY", "Wait for active tasks before deleting history", 409)
    if db.scalar(select(Job.id).join(WorkflowStep, WorkflowStep.job_id == Job.id).where(
            WorkflowStep.workflow_id == run.id, Job.status.in_(ACTIVE_JOB_STATUSES)).limit(1)):
        raise WorkflowError("HISTORY_BUSY", "Wait for active tasks before deleting history", 409)
    planning_ids = select(WorkflowPlanningRequest.id).where(WorkflowPlanningRequest.workflow_id == run.id)
    if db.scalar(select(AgentTurn.id).where(AgentTurn.planning_request_id.in_(planning_ids), AgentTurn.status.in_(["queued", "running"])).limit(1)):
        raise WorkflowError("HISTORY_BUSY", "Wait for the active conversation before deleting history", 409)
    db.execute(update(AgentTurn).where(AgentTurn.planning_request_id.in_(planning_ids)).values(planning_request_id=None))
    db.execute(delete(WorkflowPlanningRequest).where(WorkflowPlanningRequest.workflow_id == run.id))
    db.execute(update(AgentSession).where(AgentSession.active_workflow_id == run.id).values(active_workflow_id=None))
    db.execute(update(ActionProposal).where(ActionProposal.workflow_id == run.id).values(workflow_id=None))
    db.execute(delete(WorkflowInteraction).where(WorkflowInteraction.workflow_id == run.id))
    db.execute(delete(WorkflowStep).where(WorkflowStep.workflow_id == run.id))
    db.delete(run)
    db.flush()


def delete_session(db, session_id, user_id):
    session = owned_session(db, session_id, user_id, lock=True)
    try:
        with db.begin_nested():
            reconcile_session(db, session)
    except (DomainValidationError, WorkflowError) as error:
        if error.code != 'RESOURCE_NOT_FOUND':
            raise
    if db.scalar(select(AgentTurn.id).where(AgentTurn.session_id == session.id, AgentTurn.status.in_(["queued", "running"])).limit(1)):
        raise WorkflowError("HISTORY_BUSY", "Wait for the active conversation before deleting history", 409)
    proposals = list(db.scalars(select(ActionProposal).where(ActionProposal.session_id == session.id)))
    job_ids = [p.execution["job_id"] for p in proposals if p.execution.get("job_id")]
    if session.preparation_job_id:
        job_ids.append(session.preparation_job_id)
    if job_ids and db.scalar(select(Job.id).where(Job.id.in_(job_ids), Job.status.in_(ACTIVE_JOB_STATUSES)).limit(1)):
        raise WorkflowError("HISTORY_BUSY", "Wait for active tasks before deleting history", 409)
    # Delete only workflows created by this session; an independently owned run stays intact.
    runs = list(db.scalars(select(WorkflowRun).where(WorkflowRun.action_proposal_id.in_([p.id for p in proposals])).order_by(WorkflowRun.id)))
    linked_ids = {p.workflow_id for p in proposals if p.workflow_id}
    if session.active_workflow_id:
        linked_ids.add(session.active_workflow_id)
    for workflow_id in sorted(linked_ids, key=str):
        run = db.scalar(select(WorkflowRun).where(WorkflowRun.id == workflow_id,
            WorkflowRun.owner_user_id == user_id).with_for_update())
        if run is None:
            continue
        if run.status in {"approved", "running"}:
            raise WorkflowError("HISTORY_BUSY", "Wait for active tasks before deleting history", 409)
    for run in runs:
        delete_workflow(db, run.id, user_id, session_id=session.id)
    planning_ids = list(db.scalars(select(AgentTurn.planning_request_id).where(AgentTurn.session_id == session.id, AgentTurn.planning_request_id.is_not(None))))
    task_ids = set(db.scalars(select(AgentTurn.research_task_id).where(
        AgentTurn.session_id == session.id, AgentTurn.research_task_id.is_not(None))))
    if getattr(session, 'research_task_id', None):
        task_ids.add(session.research_task_id)
    db.execute(delete(CandidateSet).where(CandidateSet.session_id == session.id))
    db.execute(delete(ActionProposal).where(ActionProposal.session_id == session.id))
    db.execute(delete(AgentTurn).where(AgentTurn.session_id == session.id))
    if planning_ids:
        db.execute(delete(WorkflowPlanningRequest).where(WorkflowPlanningRequest.id.in_(planning_ids), WorkflowPlanningRequest.workflow_id.is_(None)))
    db.delete(session)
    db.flush()
    db.execute(delete(DesignDraft).where(DesignDraft.id == session.id, DesignDraft.owner_user_id == user_id))
    db.execute(delete(EditSession).where(EditSession.session_id == session.id, EditSession.owner_user_id == user_id))
    db.execute(delete(WorkflowCommand).where(WorkflowCommand.target_id == session.id, WorkflowCommand.owner_user_id == user_id))
    db.execute(delete(WorkflowEvent).where(WorkflowEvent.object_id == session.id))
    if task_ids:
        db.execute(delete(ResearchTask).where(ResearchTask.id.in_(task_ids), ResearchTask.owner_user_id == user_id,
            *(~select(model.id).where(model.research_task_id == ResearchTask.id).exists()
                for model in (AgentSession, AgentTurn, WorkflowRun, WorkflowPlanningRequest))))


def delete_planning_request(db, client_request_id, user_id):
    query = select(WorkflowPlanningRequest).where(
        WorkflowPlanningRequest.client_request_id == client_request_id,
        WorkflowPlanningRequest.owner_user_id == user_id)
    row = db.scalar(query)
    if row is None:
        raise WorkflowError("RESOURCE_NOT_FOUND", "Planning request not found", 404)
    session_ids = sorted(set(db.scalars(select(AgentTurn.session_id).where(AgentTurn.planning_request_id == row.id))), key=str)
    for session_id in session_ids:
        owned_session(db, session_id, user_id, lock=True)
    row = db.scalar(query.with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise WorkflowError("RESOURCE_NOT_FOUND", "Planning request not found", 404)
    if row.status == "planning" or db.scalar(select(AgentTurn.id).where(
            AgentTurn.planning_request_id == row.id, AgentTurn.status.in_(["queued", "running"])).limit(1)):
        raise WorkflowError("HISTORY_BUSY", "Wait for planning to finish before deleting history", 409)
    if row.workflow_id:
        raise WorkflowError("WORKFLOW_SESSION_LINKED", "Delete the associated workflow instead", 409)
    db.execute(update(AgentTurn).where(AgentTurn.planning_request_id == row.id).values(planning_request_id=None))
    db.delete(row)
    db.flush()
