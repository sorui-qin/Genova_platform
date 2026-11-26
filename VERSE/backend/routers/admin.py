from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend import schemas
from backend.db import get_db
from backend.deps import get_current_admin_user
from backend.models import Job, User


router = APIRouter(prefix="/admin", tags=["admin"])

ACTIVE_JOB_STATUSES = {"pending", "running", "queued", "blocked"}


@router.get("/monitor", response_model=schemas.AdminMonitorResponseOut)
def get_admin_monitor(
    email: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
):
    email_filter = (email or "").strip().lower()
    status_filter = (status or "").strip().lower()

    rows_stmt = (
        select(Job, User.email, User.username)
        .join(User, User.id == Job.owner_user_id)
    )
    count_stmt = select(func.count()).select_from(Job).join(User, User.id == Job.owner_user_id)

    if email_filter:
        like_value = f"%{email_filter}%"
        rows_stmt = rows_stmt.where(User.email.ilike(like_value))
        count_stmt = count_stmt.where(User.email.ilike(like_value))

    if status_filter == "deleted":
        rows_stmt = rows_stmt.where(Job.is_deleted.is_(True))
        count_stmt = count_stmt.where(Job.is_deleted.is_(True))
    elif status_filter and status_filter != "all":
        rows_stmt = rows_stmt.where(Job.status == status_filter)
        count_stmt = count_stmt.where(Job.status == status_filter)

    rows = db.execute(
        rows_stmt
        .order_by(Job.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    items = [
        schemas.AdminMonitorJobOut(
            id=job.id,
            owner_user_id=job.owner_user_id,
            owner_email=owner_email,
            owner_username=owner_username,
            job_type=job.job_type,
            status=job.status,
            priority=job.priority,
            params=job.params or {},
            summary=job.summary or {},
            is_deleted=job.is_deleted,
            deleted_at=job.deleted_at,
            created_at=job.created_at,
            updated_at=job.updated_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )
        for job, owner_email, owner_username in rows
    ]

    stats = schemas.AdminMonitorStatsOut(
        current_jobs=db.scalar(
            select(func.count()).select_from(Job).where(Job.status.in_(ACTIVE_JOB_STATUSES), Job.is_deleted.is_(False))
        ) or 0,
        total_jobs=db.scalar(select(func.count()).select_from(Job)) or 0,
        total_users=db.scalar(select(func.count()).select_from(User)) or 0,
    )

    total_matched = db.scalar(count_stmt) or 0
    return schemas.AdminMonitorResponseOut(
        stats=stats,
        total_matched=total_matched,
        items=items,
    )
