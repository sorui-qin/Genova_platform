from genova_runtime.artifact_json import read_json
import json
import uuid
from copy import deepcopy
from pathlib import Path

from sqlalchemy import select

from backend.config import settings
from backend.models import Dataset, DatasetFile, Job, JobTask, QueueOutbox
from backend.utils import utcnow
from genova_runtime.context_features import CACHE_VERSION, CONTRACT, context_fingerprint, REQUIRED_FILES
from genova_runtime.pdb2pqr_compat import file_sha256
from genova_runtime.preparation_errors import describe_preparation_error

ENGINES = ('surfgen', 'delete', 'ecloudgen', 'epso')


def reuse_epso_inputs(dataset, context, states, db, user_id):
    from genova_runtime.context_features import consume_context_inputs
    from backend.services.binding_sites import resolve_v4_context
    from fastapi import HTTPException
    import os
    keys = ('prepared_receptor_id', 'prepared_artifact_sha256', 'generation_reference', 'input_parameters')
    candidates = db.scalars(select(Dataset).where(Dataset.owner_user_id == user_id,
        Dataset.kind == 'protein_context', Dataset.status == 'ready', Dataset.id != dataset.id,
        Dataset.meta['prepared_receptor_id'].as_string() == dataset.meta['prepared_receptor_id'],
        Dataset.meta['compatibility']['models']['epso']['status'].as_string().in_(['full', 'limited'])))
    for previous in candidates:
        if any(previous.meta.get(key) != dataset.meta.get(key) for key in keys):
            continue
        try:
            source = resolve_v4_context(previous, db, user_id)
            cache = consume_context_inputs({'structure_context': source}, 'epso', dry_run=True)['prepared_input_cache']
        except (HTTPException, ValueError, OSError, KeyError):
            continue
        directory = settings.data_root / 'datasets' / str(dataset.id) / 'epso'
        directory.mkdir(exist_ok=True)
        cache = deepcopy(cache)
        for identity in cache['files'].values():
            target = directory / (identity['sha256'] + ''.join(Path(identity['path']).suffixes))
            if not target.exists():
                os.link(identity['path'], target)
            identity['path'] = str(target)
        fingerprint = context_fingerprint(context, dataset.meta['input_parameters'])
        cache.update(context_id=str(dataset.id), input_fingerprint=fingerprint)
        manifest = directory / 'model_input_cache.json'
        manifest.write_text(json.dumps(cache))
        report = directory / 'compatibility_report.json'
        report.write_text(json.dumps(dict(version=1, engine='epso', context_id=str(dataset.id),
            input_fingerprint=fingerprint, status=cache['status'], feature_validation='passed',
            model_scope=cache['model_scope'], timings={'cache_hit': True})))
        files = {**cache['files'], 'cache': {'path':str(manifest), 'sha256':file_sha256(manifest)},
            'report': {'path':str(report), 'sha256':file_sha256(report)}}
        artifacts = {}
        for name, identity in files.items():
            path = Path(identity['path']); file_id = uuid.uuid4()
            db.add(DatasetFile(id=file_id, dataset_id=dataset.id, file_role='epso_' + name,
                storage_path=str(path), original_filename=path.name.removesuffix('.gz'),
                sha256=identity['sha256'], size_bytes=path.stat().st_size, content_type='application/octet-stream'))
            artifacts[name] = dict(dataset_id=str(dataset.id), file_id=str(file_id), sha256=identity['sha256'])
        states['epso'] = dict(status=cache['status'], input_fingerprint=fingerprint, artifacts=artifacts,
            model_scope=cache['model_scope'], timings={'cache_hit': True})
        db.flush()
        return


