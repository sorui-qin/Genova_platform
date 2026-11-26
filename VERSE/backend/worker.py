import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import redis
from sqlalchemy import select, update, cast, String
from sqlalchemy.exc import InterfaceError, OperationalError, TimeoutError as SQLTimeoutError
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db import Base, SessionLocal, engine
from backend.models import Job, JobTask, QueueOutbox, SmallMoleculeResult
from backend.realtime import publish_job_event_sync
from backend.result_rows import (
    read_molecule_generation_rows,
    read_property_optimization_rows,
    upsert_small_molecule_rows,
)

from backend.utils import parse_iso_datetime, utcnow
from genova_runtime.queue_delivery import acknowledge_message, queue_consumer, reserve_message


logger = logging.getLogger("backend-worker")
TERMINAL_TASK_STATUSES = {"succeeded", "failed", "skipped", "canceled"}
ACTIVE_TASK_STATUSES = {"pending", "blocked", "queued", "running"}


def _update_protein_preparation_context(db, task, *, status_value, result_payload=None, error_message=None):
    if task.task_code.startswith("context_compatibility_"):
        from backend.services.context_features import complete_context_validation
        return complete_context_validation(db, task, status_value, result_payload, error_message)
    job = db.get(Job, task.job_id)
    if job is None or job.job_type != "protein_preparation":
        return
    if (job.params or {}).get("preparation_protocol_version") != 2:
        raise ValueError("Protein preparation requires protocol v2")
    from backend.services.prepared_receptors import complete_preparation
    return complete_preparation(db, job, task, status_value, result_payload, error_message)


def _fail_protein_preparation_context(db: Session, task: JobTask) -> None:
    try:
        _update_protein_preparation_context(db, task, status_value="failed", error_message=task.error_message, result_payload=task.output_payload)
    except ValueError as exc:
        # The Context was deleted, edited or re-prepared; the task still has to fail without crashing the worker.
        if task.task_code.startswith('context_compatibility_'):
            from backend.services.context_features import complete_context_validation
            complete_context_validation(db, task, 'failed', error=task.error_message)
        job = db.get(Job, task.job_id)
        if job and (job.params or {}).get('prepared_receptor_id'):
            from backend.models import Dataset
            receptor = db.get(Dataset, uuid.UUID(job.params['prepared_receptor_id']))
            if receptor and receptor.status == 'processing' and (receptor.meta.get('execution') or {}).get('job_id') == str(job.id):
                receptor.status = 'failed'
                receptor.meta = {**receptor.meta, 'execution': {**receptor.meta['execution'], 'status': 'failed', 'error': task.error_message}}
                receptor.updated_at = utcnow()
        logger.warning("Protein preparation result rejected for task_id=%s: %s", task.id, exc)


def ensure_tables() -> None:
    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)


def _publish_job_update(db: Session, job_id: uuid.UUID, *, task_id: uuid.UUID | None = None, redis_client: redis.Redis | None = None) -> None:
    try:
        publish_job_event_sync(
            db,
            job_id,
            task_id=task_id,
            event="job.updated",
            redis_client=redis_client,
        )
    except Exception:
        logger.exception("Failed publishing realtime update for job_id=%s", job_id)


def update_job_aggregate(db: Session, job_id: uuid.UUID) -> None:
    job = db.get(Job, job_id)
    if job is None:
        return

    tasks = db.scalars(select(JobTask).where(JobTask.job_id == job_id)).all()
    if not tasks:
        return

    tasks = [task for task in tasks if not task.task_code.startswith("plip2d_")]
    if not tasks:
        return
    statuses = [task.status for task in tasks]
    now = utcnow()
    started_candidates = [task.started_at for task in tasks if task.started_at is not None]
    finished_candidates = [task.finished_at for task in tasks if task.finished_at is not None]

    if any(status in {"running", "queued"} for status in statuses):
        job.status = "running"
    elif any(status in {"pending", "blocked"} for status in statuses):
        job.status = "pending"
    else:
        failed_count = sum(1 for status in statuses if status == "failed")
        succeeded_count = sum(1 for status in statuses if status == "succeeded")
        if failed_count == 0:
            job.status = "succeeded"
        elif succeeded_count > 0:
            job.status = "partial_succeeded"
        else:
            job.status = "failed"
        if all(status in TERMINAL_TASK_STATUSES for status in statuses):
            job.finished_at = max(finished_candidates) if finished_candidates else now

    if started_candidates and job.started_at is None:
        job.started_at = min(started_candidates)
    job.updated_at = now
    summary = dict(job.summary or {})
    summary["task_counts"] = {
        "total": len(statuses),
        "pending": sum(1 for status in statuses if status == "pending"),
        "blocked": sum(1 for status in statuses if status == "blocked"),
        "queued": sum(1 for status in statuses if status == "queued"),
        "running": sum(1 for status in statuses if status == "running"),
        "succeeded": sum(1 for status in statuses if status == "succeeded"),
        "failed": sum(1 for status in statuses if status == "failed"),
        "skipped": sum(1 for status in statuses if status == "skipped"),
        "canceled": sum(1 for status in statuses if status == "canceled"),
    }
    job.summary = summary


