"""Bounded original-file evidence within the current research task."""
import copy
import hashlib
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from backend.agent.diagnostics import diagnostic_sources, read_text_source
from backend.agent.runner import estimate_tokens
from backend.config import settings
from backend.models import ActionProposal, AgentTurn, DatasetFile, JobTask, WorkflowRun, WorkflowStep
from backend.services.jobs import get_owned_dataset, get_owned_job, ResourceNotFound


TEXT_SUFFIXES = {'.pdb', '.cif', '.mmcif', '.sdf', '.mol', '.mol2', '.csv', '.smi', '.smiles', '.json', '.txt', '.log', '.out', '.err'}


def task_sources(deps):
    state = deps.session_context or {}
    if not state.get('id'):
        return {}
    from backend.services.agent_sessions import owned_session
    session = owned_session(deps.db, UUID(state['id']), deps.user_id)
    if session.research_task_id != deps.research_task_id:
        return {}
    dataset_ids, job_ids = set(), set()

    def identities(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, str) and (key == 'dataset_id' or key.endswith('_dataset_id') or key in {'prepared_receptor_id', 'protein_context_id'}):
                    dataset_ids.add(UUID(item))
                elif key == 'job_id' and isinstance(item, str):
                    job_ids.add(UUID(item))
                elif isinstance(item, (dict, list)) and key != 'component_manifest':
                    identities(item)
        elif isinstance(value, list):
            for item in value:
                identities(item)

    identities(session.assets)
    for proposal in deps.db.scalars(select(ActionProposal).where(ActionProposal.session_id == session.id).join(
            AgentTurn,
            ActionProposal.turn_id == AgentTurn.id).where(
            AgentTurn.research_task_id == deps.research_task_id)):
        identities(proposal.payload)
        identities(proposal.execution)
        if proposal.workflow_id:
            run = deps.db.get(WorkflowRun, proposal.workflow_id)
            if run and run.research_task_id == deps.research_task_id:
                identities(run.execution_binding)
                dataset_ids.update(UUID(r['id']) for r in ((run.execution_binding or {}).get('inputs') or {}).get('resources', []))
                job_ids.update(deps.db.scalars(select(WorkflowStep.job_id).where(
                    WorkflowStep.workflow_id == run.id, WorkflowStep.job_id.is_not(None))))
    sources, visited = {}, set()

    def add(path, identity, metadata):
        path = Path(path)
        suffix = Path(path.stem).suffix.lower() if path.suffix.lower() == '.gz' else path.suffix.lower()
        if suffix not in TEXT_SUFFIXES or not path.is_file() or not path.resolve().is_relative_to(Path(settings.data_root).resolve()):
            return
        stat = path.stat()
        sid = hashlib.sha256(identity.encode()).hexdigest()[:24]
        sources[sid] = (path, {**metadata, 'source_id': sid, 'size_bytes': stat.st_size,
            'source_version': f'{stat.st_mtime_ns}:{stat.st_size}', 'ref': identity})

    while dataset_ids - visited:
        did = next(iter(dataset_ids - visited))
        visited.add(did)
        try:
            dataset = get_owned_dataset(deps.db, did, deps.user_id)
        except ResourceNotFound:
            continue
        if dataset.status == 'archived':
            continue
        identities(dataset.meta or {})
        dataset_root = Path(settings.data_root) / 'datasets' / str(did)
        if dataset_root.is_symlink():
            continue
        for row in deps.db.scalars(select(DatasetFile).where(DatasetFile.dataset_id == did)):
            if not Path(row.storage_path).resolve().is_relative_to(dataset_root.resolve()):
                continue
            add(row.storage_path, f'dataset:{did}:file:{row.id}', {'dataset_id': str(did),
                'file_id': str(row.id), 'name': row.original_filename[:255], 'sha256': row.sha256})
    for jid in job_ids:
        try:
            get_owned_job(deps.db, deps.user_id, jid)
        except ResourceNotFound:
            continue
        root = Path(settings.data_root) / 'jobs' / str(jid)
        if root.is_symlink():
            continue
        root = root.resolve()
        for task in deps.db.scalars(select(JobTask).where(JobTask.job_id == jid)):
            for key, value in (task.output_payload or {}).items():
                if not isinstance(value, str):
                    continue
                path = Path(value)
                if path.is_absolute() and path.resolve().is_relative_to(root):
                    add(path, f'job:{jid}:task:{task.id}:artifact:{key}', {'job_id': str(jid), 'name': path.name[:255]})
        for path, meta in diagnostic_sources(jid).values():
            add(path, meta['ref'], {'job_id': str(jid), 'name': meta['name'][:255]})
    return dict(sorted(sources.items()))


