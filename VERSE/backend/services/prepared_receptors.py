from genova_runtime.artifact_json import read_json
import uuid
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from backend.models import Dataset, DatasetFile
from backend.config import settings
from backend.services.protein_contexts import _dataset_or_404
from backend.structure_contracts import ComponentManifest, PreparedReceptorCreate, PreparedReceptorSpec, StructureSource
from backend.utils import utcnow
from genova_runtime.pdb2pqr_compat import file_sha256




def _source_file(db, user_id, source):
    dataset = _dataset_or_404(db, source.dataset_id, user_id)
    if dataset.kind in {"protein_context", "prepared_receptor"}:
        raise HTTPException(422, "Select an original structure dataset")
    row = db.scalar(select(DatasetFile).where(
        DatasetFile.dataset_id == dataset.id, DatasetFile.id == source.file_id,
    ))
    if row is None:
        raise HTTPException(404, "Structure file not found")
    if row.size_bytes == 0:
        raise HTTPException(422, "Structure file is empty")
    if row.size_bytes > 50 * 1024 * 1024:
        raise HTTPException(413, "Structure input exceeds its size limit")
    from backend.builtin_datasets import BUILTIN_DIR, is_builtin
    safe_path = Path(row.storage_path).resolve().is_relative_to(settings.data_root.resolve()) or is_builtin(dataset) and Path(row.storage_path).resolve().is_relative_to(BUILTIN_DIR.resolve())
    if not safe_path:
        raise HTTPException(422, "Structure path is outside shared storage")
    if not Path(row.storage_path).is_file() or row.sha256 != source.sha256 or file_sha256(row.storage_path) != source.sha256:
        raise HTTPException(409, "Source structure changed or is unavailable")
    if Path(row.original_filename).suffix.lower() not in {'.pdb', '.cif', '.mmcif'}:
        raise HTTPException(422, 'Select a PDB or mmCIF structure')
    from genova_runtime.structure_inventory import source_inventory
    try:
        raw = source_inventory(Path(row.storage_path), source.model_dump(mode='json'))
    except (ValueError, UnicodeError, KeyError) as exc:
        if 'contains no atoms' in str(exc) or 'Non-finite' in str(exc) or 'Duplicate source' in str(exc):
            raise HTTPException(422, str(exc)) from exc
        raw = dict(version=2, source=source.model_dump(mode='json'), coordinate_frame_id=f'{source.sha256}:{source.model_id}:source',
            components=[], inventory_policy="generation_auto_v1", source_format='pdb' if Path(row.original_filename).suffix.lower() == '.pdb' else 'mmcif', inventory_error=str(exc))
    return row, ComponentManifest.model_validate(raw)

def get_component_manifest(source: StructureSource, db, user_id):
    return _source_file(db, user_id, source)[1]




def _validate_edits(spec, manifest):
    from genova_runtime.structure_inventory import validate_selection
    try:
        raw = manifest.model_dump(mode="json")
        validate_selection(raw, spec.edits.model_dump(mode="json"))
        if spec.preparation.water_policy == "remove_all":
            waters = {c['component_id'] for c in raw['components'] if c['atoms'][0]['residue_name'] in {'HOH', 'WAT', 'DOD', 'H2O'}}
            if waters & set(spec.edits.retained_component_ids):
                raise ValueError("Remove-all water policy conflicts with explicitly retained water")
            if not raw.get('inventory_error') and {c['component_id'] for c in raw['components']} <= waters | set(spec.edits.excluded_component_ids):
                raise ValueError("Preparation must retain at least one non-water component")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return

def create_prepared_receptor(payload: PreparedReceptorCreate, db, user_id):
    manifest = get_component_manifest(payload.source, db, user_id)
    _validate_edits(payload, manifest)
    now = utcnow()
    dataset = Dataset(
        id=uuid.uuid4(), owner_user_id=user_id, name=payload.name,
        kind="prepared_receptor", status="draft",
        meta={**payload.model_dump(mode="json", exclude={"name"}),
              "component_manifest": manifest.model_dump(mode="json")},
        created_at=now, updated_at=now,
    )
    db.add(dataset)
    db.flush()
    return _serialize(dataset)


