import csv
import io
import json
import math
import uuid
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.services.jobs import source_reference_ligand, source_postprocessing_inputs, resolve_postprocessing_context, resolve_job_artifact, DomainValidationError
from backend.db import get_db
from backend.deps import get_current_user
from backend.models import CandidateSet, Job, JobTask, QueueOutbox, SmallMoleculeResult, User
from backend.result_query import numeric
from backend.result_rows import ensure_tarpass_rows
from genova_runtime.structure_index import file_digest, file_version, named_record, molecule, structure_index, read_record
from genova_runtime.pdb2pqr_compat import file_sha256
from tarpass.contracts import protein_residues, validate_interactions, INTERACTION_TYPES
from tarpass.filters import DEFAULT_PREFILTERS, METRICS, PROPERTY_METRICS, METRIC_INFO, validate_filters, failed_filters, metric_value
from tarpass.selection import CLUSTER_FIELDS, cluster_rows, edit_preview

router = APIRouter(prefix='/jobs', tags=['postprocessing'])
TABLE_ROW = SmallMoleculeResult.extra.delete_path(['metrics', 'original', 'interaction_details']).delete_path(['metrics', 'docked', 'interaction_details'])


def owned_job(db, user, job_id):
    job = db.scalar(select(Job).where(Job.id == job_id, Job.owner_user_id == user.id, Job.is_deleted.is_(False)))
    if job is None:
        raise HTTPException(404, 'Job not found')
    return job


def source_task(db, job):
    if job.job_type not in ('molecule_generation', 'property_optimization') or job.status != 'succeeded':
        raise HTTPException(409, 'A succeeded generation or lead optimization job is required')
    task = db.scalar(select(JobTask).where(JobTask.job_id == job.id, JobTask.task_code == job.job_type))
    if task is None or task.status != 'succeeded':
        raise HTTPException(409, 'A succeeded generation or lead optimization task is required')
    return task


def artifact_path(job, value):
    root = (settings.data_root / 'jobs' / str(job.id)).resolve()
    path = Path(str(value or '')).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(400, 'Required artifact is missing or outside the job workspace')
    return path




class Interaction2DQuery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    molecule_id: str = Field(min_length=1, max_length=200)
    pose: Literal['original', 'docked']


@lru_cache(maxsize=256)
def preview_fingerprint(sdf, version, molecule_id):
    from tarpass.interactions import molecule_fingerprint

    mol = molecule(named_record(sdf, molecule_id))
    if mol is None or not mol.GetNumAtoms() or not mol.GetNumConformers() or not mol.GetConformer().Is3D() or not all(math.isfinite(float(v)) for point in mol.GetConformer().GetPositions() for v in point):
        raise ValueError('The selected record requires a valid 3D pose')
    return molecule_fingerprint(mol)


@lru_cache(maxsize=512)
def cached_edit_preview(fragment_path, fragment_version, target_path, target_version, name):
    fragment = molecule(read_record(fragment_path, 0))
    target = molecule(named_record(target_path, name) if name is not None else read_record(target_path, 0))
    if fragment is None or target is None:
        raise ValueError('Invalid structure')
    return edit_preview(fragment, target)