def bounded_facts(facts, target=6000):
    """Preserve recent exact evidence without concatenating every read page."""
    result = []
    for fact in reversed(facts):
        fact = copy.deepcopy(fact)
        payload = fact.get('result', fact)
        if fact.get('tool') == 'inspect_session_protein' and isinstance(payload, dict):
            # The checker needs the same structural evidence as the answering model.
            # Remove duplicate per-component summaries and keep target identity plus
            # enough of each chain sequence to validate the answer within its budget.
            payload.pop('preparation_components', None)
            metadata = payload.get('chain_metadata') or []
            if metadata:
                payload['structure_title'] = next((row.get('structure_title') for row in metadata
                    if row.get('structure_title')), payload.get('structure_title'))
                for row in metadata:
                    row.pop('structure_title', None)
                    for key in ('observed_sequence', 'declared_sequence'):
                        if isinstance(row.get(key), str) and len(row[key]) > 400:
                            row[key] = row[key][:400]
                            row[key + '_truncated'] = True
                    if isinstance(row.get('entity_description'), str):
                        row['entity_description'] = row['entity_description'][:200]
            if isinstance(payload.get('ligands'), list) and len(payload['ligands']) > 12:
                payload['ligands_truncated'] = len(payload['ligands']) - 12
                payload['ligands'] = payload['ligands'][:12]
        while payload.get('lines') and estimate_tokens(fact) > target:
            payload['lines'].pop()
            payload['excerpt_only'] = True
        if estimate_tokens([fact, *result]) <= target:
            result.insert(0, fact)
    return result


def read_source(deps, source_id, source_version, start_line, start_column, limit, query, context_lines):
    entry = task_sources(deps).get(source_id)
    if not entry:
        return {'error_code': 'DIAGNOSTIC_SOURCE_MISSING'}
    path, source = entry
    if source_version != source['source_version']:
        return {**source, 'error_code': 'DIAGNOSTIC_SOURCE_CHANGED'}
    result = read_text_source(path, source, start_line, limit, query, context_lines, start_column)
    while result['lines'] and (estimate_tokens(result) > 6000 or len(json.dumps(result, ensure_ascii=False).encode()) > 65536):
        line = result['lines'][-1]
        if len(line['text']) > 128:
            line['text'] = line['text'][:len(line['text']) // 2]
            result.update(truncated=True, scan_complete=False, next_line=line['line'], next_column=line['column'] + len(line['text']))
        else:
            line = result['lines'].pop()
            result.update(truncated=True, scan_complete=False, next_line=line['line'], next_column=line['column'])
    stat = path.stat()
    if f'{stat.st_mtime_ns}:{stat.st_size}' != source_version:
        return {**source, 'error_code': 'DIAGNOSTIC_SOURCE_CHANGED'}
    saved = dict(deps.source_read_state)
    cursors = [c for c in saved.get('sources', []) if c['source_id'] != source_id]
    cursors.append({k: v for k, v in result.items() if k not in {'lines', 'matched_lines'}})
    saved['sources'] = cursors[-12:]
    saved['evidence'] = bounded_facts([*saved.get('evidence', []), result])
    deps.source_read_state = saved
    return result