def _serialize(dataset):
    result = {
        "id": str(dataset.id), "name": dataset.name, "status": dataset.status,
        **dataset.meta, "created_at": dataset.created_at.isoformat(),
        "updated_at": dataset.updated_at.isoformat(),
    }
    if dataset.status == 'processing':
        import json
        execution = result.get('execution') or {}
        job_id = uuid.UUID(execution['job_id'])
        path = settings.data_root / 'jobs' / str(job_id) / 'protein_preparation' / 'preparation_progress.json'
        if path.is_file():
            report = read_json(path)
            if report.get('requested_spec') == prepared_spec(dataset.meta).model_dump(mode='json') and report.get('stage'):
                result['execution'] = {**execution, 'stage': report['stage']}
    return result


def get_prepared_receptor(receptor_id, db, user_id):
    dataset = _dataset_or_404(db, receptor_id, user_id)
    if dataset.kind != "prepared_receptor":
        raise HTTPException(404, "Prepared receptor not found")
    meta = dataset.meta or {}
    try:
        spec = prepared_spec(meta)
        manifest = ComponentManifest.model_validate(meta["component_manifest"])
    except (ValidationError, KeyError) as exc:
        raise HTTPException(409, "Invalid prepared receptor contract") from exc
    _, current_manifest = _source_file(db, user_id, spec.source)
    if manifest.source != spec.source or manifest != current_manifest:
        raise HTTPException(409, "Manifest source mismatch")
    _validate_edits(spec, manifest)
    result = _serialize(dataset)
    if result.get('artifacts', {}).get('context_receptor'):
        from backend.services.binding_sites import artifact
        from backend.structure_contracts import FileIdentity
        from genova_runtime.structure_inventory import source_inventory
        identity = FileIdentity.model_validate(result['artifacts']['context_receptor'])
        row = artifact(db, user_id, identity)
        inventory = source_inventory(Path(row.storage_path), {**identity.model_dump(mode='json'), 'model_id':'1'})
        inventory['coordinate_frame_id'] = manifest.coordinate_frame_id
        result['context_receptor_manifest'] = ComponentManifest.model_validate(inventory).model_dump(mode='json')
        capabilities = result.get('capabilities') or {}
        operations = capabilities.get('operations') or {}
        standardization = operations.get('standardization') or {}
        if standardization.get('requested') and standardization.get('status') == 'skipped':
            from genova_runtime.preparation_policy import standardization_operation
            selected_ids = {a['atom_id'] for c in inventory['components'] for a in c['atoms']}
            operation = standardization_operation(inventory, selected_ids, True)
            if operation['status'] == 'not_applicable':
                operations = {**operations, 'standardization': operation}
                result['capabilities'] = {**capabilities, 'operations': operations,
                    'preparation_status': 'partial' if any(o['status'] in {'skipped', 'partial'} for o in operations.values()) else 'complete'}
    return result


def prepared_spec(meta):
    return PreparedReceptorSpec.model_validate({k: v for k, v in meta.items() if k not in {
        "component_manifest", "execution", "artifacts", "capabilities", "failure_artifacts",
    }})


