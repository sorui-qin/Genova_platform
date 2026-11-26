from genova_runtime.artifact_json import read_json
import json
import shutil
import uuid
from pathlib import Path

from fastapi import HTTPException

from backend.config import settings
from backend.models import Dataset, DatasetFile
from backend.structure_contracts import FileIdentity, ModelInputParameters, PreparedArtifacts, SourceComponentReference
from backend.utils import utcnow
from genova_runtime.structure_inventory import source_inventory
from genova_runtime.pdb2pqr_compat import file_sha256


def create_auto_site(request, prepared, db, user_id):
    from backend.services.binding_sites import artifact
    from backend.services.protein_contexts import _serialize_context, _context_or_404
    identities = PreparedArtifacts.model_validate(prepared['artifacts'])
    if prepared.get('capabilities', {}).get('receptor_policy') != 'protein_metals_v1' or identities.context_receptor is None or identities.context_receptor_map is None:
        raise HTTPException(409, 'CONTEXT_RECEPTOR_UPDATE_REQUIRED: build the protein/metal receptor before saving the Context')
    if request.prepared_artifact_sha256 != identities.prepared_complex.sha256:
        raise HTTPException(409, 'Prepared receptor version changed')
    parameters = request.input_parameters or ModelInputParameters()
    feature_ph = prepared['preparation']['ph']
    if feature_ph is None:
        feature_ph = ModelInputParameters().ph
    if 'ph' in parameters.model_fields_set and parameters.ph != feature_ph:
        raise HTTPException(422, 'Model feature pH must match the prepared receptor pH; preserved input uses pH 7.4')
    parameters = parameters.model_copy(update={'ph': feature_ph})
    rows = {key: artifact(db, user_id, getattr(identities, key)) for key in ('prepared_complex', 'component_manifest', 'report', 'context_receptor', 'context_receptor_map')}
    manifest = read_json(Path(rows['component_manifest'].storage_path))
    raw = prepared['component_manifest']
    choices = read_json(Path(rows['report'].storage_path))['resolved_plan']['altloc_choices']
    frame = manifest['coordinate_frame_id']
    receiver_map = read_json(Path(rows['context_receptor_map'].storage_path))
    if receiver_map['source_sha256'] != identities.prepared_complex.sha256 or receiver_map['output_sha256'] != identities.context_receptor.sha256 or receiver_map['receptor_policy'] != 'protein_metals_v1':
        raise HTTPException(409, 'Context receptor mapping binding mismatch')
    receiver_manifest = source_inventory(Path(rows['context_receptor'].storage_path), {**identities.context_receptor.model_dump(mode='json'), 'model_id':'1'})
    anchor = request.site.anchor
    if anchor.coordinate_frame_id != frame:
        raise HTTPException(422, 'Anchor coordinate frame mismatch')
    if anchor.kind == 'source_components':
        if anchor.source.model_dump(mode='json') != raw['source']:
            raise HTTPException(422, 'Anchor source identity mismatch')
        components = {c['component_id']: c for c in raw['components']}
        if not set(anchor.component_ids) <= components.keys():
            raise HTTPException(422, 'Unknown source component')
        coords = [a['coordinates'] for cid in anchor.component_ids for a in components[cid]['atoms'] if a['element'] not in {'H', 'D'}
            and (not a['altloc'] or not choices.get(a['residue_id']) or choices[a['residue_id']] == a['altloc'])]
    elif anchor.kind == 'prepared_residues':
        known = {a['residue_id'] for c in receiver_manifest['components'] for a in c['atoms']}
        if not set(anchor.residue_ids) <= known:
            raise HTTPException(422, 'Unknown prepared residue')
        coords = [a['coordinates'] for c in receiver_manifest['components'] for a in c['atoms'] if a['residue_id'] in anchor.residue_ids and a['element'] not in {'H', 'D'}]
    else:
        coords = [list(point) for point in anchor.coordinates]
    known = {c['component_id'] for c in manifest['components']}
    excluded = set(request.site.exclude_from_receptor)
    if not excluded <= known or known <= excluded:
        raise HTTPException(422, 'Unknown selection or empty receptor')
    atom_mapping = {e['source_atom_id']: e['output_atom_id'] for e in receiver_map['entries'] if e['source_atom_id']}
    excluded_atoms = {atom_mapping[a['atom_id']] for c in manifest['components'] if c['component_id'] in excluded for a in c['atoms'] if atom_mapping.get(a['atom_id'])}
    if excluded_atoms:
        raise HTTPException(422, 'Change receptor chains or components in Protein Preparation before saving the Context')
    forced = {c['component_id'] for c in manifest['components'] if not any(atom_mapping.get(a['atom_id']) for a in c['atoms'])}
    excluded |= forced
    from genova_runtime.automatic_preparation import native_connections
    unresolved = native_connections(Path(rows['context_receptor'].storage_path), receiver_manifest)[1]
    if unresolved:
        raise HTTPException(409, 'Unresolved receptor connections require verified preparation')
    from genova_runtime.preparation_policy import context_receptor_selection
    try:
        receiver_atoms, _ = context_receptor_selection(receiver_manifest)
        if receiver_atoms != {a['atom_id'] for c in receiver_manifest['components'] for a in c['atoms']}:
            raise ValueError('Context receptor contains forbidden components; update its preparation')
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not coords:
        raise HTTPException(422, 'Binding site requires anchor coordinates')
    if request.derived_from_context_id:
        _context_or_404(db, request.derived_from_context_id, user_id)
    reference = request.generation_reference
    if reference and reference.coordinate_frame_id != frame:
        raise HTTPException(422, 'Generation reference coordinate frame mismatch')
    if isinstance(reference, SourceComponentReference):
        if not any(c['component_id'] == reference.source_component_id for c in raw['components']):
            raise HTTPException(422, 'Unknown generation reference source component')
    elif reference:
        reference_row = artifact(db, user_id, reference.structure)
        if Path(reference_row.original_filename).suffix.lower() not in {'.sdf', '.mol', '.mol2'}:
            raise HTTPException(422, 'Generation reference requires SDF, MOL or MOL2')
        if reference_row.size_bytes > 10 * 1024 * 1024:
            raise HTTPException(413, 'Generation reference exceeds its size limit')
        if reference.chemical_mapping:
            artifact(db, user_id, reference.chemical_mapping)
    from sqlalchemy import select, text
    import hashlib
    scientific = request.model_dump(mode='json', exclude={'name', 'derived_from_context_id'})
    scientific['site']['exclude_from_receptor'] = sorted(excluded)
    scientific['input_parameters'] = parameters.model_dump(mode='json')
    identity = hashlib.sha256(json.dumps(scientific, sort_keys=True).encode()).hexdigest()
    lock = int(hashlib.sha256((str(user_id) + identity).encode()).hexdigest()[:16], 16)
    db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': lock if lock < 2**63 else lock - 2**64})
    candidates = db.scalars(select(Dataset).where(Dataset.owner_user_id == user_id,
        Dataset.kind == 'protein_context', Dataset.status == 'ready',
        Dataset.meta['prepared_receptor_id'].as_string() == str(request.prepared_receptor_id)).order_by(Dataset.created_at.desc()))
    for existing in candidates:
        saved = {key: existing.meta.get(key) for key in scientific}
        if saved != scientific:
            continue
        db.refresh(existing, with_for_update=True)
        from backend.services.binding_sites import resolve_v4_context
        try:
            context = resolve_v4_context(existing, db, user_id)
        except (HTTPException, ValueError, OSError):
            continue
        from backend.services.context_features import enqueue_context_validation
        enqueue_context_validation(existing, db, user_id, context=context)
        existing.name, existing.updated_at = request.name, utcnow()
        return _serialize_context(existing, db)
    context_id = uuid.uuid4()
    directory = settings.data_root / 'datasets' / str(context_id)
    directory.mkdir(parents=True, exist_ok=True)
    files = []
    def register(path, role):
        fid = uuid.uuid4()
        target = path.with_name(f'{fid}_{path.name}')
        path.replace(target)
        identity = dict(dataset_id=str(context_id), file_id=str(fid), sha256=file_sha256(target))
        files.append(DatasetFile(id=fid, dataset_id=context_id, file_role=role, storage_path=str(target),
            original_filename=path.name, sha256=identity['sha256'], size_bytes=target.stat().st_size,
            content_type='chemical/x-mmcif' if target.suffix == '.cif' else 'application/json'))
        return identity
    try:
        receptor_id = identities.context_receptor.model_dump(mode='json')
        anchors = directory / 'anchor_coordinates.json'
        anchors.write_text(json.dumps(dict(version=1, coordinate_frame_id=frame, coordinates=coords)))
        anchor_id = register(anchors, 'anchor_coordinates')
        capabilities = {**prepared['capabilities'], 'effective_receptor_sha256': receptor_id['sha256'],
            'input_preparation': 'context_features_v1', 'engine_input': 'context_preparation', 'engine_support': {engine: {'status': 'pending' if engine != 'tarpass' else 'unchecked', 'reason': 'Feature construction runs after Context save'} for engine in ('surfgen', 'delete', 'ecloudgen', 'epso', 'tarpass')}}
        capabilities['receptor_exclusions'] = [{k: row[k] for k in ('component_id','residue_id','residue_name','role')} for row in receiver_map['decisions'] if row['action'] == 'excluded']
        capabilities['restored_residue_ids'] = receiver_map['restored_residue_ids']
        meta = {**request.model_dump(mode='json', exclude={'name'}),
            'artifacts': dict(effective_receptor=receptor_id, anchor_coordinates=anchor_id), 'capabilities': capabilities}
        meta['site']['exclude_from_receptor'] = sorted(excluded)
        meta['input_parameters'] = parameters.model_dump(mode='json')
        now = utcnow()
        dataset = Dataset(id=context_id, owner_user_id=user_id, name=request.name, kind='protein_context', status='ready', meta=meta, created_at=now, updated_at=now)
        db.add(dataset)
        db.add_all(files)
        db.flush()
        from backend.services.context_features import enqueue_context_validation
        enqueue_context_validation(dataset, db, user_id)
        return _serialize_context(dataset, db)
    except BaseException:
        shutil.rmtree(directory)
        raise
