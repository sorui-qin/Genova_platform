import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, status, HTTPException
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.deps import get_current_user
from backend.models import User
from backend.schemas import ProteinContextListOut
from backend.services import protein_contexts as service

router = APIRouter(tags=["protein-contexts"])

@router.get("/datasets/{dataset_id}/protein-analysis")
def get_protein_analysis(dataset_id: uuid.UUID, file_id: uuid.UUID | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = service.get_protein_analysis(dataset_id, db=db, user_id=current_user.id, file_id=file_id)
    db.commit()
    return result


@router.post("/protein-contexts", status_code=status.HTTP_201_CREATED)
def create_protein_context(payload: dict[str, Any], db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = service.create_protein_context(payload, db=db, user_id=current_user.id)
    db.commit()
    return result


@router.get("/protein-contexts", response_model=list[ProteinContextListOut])
def list_protein_contexts(limit: int = Query(default=21, ge=1, le=200), offset: int = Query(default=0, ge=0),
                          search: str | None = Query(default=None, max_length=200),
                          db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = service.list_protein_contexts(db=db, user_id=current_user.id, limit=limit, offset=offset, search=search)
    db.commit()
    return result


@router.get("/protein-contexts/{context_id}")
def get_protein_context(context_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = service.get_protein_context(context_id, db=db, user_id=current_user.id)
    db.commit()
    return result


@router.get('/protein-contexts/{context_id}/capabilities')
def get_context_capabilities(context_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    context = service.get_protein_context(context_id, db, current_user.id)
    return {'version': 4, 'status': context['status'], 'capabilities': context.get('capabilities') or {}}


@router.post('/protein-contexts/{context_id}/retry-validation')
def retry_context_validation(context_id: uuid.UUID, engine: str = Query(...),
                             db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from backend.services.context_features import ENGINES, enqueue_context_validation
    if engine not in ENGINES:
        raise HTTPException(422, 'Unknown preparation engine')
    dataset = service._context_or_404(db, context_id, current_user.id)
    if dataset.owner_user_id != current_user.id:
        raise HTTPException(404, 'Protein Context not found')
    enqueue_context_validation(dataset, db, current_user.id, engines=[engine])
    result = service._serialize_context(dataset, db)
    db.commit()
    return result
