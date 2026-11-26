import json
import uuid
from typing import Any

import redis
import redis.asyncio as redis_async
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models import Job, JobTask


USER_CHANNEL_PREFIX = "genova:ws:user"


def get_user_channel(user_id: uuid.UUID) -> str:
    return f"{USER_CHANNEL_PREFIX}:{user_id}"


def get_async_redis_client() -> redis_async.Redis:
    return redis_async.Redis.from_url(settings.redis_url, decode_responses=True)


def get_sync_redis_client() -> redis.Redis:
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:
        return str(value)


def build_job_event(job: Job, task: JobTask | None = None, *, event: str = "job.updated", deleted: bool = False) -> dict[str, Any]:
    params = dict(job.params or {})
    job_name = str(params.get("job_name") or params.get("name") or f"{job.job_type}_{str(job.id)[:8]}")
    task_error = task.error_message if task is not None else None
    task_status = task.status if task is not None else None

    payload = {
        "event": event,
        "object": {
            "id": str(job.id),
            "name": job_name,
            "job_type": job.job_type,
            "status": job.status,
            "task_code": task.task_code if task is not None else None,
            "task_status": task_status,
            "created_at": _iso(job.created_at),
            "updated_at": _iso(job.updated_at),
            "finished_at": _iso(job.finished_at),
            "deleted": deleted,
            "error_message": task_error,
        },
    }
    return payload


def publish_user_event_sync(
    user_id: uuid.UUID,
    payload: dict[str, Any],
    *,
    redis_client: redis.Redis | None = None,
) -> None:
    client = redis_client
    should_close = client is None
    if client is None:
        client = get_sync_redis_client()
    try:
        client.publish(get_user_channel(user_id), json.dumps(payload, ensure_ascii=False))
    finally:
        if should_close and client is not None:
            client.close()


def publish_job_event_sync(
    db: Session,
    job_id: uuid.UUID,
    *,
    task_id: uuid.UUID | None = None,
    event: str = "job.updated",
    redis_client: redis.Redis | None = None,
) -> None:
    job = db.get(Job, job_id)
    if job is None:
        return
    task = db.get(JobTask, task_id) if task_id is not None else None
    publish_user_event_sync(
        job.owner_user_id,
        build_job_event(job, task, event=event),
        redis_client=redis_client,
    )

