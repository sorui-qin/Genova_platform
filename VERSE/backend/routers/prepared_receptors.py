import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.deps import get_current_user
from backend.models import User
from backend.services import prepared_receptors as service
from backend.structure_contracts import ComponentManifest, PreparedReceptorCreate, PreparedReceptorOut, PreparedReceptorSummary, StructureSource


router = APIRouter(tags=["prepared-receptors"])




@router.get("/protein-preparation/capabilities")
def preparation_capabilities(current_user: User = Depends(get_current_user)):
    return {"context_versions": [4], "preparation_version": 2}



@router.get("/prepared-receptors", response_model=list[PreparedReceptorSummary])
def list_prepared_receptors(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from sqlalchemy import select
    from backend.models import Dataset
    rows = db.execute(select(Dataset.id, Dataset.name, Dataset.status, Dataset.meta["execution"]["job_id"].astext.label("job_id")).where(Dataset.owner_user_id == current_user.id, Dataset.kind == "prepared_receptor", Dataset.meta["preparation"]["receptor_policy"].astext == "protein_metals_v1", Dataset.meta["preparation"]["scope_policy"].astext == "supported_protein_v1").order_by(Dataset.created_at.desc())).all()
    return [dict(row._mapping) for row in rows]


@router.post("/prepared-receptors", status_code=status.HTTP_201_CREATED, response_model=PreparedReceptorOut)
def create_prepared_receptor(payload: PreparedReceptorCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = service.create_prepared_receptor(payload, db=db, user_id=current_user.id)
    db.commit()
    return result




@router.get("/prepared-receptors/{receptor_id}", response_model=PreparedReceptorOut)
def get_prepared_receptor(receptor_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return service.get_prepared_receptor(receptor_id, db=db, user_id=current_user.id)


@router.get("/datasets/{dataset_id}/component-manifest", response_model=ComponentManifest)
def get_component_manifest(dataset_id: uuid.UUID, file_id: uuid.UUID, sha256: str, model_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from fastapi.exceptions import RequestValidationError
    from pydantic import ValidationError

    try:
        source = StructureSource(dataset_id=dataset_id, file_id=file_id, sha256=sha256, model_id=model_id)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc
    return service.get_component_manifest(source, db=db, user_id=current_user.id)