def submit_preparation(receptor_id, db, user_id):
    from backend.services.resources import check_admission
    check_admission(db, user_id)
    from copy import deepcopy
    from backend.models import Job, JobTask, QueueOutbox
    from backend.workflows.contracts import digest
    receptor = _dataset_or_404(db, receptor_id, user_id)
    db.refresh(receptor, with_for_update=True)
    if receptor.kind != "prepared_receptor" or receptor.owner_user_id != user_id:
        raise HTTPException(404, "Prepared receptor not found")
    if receptor.status != "draft":
        raise HTTPException(409, "Create a new preparation draft for another attempt")
    spec = prepared_spec(receptor.meta)
    source, manifest = _source_file(db, user_id, spec.source)
    _validate_edits(spec, manifest)
    saved = spec.model_dump(mode="json")
    input_hash = digest({'spec': saved, 'source_manifest': manifest.model_dump(mode='json')})
    job_id, task_id, queue_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    artifact_ids = {key: str(uuid.uuid4()) for key in ("prepared_complex", "atom_map", "component_manifest", "report", "context_receptor", "context_receptor_map")}
    task_payload = {"preparation_protocol_version": spec.version, "prepared_receptor_id": str(receptor.id),
                    "prepared_spec": saved, "protein_pdb": source.storage_path,
                    "artifact_ids": artifact_ids, "output_dir": str(settings.data_root / "jobs" / str(job_id) / "protein_preparation")}
    now = utcnow()
    job = Job(id=job_id, owner_user_id=user_id, job_type="protein_preparation", status="pending",
              input_dataset_id=receptor.id, params={"prepared_receptor_id": str(receptor.id), "preparation_protocol_version": spec.version,
              "prepared_spec": saved, "spec_hash": input_hash, "artifact_ids": artifact_ids},
              summary={"tasks": {"protein_preparation": {"queue_job_id": str(queue_id), "status": "pending", "runtime_task": "protein_preparation"}}})
    task = JobTask(id=task_id, job_id=job_id, task_code="protein_preparation", runtime_task="protein_preparation",
                   status="pending", queue_job_id=queue_id, depends_on=[], input_payload=task_payload,
                   output_payload={}, created_at=now, updated_at=now)
    db.add(job)
    db.add(task)
    db.add(QueueOutbox(job_task_id=task.id, queue_name=settings.redis_dispatch_queue, status="pending", payload={
        "job_id": str(queue_id), "task": "protein_preparation", "payload": task_payload,
        "result_queue": settings.redis_result_queue, "meta": {"job_id": str(job_id), "prepared_receptor_id": str(receptor.id)}}))
    receptor.meta = {**deepcopy(receptor.meta), "execution": {"job_id": str(job_id), "spec_hash": input_hash, "status": "queued"}}
    receptor.status, receptor.updated_at = "processing", now
    db.flush()
    return job