def interaction_preview_input(db, user, job_id, query):
    from tarpass.interactions import DETAILS_VERSION, PLIP_VERSION, diagram_cache_key

    job = owned_job(db, user, job_id)
    task = db.scalar(select(JobTask).where(JobTask.job_id == job.id, JobTask.task_code == 'tarpass'))
    if task is None or task.status != 'succeeded':
        raise HTTPException(409, 'Postprocessing results are not ready')
    ensure_tarpass_rows(db, task)
    row = db.scalar(select(SmallMoleculeResult.extra).where(SmallMoleculeResult.job_task_id == task.id,
                    SmallMoleculeResult.extra.contains({'molecule_id': query.molecule_id})))
    if row is None:
        raise HTTPException(404, 'Molecule record not found')
    sdf = artifact_path(job, task.output_payload.get(f'{query.pose}_sdf'))
    try:
        fingerprint = preview_fingerprint(str(sdf), file_version(sdf), query.molecule_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    protein = Path(str(task.output_payload.get('protein_path') or task.input_payload.get('protein_pdb') or '')).resolve()
    if not protein.is_relative_to(settings.data_root.resolve()) or not protein.is_file():
        raise HTTPException(409, 'The prepared receptor is unavailable')
    protein_hash = file_digest(protein)
    details = row['metrics'].get(query.pose, {}).get('interaction_details')
    if details and (details.get('version'), details.get('plip_version'), details.get('protein_sha256'), details.get('source_input_fingerprint', details.get('input_fingerprint'))) != (DETAILS_VERSION, PLIP_VERSION, protein_hash, fingerprint):
        details = None
    key = diagram_cache_key(protein_hash, fingerprint, query.molecule_id, query.pose, details)
    return job, {'operation': 'interactions_2d', 'molecule_id': query.molecule_id, 'pose': query.pose,
                 'input_sdf': str(sdf), 'protein_pdb': str(protein), 'protein_sha256': protein_hash,
                 'input_fingerprint': fingerprint, 'cache_key': key, 'details': details,
                 'output_dir': str(settings.data_root / 'jobs' / str(job.id) / 'interactions-2d')}


def interaction_preview_status(db, job, payload):
    cache = Path(payload['output_dir']) / f"{payload['cache_key']}.json"
    if cache.is_file():
        return {'status': 'succeeded', 'diagram': json.loads(artifact_path(job, cache).read_text())}
    task = db.scalar(select(JobTask).where(JobTask.job_id == job.id, JobTask.task_code == f"plip2d_{payload['cache_key'][:48]}"))
    if task is None:
        return {'status': 'not_requested'}
    if task.status == 'succeeded':
        return {'status': 'failed', 'error': 'The cached diagram is missing; retry to regenerate it'}
    return {'status': task.status, 'error': task.error_message.splitlines()[0] if task.error_message else None}


@router.get('/{job_id}/postprocessing/interactions-2d')
def get_interaction_preview(job_id: uuid.UUID, query: Interaction2DQuery = Depends(), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job, payload = interaction_preview_input(db, current_user, job_id, query)
    return interaction_preview_status(db, job, payload)


@router.post('/{job_id}/postprocessing/interactions-2d')
def request_interaction_preview(job_id: uuid.UUID, query: Interaction2DQuery, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from backend.utils import utcnow

    # Serialize requests for this owned Job; the existing task-code constraint also prevents duplicates.
    job = db.scalar(select(Job).where(Job.id == job_id, Job.owner_user_id == current_user.id, Job.is_deleted.is_(False)).with_for_update())
    if job is None:
        raise HTTPException(404, 'Job not found')
    job, payload = interaction_preview_input(db, current_user, job_id, query)
    db.execute(select(Job.id).where(Job.id == job.id).with_for_update())
    state = interaction_preview_status(db, job, payload)
    if state['status'] in ('succeeded', 'pending', 'queued', 'running'):
        return state
    if payload['details']:
        from tarpass.interactions import write_diagram

        write_diagram(payload, payload['details'])
        db.commit()
        return interaction_preview_status(db, job, payload)
    from backend.services.resources import check_admission
    check_admission(db, current_user.id)
    code = f"plip2d_{payload['cache_key'][:48]}"
    task = db.scalar(select(JobTask).where(JobTask.job_id == job.id, JobTask.task_code == code))
    if task is None:
        task = JobTask(id=uuid.uuid4(), job_id=job.id, task_code=code, runtime_task='tarpass', depends_on=[])
        db.add(task)
    else:
        task.retry_count += 1
    task.queue_job_id, task.status = uuid.uuid4(), 'pending'
    task.input_payload, task.output_payload, task.error_message = payload, {}, None
    task.started_at, task.finished_at, task.updated_at = None, None, utcnow()
    db.add(QueueOutbox(job_task_id=task.id, queue_name=settings.redis_dispatch_queue,
                       payload={'job_id': str(task.queue_job_id), 'task': 'tarpass', 'payload': payload,
                                'result_queue': settings.redis_result_queue, 'meta': {'job_id': str(job.id)}}, status='pending'))
    db.commit()
    return {'status': 'pending'}


def create_postprocessing_job(payload, db, user):
    from backend.services.resources import check_admission
    check_admission(db, user.id)
    from backend.routers.jobs import _get_dataset, _get_dataset_files, _pick_file, _serialize_job
    raw = payload.params.get('postprocessing')
    if not isinstance(raw, dict):
        raise HTTPException(422, 'params.postprocessing is required')
    try:
        source_id = uuid.UUID(str(raw.get('source_job_id')))
        filters = validate_filters(raw.get('prefilters', deepcopy(DEFAULT_PREFILTERS)), pre=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    source = owned_job(db, user, source_id)
    task = source_task(db, source)
    input_key = 'input_sdf' if task.output_payload.get('generated_sdf') else 'input_csv'
    artifact_key = 'generated_sdf' if input_key == 'input_sdf' else 'output_csv'
    source_path = artifact_path(source, task.output_payload.get(artifact_key))
    if input_key == 'input_csv':
        with source_path.open(newline='', encoding='utf-8-sig') as stream:
            if 'smiles' not in (csv.DictReader(stream).fieldnames or []):
                raise HTTPException(422, 'Source CSV requires a smiles column')
    inputs = task.input_payload
    try:
        reference_ligand = source_reference_ligand(task, source, data_root=settings.data_root)
        shared_binding, shared_cache = source_postprocessing_inputs(task, data_root=settings.data_root)
        shared_binding['reference_ligand'] = {'path': reference_ligand, 'sha256': file_sha256(Path(reference_ligand))} if reference_ligand else None
        context = resolve_postprocessing_context(db, user.id, inputs, raw.get('protein_context_id'))
    except DomainValidationError as exc:
        raise HTTPException(exc.http_status, str(exc)) from exc
    protein = context.get('protein_pdb')
    box = context.get('box')
    if not protein or not Path(protein).is_file() or not isinstance(box, dict):
        raise HTTPException(409, 'Source job requires a prepared Protein Context with docking box')
    from genova_runtime.structure_inputs import validate_context_snapshot, validate_context_engine_support
    try:
        validate_context_snapshot(context, protein)
        validate_context_engine_support(context, 'tarpass')
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        if any(not isinstance(box.get(key), list) or len(box[key]) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) or (key == 'size' and v <= 0) for v in box[key]) for key in ('center', 'size')):
            raise ValueError('Invalid source docking box')
        rules = validate_interactions(raw.get('key_interactions', []), protein_residues(protein))
        reference_id = uuid.UUID(str(raw['reference_dataset_id'])) if raw.get('reference_dataset_id') else None
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    reference_file = None
    if reference_id:
        _get_dataset(db, reference_id, user.id)
        reference_file = _pick_file(_get_dataset_files(db, reference_id), ['attachment'], {'.sdf', '.smi', '.txt'})
        if reference_file is None:
            raise HTTPException(422, 'Reference dataset requires SDF or SMILES text')
    if not reference_file and any(rule['metric'] in {'reference_similarity', 'scaffold_similarity'} for rule in filters):
        raise HTTPException(422, 'Reference similarity filters require reference_dataset_id')
    normalized = {'source_job_id': str(source.id), 'prefilters': filters, 'key_interactions': rules, 'reference_dataset_id': str(reference_id) if reference_id else None, 'protein_context_id': context.get('id')}
    name = payload.params.get('job_name', '')
    if not isinstance(name, str) or len(name) > 200:
        raise HTTPException(422, 'job_name must be a string of at most 200 characters')
    default_name = f"Postprocessing {source.params.get('job_name') or source.params.get('name') or str(source.id)[:8]}"[:200]
    job = Job(id=uuid.uuid4(), owner_user_id=user.id, job_type='molecule_postprocessing', status='pending', params={'postprocessing': normalized, 'job_name': name.strip() or default_name}, summary={})
    queued = JobTask(id=uuid.uuid4(), job_id=job.id, task_code='tarpass', runtime_task='tarpass', status='pending', queue_job_id=uuid.uuid4(), depends_on=[], output_payload={})
    queued.input_payload = {'source_job_id': str(source.id), input_key: str(source_path), 'protein_pdb': shared_cache['files']['protein_pdb']['path'],
                            'postprocessing_inputs': shared_binding,
                            'reference_ligand': reference_ligand, 'box': deepcopy(box),
                            'ph': inputs.get('ph', 7.4), 'output_dir': str(settings.data_root / 'jobs' / str(job.id) / 'tarpass'),
                            'prefilters': filters, 'key_interactions': rules,
                            'reference_dataset_path': reference_file.storage_path if reference_file else None}
    queued.input_payload['structure_context'] = deepcopy(context)
    job.params = {**job.params, 'structure_context': deepcopy(context), 'protein_context_id': context.get('id'), 'source_protein_context_id': source.params.get('protein_context_id')}
    if inputs.get('fragment_sdf'):
        queued.input_payload['fragment_sdf'] = str(artifact_path(source, inputs['fragment_sdf']))
    db.add(job)
    db.add(queued)
    db.add(QueueOutbox(job_task_id=queued.id, queue_name=settings.redis_dispatch_queue, payload={'job_id': str(queued.queue_job_id), 'task': 'tarpass', 'payload': queued.input_payload, 'result_queue': settings.redis_result_queue, 'meta': {'job_id': str(job.id)}}, status='pending'))
    db.flush()
    db.refresh(job)
    return _serialize_job(db, job, with_tasks=True)


@router.get('/{job_id}/postprocessing/options')
def options(job_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user), protein_context_id: uuid.UUID | None = None):
    job = owned_job(db, user, job_id)
    task = source_task(db, job)
    context = task.input_payload.get('structure_context') or {}
    if protein_context_id:
        try:
            context = resolve_postprocessing_context(db, user.id, task.input_payload, protein_context_id)
        except DomainValidationError as exc:
            raise HTTPException(exc.http_status, str(exc)) from exc
    from genova_runtime.structure_inputs import validate_context_snapshot
    try:
        validate_context_snapshot(context, context['protein_pdb'])
    except (KeyError, ValueError) as exc:
        raise HTTPException(409, 'Unsupported or invalid Protein Context; prepare a current Context') from exc
    protein = context.get('protein_pdb') or task.input_payload.get('protein_pdb')
    if not protein or not Path(protein).is_file():
        raise HTTPException(409, 'Prepared receptor is unavailable')
    try:
        reference_available = bool(source_reference_ligand(task, job, data_root=settings.data_root))
        source_postprocessing_inputs(task, data_root=settings.data_root)
    except DomainValidationError as exc:
        raise HTTPException(exc.http_status, str(exc)) from exc
    return {'residues': protein_residues(protein), 'interaction_types': sorted(INTERACTION_TYPES), 'metrics': sorted(METRICS), 'prefilter_metrics': sorted(PROPERTY_METRICS), 'metric_info': METRIC_INFO, 'reference_available': reference_available}


class ClusteringQuery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    basis: Literal['molecule', 'scaffold'] = 'molecule'
    similarity_threshold: float = Field(default=0.6, ge=0, le=1, allow_inf_nan=False)
    representatives_per_cluster: int = Field(default=1, ge=1, le=20, strict=True)
    representatives_only: bool = False


class ResultQuery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    include_prefiltered: bool = False
    include_failed: bool = False
    filters: list[dict] = Field(default_factory=list, max_length=100)
    sort_by: str = 'molecule_id'
    descending: bool = False
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)
    pose: Literal['original', 'docked'] = 'docked'
    format: Literal['csv', 'sdf'] = 'csv'
    clustering: ClusteringQuery | None = None
    candidate_set_id: uuid.UUID | None = None


