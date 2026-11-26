import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Float, cast, select
from sqlalchemy.orm import Session

from backend import schemas
from backend.db import get_db
from backend.deps import get_current_user
from backend.models import Job, SmallMoleculeResult, User


router = APIRouter(prefix="/results", tags=["results"])


@router.get("", response_model=list[schemas.SmallMoleculeResultOut])
def list_results(
    job_id: uuid.UUID | None = Query(default=None),
    task_code: str | None = Query(default=None),
    smiles: str | None = Query(default=None),
    is_hit: bool | None = Query(default=None),
    min_score: float | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    owner_job_ids = select(Job.id).where(Job.owner_user_id == current_user.id, Job.is_deleted.is_(False))
    stmt = select(SmallMoleculeResult).where(SmallMoleculeResult.job_id.in_(owner_job_ids))

    if job_id is not None:
        stmt = stmt.where(SmallMoleculeResult.job_id == job_id)
    if task_code:
        stmt = stmt.where(SmallMoleculeResult.task_code == task_code)
    if smiles:
        stmt = stmt.where(SmallMoleculeResult.smiles_canonical == smiles)
    if is_hit is not None:
        stmt = stmt.where(SmallMoleculeResult.extra["is_hit"].astext == ("true" if is_hit else "false"))
    if min_score is not None:
        stmt = stmt.where(cast(SmallMoleculeResult.extra["score"].astext, Float) >= min_score)

    rows = db.scalars(stmt.order_by(SmallMoleculeResult.created_at.desc()).limit(limit).offset(offset)).all()
    return [schemas.SmallMoleculeResultOut.model_validate(row) for row in rows]


@router.get("/{result_id}", response_model=schemas.SmallMoleculeResultOut)
def get_result(
    result_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    owner_job_ids = select(Job.id).where(Job.owner_user_id == current_user.id, Job.is_deleted.is_(False))
    row = db.scalar(
        select(SmallMoleculeResult).where(
            SmallMoleculeResult.id == result_id,
            SmallMoleculeResult.job_id.in_(owner_job_ids),
        )
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Result not found")
    return schemas.SmallMoleculeResultOut.model_validate(row)