def _mark_task_failed_from_processing_error(queue_job_id: uuid.UUID, error_message: str) -> None:
    with SessionLocal() as db:
        event_to_publish: tuple[uuid.UUID, uuid.UUID] | None = None
        with db.begin():
            task = db.scalar(select(JobTask).where(JobTask.queue_job_id == queue_job_id))
            if task is None or task.status in TERMINAL_TASK_STATUSES:
                return
            task.status = "failed"
            task.error_message = str(error_message)[:8000]
            if not task.input_payload.get('previous_output_csv'):
                task.output_payload = {}
            task.finished_at = utcnow()
            task.updated_at = utcnow()
            _fail_protein_preparation_context(db, task)
            _mark_downstream_skipped_on_failure(db, task)
            if not task.task_code.startswith("plip2d_"):
                update_job_aggregate(db, task.job_id)
                event_to_publish = (task.job_id, task.id)
        if event_to_publish:
            _publish_job_update(db, event_to_publish[0], task_id=event_to_publish[1])


def _mark_downstream_skipped_on_failure(db: Session, failed_task: JobTask) -> None:
    dependents = db.scalars(
        select(JobTask).where(
            JobTask.job_id == failed_task.job_id,
            JobTask.status.in_(["pending", "blocked"]),
        )
    ).all()
    for dep in dependents:
        depends_on = dep.depends_on or []
        if failed_task.task_code not in depends_on:
            continue
        dep.status = "skipped"
        dep.output_payload = {
            "reason": "upstream_failed",
            "upstream_task_code": failed_task.task_code,
            "upstream_task_id": str(failed_task.id),
        }
        dep.error_message = None
        dep.finished_at = utcnow()
        dep.updated_at = utcnow()


def process_outbox_batch(rds: redis.Redis) -> int:
    processed = 0
    with SessionLocal() as db:
        while True:
            pending_events: list[tuple[uuid.UUID, uuid.UUID]] = []
            with db.begin():
                stmt = (
                    select(QueueOutbox)
                    .where(QueueOutbox.status == "pending")
                    .order_by(QueueOutbox.id.asc())
                    .limit(settings.outbox_batch_size)
                    .with_for_update(skip_locked=True)
                )
                records = db.scalars(stmt).all()
                if not records:
                    break

                for row in records:
                    try:
                        task = db.scalar(select(JobTask).where(JobTask.id == row.job_task_id).with_for_update().execution_options(populate_existing=True))
                        if task is not None and (task.status in TERMINAL_TASK_STATUSES
                                                 or str(task.queue_job_id) != row.payload.get('job_id')):
                            row.status = "canceled"
                            row.updated_at = utcnow()
                            continue
                        rds.lpush(row.queue_name, json.dumps(row.payload, ensure_ascii=False))
                        row.status = "sent"
                        row.sent_at = utcnow()
                        row.updated_at = utcnow()
                        if task is not None and task.status in {"pending", "blocked"}:
                            task.status = "queued"
                            task.updated_at = utcnow()
                            if not task.task_code.startswith("plip2d_"):
                                update_job_aggregate(db, task.job_id)
                                pending_events.append((task.job_id, task.id))
                        processed += 1
                    except Exception as exc:
                        row.attempts += 1
                        row.last_error = str(exc)
                        row.updated_at = utcnow()
                        if row.attempts >= settings.outbox_max_attempts:
                            row.status = "failed"
                            task = db.get(JobTask, row.job_task_id)
                            if task is not None and task.status not in TERMINAL_TASK_STATUSES:
                                task.status = "failed"
                                task.error_message = f"Queue dispatch failed after {row.attempts} attempts"
                                if not task.input_payload.get('previous_output_csv'):
                                    task.output_payload = {}
                                task.finished_at = utcnow()
                                task.updated_at = task.finished_at
                                _fail_protein_preparation_context(db, task)
                                _mark_downstream_skipped_on_failure(db, task)
                                if not task.task_code.startswith("plip2d_"):
                                    update_job_aggregate(db, task.job_id)
                                    pending_events.append((task.job_id, task.id))
            for job_id, task_id in pending_events:
                _publish_job_update(db, job_id, task_id=task_id, redis_client=rds)
            if len(records) < settings.outbox_batch_size:
                break
    return processed