def selected_statement(db, user, job_id, query):
    job = owned_job(db, user, job_id)
    task = db.scalar(select(JobTask).where(JobTask.job_id == job.id, JobTask.task_code == 'tarpass'))
    if task is None or task.status != 'succeeded':
        raise HTTPException(409, 'Postprocessing results are not ready')
    try:
        validate_filters(query.filters)
        if query.sort_by not in METRICS | {'molecule_id'}:
            raise ValueError('Unsupported sort metric')
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    ensure_tarpass_rows(db, task)
    data = SmallMoleculeResult.extra
    statement = select(TABLE_ROW).where(SmallMoleculeResult.job_task_id == task.id)
    if query.candidate_set_id is not None:
        candidate_set = db.scalar(select(CandidateSet).where(
            CandidateSet.id == query.candidate_set_id,
            CandidateSet.owner_user_id == user.id,
            CandidateSet.postprocessing_job_id == job.id,
        ))
        if candidate_set is None:
            raise HTTPException(404, 'Candidate set not found for this postprocessing job')
        artifact = task.output_payload.get('results_json')
        if not artifact:
            raise HTTPException(409, 'Candidate set source artifact is missing')
        try:
            if file_sha256(resolve_job_artifact(job, artifact)) != candidate_set.artifact_hash:
                raise HTTPException(409, 'Candidate set source artifact changed')
        except DomainValidationError as exc:
            raise HTTPException(exc.http_status, str(exc)) from exc
        molecule_ids = [str(value) for value in (candidate_set.molecule_ids or [])]
        statement = statement.where(data['molecule_id'].astext.in_(molecule_ids))
    if not query.include_prefiltered:
        statement = statement.where(data['status'].astext != 'prefiltered')
    if not query.include_failed:
        statement = statement.where(data['status'].astext.notin_(['failed', 'invalid']))
    for rule in query.filters:
        value = numeric(data[('metrics', *rule['metric'].split('.'))].astext)
        statement = statement.where({'gt': value > rule['value'], 'lt': value < rule['value'], 'gte': value >= rule['value'], 'lte': value <= rule['value'], 'eq': value == rule['value']}[rule['op']])
    if query.sort_by == 'molecule_id':
        order = data['molecule_id'].astext
    else:
        order = numeric(data[('metrics', *query.sort_by.split('.'))].astext)
    statement = statement.order_by((order.desc() if query.descending else order.asc()).nulls_last(), data['molecule_id'].astext)
    return job, task, statement


