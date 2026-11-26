import hashlib
import json
import os
import stat
import uuid
from collections import defaultdict
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path

import jwt
from fastapi import HTTPException
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db import RETENTION_LOCK, engine
from backend.models import (ActionProposal, AgentSession, AgentTurn, DataRetentionDeletion,
    Dataset, DatasetFile, Job, JobTask, WorkflowCommand, WorkflowPlanningRequest, WorkflowRun)
from backend.retention import _delete_rows, _load_graph, _receipt_lock, retained_job_paths, purge_files
from backend.services.resources import ACTIVE
from backend.utils import utcnow


RESOURCE_KEYS = {'dataset_id', 'protein_context_id', 'protein_dataset_id', 'prepared_receptor_id',
                 'ligand_dataset_id', 'reference_dataset_id', 'derived_from_context_id'}
JOB_KEYS = {'source_job_id'}


def _relations(rows, groups, ownership):
    edges = defaultdict(set)
    by_table = {model.__tablename__: model for model in rows}
    resource_paths = {row.storage_path: (Dataset, row.dataset_id) for row in rows[DatasetFile]}

    def link(source, model, value):
        if value is None:
            return
        try:
            key = (model, uuid.UUID(str(value)))
        except ValueError:
            return
        if key in groups and key != source:
            edges[source].add(key)

    def bindings(value, source):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in RESOURCE_KEYS:
                    link(source, Dataset, item)
                elif key in JOB_KEYS:
                    link(source, Job, item)
                else:
                    bindings(item, source)
        elif isinstance(value, str) and value.startswith(str(settings.data_root) + "/"):
            if value in resource_paths:
                edges[source].add(resource_paths[value])
                return
            parts = Path(value).relative_to(settings.data_root).parts
            if len(parts) > 1 and parts[0] in {"jobs", "datasets"}:
                link(source, Job if parts[0] == "jobs" else Dataset, parts[1])
        elif isinstance(value, list):
            for item in value:
                bindings(item, source)

    for model, items in rows.items():
        for row in items:
            parents = ownership[model.__tablename__, row.id]
            for source in parents:
                for column in model.__table__.columns:
                    for foreign in column.foreign_keys:
                        target = by_table.get(foreign.column.table.name)
                        if target:
                            value = getattr(row, column.name)
                            edges[source].update(ownership.get((target.__tablename__, value), set()) - {source})
                if model is Job:
                    params = row.params or {}
                    keys = ['protein_context_id', 'structure_context']
                    keys.extend({'protein_preparation': ['prepared_receptor_id', 'prepared_spec'],
                                 'molecule_postprocessing': ['postprocessing'],
                                 'property_optimization': ['seed_source']}.get(row.job_type, []))
                    bindings({key: params.get(key) for key in keys}, source)
                elif model is JobTask:
                    bindings(row.input_payload or {}, source)
                elif model is Dataset:
                    bindings(row.meta or {}, source)
                    link(source, Job, ((row.meta or {}).get('compatibility') or {}).get('job_id'))
                    link(source, Job, ((row.meta or {}).get('execution') or {}).get('job_id'))
                elif model is AgentSession:
                    bindings(row.assets or {}, source)
                elif model is WorkflowCommand:
                    link(source, AgentSession, row.target_id)
                    link(source, WorkflowRun, row.target_id)
                elif model is ActionProposal:
                    link(source, Job, (row.execution or {}).get('job_id'))
                if model is DatasetFile:
                    path = Path(row.storage_path)
                    try:
                        parts = path.relative_to(settings.data_root).parts
                    except ValueError:
                        continue
                    if len(parts) > 1 and parts[0] == 'jobs':
                        link(source, Job, parts[1])
    return edges


def _files(root, kind, object_id, protected=()):
    files = []
    if root.is_symlink():
        return files
    for directory, _, names in os.walk(root, followlinks=False):
        for name in sorted(names):
            path = Path(directory) / name
            if path.resolve() in protected:
                continue
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue
            files.append({'kind': kind, 'object_id': str(object_id), 'name': str(path.relative_to(root)),
                'size_bytes': info.st_size if stat.S_ISREG(info.st_mode) else 0,
                'version': [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]})
    return sorted(files, key=lambda item: item['name'])