def enqueue_context_validation(dataset, db, user_id, engines=None, *, context=None):
    from backend.services.binding_sites import resolve_v4_context
    if context is None:
        context = resolve_v4_context(dataset, db, user_id)
    parameters = dataset.meta['input_parameters']
    from genova_runtime.context_features import consume_context_inputs
    states = deepcopy((dataset.meta.get('compatibility') or {}).get('models') or {})
    if engines is None and 'epso' not in states:
        reuse_epso_inputs(dataset, context, states, db, user_id)
        if 'epso' in states:
            dataset.meta = {**dataset.meta, 'compatibility': {'version':1, 'models':states}}
            db.flush()
            context = resolve_v4_context(dataset, db, user_id)
    pending = []
    for engine in engines or ENGINES:
        state = states.get(engine, {})
        if state.get('status') in {'full', 'limited'}:
            try:
                consume_context_inputs({'structure_context': context}, engine, dry_run=True)
                continue
            except (ValueError, OSError, KeyError):
                pass
        if state.get('queue_job_id'):
            active = db.scalar(select(JobTask).join(Job, Job.id == JobTask.job_id).where(
                JobTask.queue_job_id == uuid.UUID(state['queue_job_id']), Job.owner_user_id == user_id,
                JobTask.status.in_(['pending', 'queued', 'running'])))
            if active is not None:
                continue
        if engines is None and state.get('status') in {'failed', 'incompatible'}:
            continue
        pending.append(engine)
    if not pending:
        return
    from backend.services.resources import check_admission
    check_admission(db, user_id)
    now = utcnow()
    job = Job(id=uuid.uuid4(), owner_user_id=user_id, job_type='protein_preparation', input_dataset_id=dataset.id, status='pending', params=dict(phase='context_compatibility', protein_context_id=str(dataset.id), job_name=dataset.name + ' · model inputs'), summary={})
    fingerprint = context_fingerprint(context, parameters)
    db.add(job)
    for engine in pending:
        task_id, queue_id = uuid.uuid4(), uuid.uuid4()
        payload = dict(operation='prepare_context_inputs', context_id=str(dataset.id), structure_context=deepcopy(context), input_parameters=deepcopy(parameters), output_dir=str(settings.data_root / 'jobs' / str(job.id) / engine))
        task = JobTask(id=task_id, job_id=job.id, task_code='context_compatibility_' + engine, runtime_task=engine, queue_job_id=queue_id, status='pending', depends_on=[], input_payload=payload, output_payload={})
        db.add(task)
        db.add(QueueOutbox(job_task_id=task.id, queue_name=settings.redis_dispatch_queue, status='pending', payload=dict(job_id=str(queue_id), task=engine, payload=payload, result_queue=settings.redis_result_queue, meta={'job_id':str(job.id)})))
        states[engine] = dict(status='pending', queue_job_id=str(queue_id), input_fingerprint=fingerprint)
    states['tarpass'] = dict(status='unchecked', reason='Docking preparation runs only when postprocessing is requested')
    capabilities = deepcopy(dataset.meta['capabilities'])
    capabilities['engine_support'] = {name: {'status': state['status'], 'reason': state.get('error', state.get('reason', '')),
        'model_scope': state.get('model_scope', {}), **({'error_info': state['error_info']} if state.get('error_info') else {})}
        for name, state in states.items()}
    dataset.meta = {**dataset.meta, 'capabilities': capabilities, 'compatibility': dict(version=1, job_id=str(job.id), models=states)}
    db.flush()


