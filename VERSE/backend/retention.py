import fcntl
import json
import logging
import os
import shutil
import uuid

import redis
from collections import defaultdict
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, exists, select, text, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Session, defer

from backend.builtin_datasets import BUILTIN_OWNER_ID
from backend.config import settings
from backend.db import RETENTION_LOCK, engine
from backend.models import (
    ActionProposal, AgentSession, AgentTurn, AuthRefreshToken, CandidateSet, DataRetentionDeletion,
    DataRetentionPolicy, Dataset, DatasetFile, DeleteEditSpec, DesignDraft, EditSession,
    Job, JobTask, QueueOutbox, User, WorkflowCommand, WorkflowEvent,
    WorkflowInteraction, WorkflowPlanningRequest, WorkflowRun, WorkflowStep,
)
from backend.utils import utcnow
from genova_runtime.queue_worker import save_receipt


logger = logging.getLogger("data-retention")
RETENTION_DAYS = 14
TERMINAL = {"succeeded", "partial_succeeded", "failed", "canceled", "skipped"}
ROOTS = (Dataset, Job, AgentSession, WorkflowRun, WorkflowPlanningRequest, DeleteEditSpec)


def initialize_schema():
    migration = Path(__file__).parent / "migrations/20261015_data_retention.sql"
    with engine.begin() as connection:
        for statement in migration.read_text().split(";"):
            if statement.strip():
                connection.execute(text(statement))
        for statement in (Path(__file__).parent / 'migrations/20261025_manual_deletions.sql').read_text().split(';'):
            if statement.strip():
                connection.execute(text(statement))
        if settings.data_retention_enabled:
            connection.execute(insert(DataRetentionPolicy).values(id=1, first_enabled_at=utcnow())
                               .on_conflict_do_nothing(index_elements=["id"]))


def policy_status(db):
    policy = db.get(DataRetentionPolicy, 1) if settings.data_retention_enabled else None
    return {"enabled": settings.data_retention_enabled, "retention_days": RETENTION_DAYS,
            "first_enabled_at": policy.first_enabled_at if policy else None}


def _receipt_lock(stack, queue_id, held):
    if queue_id in held:
        return True
    root = settings.data_root / ".runtime_receipts"
    root.mkdir(exist_ok=True)
    stream = stack.enter_context((root / f"{queue_id}.lock").open("a"))
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    held.add(queue_id)
    return True


