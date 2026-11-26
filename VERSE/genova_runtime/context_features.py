from genova_runtime.artifact_json import read_json
import copy
import hashlib
import json
import math
import traceback
import time
from pathlib import Path

from genova_runtime.pdb2pqr_compat import file_sha256
from genova_runtime.preparation_errors import PreparationError, describe_preparation_error, residue_label

CONTRACT = 'context_features_v1'
CACHE_VERSION = 1
REQUIRED_FILES = {'surfgen': {'protein_pdb','surface_ply'}, 'delete': {'protein_pdb','reference_ligand','surface_ply'}, 'ecloudgen': {'protein_pdb','input_features'}, 'epso': {'reference_ligand'}}


def context_fingerprint(context, parameters):
    value = {key: context.get(key) for key in ('version', 'effective_receptor_sha256', 'site', 'generation_reference', 'prepared_complex')}
    value['parameters'] = parameters
    value['receptor_policy'] = context['capabilities']['receptor_policy']
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def load_shared_receptor(binding, data_root):
    # Finished generation binds these files; postprocessing does not rebuild its model features.
    root = Path(data_root).resolve()
    path = Path(binding['manifest_path']).resolve()
    if not path.is_relative_to(root) or not path.is_file() or file_sha256(path) != binding['manifest_sha256']:
        raise ValueError('SHARED_RECEPTOR_CHANGED: generation input cache is unavailable or changed')
    cache = read_json(path)
    if cache.get('version') != CACHE_VERSION or cache.get('contract') != CONTRACT or cache.get('status') not in {'full', 'limited'} or cache.get('engine') != binding['engine'] or cache.get('context_id') != binding['context_id'] or cache.get('input_fingerprint') != binding['input_fingerprint']:
        raise ValueError('SHARED_RECEPTOR_BINDING_MISMATCH: generation input cache binding changed')
    required = {'protein_pdb', 'model_receptor_map.json'}
    if not required <= cache.get('files', {}).keys():
        raise ValueError('SHARED_RECEPTOR_REQUIRED: validate a protein input when saving the Context')
    files = [cache['files'][name] for name in required]
    if binding.get('reference_ligand'):
        files.append(binding['reference_ligand'])
    for identity in files:
        target = Path(identity['path']).resolve()
        if not target.is_relative_to(root) or not target.is_file() or file_sha256(target) != identity['sha256']:
            raise ValueError('SHARED_RECEPTOR_CHANGED: a shared generation input changed')
    mapping = read_json(Path(cache['files']['model_receptor_map.json']['path']))
    if mapping['source_sha256'] != binding['effective_receptor_sha256'] or mapping['model_input_sha256'] != cache['files']['protein_pdb']['sha256']:
        raise ValueError('SHARED_RECEPTOR_BINDING_MISMATCH: receptor identity mapping changed')
    return cache