def selected_rows(db, user, job_id, query):
    job, task, statement = selected_statement(db, user, job_id, query)
    rows = list(db.scalars(statement).all())
    summary = None
    if query.clustering:
        try:
            rows, summary = cluster_rows(rows, query.clustering.model_dump(), query.sort_by)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    return job, task, rows, summary


@router.post('/{job_id}/postprocessing/results')
def results(job_id: uuid.UUID, query: ResultQuery, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if query.clustering:
        job, task, rows, summary = selected_rows(db, user, job_id, query)
        page, total = rows[query.offset:query.offset + query.limit], len(rows)
    else:
        job, task, statement = selected_statement(db, user, job_id, query)
        total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
        page = list(db.scalars(statement.offset(query.offset).limit(query.limit)).all())
        summary = None
    result_ids = {str(molecule_id): str(result_id) for result_id, molecule_id in db.execute(
        select(SmallMoleculeResult.id, SmallMoleculeResult.extra['molecule_id'].astext).where(
            SmallMoleculeResult.job_task_id == task.id)).all()}
    for row in page:
        if row.get('molecule_id') in result_ids:
            row['result_id'] = result_ids[row['molecule_id']]
    result = {'total': total, 'rows': page}
    if query.candidate_set_id is not None:
        candidate_set = db.scalar(select(CandidateSet).where(
            CandidateSet.id == query.candidate_set_id,
            CandidateSet.owner_user_id == user.id,
            CandidateSet.postprocessing_job_id == job.id,
        ))
        ids = [str(value) for value in (candidate_set.molecule_ids or [])]
        scope_rows = list(db.scalars(select(TABLE_ROW).where(
            SmallMoleculeResult.job_task_id == task.id,
            SmallMoleculeResult.extra['molecule_id'].astext.in_(ids))).all())
        result['scope_summary'] = {
            'result_count': len(scope_rows),
            'status_counts': {status: sum(row.get('status') == status for row in scope_rows)
                              for status in ('succeeded', 'partial', 'failed', 'invalid', 'prefiltered')},
        }
    if summary is not None:
        result['clustering'] = summary
    if task.input_payload.get('fragment_sdf'):
        result['edit_context'] = {'status': 'unavailable'}
        try:
            fragment, reference = task.input_payload['fragment_sdf'], task.input_payload['reference_ligand']
            fragment_version = file_version(fragment)
            result['edit_context'] = {'status': 'available', **cached_edit_preview(fragment, fragment_version, reference, file_version(reference), None)}
            sdf = artifact_path(job, task.output_payload.get('original_sdf'))
            sdf_version = file_version(sdf)
            for row in page:
                try:
                    row['edit_preview'] = cached_edit_preview(fragment, fragment_version, str(sdf), sdf_version, row['molecule_id'])
                except (ValueError, RuntimeError):
                    row['edit_preview'] = None
        except (OSError, ValueError, RuntimeError, HTTPException):
            result['edit_context'] = {'status': 'unavailable'}
    return result


@router.post('/{job_id}/postprocessing/export')
def export(job_id: uuid.UUID, query: ResultQuery, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    job, task, rows, _ = selected_rows(db, user, job_id, query)
    from backend.services.result_exports import export_rows
    response = export_rows(job, task, rows, pose=query.pose, format=query.format, clustering=query.clustering)
    if query.candidate_set_id is not None:
        candidate_set = db.scalar(select(CandidateSet).where(
            CandidateSet.id == query.candidate_set_id,
            CandidateSet.owner_user_id == user.id,
            CandidateSet.postprocessing_job_id == job.id,
        ))
        response.headers['X-Scope-Count'] = str(len(candidate_set.molecule_ids or []))
    return response