def deletion_impact(db, owner_id, job_ids):
    rows, groups, ownership, _ = _load_graph(db, owner_id, build_edges=False)
    requested = {(Job, item) for item in set(job_ids)}
    if any(key not in groups or groups[key].is_deleted for key in requested):
        raise HTTPException(404, 'Job not found')
    edges = _relations(rows, groups, ownership)
    selected = set(requested)
    while True:
        added = {source for source, targets in edges.items() if source[0] is not Dataset and targets & selected} - selected
        if not added:
            break
        selected.update(added)
    chosen = {model: {row.id for row in values if ownership[model.__tablename__, row.id] <= selected}
              for model, values in rows.items()}
    blocked, objects, files = [], [], []
    with ExitStack() as stack:
        held = set()
        for key in sorted(selected, key=lambda item: (item[0].__tablename__, str(item[1]))):
            model, item = key
            row = groups[key]
            kind = model.__tablename__
            objects.append({'kind': kind, 'id': str(item),
                'name': getattr(row, 'name', None) or getattr(row, 'goal', None)
                        or (row.params.get('job_name') if model is Job else None) or str(item),
                'version': str(getattr(row, 'updated_at', getattr(row, 'created_at', '')))})
            if ((model is Job and row.status in ACTIVE) or
                    (model is WorkflowRun and row.status in {'planning', 'approved', 'running', 'cancel_requested'}) or
                    (model is WorkflowPlanningRequest and row.status == 'planning')):
                blocked.append({'kind': kind, 'id': str(item), 'reason': 'EXECUTION_ACTIVE'})
            if model in {Job, Dataset}:
                root = settings.data_root / ('jobs' if model is Job else 'datasets') / str(item)
                files.extend(_files(root, kind, item, retained_job_paths(db, root) if model is Job else ()))
        for source in selected:
            if source[0] in {AgentSession, WorkflowRun}:
                for target in edges[source]:
                    if target[0] is Job and groups[target].status in ACTIVE:
                        blocked.append({'kind': 'jobs', 'id': str(target[1]), 'reason': 'EXECUTION_ACTIVE'})
        for task in rows[JobTask]:
            if task.id in chosen[JobTask] and (task.status in ACTIVE or not _receipt_lock(stack, str(task.queue_job_id), held)):
                blocked.append({'kind': 'jobs', 'id': str(task.job_id), 'reason': 'EXECUTION_ACTIVE'})
        for turn in rows[AgentTurn]:
            if turn.id in chosen[AgentTurn] and turn.status in {'queued', 'running'}:
                blocked.append({'kind': 'agent_sessions', 'id': str(turn.session_id), 'reason': 'CONVERSATION_ACTIVE'})
    retained_ids = {target for source in selected for target in edges[source] if target not in selected and target[0] is Dataset}
    retained_ids.update(source for source, targets in edges.items() if source[0] is Dataset and targets & selected)
    pending = list(retained_ids)
    while pending:
        for target in edges[pending.pop()]:
            if target[0] is Dataset and target not in retained_ids:
                retained_ids.add(target)
                pending.append(target)
    # Uploaded and built-in inputs are never removed merely because a consumer is deleted.
    for row in rows[Job]:
        if (Job, row.id) in selected and row.input_dataset_id and (Dataset, row.input_dataset_id) not in selected:
            retained_ids.add((Dataset, row.input_dataset_id))
    retained = []
    for _, item in sorted(retained_ids, key=lambda value: str(value[1])):
        dataset = db.get(Dataset, item)
        if dataset is not None:
            retained.append({'kind': 'datasets', 'id': str(item), 'name': dataset.name, 'files': [{'name': row.original_filename, 'size_bytes': row.size_bytes} for row in db.scalars(select(DatasetFile).where(DatasetFile.dataset_id == item))], 'reason': 'INPUT_OR_SHARED_RESOURCE'})
    public = {'objects': objects, 'files': files, 'retained': retained, 'blocked': blocked,
              'reclaimable_bytes': sum({tuple(item['version'][:2]): item['size_bytes'] for item in files}.values())}
    versions = sorted((model.__tablename__, str(row.id), str(getattr(row, 'updated_at', row.created_at)))
                      for model, values in rows.items() for row in values if row.id in chosen[model])
    fingerprint = hashlib.sha256(json.dumps([public, versions], sort_keys=True).encode()).hexdigest()
    return public, fingerprint, rows, chosen