def select_model_inventory(source, inventory, context):
    from genova_runtime.automatic_preparation import diagnose_structure
    from genova_runtime.pdb2pqr_compat import AMINO_ACIDS
    from genova_runtime.structure_inputs import RESIDUE_ALIASES
    from genova_runtime.automatic_preparation import NUCLEIC
    standard = AMINO_ACIDS | RESIDUE_ALIASES.keys()
    unsupported = [a for c in inventory['components'] if c['selection_kind'] == 'chain_records'
        and not all(a['residue_name'] in NUCLEIC for a in c['atoms'])
        for a in c['atoms'] if a['residue_name'] not in standard]
    if unsupported:
        raise PreparationError('MODEL_RESIDUE_UNSUPPORTED', 'Protein residues are not supported by the model input contract',
            [residue_label(a) for a in unsupported])
    kept = [c for c in inventory['components'] if c['selection_kind'] == 'chain_records' and all(a['residue_name'] in standard for a in c['atoms'])]
    ids = {c['component_id'] for c in kept}
    if not kept:
        raise PreparationError('MODEL_PROTEIN_UNSUPPORTED', 'No complete supported protein chain in the selected structure')
    diagnosis = diagnose_structure(source, inventory)
    if any('symmetry_operations' in edge for edge in diagnosis['reliable_connections']):
        atoms = {a['atom_id']: a for c in inventory['components'] for a in c['atoms']}
        raise PreparationError('MODEL_ASSEMBLY_REQUIRED', 'Retained covalent symmetry partners require an explicit assembly',
            [residue_label(atoms[aid]) for edge in diagnosis['reliable_connections'] if 'symmetry_operations' in edge for aid in edge['atom_ids']])
    crossing = [e for e in diagnosis['reliable_connections'] if (e['component_ids'][0] in ids) != (e['component_ids'][1] in ids)]
    if crossing:
        atoms = {a['atom_id']: a for c in inventory['components'] for a in c['atoms']}
        raise PreparationError('MODEL_COVALENT_BOUNDARY', 'No verified restoration rule for the protein/environment boundary',
            [residue_label(atoms[aid]) for edge in crossing for aid in edge['atom_ids']])
    anchors = context['anchor_coordinates']
    omitted = []
    for component in inventory['components']:
        if component['component_id'] in ids:
            continue
        distance = min(math.dist(a['coordinates'], anchor) for a in component['atoms'] for anchor in anchors)
        omitted.append(dict(component_id=component['component_id'], residue_names=sorted({a['residue_name'] for a in component['atoms']}), source_atom_ids=[a['atom_id'] for a in component['atoms']], near_site=distance <= 8, distance_to_anchor_angstrom=distance, reason='Outside the verified standard-protein model input contract'))
    result = {**inventory, 'components': kept}
    result['declared_connections'] = [e for e in diagnosis['reliable_connections'] if set(e['component_ids']) <= ids]
    scope = dict(policy='standard_protein_v1', used_component_ids=sorted(ids), ignored_components=omitted, condition_missing=False)
    return result, scope


