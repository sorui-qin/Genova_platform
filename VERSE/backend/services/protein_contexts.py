import uuid
from copy import deepcopy
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.orm import Session

from backend.builtin_datasets import BUILTIN_OWNER_ID
from backend.models import Dataset, DatasetFile
from backend.protein_context import parse_protein_pdb
from backend.structure_contracts import ProteinContextV4Create, ProteinContextV4Record


def _dataset_or_404(db: Session, dataset_id: uuid.UUID, user_id: uuid.UUID) -> Dataset:
    dataset = db.scalar(select(Dataset).where(
        Dataset.id == dataset_id,
        or_(Dataset.owner_user_id == user_id, Dataset.owner_user_id == BUILTIN_OWNER_ID),
    ))
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return dataset


def _context_or_404(db: Session, context_id: uuid.UUID, user_id: uuid.UUID) -> Dataset:
    dataset = _dataset_or_404(db, context_id, user_id)
    db.refresh(dataset, with_for_update=True)
    if dataset.kind != "protein_context" or dataset.status == "archived":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Protein Context not found")
    return dataset


def _protein_file_or_400(db: Session, dataset_id: uuid.UUID, file_id=None) -> DatasetFile:
    files = db.scalars(select(DatasetFile).where(DatasetFile.dataset_id == dataset_id)).all()
    pdb_files = [row for row in files if Path(row.original_filename).suffix.lower() in {".pdb", ".cif", ".mmcif"}]
    if file_id:
        pdb_files = [item for item in pdb_files if str(item.id) == str(file_id)]
    elif len(pdb_files) > 1:
        raise HTTPException(422, "Select a specific protein file")
    row = next((item for item in pdb_files if item.file_role == "pocket_pdb"), None) or next(iter(pdb_files), None)
    if row is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dataset does not contain a PDB file")
    if not Path(row.storage_path).is_file():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Dataset file missing: {row.storage_path}")
    return row




def _serialize_context(dataset, db):
    try:
        ProteinContextV4Record.model_validate(dataset.meta)
    except ValueError as exc:
        raise HTTPException(409, "Invalid Protein Context contract") from exc
    result = {"id": str(dataset.id), "name": dataset.name, "status": dataset.status,
              **deepcopy(dataset.meta), "created_at": dataset.created_at.isoformat(), "updated_at": dataset.updated_at.isoformat()}
    from backend.services.binding_sites import resolve_v4_context
    result['capabilities'] = resolve_v4_context(dataset, db, dataset.owner_user_id)['capabilities']
    if result.get('compatibility'):
        for name, profile in result['capabilities'].get('engine_support', {}).items():
            if name in result['compatibility']['models'] and result['compatibility']['models'][name]['status'] != profile['status']:
                result['compatibility']['models'][name].update(status=profile['status'], error=profile.get('reason', ''), error_info=profile.get('error_info'))
    return result


def get_protein_analysis(
    dataset_id: uuid.UUID,
    db: Session,
    user_id: uuid.UUID,
    file_id: uuid.UUID | None = None,
):
    dataset = _dataset_or_404(db, dataset_id, user_id)
    db.refresh(dataset, with_for_update=True)
    row = _protein_file_or_400(db, dataset.id, file_id)
    cached = (dataset.meta or {}).get("protein_analysis") or {}
    if (
        cached.get("version") == 2
        and cached.get("source_file_id") == str(row.id)
        and cached.get("source_sha256") == row.sha256
    ):
        return cached

    analysis = {
        **parse_protein_pdb(Path(row.storage_path)),
        "source_file_id": str(row.id),
        "source_sha256": row.sha256,
    }
    meta = deepcopy(dataset.meta or {})
    meta["protein_analysis"] = analysis
    dataset.meta = meta
    db.flush()
    return analysis


def create_protein_context(payload, db, user_id):
    try:
        ProteinContextV4Create.model_validate(payload)
    except ValueError as exc:
        raise HTTPException(422, "Protein Context requires the v4 contract") from exc
    from backend.services.binding_sites import create_site
    return create_site(payload, db, user_id)


def list_protein_contexts(db, user_id, limit=21, offset=0, search=None):
    stmt = select(Dataset.id, Dataset.name, Dataset.status, func.coalesce(and_(
        Dataset.status == 'ready',
        Dataset.meta['artifacts']['effective_receptor']['file_id'].astext.is_not(None),
        Dataset.meta['capabilities']['structure_validation'].astext == 'passed',
    ), False).label('ready')).where(Dataset.owner_user_id == user_id, Dataset.kind == "protein_context",
        Dataset.status != "archived", Dataset.meta["version"].as_integer() == 4,
        Dataset.meta["capabilities"]["receptor_policy"].astext == "protein_metals_v1",
        Dataset.meta["capabilities"]["input_preparation"].astext == "context_features_v1")
    if search and search.strip():
        pattern = '%' + search.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        stmt = stmt.where(or_(Dataset.name.ilike(pattern), cast(Dataset.id, String).ilike(pattern)))
    return db.execute(stmt.order_by(Dataset.created_at.desc(), Dataset.id.desc()).limit(limit).offset(offset)).all()


def get_protein_context(
    context_id: uuid.UUID,
    db: Session,
    user_id: uuid.UUID,
):
    return _serialize_context(_context_or_404(db, context_id, user_id), db)
