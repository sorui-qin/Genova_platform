from genova_runtime.artifact_json import read_json
import copy
import json
import math
import os
import time
from pathlib import Path

from genova_runtime.pdb2pqr_compat import file_sha256
from genova_runtime.structure_inventory import source_inventory
from genova_runtime.preparation_errors import PreparationError, describe_preparation_error, residue_label


def update_model_stage(payload, stage):
    context = payload.get('structure_context') or {}
    if (context.get('capabilities') or {}).get('preparation_strategy') != 'generation_auto_v1':
        return
    if payload.get('prepared_input_cache'):
        return
    path = Path(payload['output_dir']) / 'model_initialization.json'
    report = read_json(path)
    if report['effective_receptor_sha256'] != context['effective_receptor_sha256']:
        raise ValueError('Model initialization report binding mismatch')
    report['stage'] = stage
    if stage == 'completed':
        report['status'] = 'completed'
        report['feature_status'] = 'passed' if report['engine'] in {'surfgen', 'delete', 'ecloudgen'} else 'not_required'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(report))
    temporary.replace(path)


def initialize_model_task(payload, engine, *, dry_run=False, preparation=False):
    from genova_runtime.structure_inputs import materialize_engine_receptor, RESIDUE_ALIASES
    context = payload.get('structure_context') or {}
    from genova_runtime.structure_inputs import validate_context_snapshot
    validate_context_snapshot(context, context['protein_pdb'])
    if not preparation and engine != 'tarpass' and not (engine == 'epso' and payload.get('seed_reference')):
        from genova_runtime.context_features import consume_context_inputs
        return consume_context_inputs(payload, engine, dry_run=dry_run)
    payload = copy.deepcopy(payload)
    context = payload['structure_context']
    output = Path(payload['output_dir'])
    shared_cache = None
    if engine == 'tarpass':
        from genova_runtime.context_features import load_shared_receptor
        if not payload.get('postprocessing_inputs'):
            raise ValueError('SHARED_RECEPTOR_REQUIRED: postprocessing must reuse validated generation inputs')
        shared_cache = load_shared_receptor(payload['postprocessing_inputs'], os.environ.get('DATA_ROOT', '/app/data'))
        payload['protein_pdb'] = shared_cache['files']['protein_pdb']['path']
        payload['postprocessing_input_cache'] = shared_cache
        reference_file = payload['postprocessing_inputs'].get('reference_ligand')
        payload['reference_ligand'] = reference_file['path'] if reference_file else None
    if dry_run:
        if shared_cache is not None:
            return payload
        if engine != 'epso':
            payload['protein_pdb'] = str(output / 'model_receptor.pdb')
        if context.get('generation_reference') or payload.get('seed_reference'):
            payload['reference_ligand'] = str(output / 'model_reference.sdf')
        payload['model_input_plan'] = {'strategy': 'generation_auto_v1', 'chemical_validation': 'deferred_to_execution'}
        return payload
    output.mkdir(parents=True, exist_ok=True)
    report = dict(version=1, engine=engine, builder_version='generation_auto_v1', status='running', stage='initializing_inputs',
        effective_receptor_sha256=context['effective_receptor_sha256'], reference=context.get('generation_reference'),
        component_feature_coverage='unknown', expected_scope='ligand_only' if engine == 'epso' else 'method_specific_features')
    path = output / 'model_initialization.json'
    def save():
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, allow_nan=False))
        temporary.replace(path)
    save()
    try:
        source = Path(context['protein_pdb'])
        receptor_started = time.monotonic()
        inventory = source_inventory(source, {'sha256': context['effective_receptor_sha256'], 'model_id': '1'}) if engine not in {'epso', 'tarpass'} else None
        if engine != 'epso':
            if engine == 'tarpass':
                from genova_runtime.structure_identity import METAL_ELEMENTS
                model = Path(payload['protein_pdb'])
                inventory = source_inventory(model, {'sha256': shared_cache['files']['protein_pdb']['sha256'], 'model_id': '1'})
                if any(a['element'] in METAL_ELEMENTS for c in inventory['components'] for a in c['atoms']):
                    raise ValueError('SHARED_RECEPTOR_CONTAINS_METALS: revalidate generation inputs by saving the Context')
                report['model_scope'] = shared_cache['model_scope']
                report['shared_input_manifest'] = payload['postprocessing_inputs']['manifest_path']
            else:
                if preparation and engine in {'surfgen', 'delete', 'ecloudgen'}:
                    from genova_runtime.context_features import select_model_inventory
                    inventory, report['model_scope'] = select_model_inventory(source, inventory, context)
                model = materialize_engine_receptor(source, context, output, inventory=inventory if preparation else None)
                payload['protein_pdb'] = str(model)
            report['model_receptor'] = dict(path=str(model), faithful_structure=str(source))
            if engine == 'tarpass' and payload.get('key_interactions'):
                mapping_file = Path(shared_cache['files']['model_receptor_map.json']['path'])
                rows = read_json(mapping_file)['atoms']
                for rule in payload['key_interactions']:
                    for residue in rule['residues']:
                        matches = {(row['tool_chain_id'], row['tool_residue_number']) for row in rows
                            if row['author_chain_id'] == residue['chain_id'] and row['author_residue_number'] == residue['residue_number']
                            and row['insertion_code'] == residue.get('insertion_code', '')}
                        if len(matches) != 1:
                            raise ValueError('Interaction residue has no unique source-to-tool mapping')
                        residue['chain_id'], residue['residue_number'] = next(iter(matches))
                        residue['insertion_code'] = ''
                        residue['residue_name'] = RESIDUE_ALIASES.get(residue['residue_name'], residue['residue_name'])

        report['timings'] = {'receptor_s': round(time.monotonic() - receptor_started, 6)}
        reference_started = time.monotonic()
        reference = payload['postprocessing_inputs'].get('reference_ligand') if engine == 'tarpass' else payload.get('seed_reference') or context.get('generation_reference')
        if engine == 'tarpass' and shared_cache.get('reference_usage') == 'site_geometry' and (context.get('generation_reference') or {}).get('kind') == 'source_component':
            reference = context['generation_reference']
        report['stage'] = 'validating_reference'
        save()
        if reference:
            from rdkit import Chem
            from genova_runtime.entry_protein_preparation import _load_ligand, _validate_ligand_box
            geometry_reference = engine in {'surfgen', 'ecloudgen'}
            report['reference_usage'] = 'site_geometry' if geometry_reference else 'molecular_structure'
            if engine == 'tarpass' and reference.get('kind') != 'source_component':
                original = Path(reference['path'])
                molecule = _load_ligand(original)
            elif reference.get('kind') == 'source_component':
                original = context['reference_source']
                raw = source_inventory(Path(original['path']), original['source'])
                component = next(c for c in raw['components'] if c['component_id'] == reference['source_component_id'])
                choices = original['altloc_choices']
                component = {**component, 'atoms': [a for a in component['atoms'] if not a['altloc'] or choices.get(a['residue_id']) == a['altloc']]}
                if geometry_reference:
                    atoms = [a for a in component['atoms'] if a['element'] not in {'H', 'D'}]
                    molecule = Chem.RWMol()
                    conformer = Chem.Conformer(len(atoms))
                    conformer.Set3D(True)
                    for i, atom in enumerate(atoms):
                        element = Chem.Atom(atom['element'].title())
                        element.SetNoImplicit(True)
                        molecule.AddAtom(element)
                        conformer.SetAtomPosition(i, atom['coordinates'])
                    molecule.AddConformer(conformer)
                    molecule = molecule.GetMol()
                else:
                    from genova_runtime.reference_chemistry import source_ligand_from_ccd
                    molecule, template = source_ligand_from_ccd(component, [], Path(os.environ.get('DATA_ROOT', '/app/data')) / 'chemical_components')
                    report['reference_template'] = template
            else:
                original = Path(payload.get('reference_ligand') or context['reference_ligand_path'])
                if file_sha256(original) != reference['structure']['sha256']:
                    raise PreparationError('CONTEXT_CACHE_CHANGED', 'Generation reference integrity mismatch', [original.name])
                if engine == 'epso':
                    molecules = list(Chem.SDMolSupplier(str(original), removeHs=False))
                    if len(molecules) != 1:
                        raise PreparationError('REFERENCE_MOLECULE_COUNT', 'EPSO requires one valid SDF seed', [original.name])
                    if molecules[0] is None:
                        raise PreparationError('REFERENCE_CHEMISTRY_INVALID', 'EPSO requires one valid SDF seed', [original.name])
                    molecule = molecules[0]
                else:
                    molecule = _load_ligand(original, sanitize=not geometry_reference)
                if original.suffix.lower() == '.sdf' and len(list(Chem.SDMolSupplier(str(original), removeHs=False, sanitize=not geometry_reference))) != 1:
                    raise PreparationError('REFERENCE_MOLECULE_COUNT', 'Generation reference requires exactly one SDF record', [original.name])
            if engine != 'epso' and (not molecule.GetNumConformers() or not molecule.GetConformer().Is3D()):
                raise PreparationError('REFERENCE_COORDINATES_REQUIRED', 'Generation reference requires one connected molecule with 3D coordinates')
            if geometry_reference:
                molecule = Chem.RemoveAllHs(molecule, sanitize=False)
            if not geometry_reference and len(Chem.GetMolFrags(molecule)) != 1:
                raise PreparationError('REFERENCE_DISCONNECTED', 'Generation reference requires one connected molecule with 3D coordinates')
            if engine != 'epso' and any(not math.isfinite(value) for point in molecule.GetConformer().GetPositions() for value in point):
                raise PreparationError('REFERENCE_COORDINATES_REQUIRED', 'Generation reference contains non-finite coordinates')
            from genova_runtime.structure_identity import METAL_ELEMENTS
            heavy = [a for a in molecule.GetAtoms() if a.GetAtomicNum() > 1]
            if not heavy or len(heavy) == 1 and heavy[0].GetSymbol().upper() in METAL_ELEMENTS:
                raise PreparationError('REFERENCE_METAL_ION', 'A metal ion can locate a site but cannot be the generation reference ligand')
            if engine != 'epso':
                if engine == 'tarpass':
                    _validate_ligand_box(molecule, context['box'])
                from genova_runtime.structure_inputs import reference_contact_diagnostics
                report['reference_contacts'] = reference_contact_diagnostics(molecule, [a for c in inventory['components'] for a in c['atoms']])
                if any(row['severity'] == 'error' for row in report['reference_contacts']):
                    atoms = {a['atom_id']: a for c in inventory['components'] for a in c['atoms']}
                    raise PreparationError('REFERENCE_HEAVY_CLASH', 'Reference and retained receptor overlap; inspect the model initialization report',
                        [residue_label(atoms[row['receptor_atom_id']]) for row in report['reference_contacts'] if row['severity'] == 'error'])
            if engine == 'tarpass' and reference.get('kind') != 'source_component':
                target = original
            else:
                target = output / 'model_reference.sdf'
                with Chem.SDWriter(str(target)) as writer:
                    writer.write(molecule)
            payload['reference_ligand'] = str(target)
            context['reference_ligand_path'] = str(target)
            report['resolved_reference'] = dict(path=str(target), source=reference)
        elif engine in {'delete', 'epso'}:
            raise PreparationError('REFERENCE_REQUIRED', f'{engine} requires a generation reference')
        if not preparation and engine == 'delete' and payload.get('edit'):
            from genova_runtime.delete_edits import prepare_fragment
            fragment = output / 'fragment.sdf'
            metadata = prepare_fragment(payload['reference_ligand'], payload['edit'], fragment)
            payload.update(fragment_sdf=str(fragment), anchor_atom_indices=metadata['anchor_atom_indices'] if metadata['edit_mode'] == 'derivation_site' else [])
            report['edit_metadata'] = metadata
        if engine == 'epso':
            from genova_runtime.epso_objectives import read_seed
            payload['reference_smiles'] = read_seed(payload['reference_ligand'])
        report['timings']['reference_s'] = round(time.monotonic() - reference_started, 6)
        report['status'] = 'inputs_materialized'
        report['stage'] = 'inputs_ready'
        report['feature_status'] = 'pending_actual_builder'
        save()
        payload['model_inputs_initialized'] = True
        return payload
    except Exception as exc:
        import traceback
        report.update(status='failed', error=str(exc), error_info=describe_preparation_error(exc, report['stage']), traceback=traceback.format_exc())
        save()
        raise