def prepare_context_inputs(payload, engine, dry_run=False):
    from genova_runtime.model_initialization import initialize_model_task
    from genova_runtime.automatic_preparation import PreparationFailure
    output = Path(payload['output_dir'])
    context = payload['structure_context']
    parameters = payload['input_parameters']
    fingerprint = context_fingerprint(context, parameters)
    if dry_run:
        return dict(engine=engine, operation='prepare_context_inputs', dry_run=True, input_fingerprint=fingerprint)
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / 'compatibility_report.json'
    started = time.monotonic()
    report = dict(timings={}, version=1, engine=engine, context_id=payload['context_id'], input_fingerprint=fingerprint, status='running', parameters=parameters, stage='initializing_inputs')
    def save():
        temporary = report_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, allow_nan=False))
        temporary.replace(report_path)
    save()
    try:
        adapted = initialize_model_task({**payload, 'ph': parameters['ph'], 'seed': parameters['condition_seed']}, engine, preparation=True)
        report['timings']['initialization_s'] = round(time.monotonic() - started, 6)
        feature_started = time.monotonic()
        report['stage'] = 'building_features'
        save()
        if engine == 'surfgen':
            from genova_runtime.entry_surfgen import prepare_surface
            features = prepare_surface(adapted)
        elif engine == 'delete':
            from genova_runtime.entry_delete import _prepare_surface
            surface = _prepare_surface(adapted)
            features = {'surface_ply': str(surface)}
        elif engine == 'ecloudgen':
            import sys
            from genova_runtime.utils import run_subprocess
            target = output / 'input_features.npz'
            location = ['--reference', adapted['reference_ligand']] if adapted.get('reference_ligand') else ['--center', *map(str, context['box']['center'])]
            run_subprocess([sys.executable, '-m', 'genova_runtime.ecloud_inputs', '--protein', adapted['protein_pdb'], *location, '--output', str(target), '--seed', str(parameters['condition_seed'])], output, False, timeout=7200, log_path=output / 'feature_builder.log')
            features = {'input_features': str(target)}
        elif engine == 'epso':
            features = {}
        else:
            raise ValueError('Unknown context preparation engine')
        report['timings']['features_s'] = round(time.monotonic() - feature_started, 6)
        initialized = json.loads((output / 'model_initialization.json').read_text())
        report['timings'].update(initialized.get('timings', {}))
        scope = initialized.get('model_scope', {})
        status = 'full'
        files = {name: value for name, value in {'protein_pdb': adapted.get('protein_pdb') if engine != 'epso' else None, 'reference_ligand': adapted.get('reference_ligand'), **features}.items() if value}
        files = {name: dict(path=value, sha256=file_sha256(value)) for name, value in files.items()}
        for name in ('model_receptor_map.json',):
            if (output / name).is_file():
                files[name] = dict(path=str(output / name), sha256=file_sha256(output / name))
        import os
        from genova_runtime.artifact_json import compress_json
        shared = output.parent / 'shared'
        shared.mkdir(exist_ok=True)
        for name in ('protein_pdb', 'reference_ligand', 'model_receptor_map.json'):
            if name not in files:
                continue
            source = Path(files[name]['path'])
            stored = compress_json(source) if name.endswith('.json') else source
            checksum = file_sha256(stored)
            target = shared / (checksum + ''.join(stored.suffixes))
            try:
                os.link(stored, target)
            except FileExistsError:
                if file_sha256(target) != checksum:
                    raise ValueError('Shared model artifact hash mismatch')
            files[name] = dict(path=str(target), sha256=checksum)
        if 'protein_pdb' in files:
            initialized['model_receptor']['path'] = files['protein_pdb']['path']
        if 'reference_ligand' in files:
            initialized['resolved_reference']['path'] = files['reference_ligand']['path']
        (output / 'model_initialization.json').write_text(json.dumps(initialized, allow_nan=False))
        if not REQUIRED_FILES[engine] <= files.keys():
            raise PreparationError('REQUIRED_MODEL_INPUTS_MISSING', 'Required prepared model inputs are missing', REQUIRED_FILES[engine] - files.keys())
        cache = dict(version=CACHE_VERSION, contract=CONTRACT, engine=engine, context_id=payload['context_id'], input_fingerprint=fingerprint, parameters=parameters, status=status, files=files, model_scope=scope, reference_smiles=adapted.get('reference_smiles'), reference_usage=initialized.get('reference_usage'))
        cache_path = output / 'model_input_cache.json'
        cache_path.write_text(json.dumps(cache, allow_nan=False))
        report['timings']['total_s'] = round(time.monotonic() - started, 6)
        report.update(status=status, model_scope=scope, feature_validation='passed')
        save()
        return dict(engine=engine, context_id=payload['context_id'], input_fingerprint=fingerprint, cache_manifest=str(cache_path), cache_sha256=file_sha256(cache_path), compatibility_report=str(report_path), report_sha256=file_sha256(report_path))
    except Exception as error:
        report['timings']['total_s'] = round(time.monotonic() - started, 6)
        initialized_path = output / 'model_initialization.json'
        initialized = read_json(initialized_path) if initialized_path.is_file() else {}
        info = initialized.get('error_info') or describe_preparation_error(error, report['stage'])
        report.update(status='incompatible' if info['error_category'] == 'input' else 'failed', error=str(error), error_info=info, traceback=traceback.format_exc())
        save()
        raise PreparationFailure(str(error), dict(engine=engine, context_id=payload['context_id'], input_fingerprint=fingerprint, error_info=info, compatibility_report=str(report_path), report_sha256=file_sha256(report_path))) from error


