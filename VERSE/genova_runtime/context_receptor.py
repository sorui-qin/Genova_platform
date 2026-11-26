import copy
import importlib.metadata
import json

from genova_runtime.pdb2pqr_compat import AMINO_ACIDS, file_sha256
from genova_runtime.preparation_policy import RECEPTOR_POLICY, context_receptor_selection, receptor_removal_plan
from genova_runtime.structure_inventory import source_inventory, tool_structure, write_cif, restore_tool_identities, validate_integrity
from genova_runtime.preparation_errors import PreparationError


def build_context_receptor(source, manifest, output, options, *, restore_residue_ids=()):
    from genova_runtime.automatic_preparation import diagnose_structure, process_standard
    selected, decisions = context_receptor_selection(manifest)
    diagnosis = diagnose_structure(source, manifest)
    atoms = {a['atom_id']: a for c in manifest['components'] for a in c['atoms']}
    crossings, preserved_connections = receptor_removal_plan(manifest, selected, diagnosis)
    # Unsupported chemistry stays connected, including multi-residue cofactors/modifications.
    pending = {aid for edge in preserved_connections for aid in edge['atom_ids']}
    while pending - selected:
        attached_residues = {atoms[aid]['residue_id'] for aid in pending}
        selected.update(aid for aid, a in atoms.items() if a['residue_id'] in attached_residues)
        pending = {aid for edge in diagnosis['reliable_connections'] if any(a in selected for a in edge['atom_ids']) for aid in edge['atom_ids']}
    crossings = [e for e in crossings if not all(a in selected for a in e['atom_ids'])]
    for decision in decisions:
        if decision['action'] == 'excluded' and set(decision['atom_ids']) <= selected:
            decision.update(action='retained', reason='No verified covalent restoration template; original modification and connections preserved')
    if diagnosis['unresolved_connections']:
        raise PreparationError('CONTEXT_CONNECTION_UNRESOLVED', 'Cannot verify receptor removal boundaries',
            [row['connection_id'] for row in diagnosis['unresolved_connections']])
    restore = set(restore_residue_ids) | {atoms[aid]['residue_id'] for edge in crossings for aid in edge['atom_ids'] if aid in selected}
    restore_labels = ', '.join(sorted({f"{a['author_chain_id']}:{a['residue_name']}{a['author_residue_number']}{a['insertion_code']}" for a in atoms.values() if a['residue_id'] in restore}))
    if any(a['residue_name'] not in AMINO_ACIDS for a in atoms.values() if a['residue_id'] in restore):
        raise PreparationError('COVALENT_RESTORATION_UNSUPPORTED', restore_labels, restore_labels.split(', '))
    if restore and options['protonation_policy'] != 'recompute':
        raise PreparationError('COVALENT_RESTORATION_REQUIRES_PROTONATION', restore_labels, restore_labels.split(', '))
    if any(all(a in selected for a in e['atom_ids']) and any(atoms[a]['residue_id'] in restore for a in e['atom_ids']) for e in diagnosis['coordination_candidates']):
        raise PreparationError('COVALENT_RESTORATION_METAL_ENVIRONMENT_UNSUPPORTED', restore_labels, restore_labels.split(', '))
    projected = copy.deepcopy(manifest)
    projected['components'] = [{**c, 'atoms': [a for a in c['atoms'] if a['atom_id'] in selected]} for c in projected['components']]
    projected['components'] = [c for c in projected['components'] if c['atoms']]
    projected['declared_connections'] = [e for e in diagnosis['reliable_connections'] if all(a in selected for a in e['atom_ids'])]
    projected['declared_connections'] += [dict(e, evidence='CIF:metalc') for e in diagnosis['coordination_candidates']
        if e['evidence'] != 'metal_donor_geometry' and all(a in selected for a in e['atom_ids'])]
    projected['external_coordination_connections'] = [e for e in manifest.get('external_coordination_connections', []) if all(a in selected for a in e['atom_ids'])]
    baseline = copy.deepcopy(projected)
    output.mkdir(parents=True, exist_ok=True)
    operations = {}
    parameterization = None
    if restore:
        tool = output / 'restoration_input.pdb'
        for component in projected['components']:
            order = {rid: i for i, rid in enumerate(dict.fromkeys(a['residue_id'] for a in component['atoms']))}
            component['atoms'].sort(key=lambda a: (order[a['residue_id']], a['source_record']))
        mapping = tool_structure(projected, tool)
        (output / 'restoration_plan.json').write_text(json.dumps(dict(receptor_policy=RECEPTOR_POLICY,
            restored_residue_ids=sorted(restore), removed_connections=crossings, tool_mapping=mapping)))
        operations = {key: dict(requested=True, status='pending') for key in ('repair', 'protonation')}
        operations['minimization'] = dict(requested=False, status='not_requested')
        boundary = {atoms[aid]['residue_id'] for edge in diagnosis['coordination_candidates'] for aid in edge['atom_ids']
            if aid in selected and atoms[aid]['element'] not in {'H', 'D'} and atoms[aid]['residue_id'] not in restore}
        try:
            processed = process_standard(tool, output, {**options, 'repair_missing_atoms': True, 'minimization_policy': 'none',
                'nonstandard_policy': 'preserve'}, operations,
                dict(reliable_connections=projected['declared_connections']), mapping, joint=False, protected_residues=boundary)
        except ValueError as exc:
            raise PreparationError('COVALENT_RESTORATION_FAILED', restore_labels + '; ' + str(exc), restore_labels.split(', ')) from exc
        parameterization = processed['parameterization']
        restored = restore_tool_identities(processed['manifest'], mapping)
        # Only the severed residues consume the repair output; other input states stay intact.
        replacements = {(a['chain_instance_id'], a['author_chain_id'], a['author_residue_number'], a['insertion_code']): [] for c in projected['components'] for a in c['atoms'] if a['residue_id'] in restore}
        for c in restored['components']:
            for a in c['atoms']:
                key = (a['chain_instance_id'], a['author_chain_id'], a['author_residue_number'], a['insertion_code'])
                if key in replacements:
                    replacements[key].append(a)
        for c in projected['components']:
            residues = {}
            for a in c['atoms']:
                residues.setdefault(a['residue_id'], []).append(a)
            kept = []
            for rid, old in residues.items():
                if rid not in restore:
                    kept.extend(old)
                    continue
                key = (old[0]['chain_instance_id'], old[0]['author_chain_id'], old[0]['author_residue_number'], old[0]['insertion_code'])
                new = replacements[key]
                original_heavy = {a['atom_name']: a for a in old if a['element'] not in {'H', 'D'}}
                repaired = {a['atom_name']: a for a in new}
                if not new or not any(a['element'] == 'H' for a in new) or not original_heavy.keys() <= repaired.keys():
                    raise PreparationError('COVALENT_RESTORATION_FAILED', rid, restore_labels.split(', '))
                for name, atom in original_heavy.items():
                    if repaired[name]['element'] != atom['element']:
                        raise PreparationError('COVALENT_RESTORATION_CHANGED_IDENTITY', rid, restore_labels.split(', '))
                    repaired[name]['coordinates'] = atom['coordinates']
                for a in new:
                    a['source_record'] = original_heavy.get(a['atom_name'], old[0])['source_record']
                kept.extend({**a, 'residue_id': rid, 'chain_instance_id': old[0]['chain_instance_id']} for a in new)
            c['atoms'] = kept
        projected['declared_connections'] = [e for e in projected['declared_connections'] if all(atoms[aid]['residue_id'] not in restore for aid in e['atom_ids'])]
        if any(e for e in diagnosis['reliable_connections'] if all(a in selected for a in e['atom_ids']) and any(atoms[a]['residue_id'] in restore for a in e['atom_ids']) and len({atoms[a]['residue_id'] for a in e['atom_ids']}) > 1):
            raise PreparationError('COVALENT_RESTORATION_UNSUPPORTED_RETAINED_BOND', restore_labels, restore_labels.split(', '))
    integrity = validate_integrity(baseline, projected, stage='covalent_restoration', restored_residue_ids=restore)
    target = output / 'context_receptor.cif'
    write_cif(projected, target)
    actual = source_inventory(target, dict(sha256=file_sha256(target), model_id='1'))
    actual['coordinate_frame_id'] = manifest['coordinate_frame_id']
    serialization = validate_integrity(projected, actual, stage='context_receptor_serialization', restored_residue_ids=restore)
    context_receptor_selection(actual)
    def key(a):
        return (a['author_chain_id'], a.get('label_asym_id') or a['chain_instance_id'].split(':chain:')[-1].replace(':', '_'), a['author_residue_number'], a['insertion_code'], a['atom_name'])
    after = {key(a): a for c in actual['components'] for a in c['atoms']}
    if len(after) != sum(len(c['atoms']) for c in actual['components']):
        raise ValueError('CONTEXT_RECEPTOR_MAPPING_AMBIGUOUS')
    entries, mapped = [], set()
    for atom in atoms.values():
        new = after.get(key(atom)) if atom['atom_id'] in selected else None
        if atom['atom_id'] in selected and atom['element'] not in {'H', 'D'} and new is None:
            raise ValueError('CONTEXT_RECEPTOR_REMOVED_PROTEIN_ATOM: ' + atom['atom_id'])
        if new:
            mapped.add(new['atom_id'])
        entries.append(dict(source_atom_id=atom['atom_id'], output_atom_id=new['atom_id'] if new else None, change=('retained' if new['coordinates'] == atom['coordinates'] else 'replaced') if new else 'deleted'))
    entries.extend(dict(source_atom_id=None, output_atom_id=a['atom_id'], change='added') for a in after.values() if a['atom_id'] not in mapped)
    report = dict(version=1, receptor_policy=RECEPTOR_POLICY, source_sha256=file_sha256(source), output_sha256=file_sha256(target),
        coordinate_frame_id=manifest['coordinate_frame_id'], decisions=decisions, removed_connections=crossings,
        preserved_connections=preserved_connections, unsupported_restorations=[dict(connection=e, status='skipped', reason='No verified covalent restoration template', impact='MODEL_COVALENT_BOUNDARY') for e in preserved_connections],
        restored_residue_ids=sorted(restore), restoration_operations=operations, restoration_parameterization=parameterization, integrity=integrity, serialization=serialization, entries=entries,
        retained_coordination_changes=[e for e in diagnosis['coordination_candidates'] if any(a in selected for a in e['atom_ids']) and not all(a in selected for a in e['atom_ids'])])
    report['restoration_tool_versions'] = {name: importlib.metadata.version(name) for name in ('pdbfixer','pdb2pqr','openmm')} if restore else {}
    map_path = output / 'context_receptor_map.json'
    map_path.write_text(json.dumps(report, allow_nan=False))
    return target, map_path, report
