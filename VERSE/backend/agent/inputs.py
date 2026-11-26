from pathlib import Path

from sqlalchemy import func, literal, or_, select
from sqlalchemy.orm import defer

from backend.models import Dataset, DatasetFile


def search_inputs(db, user_id, query, *, protein_only=False):
    query = query.strip()[:200]
    files = select(DatasetFile.id).where(DatasetFile.dataset_id == Dataset.id)
    stem = func.regexp_replace(DatasetFile.original_filename, r'\.[^.]*$', '')
    match = or_(Dataset.name.icontains(query, autoescape=True), files.where(or_(
        DatasetFile.original_filename.icontains(query, autoescape=True),
        (func.length(stem) >= 3) & (func.strpos(func.lower(literal(query)), func.lower(stem)) > 0),
    )).exists())
    stmt = select(Dataset).where(Dataset.owner_user_id == user_id, Dataset.status != 'archived', match)
    if protein_only:
        stmt = stmt.where(Dataset.kind.notin_(['protein_context', 'prepared_receptor']), files.where(
            DatasetFile.original_filename.op('~*')(r'\.(pdb|cif|mmcif)$')).exists()).options(defer(Dataset.meta))
    else:
        stmt = stmt.where(or_(Dataset.kind.notin_(['protein_context', 'prepared_receptor']),
            (Dataset.kind == 'prepared_receptor') & (Dataset.meta['preparation']['receptor_policy'].astext == 'protein_metals_v1') & (Dataset.meta['preparation']['scope_policy'].astext == 'supported_protein_v1'),
            (Dataset.kind == 'protein_context') & (Dataset.meta['capabilities']['receptor_policy'].astext == 'protein_metals_v1') & (Dataset.meta['capabilities']['input_preparation'].astext == 'context_features_v1')))
    rows = db.scalars(stmt.order_by(Dataset.created_at.desc(), Dataset.id.desc()).limit(20)).all()
    by_dataset = {row.id: [] for row in rows}
    if by_dataset:
        for file in db.scalars(select(DatasetFile).where(DatasetFile.dataset_id.in_(by_dataset)).order_by(DatasetFile.created_at, DatasetFile.id)):
            if not protein_only or Path(file.original_filename).suffix.lower() in {'.pdb', '.cif', '.mmcif'}:
                by_dataset[file.dataset_id].append({'id': str(file.id), 'name': file.original_filename, 'role': file.file_role})
    return [{'id': str(row.id), 'name': row.name, 'kind': row.kind, 'preparation_status': row.status,
             'files': by_dataset[row.id]} for row in rows]
