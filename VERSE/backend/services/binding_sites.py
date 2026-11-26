from genova_runtime.artifact_json import read_json
import json
from copy import deepcopy
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from backend.models import DatasetFile
from backend.structure_contracts import ProteinContextV4Create, ProteinContextV4Record, FileIdentity
from genova_runtime.pdb2pqr_compat import file_sha256
from genova_runtime.context_features import CACHE_VERSION, CONTRACT
from genova_runtime.preparation_errors import describe_preparation_error




def artifact(db, owner_id, identity):
    from backend.services.protein_contexts import _dataset_or_404
    dataset = _dataset_or_404(db, identity.dataset_id, owner_id)
    row = db.scalar(select(DatasetFile).where(DatasetFile.dataset_id == dataset.id, DatasetFile.id == identity.file_id))
    if row is None:
        raise HTTPException(404, 'Artifact not found')
    path = Path(row.storage_path)
    if not path.is_file() or row.sha256 != identity.sha256 or file_sha256(path) != identity.sha256:
        raise HTTPException(409, 'Artifact content changed or is unavailable')
    return row


def create_site(payload, db, user_id):
    from backend.services.prepared_receptors import get_prepared_receptor
    request = ProteinContextV4Create.model_validate(payload)
    prepared = get_prepared_receptor(request.prepared_receptor_id, db, user_id)
    if prepared['status'] != 'ready' or not prepared.get('artifacts'):
        raise HTTPException(409, 'Preparation must finish before defining a binding site')
    from backend.services.automatic_sites import create_auto_site
    return create_auto_site(request, prepared, db, user_id)


def resolve_v4_context(dataset, db, user_id, engine=None):
    if dataset.status != "ready":
        raise HTTPException(409, "Protein Context is not ready or has been archived")
    from backend.services.prepared_receptors import get_prepared_receptor
    try:
        spec = ProteinContextV4Record.model_validate(dataset.meta)
    except ValidationError as exc:
        raise HTTPException(409, 'Invalid v4 context artifact contract') from exc
    prepared = get_prepared_receptor(spec.prepared_receptor_id, db, user_id)
    if prepared['status'] != 'ready' or prepared['artifacts']['prepared_complex']['sha256'] != spec.prepared_artifact_sha256:
        raise HTTPException(409, 'Prepared resource binding changed')
    protein = artifact(db, user_id, spec.artifacts.effective_receptor)
    anchor = artifact(db, user_id, spec.artifacts.anchor_coordinates)
    anchors = read_json(Path(anchor.storage_path))
    if anchors['coordinate_frame_id'] != spec.site.anchor.coordinate_frame_id or not anchors['coordinates']:
        raise HTTPException(409, 'Anchor coordinate binding changed')
    reference = spec.generation_reference
    from backend.structure_contracts import SourceComponentReference
    deferred_source = isinstance(reference, SourceComponentReference)
    ligand = artifact(db, user_id, reference.structure) if reference and not deferred_source else None
    result = {'version': 4, 'id': str(dataset.id), 'name': dataset.name,
              'context_dataset_id': str(dataset.id), 'ph': prepared['preparation']['ph'], 'prepared_receptor_id': str(spec.prepared_receptor_id),
              'protein_dataset_id': str(protein.dataset_id), 'protein_file_id': str(protein.id), 'protein_pdb': protein.storage_path,
              'reference_ligand_file_id': str(ligand.id) if ligand else None,
              'reference_ligand_path': ligand.storage_path if ligand else None,
              'generation_reference': reference.model_dump(mode='json') if reference else None,
              'site': spec.site.model_dump(mode='json'), 'box': spec.site.box.model_dump(mode='json'),
              'anchor_coordinates': anchors['coordinates'], 'capabilities': deepcopy(spec.capabilities),
              'effective_receptor_sha256': spec.artifacts.effective_receptor.sha256}
    artifact(db, user_id, FileIdentity.model_validate(prepared['artifacts']['prepared_complex']))
    if deferred_source:
        from backend.services.prepared_receptors import _source_file
        from backend.structure_contracts import StructureSource
        original, raw = _source_file(db, user_id, StructureSource.model_validate(prepared['source']))
        report_row = artifact(db, user_id, FileIdentity.model_validate(prepared['artifacts']['report']))
        choices = read_json(Path(report_row.storage_path))['resolved_plan']['altloc_choices']
        result['reference_source'] = {'path': original.storage_path, 'source': prepared['source'], 'manifest': raw.model_dump(mode='json'), 'altloc_choices': choices}
    result['prepared_complex'] = prepared['artifacts']['prepared_complex']
    result['input_parameters'] = spec.input_parameters.model_dump(mode='json')
    result['ph'] = spec.input_parameters.ph
    result['model_inputs'] = {}
    for name, entry in (spec.compatibility or {}).get('models', {}).items():
        item = {'status': entry['status']}
        if entry.get('artifacts', {}).get('cache'):
            try:
                cache_row = artifact(db, user_id, FileIdentity.model_validate(entry['artifacts']['cache']))
                cache = read_json(Path(cache_row.storage_path))
            except (HTTPException, ValueError, OSError, EOFError):
                item.update(status='unchecked', error='Prepared model cache is unavailable; retry this model validation')
                result['capabilities']['engine_support'][name] = {'status': 'unchecked', 'reason': item['error'],
                    'error_info': describe_preparation_error('CONTEXT_CACHE_CHANGED: ' + item['error'])}
            else:
                item.update(manifest_path=cache_row.storage_path, manifest_sha256=cache_row.sha256)
                if cache.get('version') != CACHE_VERSION or cache.get('contract') != CONTRACT:
                    item['status'] = 'unchecked'
                    reason = 'Model input cache version changed; retry this model validation'
                    result['capabilities']['engine_support'][name] = {'status':'unchecked', 'reason':reason,
                        'error_info': describe_preparation_error('CONTEXT_CACHE_STALE: ' + reason)}
        result['model_inputs'][name] = item
    from genova_runtime.context_features import consume_context_inputs
    for name, item in result['model_inputs'].items():
        if name == 'tarpass' or item['status'] not in {'full', 'limited'}:
            continue
        try:
            consume_context_inputs({'structure_context':result}, name, dry_run=True)
        except (ValueError, OSError, KeyError):
            item['status'] = 'unchecked'
            result['capabilities']['engine_support'][name] = {'status':'unchecked',
                'reason':'Prepared input changed or is missing; retry this model validation'}
    from genova_runtime.structure_inputs import validate_context_snapshot
    try:
        validate_context_snapshot(result, protein.storage_path)
        if engine:
            from genova_runtime.structure_inputs import validate_engine_context
            validate_engine_context(result, engine)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return result
