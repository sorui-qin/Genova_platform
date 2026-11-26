import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import time

from sqlalchemy import case, select, or_, and_

from backend.utils import utcnow
from backend.config import settings
from backend.db import Base, SessionLocal, engine
from backend.models import WorkflowRun, AgentSession, AgentTurn, ResearchTask
from backend.services.agent_sessions import reconcile_session
from backend.services.agent_turns import claim_next_turn, run_turn
from backend.services.workflows import advance_locked_workflow, lock_workflow_for_tick


logger = logging.getLogger("workflow-worker")
_tick_failures = {}


def defer_tick_retry(key, error):
    from sqlalchemy.exc import OperationalError, TimeoutError as SQLTimeoutError
    from backend.agent.errors import exception_details
    transient = isinstance(error, (OperationalError, SQLTimeoutError, ConnectionError, TimeoutError)) or exception_details(error)['error_code'] in {
        'AGENT_CONNECTION_ERROR', 'AGENT_CONNECTION_TIMEOUT', 'AGENT_PROVIDER_UNAVAILABLE', 'AGENT_RATE_LIMITED', 'SAFETY_CHECK_UNAVAILABLE'}
    attempts = _tick_failures.get(key, (0, 0))[0] + 1
    _tick_failures[key] = (attempts, time.monotonic() + 5 * 2 ** min(attempts - 1, 2))
    return transient and attempts < 3


def tick_ready(key):
    return time.monotonic() >= _tick_failures.get(key, (0, 0))[1]