def _load_graph(db, owner_id, *, build_edges=True):
    def query(model):
        stmt = select(model)
        if not build_edges:
            bindings = {Dataset: {'meta'}, Job: {'params'}, JobTask: {'input_payload'},
                        AgentSession: {'assets'}, ActionProposal: {'execution'}}
            stmt = stmt.options(*(defer(getattr(model, column.key)) for column in model.__table__.columns
                                  if isinstance(column.type, JSONB) and column.key not in bindings.get(model, set())))
        return stmt

    rows = {model: list(db.scalars(query(model).where(model.owner_user_id == owner_id))) for model in ROOTS}
    groups = {(model, row.id): row for model in ROOTS for row in rows[model]}
    aliases = defaultdict(set)
    ownership = defaultdict(set)
    members = []

    def attach(row, group):
        ownership[row.__tablename__, row.id].add(group)
        if isinstance(row.id, uuid.UUID):
            aliases[row.id].add(group)
        members.append((row, group))

    for group, row in groups.items():
        attach(row, group)
    children = (
        (DatasetFile, "dataset_id", Dataset), (JobTask, "job_id", Job),
        (WorkflowStep, "workflow_id", WorkflowRun), (WorkflowInteraction, "workflow_id", WorkflowRun),
        (AgentTurn, "session_id", AgentSession), (ActionProposal, "session_id", AgentSession),
        (CandidateSet, "session_id", AgentSession),
    )
    for model, field, parent in children:
        rows[model] = list(db.scalars(query(model).where(getattr(model, field).in_([r.id for r in rows[parent]]))))
        for row in rows[model]:
            group = (parent, getattr(row, field))
            attach(row, group)
            if model is JobTask:
                aliases[row.queue_job_id].add(group)
    for model, field in ((DesignDraft, "id"), (EditSession, "session_id"), (WorkflowCommand, "target_id")):
        rows[model] = list(db.scalars(query(model).where(model.owner_user_id == owner_id)))
        for row in rows[model]:
            parent = (AgentSession, getattr(row, field))
            group = parent if parent in groups else (model, row.id)
            if group not in groups:
                groups[group] = row
            attach(row, group)
    rows[WorkflowEvent] = list(db.scalars(query(WorkflowEvent).where(WorkflowEvent.object_id.in_(aliases))))
    for row in rows[WorkflowEvent]:
        for group in list(aliases[row.object_id]):
            attach(row, group)
    rows[QueueOutbox] = list(db.scalars(query(QueueOutbox).where(QueueOutbox.job_task_id.in_([r.id for r in rows[JobTask]]))))
    for row in rows[QueueOutbox]:
        for group in ownership[JobTask.__tablename__, row.job_task_id]:
            attach(row, group)
    edges = defaultdict(set)
    if not build_edges:
        return rows, groups, ownership, edges
    paths = {row.storage_path: (Dataset, row.dataset_id) for row in rows[DatasetFile]}

    def references(value, source):
        if isinstance(value, dict):
            for key, item in value.items():
                references(key, source)
                references(item, source)
        elif isinstance(value, (list, tuple)):
            for item in value:
                references(item, source)
        elif isinstance(value, (str, uuid.UUID)):
            targets = {paths[value]} if value in paths else set()
            if not targets:
                try:
                    # Client-chosen session/command UUIDs can match IDs in other tables.
                    targets = aliases.get(uuid.UUID(str(value)), set())
                except ValueError:
                    prefix = str(settings.data_root) + "/"
                    if isinstance(value, str) and value.startswith(prefix):
                        parts = value[len(prefix):].split("/")
                        if len(parts) >= 2 and parts[0] in {"datasets", "jobs"}:
                            try:
                                target = (Dataset if parts[0] == "datasets" else Job, uuid.UUID(parts[1]))
                                if target in groups:
                                    targets = {target}
                            except ValueError:
                                pass
            edges[source].update(targets - {source})

    for row, source in members:
        for column in row.__table__.columns:
            if column.name not in {"id", "owner_user_id"}:
                value = getattr(row, column.name)
                if column.foreign_keys:
                    for foreign in column.foreign_keys:
                        edges[source].update(ownership.get((foreign.column.table.name, value), set()) - {source})
                else:
                    references(value, source)
    return rows, groups, ownership, edges


def expired_groups(rows, groups, edges, cutoff, busy_jobs=()):
    kept = set()
    executing = set()
    file_dates = defaultdict(list)
    interaction_dates = defaultdict(list)
    for row in rows[DatasetFile]:
        file_dates[row.dataset_id].append(row.created_at)
    for row in rows[WorkflowInteraction]:
        interaction_dates[row.workflow_id].append(row.created_at)
    for key, row in groups.items():
        model = key[0]
        activity = getattr(row, "created_at", None)
        if model is Dataset:
            activity = max([row.created_at, *file_dates[row.id]])
        elif model is Job:
            activity = row.finished_at or row.updated_at
            if row.status not in TERMINAL or row.id in busy_jobs:
                executing.add(key)
        elif model is AgentSession:
            activity = row.last_user_activity_at or row.created_at
        elif model in {WorkflowRun, WorkflowPlanningRequest}:
            activity = row.updated_at
            if model is WorkflowRun:
                activity = max([activity, *interaction_dates[row.id]])
            if row.status in {"approved", "running", "cancel_requested", "planning"}:
                executing.add(key)
        if activity is not None and activity > cutoff:
            kept.add(key)
    for row in rows[JobTask]:
        if row.status not in TERMINAL:
            executing.add((Job, row.job_id))
    for row in rows[AgentTurn]:
        if row.status in {"queued", "running"}:
            executing.add((AgentSession, row.session_id))
    # Preserve the conversation and workflow driving work that has not actually finished.
    parents = defaultdict(set)
    for source, targets in edges.items():
        for target in targets:
            parents[target].add(source)
    pending = list(executing)
    while pending:
        for parent in parents[pending.pop()] - executing:
            executing.add(parent)
            pending.append(parent)
    kept.update(executing)
    pending = list(kept)
    while pending:
        for target in edges[pending.pop()] - kept:
            kept.add(target)
            pending.append(target)
    return set(groups) - kept