def complete_preparation(db, job, task, status_value, result=None, error=None):
    import json
    import shutil
    from backend.structure_contracts import PreparedArtifacts, SourceMapping
    from backend.workflows.contracts import digest
    params = job.params
    receptor = db.get(Dataset, uuid.UUID(params['prepared_receptor_id']))
    if receptor is None or receptor.owner_user_id != job.owner_user_id or receptor.kind != 'prepared_receptor':
        raise ValueError('Prepared receptor is missing or belongs to another user')
    db.refresh(receptor, with_for_update=True)
    spec = prepared_spec(receptor.meta).model_dump(mode='json')
    execution = (receptor.meta or {}).get('execution') or {}
    input_hash = digest({'spec': spec, 'source_manifest': ComponentManifest.model_validate(receptor.meta['component_manifest']).model_dump(mode='json')})
    if execution.get('job_id') != str(job.id) or execution.get('spec_hash') != input_hash or params['spec_hash'] != input_hash or spec != params['prepared_spec']:
        raise ValueError('Preparation result belongs to a stale input or attempt')
    attaching_failure_report = (spec['preparation'].get('strategy') == 'generation_auto_v1' and execution.get('status') == 'failed'
        and status_value != 'succeeded' and result and result.get('report') and not receptor.meta.get('failure_artifacts'))
    if execution.get('status') in {'succeeded', 'failed'} and not attaching_failure_report:
        return
    if status_value != 'succeeded':
        from genova_runtime.preparation_errors import describe_preparation_error
        failure_report = {}
        if result and result.get('report') and spec['preparation'].get('strategy') == 'generation_auto_v1':
            report_path = Path(result['report']).resolve()
            root = (settings.data_root / 'jobs' / str(job.id)).resolve()
            if not report_path.is_relative_to(root) or not report_path.is_file() or file_sha256(report_path) != result.get('artifact_sha256', {}).get('report'):
                raise ValueError('Invalid failure report path or hash')
            failure_report = read_json(report_path)
            if failure_report.get('requested_spec') != spec or failure_report.get('status') != 'failed':
                raise ValueError('Failure report does not match the requested specification')
            directory = settings.data_root / 'datasets' / str(receptor.id)
            directory.mkdir(parents=True, exist_ok=True)
            fid = uuid.UUID(params['artifact_ids']['report'])
            target = directory / f'{fid}_preparation_report.json'
            shutil.copy2(report_path, target)
            db.add(DatasetFile(id=fid, dataset_id=receptor.id, file_role='report', storage_path=str(target), original_filename='preparation_report.json',
                size_bytes=target.stat().st_size, sha256=file_sha256(target), content_type='application/json'))
            receptor.meta = {**receptor.meta, 'failure_artifacts': {'report': {'dataset_id': str(receptor.id), 'file_id': str(fid), 'sha256': file_sha256(target)}}}
        receptor.status = 'failed'
        info = failure_report.get('error_info') or (result or {}).get('error_info') or describe_preparation_error(error or 'Preparation failed', 'execution')
        receptor.meta = {**receptor.meta, 'execution': {**execution, 'status': 'failed',
            'error': failure_report.get('error') or str(error or 'Preparation failed')[:2000], 'error_info': info}}
        receptor.updated_at = utcnow()
        return
    result = result or {}
    try:
        _source_file(db, job.owner_user_id, prepared_spec(receptor.meta).source)
    except HTTPException as exc:
        raise ValueError(str(exc.detail)) from exc
    if result.get('preparation_protocol_version') != spec['version'] or result.get('source_sha256') != spec['source']['sha256']:
        raise ValueError('Invalid preparation result protocol or source identity')
    root = (settings.data_root / 'jobs' / str(job.id)).resolve()
    sources = {}
    for key in params['artifact_ids']:
        source = Path(result[key]).resolve()
        if not source.is_relative_to(root) or not source.is_file() or file_sha256(source) != result['artifact_sha256'].get(key):
            raise ValueError('Invalid preparation artifact path or hash')
        sources[key] = source
    report = read_json(sources['report'])
    capabilities = report['capabilities']
    if capabilities != result['capabilities'] or capabilities['structure_validation'] != 'passed' or capabilities['artifact_sha256'] != result['artifact_sha256']['prepared_complex']:
        raise ValueError('Preparation capabilities do not match the actual artifact')
    mapping = read_json(sources['atom_map'])
    from genova_runtime.preparation_policy import RECEPTOR_POLICY, context_receptor_selection
    from genova_runtime.structure_inventory import source_inventory
    receptor_map = read_json(sources['context_receptor_map'])
    if capabilities.get('receptor_policy') != RECEPTOR_POLICY or capabilities.get('context_receptor_sha256') != result['artifact_sha256']['context_receptor'] or receptor_map['source_sha256'] != result['artifact_sha256']['prepared_complex'] or receptor_map['output_sha256'] != result['artifact_sha256']['context_receptor']:
        raise ValueError('Context receptor artifact binding mismatch')
    actual_receptor = source_inventory(sources['context_receptor'], dict(sha256=result['artifact_sha256']['context_receptor'], model_id='1'))
    selected_receptor, _ = context_receptor_selection(actual_receptor)
    if selected_receptor != {a['atom_id'] for c in actual_receptor['components'] for a in c['atoms']}:
        raise ValueError('Context receptor contains forbidden components')
    full_manifest = source_inventory(sources['prepared_complex'], dict(sha256=result['artifact_sha256']['prepared_complex'], model_id='1'))
    expected, decisions = context_receptor_selection(full_manifest)
    original_atoms = {a['atom_id']: a for c in full_manifest['components'] for a in c['atoms']}
    output_atoms = {a['atom_id']: a for c in actual_receptor['components'] for a in c['atoms']}
    source_entries = [e['source_atom_id'] for e in receptor_map['entries'] if e['source_atom_id']]
    output_entries = [e['output_atom_id'] for e in receptor_map['entries'] if e['output_atom_id']]
    if set(source_entries) != original_atoms.keys() or len(source_entries) != len(set(source_entries)) or set(output_entries) != output_atoms.keys() or len(output_entries) != len(set(output_entries)) or receptor_map['decisions'] != decisions:
        raise ValueError('Context receptor mapping coverage mismatch')
    for entry in receptor_map['entries']:
        before = original_atoms.get(entry['source_atom_id'])
        after = output_atoms.get(entry['output_atom_id'])
        if before is None:
            continue
        if (before['atom_id'] not in expected and after is not None) or (before['atom_id'] in expected and before['element'] not in {'H', 'D'} and after is None):
            raise ValueError('Context receptor violates forced component selection')
        keys = ('atom_name','element','author_chain_id','author_residue_number','insertion_code')
        if before['element'] not in {'H','D'} or before['residue_id'] not in receptor_map['restored_residue_ids']:
            keys += ('coordinates',)
        if after is not None and any(before[k] != after[k] for k in keys):
            raise ValueError('Context receptor changed a retained source atom')
    SourceMapping.model_validate({k: v for k, v in mapping.items() if k != 'max_atom_displacement_angstrom'})
    if mapping['source'] != spec['source'] or mapping['output']['sha256'] != result['artifact_sha256']['prepared_complex']:
        raise ValueError('Preparation atom map identity mismatch')
    from genova_runtime.structure_inventory import source_inventory
    if report.get('requested_spec') != spec or report.get('strategy') != 'generation_auto_v1':
        raise ValueError('Automatic preparation request binding mismatch')
    raw = receptor.meta['component_manifest']
    plan = report['resolved_plan']
    if plan['source'] != spec['source'] or plan['strategy'] != 'generation_auto_v1':
        raise ValueError('Automatic preparation plan binding mismatch')
    from genova_runtime.structure_inventory import validate_selection, resolve_altlocs
    expected_choices, expected_residues = resolve_altlocs(raw, spec['edits']['altloc_choices'], automatic=True)
    if plan['altloc_choices'] != expected_choices or plan['excluded_residue_ids'] != expected_residues:
        raise ValueError('Automatic conformer plan does not match the requested policy')
    validate_selection(raw, {'excluded_component_ids': plan['excluded_component_ids'], 'altloc_choices': plan['altloc_choices']})
    auto_removed = set(plan['excluded_component_ids']) - set(spec['edits']['excluded_component_ids'])
    water_ids = {c['component_id'] for c in raw['components'] if c['atoms'][0]['residue_name'] in {'HOH', 'WAT', 'DOD', 'H2O'}}
    if not auto_removed <= water_ids or (auto_removed and spec['preparation']['water_policy'] not in {'remove_all'}):
        raise ValueError('Unauthorized automatic component exclusion')
    if spec['preparation']['water_policy'] == 'remove_all' and not water_ids <= set(plan['excluded_component_ids']):
        raise ValueError('Preparation did not remove all water required by the request')
    if any(plan['altloc_choices'].get(key) != value for key, value in spec['edits']['altloc_choices'].items()):
        raise ValueError('Preparation changed an explicit alternate location')
    if not set(spec['edits']['excluded_component_ids']) <= set(plan['excluded_component_ids']):
        raise ValueError('Preparation ignored an explicit exclusion')
    if set(spec['edits'].get('retained_component_ids', [])) & set(plan['excluded_component_ids']):
        raise ValueError('Preparation removed an explicitly retained component')
    selected = {a['atom_id']: a for c in raw['components'] if c['component_id'] not in plan['excluded_component_ids'] for a in c['atoms']
                if a['residue_id'] not in plan['excluded_residue_ids'] and (not a['altloc'] or not plan['altloc_choices'].get(a['residue_id']) or plan['altloc_choices'][a['residue_id']] == a['altloc'])}
    mapped = {e['source_atom_id']: e for e in mapping['entries'] if e['source_atom_id']}
    if set(mapped) != {a['atom_id'] for c in raw['components'] for a in c['atoms']}:
        raise ValueError('Automatic preparation source atom coverage mismatch')
    if any(not mapped[aid]['output_atom_id'] for aid, a in selected.items() if a['element'] not in {'H', 'D'}):
        raise ValueError('Automatic preparation lost retained heavy atoms')
    if any(e['output_atom_id'] for aid, e in mapped.items() if aid not in selected):
        raise ValueError('Excluded atom remains in automatic preparation')
    actual = source_inventory(sources['prepared_complex'], {**mapping['output'], 'model_id': '1'})
    actual_ids = {a['atom_id'] for c in actual['components'] for a in c['atoms']}
    actual_atoms = {a['atom_id']: a for c in actual['components'] for a in c['atoms']}
    for aid, source_atom in selected.items():
        output_id = mapped[aid]['output_atom_id']
        if output_id is None:
            continue
        output_atom = actual_atoms.get(output_id)
        chain = source_atom.get('label_asym_id') or source_atom['chain_instance_id'].split(':chain:')[-1].replace(':', '_')
        if output_atom is None or output_atom['element'] != source_atom['element'] or output_atom['author_chain_id'] != (source_atom['author_chain_id'] or chain) or output_atom['author_residue_number'] != source_atom['author_residue_number'] or output_atom['insertion_code'] != source_atom['insertion_code'] or output_atom['atom_name'] != source_atom['atom_name']:
            raise ValueError('Automatic preparation atom mapping changed source identity')

    if {e['output_atom_id'] for e in mapping['entries'] if e['output_atom_id']} != actual_ids:
        raise ValueError('Automatic preparation output atom coverage mismatch')
    if report['operation_results'] != capabilities['operations']:
        raise ValueError('Automatic preparation operation report mismatch')
    manifest = ComponentManifest.model_validate(read_json(sources['component_manifest']))
    if manifest.source.sha256 != result['artifact_sha256']['prepared_complex']:
        raise ValueError('Prepared manifest identity mismatch')
    identities = {key: {'dataset_id': str(receptor.id), 'file_id': fid, 'sha256': result['artifact_sha256'][key]} for key, fid in params['artifact_ids'].items()}
    PreparedArtifacts.model_validate(identities)
    if mapping['output'] != identities['prepared_complex'] or str(manifest.source.file_id) != params['artifact_ids']['prepared_complex']:
        raise ValueError('Preparation artifact binding mismatch')
    directory = settings.data_root / 'datasets' / str(receptor.id)
    directory.mkdir(parents=True, exist_ok=True)
    for key, source in sources.items():
        fid = uuid.UUID(params['artifact_ids'][key])
        target = directory / f'{fid}_{source.name}'
        import os
        if target.exists():
            if file_sha256(target) != identities[key]['sha256']:
                raise ValueError('Published preparation artifact hash mismatch')
        else:
            os.link(source, target)
        db.add(DatasetFile(id=fid, dataset_id=receptor.id, file_role=key, storage_path=str(target),
                           original_filename=source.name.removesuffix('.gz'), size_bytes=target.stat().st_size,
                           sha256=identities[key]['sha256'], content_type=('chemical/x-mmcif' if source.suffix == '.cif' else 'chemical/x-pdb') if key in {'prepared_complex', 'context_receptor'} else 'application/json'))
    receptor.meta = {**receptor.meta, 'execution': {**execution, 'status': 'succeeded'},
                     'artifacts': identities, 'capabilities': capabilities}
    receptor.status, receptor.updated_at = 'ready', utcnow()
