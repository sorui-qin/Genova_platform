import uuid
import math
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from rdkit import Chem
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.builtin_datasets import BUILTIN_OWNER_ID
from backend.db import get_db
from backend.deps import get_current_user
from backend.models import Dataset, DatasetFile, JobTask, SmallMoleculeResult, User
from backend.routers.postprocessing import artifact_path, owned_job
from backend.services.jobs import resolve_postprocessing_protein_artifact
from genova_runtime.structure_index import read_record, structure_index, molecule

router = APIRouter(prefix='/jobs', tags=['structures'])


def structure_artifact(db, user, job_id, pose):
    job = owned_job(db, user, job_id)
    codes = ['tarpass'] if pose != 'generated' else ['molecule_generation', 'surfgen_inference', 'property_optimization']
    task = db.scalar(select(JobTask).where(JobTask.job_id == job.id, JobTask.task_code.in_(codes), JobTask.status == 'succeeded'))
    if task is None:
        raise HTTPException(409, 'Structure results are not ready')
    return task, artifact_path(job, task.output_payload.get('generated_sdf' if pose == 'generated' else f'{pose}_sdf'))


@router.get('/{job_id}/structures/context')
def context(job_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    job = owned_job(db, user, job_id)
    codes = ['tarpass'] if job.job_type == 'molecule_postprocessing' else ['molecule_generation', 'surfgen_inference', 'property_optimization']
    task = db.scalar(select(JobTask).where(JobTask.job_id == job.id, JobTask.task_code.in_(codes)))
    inputs = task.input_payload if task else {}
    result = {}
    for key, path in [('protein', inputs.get('protein_pdb')), ('reference', inputs.get('reference_ligand') or (task.output_payload.get('ligand_path') if task else None))]:
        if key == 'protein' and job.job_type == 'molecule_postprocessing' and task and task.output_payload.get('protein_path'):
            path = resolve_postprocessing_protein_artifact(db, user.id, job, task)
            result[key] = dict(job_id=str(job.id), task_code=task.task_code, key='protein_path', format=path.suffix.lstrip('.').lower())
            continue
        file = db.scalar(select(DatasetFile).join(Dataset).where(DatasetFile.storage_path == path,
                         Dataset.owner_user_id.in_([user.id, BUILTIN_OWNER_ID]))) if path else None
        result[key] = {'dataset_id': str(file.dataset_id), 'file_id': str(file.id),
                       'format': Path(file.original_filename).suffix.lstrip('.').lower()} if file else None
    return result


@router.get('/{job_id}/structures')
def list_structures(job_id: uuid.UUID, result_id: uuid.UUID | None = None, molecule_id: str | None = Query(default=None, max_length=200),
                    pose: Literal['generated', 'original', 'docked'] = 'generated', offset: int = Query(default=0, ge=0),
                    limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task, path = structure_artifact(db, user, job_id, pose)
    index = structure_index(path)
    if pose == 'generated':
        row = db.scalar(select(SmallMoleculeResult).where(SmallMoleculeResult.job_task_id == task.id, SmallMoleculeResult.id == result_id))
        if row is None:
            raise HTTPException(404, 'Molecule result not found')
        mol = Chem.MolFromSmiles(row.smiles)
        key = Chem.MolToSmiles(Chem.RemoveHs(mol)) if mol is not None else ''
        ids = index['smiles'].get(key, [])
    else:
        if not molecule_id:
            raise HTTPException(422, 'molecule_id is required')
        ids = index['names'].get(molecule_id, [])
    return {'total': len(ids), 'records': [{'source_index': i} for i in ids[offset:offset + limit]], 'version': ':'.join(map(str, index['version']))}


@router.get('/{job_id}/structures/{source_index}')
def get_structure(job_id: uuid.UUID, source_index: int, pose: Literal['generated', 'original', 'docked'] = 'generated',
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _, path = structure_artifact(db, user, job_id, pose)
    if source_index < 0 or source_index >= len(structure_index(path)['records']):
        raise HTTPException(404, 'Structure record not found')
    block = read_record(path, source_index)
    mol = molecule(block)
    if mol is None or not mol.GetNumAtoms() or not mol.GetNumConformers() or not mol.GetConformer().Is3D() or not all(math.isfinite(float(v)) for point in mol.GetConformer().GetPositions() for v in point):
        raise HTTPException(409, 'The selected record requires a valid 3D pose')
    return Response(block, media_type='chemical/x-mdl-sdfile', headers={'Cache-Control': 'private, no-store'})
