import json
from pathlib import Path

from genova_runtime.entry_protein_preparation import COFACTORS
from genova_runtime.pdb2pqr_compat import AMINO_ACIDS
from genova_runtime.structure_identity import METAL_ELEMENTS

PREPARATION_FORCEFIELDS = ('amber14-all.xml', 'amber14/tip3p.xml', 'implicit/obc2.xml')


# Snapshot of the installed PDBFixer 1.12.0 substitutions and templates; checked against the Worker in tests.
PDBFIXER_TEMPLATES = json.loads(Path(__file__).with_name('pdbfixer_templates.json').read_text())
WATER_NAMES = {'HOH', 'WAT', 'DOD', 'H2O'}
RECEPTOR_POLICY = 'protein_metals_v1'
# Only a single thiol attachment has a verified, heavy-atom-preserving restoration.
RESTORABLE_ATTACHMENTS = {('CYS', 'SG')}
# Explicit, heavy-atom-preserving conversions. Extend only after verifying the
# parent-template atom names and coordinates in the preparation Worker.
STANDARDIZABLE_RESIDUES = {
    'MSE': {'to': 'MET', 'atom_renames': {'SE': 'SD'}, 'element_renames': {'SE': 'S'}},
}


def receptor_removal_plan(manifest, selected, diagnosis):
    atoms = {a['atom_id']: a for c in manifest['components'] for a in c['atoms']}
    components = {c['component_id']: c for c in manifest['components']}
    standard_names = AMINO_ACIDS | {'HID', 'HIE', 'HIP', 'CYX'}
    nonstandard_chains = {a['chain_instance_id'] for c in manifest['components'] if c['selection_kind'] == 'chain_records'
        for a in c['atoms'] if a['residue_name'] not in standard_names}
    crossings = [e for e in diagnosis['reliable_connections'] if any(a in selected for a in e['atom_ids']) and not all(a in selected for a in e['atom_ids'])]
    restorable, preserved = [], []
    for edge in crossings:
        retained = [atoms[a] for a in edge['atom_ids'] if a in selected]
        removed = [atoms[a] for a in edge['atom_ids'] if a not in selected]
        rid = retained[0]['residue_id']
        involved = [e for e in diagnosis['reliable_connections'] if any(atoms[a]['residue_id'] == rid for a in e['atom_ids'])
            and len({atoms[a]['residue_id'] for a in e['atom_ids']}) > 1]
        coordinated = any(any(atoms[a]['residue_id'] == rid for a in e['atom_ids']) for e in diagnosis['coordination_candidates'])
        supported = ('symmetry_operations' not in edge and len(involved) == 1 and not coordinated
            and retained[0]['chain_instance_id'] not in nonstandard_chains
            and (retained[0]['residue_name'], retained[0]['atom_name']) in RESTORABLE_ATTACHMENTS
            and removed[0]['residue_name'] not in COFACTORS | WATER_NAMES
            and removed[0]['element'] not in METAL_ELEMENTS
            and not any(c['selection_kind'] == 'chain_records' and any(a['residue_id'] == removed[0]['residue_id'] for a in c['atoms']) for c in components.values()))
        (restorable if supported else preserved).append(edge)
    return restorable, preserved


def _polymer_residue_atoms(manifest, selected_atom_ids):
    import copy

    from genova_runtime.structure_identity import merge_polymer_records
    selected = set(selected_atom_ids)
    components = {}
    for component in manifest['components']:
        atoms = [copy.deepcopy(a) for a in component['atoms'] if a['atom_id'] in selected]
        if atoms:
            components[component['component_id']] = {**component, 'atoms': atoms}
    merge_polymer_records(components)
    residues = {}
    for component in components.values():
        if component['selection_kind'] != 'chain_records':
            continue
        for atom in component['atoms']:
            residues.setdefault(atom['residue_id'], []).append(atom)
    return residues, {a['atom_id']: a for c in components.values() for a in c['atoms']}


def standardization_plan(manifest, selected_atom_ids, diagnosis, *, requested):
    from genova_runtime.automatic_preparation import NUCLEIC
    from genova_runtime.structure_inputs import RESIDUE_ALIASES
    operation = dict(requested=requested, status='not_requested', scope='retained_modifications')
    if not requested:
        return operation
    residues, atoms = _polymer_residue_atoms(manifest, selected_atom_ids)
    standard = AMINO_ACIDS | RESIDUE_ALIASES.keys() | NUCLEIC
    connections = diagnosis.get('reliable_connections', [])
    coordination = diagnosis.get('coordination_candidates', [])
    converted, preserved, failed = [], [], []
    def connected(rid, edges):
        return any(rid in {atoms[aid]['residue_id'] for aid in edge['atom_ids'] if aid in atoms} for edge in edges)
    for rid, residue_atoms in sorted(residues.items()):
        name = residue_atoms[0]['residue_name']
        if name in standard:
            continue
        heavy = {a['atom_name']: a for a in residue_atoms if a['element'] not in {'H', 'D'}}
        spec = STANDARDIZABLE_RESIDUES.get(name)
        reason = None
        if spec is None:
            reason = 'No verified parent mapping; modification preserved'
        else:
            parent = PDBFIXER_TEMPLATES['heavy_atom_names'].get(spec['to'], ())
            mapped = {spec['atom_renames'].get(atom, atom) for atom in heavy}
            if not heavy:
                reason = 'No heavy atoms available for conversion'
            elif not mapped - {'OXT'} <= set(parent):
                reason = 'Atom set does not match the verified parent template'
            elif any(source not in heavy for source in spec['atom_renames']):
                reason = 'Required renamed atom is missing'
            elif connected(rid, connections):
                reason = 'Covalent connection blocks conversion'
            elif connected(rid, coordination):
                reason = 'Coordination or special environment blocks conversion'
        label = dict(chain_id=residue_atoms[0]['author_chain_id'], residue_number=residue_atoms[0]['author_residue_number'],
            insertion_code=residue_atoms[0]['insertion_code'])
        if reason:
            preserved.append(dict(source_residue_id=rid, residue_name=name, reason=reason,
                impact=['pdb2pqr', 'surfgen', 'delete'], **label))
            continue
        atom_mapping = []
        for source, target in sorted(spec['atom_renames'].items()):
            source_element = heavy[source]['element']
            atom_mapping.append(dict(source_atom_name=source, output_atom_name=target,
                source_element=source_element, output_element=spec['element_renames'].get(source, source_element)))
        converted.append(dict(source_residue_id=rid, from_residue_name=name, to_residue_name=spec['to'],
            atom_mapping=atom_mapping, **label))
    operation.update(converted=converted, preserved=preserved, failed=failed,
        residue_ids=sorted({*([r['source_residue_id'] for r in preserved]), *([r['source_residue_id'] for r in converted])}))
    operation['status'] = 'not_applicable' if not (converted or preserved) else 'pending'
    return operation