def consume_context_inputs(payload, engine, dry_run=False):
    context = payload['structure_context']
    entry = (context.get('model_inputs') or {}).get(engine)
    if not entry or entry.get('status') not in {'full', 'limited'}:
        raise ValueError(f'CONTEXT_INPUTS_NOT_READY: validate {engine} inputs by saving the Context')
    path = Path(entry['manifest_path'])
    if not path.is_file() or file_sha256(path) != entry['manifest_sha256']:
        raise ValueError('CONTEXT_CACHE_CHANGED: revalidate the Context')
    cache = read_json(path)
    parameters = context['input_parameters']
    if cache.get('version') != CACHE_VERSION or cache.get('status') not in {'full','limited'} or not REQUIRED_FILES[engine] <= cache.get('files',{}).keys() or cache['engine'] != engine or cache['context_id'] != context['context_dataset_id'] or cache['contract'] != CONTRACT or cache['input_fingerprint'] != context_fingerprint(context, parameters):
        raise ValueError('CONTEXT_CACHE_STALE: context or feature parameters changed; revalidate the Context')
    if engine in {'surfgen', 'delete'} and float(payload.get('ph', parameters['ph'])) != parameters['ph']:
        raise ValueError('CONTEXT_CACHE_STALE: surface pH changed; revalidate the Context')
    reference_override = payload.get('seed_reference')
    if engine != 'epso' and reference_override and reference_override['structure']['sha256'] != ((context.get('generation_reference') or {}).get('structure') or {}).get('sha256'):
        raise ValueError('CONTEXT_CACHE_STALE: seed/reference changed; revalidate the Context')
    for item in cache['files'].values():
        target = Path(item['path'])
        if not target.is_file() or file_sha256(target) != item['sha256']:
            raise ValueError('CONTEXT_CACHE_CHANGED: a prepared input changed; revalidate the Context')
    result = copy.deepcopy(payload)
    if engine == 'epso' and reference_override:
        seed_path = Path(result.get('reference_ligand') or '')
        if not seed_path.is_file() or file_sha256(seed_path) != reference_override['structure']['sha256']:
            raise ValueError('CONTEXT_CACHE_CHANGED: EPSO seed artifact changed')
    for name in ('protein_pdb', 'reference_ligand', 'surface_ply', 'input_features'):
        if name in cache['files'] and not (name == 'reference_ligand' and engine == 'epso' and reference_override):
            result[name] = cache['files'][name]['path']
    result.update(model_inputs_initialized=True, prepared_input_cache=cache,
                  reference_smiles=payload.get('reference_smiles') if engine == 'epso' and reference_override else cache.get('reference_smiles'))
    if engine == 'delete' and payload.get('edit'):
        result['fragment_sdf'] = str(Path(payload['output_dir']) / 'fragment.sdf')
        from genova_runtime.delete_edits import prepare_fragment
        if not dry_run:
            output = Path(payload['output_dir']); output.mkdir(parents=True, exist_ok=True)
            fragment = output / 'fragment.sdf'
            metadata = prepare_fragment(result['reference_ligand'], payload['edit'], fragment)
            result.update(fragment_sdf=str(fragment), anchor_atom_indices=metadata['anchor_atom_indices'] if metadata['edit_mode'] == 'derivation_site' else [])
    return result


def generation_context_report(payload, result):
    cache = payload.get('prepared_input_cache')
    if not cache:
        return result
    output = Path(payload['output_dir'])
    report = dict(version=1, input_fingerprint=cache['input_fingerprint'], compatibility=cache['status'], model_scope=cache['model_scope'], geometry=dict(status='not_evaluated', reason='Generation has no source-frame 3D poses; check geometry during postprocessing'))
    if result.get('generated_sdf'):
        from rdkit import Chem
        from genova_runtime.structure_inventory import source_inventory
        from genova_runtime.structure_inputs import reference_contact_diagnostics
        context = payload['structure_context']
        faithful = source_inventory(context['protein_pdb'],dict(sha256=context['effective_receptor_sha256'],model_id='1'))
        atoms = [a for c in faithful['components'] for a in c['atoms']]
        records = []
        for index, molecule in enumerate(Chem.SDMolSupplier(result['generated_sdf'], removeHs=False)):
            if molecule is None or not molecule.GetNumConformers() or not molecule.GetConformer().Is3D():
                records.append(dict(index=index,status='unavailable'))
                continue
            contacts = reference_contact_diagnostics(molecule,atoms)
            clashes = [row for row in contacts if row['severity']=='error']
            records.append(dict(index=index,status='severe_overlap' if clashes else 'no_severe_overlap',contacts=contacts,severe_overlap_count=len(clashes)))
        report['geometry'] = dict(status='evaluated', criterion='reference_contact_diagnostics_v1; conservative heavy-atom overlap, not docking validation', records=records)
    path = output/'generation_context_report.json'
    path.write_text(json.dumps(report))
    return {**result, 'context_preparation_report':str(path), 'context_compatibility':cache['status'], 'condition_missing':cache['model_scope'].get('condition_missing',False), 'conditioning_limits':cache['model_scope'].get('ignored_components',[])}


if __name__ == '__main__':
    import os
    os.nice(10)
    import sys
    from genova_runtime.automatic_preparation import PreparationFailure
    destination = Path(sys.argv[1])
    request = json.load(sys.stdin)
    try:
        value = prepare_context_inputs(request, request['compatibility_engine'])
    except PreparationFailure as error:
        destination.write_text(json.dumps(dict(status='failed',error=str(error),result=error.result)))
        raise
    else:
        destination.write_text(json.dumps(dict(status='succeeded',result=value)))