def complete_context_validation(db, task, status_value, result=None, error=None):
    from backend.services.binding_sites import resolve_v4_context
    engine = task.runtime_task
    context_id = uuid.UUID(task.input_payload['context_id'])
    dataset = db.get(Dataset, context_id)
    job = db.get(Job, task.job_id)
    if dataset is None or job is None or dataset.owner_user_id != job.owner_user_id or dataset.status == 'archived':
        raise ValueError('Context validation resource is unavailable')
    db.refresh(dataset, with_for_update=True)
    compatibility = deepcopy(dataset.meta.get('compatibility') or {})
    state = compatibility.get('models', {}).get(engine) or {}
    if state.get('queue_job_id') != str(task.queue_job_id):
        return
    attaching_failure_report = state.get('status') in {'incompatible', 'failed'} and status_value != 'succeeded' and result and result.get('compatibility_report') and not state.get('artifacts', {}).get('report')
    if state.get('status') in {'full', 'limited', 'incompatible', 'failed'} and not attaching_failure_report:
        return
    if status_value == 'succeeded':
        current = resolve_v4_context(dataset, db, dataset.owner_user_id)
        if state['input_fingerprint'] != context_fingerprint(current, dataset.meta['input_parameters']):
            raise ValueError('Context changed while its features were being prepared')
    root = (settings.data_root / 'jobs' / str(job.id)).resolve()
    result = result or {}
    files = {}
    report = None
    if result.get('compatibility_report'):
        path = Path(result['compatibility_report']).resolve()
        if not path.is_relative_to(root) or not path.is_file() or file_sha256(path) != result.get('report_sha256'):
            raise ValueError('Invalid compatibility report artifact')
        report = read_json(path)
        if report['context_id'] != str(dataset.id) or report['engine'] != engine or report['input_fingerprint'] != state['input_fingerprint']:
            raise ValueError('Compatibility report binding mismatch')
        files['report'] = dict(path=str(path), sha256=file_sha256(path))
    if status_value == 'succeeded':
        cache_path = Path(result['cache_manifest']).resolve()
        if not cache_path.is_relative_to(root) or not cache_path.is_file() or file_sha256(cache_path) != result.get('cache_sha256'):
            raise ValueError('Invalid context feature cache artifact')
        cache = read_json(cache_path)
        if not report or cache.get('version') != CACHE_VERSION or cache.get('contract') != CONTRACT or not REQUIRED_FILES[engine] <= cache.get('files',{}).keys() or cache['context_id'] != str(dataset.id) or cache['engine'] != engine or cache['input_fingerprint'] != state['input_fingerprint'] or cache['status'] not in {'full', 'limited'} or report['feature_validation'] != 'passed':
            raise ValueError('Context feature cache binding mismatch')
        files['cache'] = dict(path=str(cache_path), sha256=file_sha256(cache_path))
        for name, identity in cache['files'].items():
            path = Path(identity['path']).resolve()
            if not path.is_relative_to(root) or not path.is_file() or file_sha256(path) != identity['sha256']:
                raise ValueError('Prepared model input artifact changed')
            files[name] = identity
        state.update(status=cache['status'], model_scope=cache['model_scope'])
    else:
        info = (report or {}).get('error_info') or result.get('error_info') or describe_preparation_error(error or 'Context feature preparation failed', 'execution')
        state.update(status='incompatible' if info['error_category'] == 'input' else 'failed',
            error=(report or {}).get('error') or str(error or 'Context feature preparation failed'), error_info=info)
    registered = {}
    for name, item in files.items():
        file_id = uuid.uuid4(); path = Path(item['path'])
        db.add(DatasetFile(id=file_id, dataset_id=dataset.id, file_role=engine + '_' + name, storage_path=str(path), original_filename=path.name.removesuffix('.gz'), sha256=item['sha256'], size_bytes=path.stat().st_size, content_type='application/octet-stream'))
        registered[name] = dict(dataset_id=str(dataset.id), file_id=str(file_id), sha256=item['sha256'])
    state['artifacts'] = registered
    if report and report.get('timings'):
        state['timings'] = deepcopy(report['timings'])
        if task.started_at and task.created_at:
            state['timings']['queue_wait_s'] = max(0, (task.started_at - task.created_at).total_seconds())
        if task.finished_at and task.started_at:
            state['timings']['worker_s'] = max(0, (task.finished_at - task.started_at).total_seconds())
    compatibility['models'][engine] = state
    capabilities = deepcopy(dataset.meta['capabilities'])
    capabilities['engine_support'] = {name: {'status': row['status'], 'reason': row.get('error', row.get('reason', '')), 'model_scope': row.get('model_scope', {}),
        **({'error_info': row['error_info']} if row.get('error_info') else {})} for name,row in compatibility['models'].items()}
    dataset.meta = {**dataset.meta, 'compatibility': compatibility, 'capabilities': capabilities}
    dataset.updated_at = utcnow()
    db.flush()