def preview_deletion(db, owner_id, job_ids):
    public, fingerprint, _, _ = deletion_impact(db, owner_id, job_ids)
    token = jwt.encode({'type': 'job_deletion', 'sub': str(owner_id),
        'job_ids': sorted(str(item) for item in set(job_ids)),
        'deleted_job_ids': [item['id'] for item in public['objects'] if item['kind'] == 'jobs'], 'fingerprint': fingerprint,
        'request_id': str(uuid.uuid4()), 'exp': utcnow() + timedelta(minutes=10)},
        settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return {**public, 'objects': [{key: value for key, value in item.items() if key != 'version'} for item in public['objects']],
            'files': [{key: value for key, value in item.items() if key != 'version'} for item in public['files']],
            'confirmation_token': token}


def confirm_deletion(owner_id, job_ids, token):
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm],
                            options={'require': ['exp', 'sub', 'request_id', 'fingerprint', 'job_ids', 'deleted_job_ids']})
        if claims.get('type') != 'job_deletion' or claims['sub'] != str(owner_id) or claims['job_ids'] != sorted(str(item) for item in set(job_ids)):
            raise ValueError()
        request_id = uuid.UUID(claims['request_id'])
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(409, {'error_code': 'DELETE_PREVIEW_CHANGED', 'message': 'Refresh the deletion preview and confirm again'}) from None
    with engine.connect().execution_options(retention_cleanup=True) as connection, Session(bind=connection, expire_on_commit=False) as db, ExitStack() as stack:
        held = set()
        with db.begin():
            if not db.scalar(text('SELECT pg_try_advisory_xact_lock(:key)'), {'key': RETENTION_LOCK}):
                raise HTTPException(409, {'error_code': 'DELETE_BUSY', 'message': 'Resources are busy; retry shortly'})
            pending = db.get(DataRetentionDeletion, request_id)
            if pending is not None and pending.owner_user_id == owner_id:
                return {'job_ids': claims['job_ids'], 'deleted_job_ids': claims['deleted_job_ids'], 'deleted': True, 'cleanup_status': 'pending'}
            existing = list(db.scalars(select(Job).where(Job.id.in_(job_ids), Job.owner_user_id == owner_id)))
            if len(existing) == len(set(job_ids)) and all(row.is_deleted for row in existing):
                return {'job_ids': claims['job_ids'], 'deleted_job_ids': claims['deleted_job_ids'], 'deleted': True, 'cleanup_status': 'completed'}
            public, fingerprint, rows, chosen = deletion_impact(db, owner_id, job_ids)
            if fingerprint != claims['fingerprint']:
                raise HTTPException(409, {'error_code': 'DELETE_PREVIEW_CHANGED', 'message': 'Dependencies changed; refresh and confirm again'})
            if public['blocked']:
                raise HTTPException(409, {'error_code': 'DELETE_BUSY', 'message': 'Wait for the listed executions before deleting'})
            for task in rows[JobTask]:
                if task.id in chosen[JobTask] and not _receipt_lock(stack, str(task.queue_job_id), held):
                    raise HTTPException(409, {'error_code': 'DELETE_BUSY', 'message': 'Computation has not stopped'})
            # Refuse any foreign-key reference not represented in this owner's confirmed group.
            from backend.db import Base
            for table in Base.metadata.sorted_tables:
                if table.name not in {model.__tablename__ for model in chosen}:
                    continue
                own_model = next(model for model in chosen if model.__tablename__ == table.name)
                for column in table.columns:
                    for foreign in column.foreign_keys:
                        target = next((model for model in chosen if model.__tablename__ == foreign.column.table.name), None)
                        if target and chosen[target]:
                            outside = select(table.c.id).where(column.in_(chosen[target]), ~table.c.id.in_(chosen[own_model])).limit(1)
                            if db.scalar(outside) is not None:
                                raise HTTPException(409, 'A resource outside the confirmed group still depends on these objects')
            deleted_job_ids = sorted(str(item) for item in chosen[Job])
            queue_ids = [str(task.queue_job_id) for task in rows[JobTask] if task.id in chosen[JobTask]]
            paths = [f'{directory}/{item}' for model, directory in ((Job, 'jobs'), (Dataset, 'datasets')) for item in chosen[model]]
            db.add(DataRetentionDeletion(id=request_id, owner_user_id=owner_id, origin='manual', paths=paths, queue_job_ids=queue_ids))
            db.execute(update(WorkflowRun).where(WorkflowRun.id.in_(chosen[WorkflowRun])).values(action_proposal_id=None))
            db.execute(update(AgentSession).where(AgentSession.id.in_(chosen[AgentSession])).values(active_workflow_id=None, preparation_job_id=None))
            db.execute(update(ActionProposal).where(ActionProposal.id.in_(chosen[ActionProposal])).values(workflow_id=None))
            db.execute(update(Job).where(Job.id.in_(chosen[Job])).values(is_deleted=True, deleted_at=utcnow(),
                input_dataset_id=None, params={}, summary={}, updated_at=utcnow()))
            order = ['WorkflowEvent', 'WorkflowCommand', 'EditSession', 'DesignDraft', 'CandidateSet', 'ActionProposal',
                     'AgentTurn', 'AgentSession', 'WorkflowPlanningRequest', 'WorkflowInteraction', 'WorkflowStep', 'WorkflowRun',
                     'QueueOutbox', 'JobTask', 'DatasetFile', 'Dataset', 'DeleteEditSpec']
            for name in order:
                for model in chosen:
                    if model.__name__ == name:
                        _delete_rows(db, model, chosen[model])
        with db.begin():
            purge_files(db, None, stack, held, manual_only=True, request_id=request_id)
        status = 'pending' if db.get(DataRetentionDeletion, request_id) is not None else 'completed'
    return {'job_ids': claims['job_ids'], 'deleted_job_ids': deleted_job_ids, 'deleted': True, 'cleanup_status': status}