def _delete_rows(db, model, ids):
    ids = list(ids)
    for start in range(0, len(ids), 100):
        db.execute(delete(model).where(model.id.in_(ids[start:start + 100])), execution_options={"synchronize_session": False})


def delete_expired(db, owner_id, cutoff, stack, held):
    rows, groups, ownership, edges = _load_graph(db, owner_id)
    jobs = {row.id: row for row in rows[Job]}
    busy = set()
    for task in rows[JobTask]:
        job = jobs[task.job_id]
        if (job.status in TERMINAL and (job.finished_at or job.updated_at) <= cutoff
                and not _receipt_lock(stack, str(task.queue_job_id), held)):
            busy.add(job.id)
    expired = expired_groups(rows, groups, edges, cutoff, busy)
    selected = {model: {row.id for row in values if ownership[model.__tablename__, row.id] <= expired}
                for model, values in rows.items()}
    paths = [f"{directory}/{item}" for model, directory in ((Job, "jobs"), (Dataset, "datasets")) for item in selected[model]]
    queue_ids = [str(row.queue_job_id) for row in rows[JobTask] if row.id in selected[JobTask]]
    if paths or queue_ids:
        db.add(DataRetentionDeletion(paths=paths, queue_job_ids=queue_ids, owner_user_id=owner_id))
    # These nullable links form the session/proposal/workflow cycle; all selected groups expire together.
    db.execute(update(WorkflowRun).where(WorkflowRun.id.in_(selected[WorkflowRun])).values(action_proposal_id=None))
    db.execute(update(AgentSession).where(AgentSession.id.in_(selected[AgentSession])).values(active_workflow_id=None, preparation_job_id=None))
    db.execute(update(ActionProposal).where(ActionProposal.id.in_(selected[ActionProposal])).values(workflow_id=None))
    for model in (WorkflowEvent, WorkflowCommand, EditSession, DesignDraft, CandidateSet, ActionProposal,
                  AgentTurn, AgentSession, WorkflowPlanningRequest, WorkflowInteraction, WorkflowStep, WorkflowRun,
                  QueueOutbox, Job, Dataset, DeleteEditSpec):
        _delete_rows(db, model, selected[model])
    db.flush()
    return {"deleted_groups": len(expired), "retained_groups": len(groups) - len(expired)}


def _purge_redis(client, queue_ids):
    if not queue_ids:
        return
    with client.pipeline() as pipe:
        for item in queue_ids:
            pipe.set(f"genova:expired:{item}", "1")
            pipe.delete(f"genova:job:{item}")
        pipe.execute()
    wanted = set(queue_ids)
    for name in client.scan_iter(match="genova:queue:*", _type="list"):
        offset = 0
        while True:
            messages = client.lrange(name, offset, offset + 99)
            if not messages:
                break
            removed = 0
            for raw in messages:
                try:
                    message = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                if isinstance(message, dict) and str(message.get("job_id")) in wanted:
                    removed += client.lrem(name, 0, raw)
            offset += max(0, len(messages) - removed)


def retained_job_paths(db, root):
    return {Path(path).resolve() for path in db.scalars(select(DatasetFile.storage_path)
        .where(DatasetFile.storage_path.startswith(str(root) + '/', autoescape=True)))}