def standardization_operation(manifest, selected_atom_ids, requested, *, diagnosis=None, actual=None, executed=True):
    operation = standardization_plan(manifest, selected_atom_ids, diagnosis or {'reliable_connections': [], 'coordination_candidates': []}, requested=requested)
    if not requested:
        return operation
    planned = operation.pop('converted', [])
    preserved = operation.get('preserved', [])
    failed = list(operation.get('failed', []))
    converted = []
    if not executed:
        failed.extend(dict(row, reason='Standard protein processing was not executed; modification preserved') for row in planned)
    elif actual is None:
        converted = planned
    else:
        actual_by_id = {row['source_residue_id']: row for row in actual}
        converted = [dict(actual_by_id[row['source_residue_id']], chain_id=row['chain_id'],
            residue_number=row['residue_number'], insertion_code=row['insertion_code'])
            for row in planned if row['source_residue_id'] in actual_by_id]
        failed.extend(dict(row, reason=row.get('reason') or 'Conversion was not executed')
            for row in planned if row['source_residue_id'] not in actual_by_id)
    if not executed:
        status = 'skipped' if planned or preserved else ('not_applicable' if not failed else 'skipped')
    elif converted and not (failed or preserved):
        status = 'completed'
    elif converted:
        status = 'partial'
    elif failed:
        status = 'failed'
    elif preserved:
        status = 'skipped'
    else:
        status = 'not_applicable'
    reasons = [row['reason'] for row in [*failed, *preserved] if row.get('reason')]
    operation.update(status=status, converted=converted, preserved=preserved, failed=failed)
    if reasons:
        operation['reason'] = reasons[0] if len(reasons) == 1 else f'{len(reasons)} modifications were not converted; see preserved and failed entries'
    return operation



def context_receptor_selection(manifest):
    import copy
    from genova_runtime.automatic_preparation import NUCLEIC
    from genova_runtime.structure_inputs import RESIDUE_ALIASES
    from genova_runtime.structure_identity import merge_polymer_records
    polymers = {c['component_id']: copy.deepcopy(c) for c in manifest['components']}
    merge_polymer_records(polymers)
    polymer_residues = {a['residue_id'] for c in polymers.values() if c['selection_kind'] == 'chain_records' for a in c['atoms']}
    selected, decisions = set(), []
    for component in manifest['components']:
        residues = {}
        for atom in component['atoms']:
            residues.setdefault(atom['residue_id'], []).append(atom)
        for rid, atoms in residues.items():
            heavy = [a for a in atoms if a['element'] not in {'H', 'D'}]
            name = atoms[0]['residue_name']
            if name in NUCLEIC:
                role = 'nucleic_acid'
            elif rid in polymer_residues:
                role = 'protein'
            elif name in COFACTORS:
                role = 'cofactor'
            elif len(heavy) == 1 and heavy[0]['element'] in METAL_ELEMENTS:
                role = 'metal_ion'
            elif name in WATER_NAMES:
                role = 'water'
            elif any(a['record_type'] == 'ATOM' for a in atoms):
                raise ValueError('RECEPTOR_COMPONENT_UNCLASSIFIED: ' + rid + ' (' + name + ')')
            else:
                role = 'nonprotein_component'
            keep = role in {'protein', 'metal_ion'}
            if keep:
                selected.update(a['atom_id'] for a in atoms)
            decisions.append(dict(component_id=component['component_id'], residue_id=rid, residue_name=name,
                role=role, action='retained' if keep else 'excluded', atom_ids=[a['atom_id'] for a in atoms]))
    if not any(d['role'] == 'protein' for d in decisions):
        raise ValueError('CONTEXT_RECEPTOR_EMPTY: no selected protein residues')
    return selected, decisions


def water_components(manifest):
    return [c['component_id'] for c in manifest['components'] if c['selection_kind'] != 'chain_records'
            and c['atoms'][0]['residue_name'] in WATER_NAMES
            and len({a['atom_name'] for a in c['atoms'] if a['element'] == 'O'}) == 1
            and all(a['element'] in {'O', 'H', 'D'} for a in c['atoms'])]