def process_batch(limit: int = 20) -> int:
    with SessionLocal() as db:
        workflow_ids = list(
            db.scalars(
                select(WorkflowRun.id)
                .where(WorkflowRun.status.in_(["approved", "running", "cancel_requested"]),
                    WorkflowRun.refinement_state.is_distinct_from("reconciliation_failed"),
                    or_(WorkflowRun.status == 'cancel_requested', WorkflowRun.research_task_id.is_(None),
                        WorkflowRun.research_task_id.in_(select(ResearchTask.id).where(
                            ResearchTask.state.in_(['allowed', 'unassessed']),
                            ResearchTask.assessment['needs_action_clearance'].as_boolean().is_distinct_from(True)))))
                .order_by(WorkflowRun.updated_at.asc())
                .limit(limit)
            ).all()
        )

    processed = 0
    for workflow_id in workflow_ids:
        if not tick_ready(("workflow", workflow_id)):
            continue
        try:
            with SessionLocal() as db:
                from backend.agent.research_safety import assess_existing, pending_active
                import asyncio
                current = db.get(WorkflowRun, workflow_id)
                task = db.get(ResearchTask, current.research_task_id) if current and current.research_task_id else None
                if current and current.status != "cancel_requested" and task and pending_active(db, task):
                    continue
                if current and current.status != "cancel_requested" and (task is None or (task.state == "unassessed" and not pending_active(db, task))):
                    asyncio.run(assess_existing(db, current.owner_user_id, workflow=current))
                    db.commit()
                db.rollback()
                with db.begin():
                    run = lock_workflow_for_tick(db, workflow_id)
                    if run is None or run.status not in {"approved", "running", "cancel_requested"}:
                        continue
                    advance_locked_workflow(db, run)
                    processed += 1
            _tick_failures.pop(('workflow', workflow_id), None)
        except Exception as error:
            from backend.services.workflows import WorkflowError
            if isinstance(error, WorkflowError) and error.code in {'SAFETY_ASSESSMENT_REQUIRED', 'RESEARCH_TASK_BLOCKED', 'RESEARCH_TASK_READ_ONLY'}:
                with SessionLocal() as db, db.begin():
                    for session in db.scalars(select(AgentSession).where(AgentSession.active_workflow_id == workflow_id)):
                        session.last_error, session.phase = 'SAFETY_ASSESSMENT_REQUIRED', 'waiting_input'
                _tick_failures.pop(('workflow', workflow_id), None)
                continue
            logger.exception("Workflow tick failed. workflow_id=%s", workflow_id)
            if not defer_tick_retry(('workflow', workflow_id), error):
                with SessionLocal() as db, db.begin():
                    run = db.get(WorkflowRun, workflow_id)
                    if run:
                        run.refinement_state = 'reconciliation_failed'
                    for session in db.scalars(select(AgentSession).where(AgentSession.active_workflow_id == workflow_id)):
                        session.last_error, session.phase = 'SESSION_RECONCILIATION_FAILED', 'failed'
                _tick_failures.pop(('workflow', workflow_id), None)

    with SessionLocal() as db:
        expired = AgentSession.id.in_(select(AgentTurn.session_id).where(AgentTurn.status == "running", AgentTurn.lease_until < utcnow()))
        active = or_(AgentSession.phase.in_(["preparing", "executing", "analyzing", "waiting_input", "cancel_requested"]), expired)
        ready = and_(AgentSession.phase == 'ready_for_planning', AgentSession.research_task_id.in_(
            select(ResearchTask.id).where(ResearchTask.state == 'allowed')))
        reading = AgentSession.id.in_(select(AgentTurn.session_id).where(
            AgentTurn.audit['reading_resumed_by'].as_string().is_(None),
            AgentTurn.audit['reading_stopped'].as_boolean().is_distinct_from(True),
            or_(AgentTurn.audit['reading_stalled'].as_integer().is_(None), AgentTurn.audit['reading_stalled'].as_integer() < 2),
            or_(AgentTurn.response['investigation_status'].as_string() == 'paused',
                and_(or_(AgentTurn.status == 'interrupted',
                         and_(AgentTurn.status == 'failed', AgentTurn.response['retryable'].as_boolean().is_(True))),
                    or_(AgentTurn.audit['source_read_state'].as_string().not_in(['{}', 'null']),
                        AgentTurn.audit['diagnostic_state'].as_string().not_in(['{}', 'null']))))))
        # Sessions with work in flight go first so finished history cannot delay them.
        ids = list(db.scalars(select(AgentSession.id).where(or_(ready, active, reading),
            AgentSession.last_error.is_distinct_from('SESSION_RECONCILIATION_FAILED'),
            AgentSession.last_error.is_distinct_from('SAFETY_ASSESSMENT_REQUIRED'))
            .order_by(case((active, 0), else_=1), AgentSession.updated_at).limit(limit)))
    for session_id in ids:
        if not tick_ready(("session", session_id)):
            continue
        try:
            with SessionLocal() as db, db.begin():
                session = db.scalar(select(AgentSession).where(AgentSession.id == session_id).with_for_update(skip_locked=True))
                if session:
                    reconcile_session(db, session)
                    session.updated_at = utcnow()
            _tick_failures.pop(('session', session_id), None)
        except Exception as error:
            logger.exception("Agent session reconciliation failed. session_id=%s", session_id)
            if defer_tick_retry(('session', session_id), error):
                continue
            # Move a failing session to the back of the queue so it cannot hold every slot.
            try:
                with SessionLocal() as db, db.begin():
                    session = db.scalar(select(AgentSession).where(AgentSession.id == session_id).with_for_update(skip_locked=True))
                    if session:
                        session.updated_at = utcnow()
                        session.last_error = 'SESSION_RECONCILIATION_FAILED'
                        session.phase = 'failed'
                _tick_failures.pop(('session', session_id), None)
            except Exception:
                logger.exception("Agent session rotation failed. session_id=%s", session_id)
    return processed


def main() -> None:
    from backend.agent.runner import Budget
    from dataclasses import asdict
    import logging
    logging.getLogger("backend-agent").warning("Agent effective budget: %s", asdict(Budget()))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)
    logger.info("Workflow worker online. poll_seconds=%s", settings.workflow_poll_seconds)
    # ponytail: two concurrent model turns per worker; increase only after measuring queue delay.
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="agent-turn")
    futures = set()
    while True:
        try:
            for future in list(futures):
                if future.done():
                    futures.remove(future)
                    try:
                        future.result()
                    except Exception:
                        logger.exception("Agent turn runner stopped; its lease will expire")
            while len(futures) < 2:
                claim = claim_next_turn()
                if claim is None:
                    break
                futures.add(executor.submit(lambda args=claim: asyncio.run(run_turn(*args))))
            processed = process_batch()
        except Exception:
            logger.exception("Workflow batch failed")
            processed = 0
        time.sleep(settings.workflow_poll_seconds)


if __name__ == "__main__":
    main()