def purge_files(db, client, stack, held, *, manual_only=False, request_id=None):
    query = select(DataRetentionDeletion).order_by(DataRetentionDeletion.created_at).limit(100)
    if manual_only or not settings.data_retention_enabled:
        query = query.where(DataRetentionDeletion.origin == 'manual')
    if request_id is not None:
        query = query.where(DataRetentionDeletion.id == request_id)
    client = client if client is not None else redis.Redis.from_url(settings.redis_url, decode_responses=True)
    completed = 0
    for row in db.scalars(query):
        if not all(_receipt_lock(stack, item, held) for item in row.queue_job_ids):
            continue
        try:
            for item in row.queue_job_ids:
                # A content-free marker prevents late duplicate queue messages from rerunning deleted work.
                save_receipt(settings.data_root / ".runtime_receipts" / f"{item}.json", {"expired": True})
            _purge_redis(client, row.queue_job_ids)
            for relative in row.paths:
                path = settings.data_root / relative
                parts = Path(relative).parts
                if len(parts) != 2 or parts[0] not in {"jobs", "datasets"} or str(uuid.UUID(parts[1])) != parts[1]:
                    raise ValueError("Invalid retention deletion path")
                if path.parent.resolve() != settings.data_root / parts[0]:
                    raise ValueError("Retention directory must not be a symlink")
                if path.is_symlink():
                    path.unlink()
                elif path.exists():
                    protected = retained_job_paths(db, path) if row.origin == 'manual' and parts[0] == 'jobs' else set()
                    if protected:
                        for directory, folders, names in os.walk(path, topdown=False, followlinks=False):
                            for name in names:
                                item = Path(directory) / name
                                if item.resolve() not in protected:
                                    item.unlink()
                            for name in folders:
                                item = Path(directory) / name
                                if item.is_symlink():
                                    if not any(saved.is_relative_to(item.resolve()) for saved in protected):
                                        item.unlink()
                                elif not any(item.iterdir()):
                                    item.rmdir()
                    else:
                        shutil.rmtree(path)
            db.delete(row)
            completed += 1
        except (OSError, ValueError, RuntimeError, redis.RedisError) as exc:
            logger.warning("File deletion pending retry. deletion_id=%s error_type=%s", row.id, type(exc).__name__)
    db.flush()
    return completed


def retry_manual_deletions(client):
    with engine.connect().execution_options(retention_cleanup=True) as connection, Session(bind=connection) as db, ExitStack() as stack:
        with db.begin():
            purge_files(db, client, stack, set(), manual_only=True)