def recover_outbox() -> None:
    with SessionLocal() as db, db.begin():
        db.execute(update(QueueOutbox).where(
            QueueOutbox.status == "sent",
            QueueOutbox.job_task_id.in_(select(JobTask.id).where(
                JobTask.status.in_(ACTIVE_TASK_STATUSES),
                cast(JobTask.queue_job_id, String) == QueueOutbox.payload['job_id'].astext,
            )),
        ).values(status="pending", attempts=0, last_error=None))


def process_one_result(rds: redis.Redis) -> bool:
    raw = reserve_message(rds, settings.redis_result_queue, settings.result_brpop_timeout)
    if raw is None:
        return False
    _process_result_message(rds, raw)
    acknowledge_message(rds, settings.redis_result_queue, raw)
    return True


def _process_result_message(rds: redis.Redis, raw) -> None:
    try:
        message = json.loads(raw)
        if not isinstance(message, dict):
            raise ValueError("Result message must be an object")
    except Exception:
        logger.exception("Invalid result queue message: %s", raw)
        return

    queue_job_id_raw = str(message.get("job_id", "")).strip()
    if not queue_job_id_raw:
        logger.error("Result missing job_id: %s", message)
        return

    try:
        queue_job_id = uuid.UUID(queue_job_id_raw)
    except Exception:
        logger.warning("Skip invalid result message job_id=%s", queue_job_id_raw)
        return

    try:
        event_to_publish: tuple[uuid.UUID, uuid.UUID] | None = None
        with SessionLocal() as db:
            with db.begin():
                task = db.scalar(select(JobTask).where(JobTask.queue_job_id == queue_job_id)
                                 .with_for_update().execution_options(populate_existing=True))
                if task is None:
                    logger.warning("No job_task found for queue_job_id=%s", queue_job_id)
                    return

                if task.status in TERMINAL_TASK_STATUSES:
                    if task.status == 'canceled' and task.task_code == 'protein_preparation' and message.get('status') == 'failed' and isinstance(message.get('result'), dict) and message['result'].get('report'):
                        _update_protein_preparation_context(db, task, status_value='failed', result_payload=message['result'], error_message=task.error_message)
                    if task.status == 'canceled' and task.task_code.startswith('context_compatibility_') and message.get('status') == 'failed' and isinstance(message.get('result'), dict) and message['result'].get('compatibility_report'):
                        _update_protein_preparation_context(db, task, status_value='failed', result_payload=message['result'], error_message=task.error_message)
                    return

                task.started_at = parse_iso_datetime(message.get("started_at")) or task.started_at or utcnow()
                task.finished_at = parse_iso_datetime(message.get("finished_at")) or utcnow()
                task.updated_at = utcnow()

                status_value = str(message.get("status", "")).strip().lower()
                if status_value == "succeeded":
                    task.status = "succeeded"
                    result_payload = message.get("result", {})
                    if not isinstance(result_payload, dict):
                        result_payload = {"raw": result_payload}
                    task.output_payload = result_payload
                    task.error_message = None

                    inserted = 0
                    if task.task_code.startswith('plip2d_') and result_payload.get('interaction_details'):
                        row = db.scalar(select(SmallMoleculeResult).where(
                            SmallMoleculeResult.job_id == task.job_id,
                            SmallMoleculeResult.task_code == 'tarpass',
                            SmallMoleculeResult.extra.contains({'molecule_id': task.input_payload['molecule_id']}),
                        ).with_for_update())
                        if row is not None:
                            extra = deepcopy(row.extra)
                            extra.setdefault('metrics', {}).setdefault(task.input_payload['pose'], {})['interaction_details'] = result_payload['interaction_details']
                            row.extra = extra
                    elif task.task_code == "protein_preparation" or task.task_code.startswith("context_compatibility_"):
                        _update_protein_preparation_context(
                            db,
                            task,
                            status_value="succeeded",
                            result_payload=result_payload,
                        )
                    elif task.task_code == "tarpass":
                        from backend.result_rows import read_tarpass_rows
                        inserted += upsert_small_molecule_rows(db, job_id=task.job_id, job_task_id=task.id, task_code='tarpass', rows=read_tarpass_rows(result_payload))
                        task.output_payload = {**task.output_payload, 'result_index_version': 1}
                    elif task.task_code == "molecule_generation":
                        mol_gen_rows = read_molecule_generation_rows(result_payload)
                        inserted += upsert_small_molecule_rows(
                            db,
                            job_id=task.job_id,
                            job_task_id=task.id,
                            task_code="molecule_generation",
                            rows=mol_gen_rows,
                        )
                    elif task.task_code == "property_optimization":
                        property_rows = read_property_optimization_rows(result_payload)
                        inserted += upsert_small_molecule_rows(
                            db,
                            job_id=task.job_id,
                            job_task_id=task.id,
                            task_code="property_optimization",
                            rows=property_rows,
                        )
                    if task.task_code in {'tarpass', 'molecule_generation', 'property_optimization'}:
                        from genova_runtime.structure_index import structure_index
                        for key in ('generated_sdf', 'original_sdf', 'docked_sdf'):
                            path = result_payload.get(key)
                            if path and Path(path).is_file():
                                try:
                                    structure_index(path)
                                except (OSError, ValueError, RuntimeError):
                                    logger.exception('Structure index will be rebuilt on first access: %s', path)
                    if inserted:
                        payload = dict(task.output_payload or {})
                        payload["inserted_rows"] = inserted
                        task.output_payload = payload

                else:
                    task.status = "failed"
                    task.error_message = str(message.get("error", ""))[:8000]
                    if not task.input_payload.get('previous_output_csv'):
                        task.output_payload = message.get("result") or {}
                    _fail_protein_preparation_context(db, task)
                    _mark_downstream_skipped_on_failure(db, task)

                if not task.task_code.startswith("plip2d_"):
                    update_job_aggregate(db, task.job_id)
                    event_to_publish = (task.job_id, task.id)
            if task.status == 'succeeded':
                try:
                    from backend.services.artifact_cleanup import cleanup_task_artifacts
                    cleanup_task_artifacts(task)
                except Exception:
                    logger.exception('Artifact cleanup failed for task_id=%s', task.id)
            if event_to_publish:
                _publish_job_update(db, event_to_publish[0], task_id=event_to_publish[1], redis_client=rds)
    except (InterfaceError, OperationalError, SQLTimeoutError):
        raise
    except Exception as exc:
        logger.exception("Failed processing result message for queue_job_id=%s", queue_job_id)
        _mark_task_failed_from_processing_error(
            queue_job_id,
            f"backend-worker result processing failed: {exc}",
        )
    return


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    ensure_tables()
    rds = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    logger.info(
        "Backend worker online. dispatch_queue=%s result_queue=%s",
        settings.redis_dispatch_queue,
        settings.redis_result_queue,
    )

    from backend.retention import sweep
    cleaner = ThreadPoolExecutor(max_workers=1, thread_name_prefix="data-retention")
    cleanup = None
    next_cleanup = 0
    next_automatic_cleanup = 0
    with queue_consumer(rds, settings.redis_result_queue):
        recover_outbox()
        while True:
            if cleanup is not None and cleanup.done():
                try:
                    completed = cleanup.result()
                except Exception:
                    logger.exception("Retention worker failed; retrying in one minute")
                    completed = False
                if not completed:
                    next_automatic_cleanup = 0
                cleanup = None
            if cleaner and time.monotonic() >= next_cleanup and (cleanup is None or cleanup.done()):
                automatic = time.monotonic() >= next_automatic_cleanup
                cleanup = cleaner.submit(sweep, rds, automatic=automatic)
                next_cleanup = time.monotonic() + 30
                if automatic:
                    next_automatic_cleanup = time.monotonic() + 3600
            sent = process_outbox_batch(rds)
            got_result = process_one_result(rds)
            if sent == 0 and not got_result:
                time.sleep(settings.worker_idle_sleep_seconds)


if __name__ == "__main__":
    main()