def maintain_runtime():
    from genova_runtime.queue_worker import compact_receipt
    compacted = 0
    removed = 0
    archives = 0
    cutoff = utcnow() - timedelta(days=1)
    with Session(engine) as db, db.begin():
        tokens = db.execute(delete(AuthRefreshToken).where(AuthRefreshToken.expires_at <= utcnow())).rowcount
        incomplete = list(db.scalars(select(Job).where(Job.status == 'pending',
            Job.created_at <= utcnow() - timedelta(hours=1),
            ~exists(select(JobTask.id).where(JobTask.job_id == Job.id))).with_for_update(skip_locked=True)))
        for job in incomplete:
            job.status = 'failed'
            job.finished_at = utcnow()
            job.summary = {**(job.summary or {}), 'error_code': 'JOB_TASKS_MISSING',
                'error': 'Task creation did not complete; no executable JobTask exists. Create a new task to retry.'}
            db.execute(update(WorkflowStep).where(WorkflowStep.job_id == job.id,
                WorkflowStep.status.in_(['pending', 'submitted', 'running']))
                .values(status='failed', error_message=job.summary['error']))
        tasks = db.execute(select(JobTask.queue_job_id, JobTask.status, JobTask.output_payload, JobTask.error_message)
            .where(JobTask.status.in_(['succeeded', 'failed', 'canceled', 'skipped']))
            .execution_options(yield_per=100))
        for queue_id, status, result, error in tasks:
            compacted += compact_receipt(settings.data_root / '.runtime_receipts' / f'{queue_id}.json', status,
                result=result or {}, error=error or '')
        known = {str(item) for item in db.scalars(select(Job.id))}
        known.update(str(item) for item in db.scalars(select(JobTask.queue_job_id)))
        for path in (settings.data_root / 'jobs').glob('*'):
            if path.is_symlink() or not path.is_dir() or path.name in known or path.stat().st_mtime > cutoff.timestamp():
                continue
            try:
                if str(uuid.UUID(path.name)) != path.name:
                    continue
            except ValueError:
                continue
            # rmdir refuses nonempty directories, including newly created runtime files.
            try:
                for child in sorted(path.rglob('*'), key=lambda item: len(item.parts), reverse=True):
                    if child.is_dir() and not child.is_symlink():
                        try:
                            child.rmdir()
                        except OSError:
                            pass
                path.rmdir()
                removed += 1
            except OSError:
                continue
        for path in (settings.data_root / 'tmp').glob('*.zip'):
            if path.is_file() and not path.is_symlink() and path.stat().st_mtime <= cutoff.timestamp():
                path.unlink(missing_ok=True)
                archives += 1
    if compacted or removed or tokens or incomplete or archives:
        logger.info('Runtime maintenance. receipts_compacted=%s empty_directories_removed=%s expired_tokens_removed=%s incomplete_jobs_failed=%s temporary_archives_removed=%s', compacted, removed, tokens, len(incomplete), archives)
    return {'receipts_compacted': compacted, 'empty_directories_removed': removed,
        'expired_tokens_removed': tokens, 'incomplete_jobs_failed': len(incomplete), 'temporary_archives_removed': archives}


def sweep(client, *, automatic=True):
    retry_manual_deletions(client)
    if not automatic:
        return True
    maintain_runtime()
    if not settings.data_retention_enabled:
        return True
    completed = True
    with engine.connect().execution_options(retention_cleanup=True) as connection:
        with Session(bind=connection) as db:
            owners = list(db.scalars(select(User.id).where(User.id != BUILTIN_OWNER_ID)))
            db.rollback()
        for owner in [*owners, None]:
            try:
                with ExitStack() as stack, Session(bind=connection, expire_on_commit=False) as db:
                    held = set()
                    with db.begin():
                        if not db.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": RETENTION_LOCK}):
                            completed = False
                            continue
                        policy = db.get(DataRetentionPolicy, 1)
                        cutoff = utcnow() - timedelta(days=RETENTION_DAYS)
                        if policy is None:
                            return False
                        if owner is not None and policy.first_enabled_at <= cutoff:
                            counts = delete_expired(db, owner, cutoff, stack, held)
                            logger.info("Retention sweep. %s", counts)
                        elif owner is None and policy.first_enabled_at <= cutoff:
                            parents = (AgentSession, WorkflowRun, DesignDraft, EditSession, ActionProposal, AgentTurn, CandidateSet, Job, Dataset, DeleteEditSpec, WorkflowPlanningRequest)
                            db.execute(delete(WorkflowEvent).where(WorkflowEvent.created_at <= cutoff,
                                *(~exists(select(model.id).where(model.id == WorkflowEvent.object_id)) for model in parents)))
                    with db.begin():
                        purge_files(db, client, stack, held)
                if owner is None and policy.first_enabled_at <= cutoff:
                    # Interrupted ZIP downloads are the only unowned artifacts in this directory.
                    for path in (settings.data_root / "tmp").glob("*.zip"):
                        if path.lstat().st_mtime <= cutoff.timestamp():
                            path.unlink(missing_ok=True)
            except Exception:
                completed = False
                logger.exception("Retention sweep failed; later sweeps will retry")
    return completed
