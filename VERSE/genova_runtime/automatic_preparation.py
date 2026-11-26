import copy
import importlib.metadata
import json
import math
import time
import traceback
from itertools import product
from pathlib import Path

from genova_runtime.pdb2pqr_compat import AMINO_ACIDS, file_sha256
from genova_runtime.structure_identity import METAL_ELEMENTS, component_connections, connection_kind, component_manifest
from genova_runtime.structure_inventory import source_inventory, tool_structure, write_cif, restore_tool_identities, validate_selection
from genova_runtime.preparation_errors import PreparationError, describe_preparation_error, residue_label

STRATEGY = 'generation_auto_v1'
WATERS = {'HOH', 'WAT', 'DOD', 'H2O'}
NUCLEIC = {'DA', 'DC', 'DG', 'DT', 'DI', 'DU', 'A', 'C', 'G', 'U', 'I'}
# Versioned conservative contact bounds, in Å; geometry is evidence of contact, never a new covalent bond.
METAL_DONOR_BOUNDS = {'MG': (1.6, 2.8), 'CA': (1.8, 3.2), 'NA': (1.8, 3.4), 'ZN': (1.5, 2.8), 'FE': (1.5, 2.9)}


class PreparationFailure(ValueError):
    def __init__(self, message, result):
        super().__init__(message)
        self.result = result


def native_connections(path, manifest):
    from Bio.PDB.MMCIF2Dict import MMCIF2Dict
    data = MMCIF2Dict(str(path))
    atoms = [a for c in manifest['components'] for a in c['atoms']]
    owners = {a['atom_id']: c['component_id'] for c in manifest['components'] for a in c['atoms']}
    edges, unresolved = [], []
    def field(name, i):
        values = data.get('_struct_conn.' + name)
        value = values[i] if values else ''
        return '' if value in {'.', '?'} else str(value)
    for i in range(len(data.get('_struct_conn.id', []))):
        kind = field('conn_type_id', i)
        if kind not in {'covale', 'disulf', 'metalc'}:
            continue
        ends = []
        for part in ('ptnr1', 'ptnr2'):
            chain, number, name, atom = [field(part + '_' + key, i) for key in
                ('label_asym_id', 'auth_seq_id', 'label_comp_id', 'label_atom_id')]
            label_number = field(part + '_label_seq_id', i)
            alt, insertion = field('pdbx_' + part + '_label_alt_id', i), field('pdbx_' + part + '_PDB_ins_code', i)
            rows = [a for a in atoms if a.get('label_asym_id') == chain and a['residue_name'] == name
                and a['atom_name'] == atom and a['insertion_code'] == insertion
                and (not number or str(a['author_residue_number']) == number)
                and (not label_number or a.get('label_seq_id') == label_number) and (not alt or a['altloc'] == alt)]
            if not rows or len({a['residue_id'] for a in rows}) != 1:
                rows = []
            ends.append(rows)
        if not all(ends):
            unresolved.append({'connection_id': field('id', i), 'type': kind, 'reason': 'Unresolved or ambiguous connection endpoint'})
            continue
        symmetries = [field(part + '_symmetry', i) or '1_555' for part in ('ptnr1', 'ptnr2')]
        for a, b in product(*ends):
            if a['altloc'] and b['altloc'] and a['altloc'] != b['altloc']:
                continue
            edge = dict(atom_ids=[a['atom_id'], b['atom_id']], component_ids=[owners[a['atom_id']], owners[b['atom_id']]], evidence='CIF:' + kind)
            if any(s != '1_555' for s in symmetries):
                edge['symmetry_operations'] = symmetries
            edges.append(edge)
    return edges, unresolved


def diagnose_structure(path, manifest):
    components = {c['component_id']: c for c in manifest['components']}
    atoms = {a['atom_id']: a for c in components.values() for a in c['atoms']}
    unresolved = []
    if manifest['source_format'] == 'mmcif':
        links, unresolved = native_connections(path, manifest)
    else:
        links = component_connections(path, manifest, include_external=True, allow_external_covalent=True)
    diagnostics, reliable, coordination = [], [], []
    diagnostics.extend(dict(code="OCCUPANCY_OUT_OF_RANGE", stage="diagnosis", severity="warning", atom_ids=[a["atom_id"]], evidence=a["occupancy"], action="preserve_source_occupancy", impact="alternate_location_selection", retryable=False) for a in atoms.values() if not 0 <= a["occupancy"] <= 1)
    for edge in links:
        a, b = [atoms[aid] for aid in edge['atom_ids']]
        distance = math.dist(a['coordinates'], b['coordinates'])
        metal = a if a['element'] in METAL_ELEMENTS else b if b['element'] in METAL_ELEMENTS else None
        hydrogen = any(x['element'] in {'H', 'D'} for x in (a, b))
        water = any(x['residue_name'] in WATERS for x in (a, b))
        explicit = edge['evidence'] != 'possible_covalent_distance'
        if metal:
            other = b if metal is a else a
            low, high = METAL_DONOR_BOUNDS.get(metal['element'], (1.4, 3.4))
            kind = 'clash' if distance < low else 'coordination_candidate' if other['element'] in {'N', 'O', 'S'} and distance <= high else 'proximity'
            if explicit and connection_kind(edge, components) == 'covalent':
                kind = 'reliable_covalent'
        elif explicit:
            kind = 'reliable_covalent'
        elif hydrogen:
            kind = 'hydrogen_contact'
        elif water:
            kind = 'water_contact'
        else:
            kind = 'clash' if distance < 0.6 else 'unresolved_contact'
        if 'symmetry_operations' in edge and explicit and connection_kind(edge, components) == 'coordination':
            kind = 'external_coordination'
        if kind == 'reliable_covalent':
            if a['residue_id'] == b['residue_id']:
                role = 'residue_internal'
            elif a['residue_name'] in {'CYS', 'CYX'} and b['residue_name'] in {'CYS', 'CYX'} and a['atom_name'] == b['atom_name'] == 'SG':
                role = 'disulfide'
            elif all(components[cid]['selection_kind'] == 'chain_records' for cid in edge['component_ids']):
                role = 'protein_internal'
            else:
                from genova_runtime.entry_protein_preparation import COFACTORS
                role = 'cofactor_attachment' if any(x['residue_name'] in COFACTORS for x in (a, b)) else 'ligand_attachment'
            edge = dict(edge, connection_role=role)
            reliable.append(edge)
        if kind in {'coordination_candidate', 'external_coordination'}:
            coordination.append(edge)
        diagnostics.append(dict(code=kind.upper(), stage='diagnosis', severity='warning' if kind in {'clash', 'unresolved_contact'} else 'info',
            atom_ids=edge['atom_ids'], component_ids=edge['component_ids'], evidence=edge['evidence'], chemical_type=kind,
            distance_angstrom=distance, action='retain_evidence', impact='preparation_operations', retryable=False,
            **({'symmetry_operations': edge['symmetry_operations']} if 'symmetry_operations' in edge else {})))
    # Metal donor candidates beyond the ordinary covalent-radius neighborhood are also considered.
    cells = {}
    owners = {a['atom_id']: cid for cid, c in components.items() for a in c['atoms']}
    for a in atoms.values():
        if a['element'] in {'N', 'O', 'S'}:
            cells.setdefault(tuple(math.floor(v / 4) for v in a['coordinates']), []).append(a)
    seen = {frozenset(e['atom_ids']) for e in coordination}
    for metal in atoms.values():
        if metal['element'] not in METAL_ELEMENTS:
            continue
        cell = tuple(math.floor(v / 4) for v in metal['coordinates'])
        low, high = METAL_DONOR_BOUNDS.get(metal['element'], (1.4, 3.4))
        for offset in product((-1, 0, 1), repeat=3):
            for other in cells.get(tuple(a+b for a, b in zip(cell, offset)), []):
                pair = frozenset((metal['atom_id'], other['atom_id']))
                distance = math.dist(metal['coordinates'], other['coordinates'])
                if pair not in seen and low <= distance <= high and owners[metal['atom_id']] != owners[other['atom_id']]:
                    edge = dict(atom_ids=[metal['atom_id'], other['atom_id']], component_ids=[owners[metal['atom_id']], owners[other['atom_id']]], evidence='metal_donor_geometry')
                    coordination.append(edge)
                    seen.add(pair)
                    diagnostics.append(dict(code='COORDINATION_CANDIDATE', stage='diagnosis', severity='info', **edge,
                        chemical_type='coordination_candidate', distance_angstrom=distance, action='protect_coordination_water',
                        impact='water_selection', retryable=False, bounds_angstrom=[low, high]))
    diagnostics.extend(dict(code='UNRESOLVED_CONNECTION', stage='diagnosis', severity='warning', evidence=row,
        action='preserve_structure_skip_chemistry', impact='preparation_operations', retryable=False) for row in unresolved)
    return {'diagnostics': diagnostics, 'reliable_connections': reliable, 'coordination_candidates': coordination, 'unresolved_connections': unresolved}


def resolve_plan(manifest, spec, diagnosis):
    from genova_runtime.structure_inventory import resolve_altlocs
    edits, options = spec['edits'], spec['preparation']
    choices, excluded_residues = resolve_altlocs(manifest, edits.get('altloc_choices', {}), automatic=True)
    user_excluded = set(edits['excluded_component_ids'])
    protected = set(edits.get('retained_component_ids', []))
    water_ids = {c['component_id'] for c in manifest['components'] if c['atoms'][0]['residue_name'] in WATERS}
    protected |= {cid for e in diagnosis['coordination_candidates'] if not set(e['component_ids']) & user_excluded for cid in e['component_ids'] if cid in water_ids}
    protected |= {cid for e in diagnosis['reliable_connections'] if not set(e['component_ids']) & user_excluded for cid in e['component_ids'] if cid in water_ids}
    excluded = set(edits['excluded_component_ids'])
    if options['water_policy'] == 'remove_all':
        if water_ids & set(edits.get('retained_component_ids', [])):
            raise ValueError('Remove-all water policy conflicts with explicitly retained water')
        excluded |= water_ids
    selected = [a for c in manifest['components'] if c['component_id'] not in excluded for a in c['atoms']
        if a['residue_id'] not in excluded_residues and (not a['altloc'] or not choices.get(a['residue_id']) or choices[a['residue_id']] == a['altloc'])]
    if not selected:
        raise ValueError('EMPTY_SELECTION: water policy and edits leave no atoms')
    if excluded and diagnosis['unresolved_connections']:
        raise ValueError('UNRESOLVED_CONNECTION_SELECTION: exclusions require unambiguous connection endpoints')
    crossing = [e for e in diagnosis['reliable_connections'] if (e['component_ids'][0] in excluded) != (e['component_ids'][1] in excluded)]
    restore = set()
    if crossing:
        atoms = {a['atom_id']: a for c in manifest['components'] for a in c['atoms']}
        components = {c['component_id']: c for c in manifest['components']}
        for edge in crossing:
            retained = [atoms[aid] for aid, cid in zip(edge['atom_ids'], edge['component_ids']) if cid not in excluded]
            removed = [components[cid] for cid in edge['component_ids'] if cid in excluded]
            if 'symmetry_operations' in edge or any(a['residue_name'] not in AMINO_ACIDS or a['record_type'] != 'ATOM' for a in retained) or any(c['selection_kind'] == 'chain_records' for c in removed):
                raise PreparationError('COVALENT_CUT_REQUIRES_TEMPLATE', 'Requested exclusion has no verified protein residue restoration template',
                    [residue_label(atoms[aid]) for aid in edge['atom_ids']])
            restore.update(a['residue_id'] for a in retained)
        if options['protonation_policy'] != 'recompute':
            raise PreparationError('COVALENT_RESTORATION_REQUIRES_PROTONATION', 'Removing a covalent ligand requires residue protonation',
                [residue_label(a) for a in atoms.values() if a['residue_id'] in restore])
    selected_ids = {a['atom_id'] for a in selected}
    for edge in diagnosis['reliable_connections']:
        if not set(edge['component_ids']) & excluded and (edge['atom_ids'][0] in selected_ids) != (edge['atom_ids'][1] in selected_ids):
            raise ValueError('ALTLOC_CONNECTION_CONFLICT: selected alternate location cuts a reliable connection')
    by_component = {c['component_id']: c for c in manifest['components']}
    parents = {cid: cid for cid, c in by_component.items() if c['selection_kind'] != 'chain_records'}
    def root(cid):
        while parents[cid] != cid:
            cid = parents[cid]
        return cid
    attachments = []
    for edge in diagnosis['reliable_connections']:
        left, right = edge['component_ids']
        if left in parents and right in parents:
            parents[root(right)] = root(left)
        elif left != right:
            attachments.append(edge)
    groups = {}
    for cid in parents:
        groups.setdefault(root(cid), []).append(cid)
    entities = [dict(kind='connected_environment', component_ids=sorted(ids),
        receptor_attachments=[edge for edge in attachments if set(edge['component_ids']) & set(ids)]) for ids in groups.values()]
    return dict(strategy=STRATEGY, source=spec['source'], excluded_component_ids=sorted(excluded), altloc_choices=choices, excluded_residue_ids=excluded_residues,
        removed_connections=crossing, restoration_residue_ids=sorted(restore),
        entities=entities, protected_water_component_ids=sorted(water_ids & protected - excluded), selected_atom_ids=[a['atom_id'] for a in selected],
        contact_rules=dict(version=1, metal_donor_bounds_angstrom=METAL_DONOR_BOUNDS, severe_heavy_overlap_angstrom=0.6))


def process_standard(tool_input, output, options, operations, diagnosis, mapping, *, joint, protected_residues=(), blocked_chains=(), standardizations=None):
    from genova_runtime.entry_protein_preparation import _repair_protein, _minimize_protein, _openmm_structure
    from genova_runtime.pdb2pqr_compat import run_pdb2pqr
    from genova_runtime.preparation_policy import PREPARATION_FORCEFIELDS
    from genova_runtime.structure_identity import export_components, merge_polymer_records
    work = output / 'standard_processing'
    work.mkdir(parents=True, exist_ok=True)
    identity = dict(sha256=file_sha256(tool_input), model_id='1')
    inventory = component_manifest(tool_input, identity, analyze_connections=False)
    merged = {c['component_id']: copy.deepcopy(c) for c in inventory['components']}
    merge_polymer_records(merged)
    standard = AMINO_ACIDS | {'HID', 'HIE', 'HIP', 'CYX'}
    standardizations = standardizations or {}
    convertible = {row['source_residue_id'] for row in standardizations.get('converted', [])}
    tool_residue_source = {(row['tool_chain_id'], int(row['tool_residue_number']), row['insertion_code']): row['source_residue_id']
        for row in mapping['atoms']}
    def standard_component(component):
        if component['selection_kind'] != 'chain_records' or any(a['author_chain_id'] in blocked_chains for a in component['atoms']):
            return False
        for atom in component['atoms']:
            if atom['residue_name'] in standard:
                continue
            source_id = tool_residue_source.get((atom['author_chain_id'], atom['author_residue_number'], atom['insertion_code']))
            if source_id not in convertible:
                return False
        return True
    protein_ids = {c['component_id'] for c in merged.values() if standard_component(c)}
    protein_input = work / 'selected_protein.pdb'
    export_components(tool_input, {**inventory, 'components': list(merged.values())},
        [c['component_id'] for c in merged.values() if c['component_id'] not in protein_ids], protein_input)
    current, diagnostics = protein_input, {}
    if options['repair_missing_atoms']:
        fixed = work / 'fixed.pdb'
        standardize_keys = {(row['tool_chain_id'], int(row['tool_residue_number']), row['insertion_code']) for row in mapping['atoms']
            if row['source_residue_id'] in convertible}
        diagnostics['repair'] = _repair_protein(current, fixed, add_hydrogens=options['protonation_policy'] == 'recompute' and not protected_residues,
            nonstandard_policy=options['nonstandard_policy'], standardize_keys=standardize_keys, residue_source_ids=tool_residue_source)
        current = fixed
        operations['repair']['status'] = 'completed'
    assignment = dict(status='not_checked', reason='Protonation was not requested; input state preserved')
    if options['protonation_policy'] == 'recompute':
        charged = work / 'charged.pdb'
        try:
            assignment = {**run_pdb2pqr(current, work / 'protein.pqr', charged,
                {'repair_structure': False, 'add_hydrogens': True, 'update_protonation': True, 'optimize_hydrogen_bonds': True}, options['ph']), 'status': 'passed'}
        except (ValueError, RuntimeError) as exc:
            assignment = dict(status='failed', reason=str(exc), impact=['surfgen', 'delete'])
            operations['protonation'].update(status='failed', reason=str(exc))
        else:
            current = charged
            operations['protonation']['status'] = 'completed'
    if protected_residues and options['protonation_policy'] == 'recompute':
        protected_tool = {(row['tool_chain_id'], row['tool_residue_number']) for row in mapping['atoms'] if row['source_residue_id'] in protected_residues}
        original_names = {(line[21:22].strip(), int(line[22:26]), line[12:16].strip()) for line in protein_input.read_text().splitlines() if line.startswith(('ATOM  ', 'HETATM'))}
        kept, skipped_heavy_atoms = [], []
        for line in current.read_text().splitlines():
            if line.startswith(('ATOM  ', 'HETATM')) and (line[21:22].strip(), int(line[22:26])) in protected_tool:
                if line[76:78].strip() in {'H', 'D'}:
                    continue
                if (line[21:22].strip(), int(line[22:26]), line[12:16].strip()) not in original_names:
                    skipped_heavy_atoms.append(line[12:16].strip())
                    continue
            kept.append(line)
        if skipped_heavy_atoms and operations['repair']['requested']:
            operations['repair'].update(status='partial', reason='No heavy atoms are added at unverified special-environment boundaries', protected_residue_ids=sorted(protected_residues))
        kept.extend(line for line in protein_input.read_text().splitlines() if line.startswith(('ATOM  ', 'HETATM')) and (line[21:22].strip(), int(line[22:26])) in protected_tool and line[76:78].strip() in {'H', 'D'})
        preserved = work / 'protected_hydrogen_states.pdb'
        preserved.write_text('\n'.join(line for line in kept if line != 'END') + '\nEND\n')
        current = preserved
        assignment.update(status='partial', scope='standard_protein_except_protected_hydrogen_states')
        operations['protonation'].update(status='partial', reason='Hydrogen states at special environment boundaries are preserved from the source', protected_residue_ids=sorted(protected_residues))
    protein_manifest = component_manifest(current, dict(sha256=file_sha256(current), model_id='1'), analyze_connections=False)
    environment = [c for c in inventory['components'] if c['component_id'] not in protein_ids]
    combined = {**protein_manifest, 'components': protein_manifest['components'] + environment}
    # Use source tool identities to restore each declared bond after the protein tool renumbers records.
    tool_by_source = {row['source_atom_id']: (row['tool_chain_id'], row['tool_residue_number'], row['atom_name']) for row in mapping['atoms']}
    atoms = {(a['author_chain_id'], a['author_residue_number'], a['atom_name']): (a, c['component_id']) for c in combined['components'] for a in c['atoms']}
    if operations['minimization']['requested']:
        if not joint:
            operations['minimization'].update(status='skipped', reason='Joint environment parameters are unavailable; isolated-protein minimization is not applied')
        else:
            # Keep the established tool aliases and residue numbers in the joint minimization input.
            joint_input = work / 'joint_input.pdb'
            lines = current.read_text().splitlines()
            lines = [line for line in lines if line.startswith(('ATOM  ', 'HETATM', 'TER'))]
            original_lines = tool_input.read_text().splitlines()
            lines.extend(original_lines[a['source_record'] - 1] for c in environment for a in c['atoms'])
            joint_input.write_text('\n'.join([line[:6] + f'{i:5d}' + line[11:] if line.startswith(('ATOM  ', 'HETATM')) else line for i, line in enumerate(lines, 1)] + ['END']) + '\n')
            from openmm.app import ForceField
            forcefield = ForceField(*PREPARATION_FORCEFIELDS)
            structure = _openmm_structure(joint_input)
            if forcefield.getUnmatchedResidues(structure.topology):
                operations['minimization'].update(status='skipped', reason='Joint structure does not match verified force-field templates')
            else:
                minimized = work / 'minimized.pdb'
                diagnostics['minimization'] = _minimize_protein(joint_input, minimized, tool_input, platform_name='CPU', forcefield_files=PREPARATION_FORCEFIELDS)
                operations['minimization']['status'] = 'completed'
                combined = component_manifest(minimized, dict(sha256=file_sha256(minimized), model_id='1'), analyze_connections=False)
    atoms = {(a['author_chain_id'], a['author_residue_number'], a['atom_name']): (a, c['component_id']) for c in combined['components'] for a in c['atoms']}
    combined['declared_connections'] = []
    for edge in diagnosis['reliable_connections']:
        if 'symmetry_operations' in edge:
            continue
        ends = [atoms.get(tool_by_source.get(aid)) for aid in edge['atom_ids']]
        if all(ends):
            combined['declared_connections'].append(dict(atom_ids=[row[0]['atom_id'] for row in ends], component_ids=[row[1] for row in ends], evidence=edge['evidence']))
    for name, row in operations.items():
        row['scope'] = 'standard_protein' if name != 'minimization' else 'retained_joint_system'
    return dict(manifest=combined, parameterization=assignment, diagnostics=diagnostics,
        standardizations=(diagnostics.get('repair') or {}).get('nonstandard_residues_replaced', []))


def validate_auto_request(spec):
    import re
    import uuid
    if set(spec) != {'version', 'source', 'edits', 'preparation'} or type(spec['version']) is not int or spec['version'] != 2:
        raise ValueError('Unsupported automatic preparation request')
    source, edits, options = spec['source'], spec['edits'], spec['preparation']
    if set(source) != {'dataset_id', 'file_id', 'sha256', 'model_id'} or not re.fullmatch('[0-9a-f]{64}', source['sha256']) or not isinstance(source['model_id'], str) or not source['model_id'].strip():
        raise ValueError('Invalid source identity')
    uuid.UUID(source['dataset_id'])
    uuid.UUID(source['file_id'])
    if not {'excluded_component_ids', 'altloc_choices'} <= edits.keys() or edits.keys() - {'excluded_component_ids', 'retained_component_ids', 'altloc_choices'}:
        raise ValueError('Unknown component edit fields')
    for field in ('excluded_component_ids', 'retained_component_ids'):
        values = edits.get(field, [])
        if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values) or len(values) != len(set(values)):
            raise ValueError('Invalid component selection')
    if set(edits['excluded_component_ids']) & set(edits.get('retained_component_ids', [])):
        raise ValueError('Conflicting component selection')
    if not isinstance(edits['altloc_choices'], dict) or any(not key or not isinstance(value, str) or len(value) != 1 for key, value in edits['altloc_choices'].items()):
        raise ValueError('Invalid alternate-location selection')
    expected = {'scope_policy', 'receptor_policy', 'strategy', 'water_policy', 'mode', 'repair_missing_atoms', 'missing_residue_policy', 'nonstandard_policy', 'protonation_policy', 'ph', 'minimization_policy'}
    if set(options) != expected or options['receptor_policy'] != 'protein_metals_v1' or options['scope_policy'] != 'supported_protein_v1' or options['strategy'] != STRATEGY or options['water_policy'] != 'remove_all':
        raise ValueError('Unsupported preparation contract; automatic protein/metal preparation is required')
    if type(options['repair_missing_atoms']) is not bool or options['mode'] != 'standard' or options['missing_residue_policy'] != 'report_only' or options['nonstandard_policy'] not in {'preserve', 'standardize_supported'} or options['protonation_policy'] not in {'preserve', 'recompute'} or options['minimization_policy'] not in {'none', 'restrained_if_supported'}:
        raise ValueError('Invalid preparation operation')
    ph = options['ph']
    if options['protonation_policy'] == 'recompute':
        if type(ph) not in (int, float) or not math.isfinite(ph) or not 0 <= ph <= 14:
            raise ValueError('Invalid protonation pH')
    elif ph is not None:
        raise ValueError('Preserved protonation must not specify pH')
    if options['nonstandard_policy'] == 'standardize_supported' and (not options['repair_missing_atoms'] or options['protonation_policy'] != 'recompute' or options['mode'] != 'standard'):
        raise ValueError('Standardization requires repair and recomputed protonation')


def run_job(payload, dry_run=False):
    if payload.get('reused_prepared'):
        raise ValueError('Legacy prepared-resource upgrades are not supported')
    spec = copy.deepcopy(payload['prepared_spec'])
    validate_auto_request(spec)
    if spec['preparation'].get('strategy') != STRATEGY or payload.get('preparation_protocol_version') != 2:
        raise ValueError('Unsupported automatic preparation strategy')
    output = Path(payload['output_dir'])
    output.mkdir(parents=True, exist_ok=True)
    report = dict(version=2, preparation_protocol_version=2, strategy=STRATEGY, requested_spec=spec,
        resolved_plan=None, operation_results={}, diagnostics=[], artifacts={}, stages=[], status='running')
    report_path = output / 'preparation_report.json'
    def publish_report():
        temporary = report_path.with_suffix('.tmp')
        published = {k: v for k, v in report.items() if k not in {'source_manifest', 'connections', 'excluded_component_ids'}}
        if published.get('resolved_plan'):
            published['resolved_plan'] = {k: v for k, v in published['resolved_plan'].items()
                if k not in {'selected_atom_ids', 'polymer_classes', 'tools'}}
        if published.get('context_receptor'):
            published['context_receptor'] = {k: v for k, v in published['context_receptor'].items()
                if k in {'receptor_policy', 'source_sha256', 'output_sha256', 'restored_residue_ids', 'restoration_operations', 'restoration_tool_versions'}}
        temporary.write_text(json.dumps(report if report['status'] == 'failed' else published, ensure_ascii=False, allow_nan=False))
        temporary.replace(report_path)
    def stage(name):
        report['stages'].append({'stage': name, 'time_monotonic': time.monotonic()})
        publish_report()
        progress = output / 'preparation_progress.json'
        temporary = progress.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(requested_spec=spec, stage=name)))
        temporary.replace(progress)
    try:
        stage('reading_mapping')
        source = Path(payload['protein_pdb'])
        manifest = source_inventory(source, spec['source'])
        validate_selection(manifest, spec['edits'])
        stage('diagnosing_planning')
        report['source_manifest'] = manifest
        diagnosis = diagnose_structure(source, manifest)
        report['diagnostics'] = diagnosis['diagnostics']
        plan = resolve_plan(manifest, spec, diagnosis)
        report['resolved_plan'] = plan
        report['source_manifest'] = manifest
        selected = [a for c in manifest['components'] if c['component_id'] not in plan['excluded_component_ids'] for a in c['atoms']
            if a['atom_id'] in set(plan['selected_atom_ids'])]
        selected_ids = set(plan['selected_atom_ids'])
        severe = [d for d in diagnosis['diagnostics'] if d['code'] == 'CLASH' and all(aid in selected_ids for aid in d['atom_ids'])
            and d['distance_angstrom'] < 0.6 and all(next(a for a in selected if a['atom_id'] == aid)['element'] not in {'H', 'D'} for aid in d['atom_ids'])]
        if severe:
            raise ValueError('SEVERE_HEAVY_OVERLAP: retained heavy atoms overlap; inspect the saved diagnosis')
        options = spec['preparation']
        from genova_runtime.preparation_policy import standardization_plan
        from genova_runtime.structure_identity import merge_polymer_records
        standardizations = standardization_plan(manifest, selected_ids, diagnosis, requested=options['nonstandard_policy'] == 'standardize_supported')
        convertible = {row['source_residue_id'] for row in standardizations.get('converted', [])}
        standard_names = AMINO_ACIDS | {'HID', 'HIE', 'HIP', 'CYX'}
        merged = {c['component_id']: copy.deepcopy(c) for c in manifest['components']}
        merge_polymer_records(merged)
        polymer_ids = {a['atom_id'] for c in merged.values() if c['selection_kind'] == 'chain_records' for a in c['atoms']}
        protein = [a for a in selected if a['atom_id'] in polymer_ids and (a['residue_name'] in standard_names or a['residue_id'] in convertible)]
        environment = [a for a in selected if a not in protein]
        connected_environment = [e for e in diagnosis['reliable_connections'] if all(aid in selected_ids for aid in e['atom_ids'])
            and any(a['atom_id'] in e['atom_ids'] for a in environment)]
        boundary_atoms = {a['atom_id'] for a in protein}
        cross_contacts = [d for d in diagnosis['diagnostics'] if d.get('atom_ids') and any(aid in boundary_atoms for aid in d['atom_ids']) and any(aid not in boundary_atoms for aid in d['atom_ids']) and d.get('chemical_type') not in {'hydrogen_contact', 'water_contact', 'proximity'} and all(aid in selected_ids for aid in d['atom_ids'])]
        independent = bool(protein) and not connected_environment and not cross_contacts and not any(a['residue_name'] in NUCLEIC or a['atom_id'] in polymer_ids for a in environment)
        safe = bool(protein) and not connected_environment and not diagnosis['unresolved_connections'] and not any('symmetry_operations' in e for e in diagnosis['reliable_connections'])
        tools = {}
        for tool in ('biopython', 'pdbfixer', 'pdb2pqr', 'openmm', 'rdkit'):
            try:
                tools[tool] = importlib.metadata.version(tool)
            except importlib.metadata.PackageNotFoundError:
                tools[tool] = 'unavailable'
        plan['tools'] = tools
        plan['polymer_classes'] = {kind: sorted({a['residue_id'] for a in selected if (a['residue_name'] in NUCLEIC if kind == 'nucleic_acid' else (a['residue_name'] in standard_names or a['residue_id'] in convertible))}) for kind in ('protein', 'nucleic_acid')}
        requested = dict(repair=options['repair_missing_atoms'], protonation=options['protonation_policy'] == 'recompute', minimization=options['minimization_policy'] != 'none')
        operations = {name: dict(requested=value, status='pending' if value else 'not_requested', scope='retained_structure') for name, value in requested.items()}
        report['operation_results'] = operations
        reason = 'Retained covalent modifications, unsupported polymer or environment has no verified joint preparation strategy'
        tool_input = output / 'tool_input.pdb'
        mapping = None
        try:
            manifest['declared_connections'] = diagnosis['reliable_connections'] + [dict(e, evidence='CIF:metalc') for e in diagnosis['coordination_candidates'] if e['evidence'] != 'metal_donor_geometry']
            mapping = tool_structure(manifest, tool_input, plan['excluded_component_ids'], plan['altloc_choices'], plan['excluded_residue_ids'])
        except ValueError as exc:
            if not str(exc).startswith('TOOL_FORMAT_CAPACITY:'):
                raise
            safe, reason = False, str(exc)
        if any(a['atom_id'] in polymer_ids and a['residue_name'] not in standard_names and a['residue_id'] not in convertible for a in selected):
            safe = False
        backbone = {}
        for a in protein:
            backbone.setdefault(a['residue_id'], set()).add(a['atom_name'])
        if any(len(names & {'N', 'CA', 'C'}) < 2 for names in backbone.values()):
            safe = False
            independent = False
        joint = safe
        if any(a['residue_name'] in WATERS for a in environment):
            joint = False
            safe = independent
            reason = 'Retained water requires a verified joint hydrogen-state strategy'
        if any(tools[t] == 'unavailable' for t in ('pdbfixer', 'pdb2pqr', 'openmm')):
            safe, reason = False, 'Required preparation tools are unavailable; source coordinates retained'
        protected_residues, blocked_chains = set(), set()
        if mapping:
            protein_ids = {a['atom_id'] for a in protein}
            source_atoms = {a['atom_id']: a for a in selected}
            for edge in diagnosis['reliable_connections'] + diagnosis['coordination_candidates']:
                if all(aid in selected_ids for aid in edge['atom_ids']) and any(aid not in protein_ids for aid in edge['atom_ids']):
                    protected_residues.update(source_atoms[aid]['residue_id'] for aid in edge['atom_ids'] if aid in protein_ids)
            protected_residues.update(source_atoms[aid]['residue_id'] for row in cross_contacts for aid in row['atom_ids'] if aid in protein_ids)
            environment_residues = {}
            for atom in environment:
                environment_residues.setdefault(atom['residue_id'], []).append(atom)
            for residue in environment_residues.values():
                if {'N', 'CA', 'C'} <= {a['atom_name'] for a in residue}:
                    blocked_chains.update(row['tool_chain_id'] for row in mapping['atoms'] if row['chain_instance_id'] == residue[0]['chain_instance_id'])
            tool_chains = {row['source_atom_id']: row['tool_chain_id'] for row in mapping['atoms']}
            eligible = [a for a in protein if tool_chains[a['atom_id']] not in blocked_chains]
            safe = bool(eligible) and all(len(backbone[a['residue_id']] & {'N', 'CA', 'C'}) >= 2 for a in eligible) and all(tools[t] != 'unavailable' for t in ('pdbfixer', 'pdb2pqr', 'openmm'))
            joint = safe and not environment and not protected_residues
            plan['protected_hydrogen_residue_ids'] = sorted(protected_residues)
            plan['blocked_tool_chains'] = sorted(blocked_chains)
        plan['processing_scope'] = 'joint_retained_structure' if safe and joint else 'independent_standard_protein' if safe else 'fidelity_only'
        if safe and not joint:
            plan['boundary_strategy'] = 'existing_disconnected_standard_protein_v1'
            plan['skipped_joint_operations'] = ['minimization']
        if dry_run:
            return dict(preparation_protocol_version=2, strategy=STRATEGY, grid_required=False, requested_spec=spec, resolved_plan=plan, diagnostics=report['diagnostics'])
        stage('structure_processing')
        processed = None
        if safe and options['mode'] == 'standard' and any(requested.values()):
            processed = process_standard(tool_input, output, options, operations, diagnosis, mapping,
                joint=plan['processing_scope'] == 'joint_retained_structure', protected_residues=protected_residues, blocked_chains=blocked_chains,
                standardizations=standardizations)
            report['tool_processing'] = processed['diagnostics']
        if not processed:
            if safe and not any(requested.values()):
                reason = 'No structure-changing operations were requested'
            for row in operations.values():
                if row['requested']:
                    row.update(status='skipped', reason=reason, unprocessed_residue_ids=sorted({a['residue_id'] for a in selected}))
            if any(requested.values()):
                report['diagnostics'].append(dict(code='OPTIONAL_OPERATIONS_SKIPPED', severity='warning', stage='structure_processing',
                    evidence=reason, action='preserve_selected_atoms_and_coordinates', impact=list(name for name, value in requested.items() if value), retryable=False))
        for name, row in operations.items():
            if row['requested'] and row['status'] == 'skipped':
                report['diagnostics'].append(dict(code='OPERATION_SKIPPED', stage='structure_processing', severity='warning', evidence=row['reason'], action='skip_' + name, impact=row['scope'], retryable=False))
        from genova_runtime.preparation_policy import standardization_operation
        operations['standardization'] = standardization_operation(manifest, selected_ids, options['nonstandard_policy'] == 'standardize_supported',
            diagnosis=diagnosis, actual=(processed.get('standardizations', []) if processed else []), executed=bool(processed))
        stage('output_validation')
        prepared = output / 'prepared_complex.cif'
        if processed:
            restored = restore_tool_identities(processed['manifest'], mapping,
                preserve_heavy=operations['minimization']['status'] != 'completed')
            write_cif(restored, prepared)
        else:
            write_cif(manifest, prepared, plan['excluded_component_ids'], plan['altloc_choices'], plan['excluded_residue_ids'])
        identity = dict(dataset_id=payload['prepared_receptor_id'], file_id=payload['artifact_ids']['prepared_complex'], sha256=file_sha256(prepared))
        output_manifest = source_inventory(prepared, dict(**identity, model_id='1'))
        output_manifest['coordinate_frame_id'] = manifest['coordinate_frame_id']
        output_edges = native_connections(prepared, output_manifest)[0]
        output_manifest['declared_connections'] = [e for e in output_edges if 'symmetry_operations' not in e]
        output_manifest['external_coordination_connections'] = [e for e in output_edges if 'symmetry_operations' in e and e['evidence'] == 'CIF:metalc']
        def key(a, atom_name=None):
            chain = a.get('label_asym_id') or a['chain_instance_id'].split(':chain:')[-1].replace(':', '_')
            return (chain, a['author_chain_id'] or chain, a['author_residue_number'], a['insertion_code'],
                atom_name or a['atom_name'], '' if a['residue_id'] in plan['altloc_choices'] else a['altloc'])
        atom_alias = {(row['source_residue_id'], atom['source_atom_name']): atom
            for row in (processed.get('standardizations', []) if processed else [])
            for atom in row.get('atom_mapping', [])}
        after = {key(a): a for c in output_manifest['components'] for a in c['atoms']}
        if len(after) != sum(len(c['atoms']) for c in output_manifest['components']):
            raise ValueError('Ambiguous output atom identity')
        entries, matched, displacement = [], set(), 0.0
        for c in manifest['components']:
            for a in c['atoms']:
                alias = atom_alias.get((a['residue_id'], a['atom_name']))
                b = after.get(key(a, alias['output_atom_name'] if alias else None)) if a['atom_id'] in selected_ids else None
                if a['atom_id'] in selected_ids and b is None and (a['element'] not in {'H', 'D'} or options['protonation_policy'] == 'preserve'):
                    raise ValueError('Preparation removed a retained heavy atom: ' + a['atom_id'])
                if b:
                    if a['element'] != b['element'] and (not alias or b['element'] != alias['output_element']):
                        raise ValueError('Preparation changed element identity')
                    matched.add(b['atom_id'])
                    displacement = max(displacement, math.dist(a['coordinates'], b['coordinates']))
                    if not processed and math.dist(a['coordinates'], b['coordinates']) > 0.000002:
                        raise ValueError('Fidelity preparation changed source coordinates')
                entries.append(dict(change=('renamed' if (a['residue_name'] != b['residue_name'] or a['atom_name'] != b['atom_name']) else 'retained') if b else 'deleted', source_atom_id=a['atom_id'], source_residue_id=a['residue_id'],
                    output_atom_id=b['atom_id'] if b else None, output_residue_id=b['residue_id'] if b else None))
        entries.extend(dict(change='added', source_atom_id=None, source_residue_id=None, output_atom_id=b['atom_id'], output_residue_id=b['residue_id']) for b in after.values() if b['atom_id'] not in matched)
        atom_map = dict(version=1, source=spec['source'], output=identity, source_coordinate_frame_id=manifest['coordinate_frame_id'],
            output_coordinate_frame_id=manifest['coordinate_frame_id'], entries=entries, max_atom_displacement_angstrom=displacement)
        report['effective_diagnostics'] = diagnose_structure(prepared, output_manifest)['diagnostics']
        capabilities = dict(version=2, preparation_strategy=STRATEGY, resolved_altloc_choices=plan['altloc_choices'], artifact_sha256=identity['sha256'], structure_validation='passed',
            preparation_status='partial' if any(r['status'] in {'skipped', 'partial'} for r in operations.values()) else 'complete', operations=operations,
            protein_parameterization=processed['parameterization'] if processed else dict(status='not_checked', reason=reason),
            engine_input='context_preparation' if options.get('scope_policy') else 'deferred_to_generation', tools=tools)
        report.update(status='succeeded', capabilities=capabilities, excluded_component_ids=plan['excluded_component_ids'],
            max_atom_displacement_angstrom=displacement, prepared_atom_count=len(after), connections=diagnosis['reliable_connections'])
        outputs = dict(prepared_complex=prepared, atom_map=output / 'atom_map.json', component_manifest=output / 'component_manifest.json', report=report_path)
        from genova_runtime.context_receptor import build_context_receptor
        stage('context_receptor')
        restore = {e['output_residue_id'] for e in entries if e['source_residue_id'] in plan['restoration_residue_ids'] and e['output_residue_id']}
        receptor_path, receptor_map, receptor_report = build_context_receptor(prepared, output_manifest, output / 'context_receptor', options,
            restore_residue_ids=restore)
        outputs.update(context_receptor=receptor_path, context_receptor_map=receptor_map)
        capabilities.update(receptor_policy=options['receptor_policy'], context_receptor_sha256=file_sha256(receptor_path))
        report['context_receptor'] = {k: v for k, v in receptor_report.items() if k != 'entries'}
        for name, value in (('atom_map', atom_map), ('component_manifest', output_manifest)):
            temporary = outputs[name].with_suffix('.tmp')
            temporary.write_text(json.dumps(value, allow_nan=False))
            temporary.replace(outputs[name])
        report['artifacts'] = {name: dict(path=str(path)) for name, path in outputs.items() if name != 'report'}
        stage('published')
        return dict(preparation_protocol_version=2, strategy=STRATEGY, source_sha256=spec['source']['sha256'], capabilities=capabilities,
            artifact_sha256={name: file_sha256(path) for name, path in outputs.items()}, **{name: str(path) for name, path in outputs.items()})
    except Exception as exc:
        info = describe_preparation_error(exc, report['stages'][-1]['stage'])
        report.update(status='failed', error=str(exc), error_info=info, traceback=traceback.format_exc())
        report['diagnostics'].append(dict(code='PREPARATION_FAILED', severity='error', stage=report['stages'][-1]['stage'],
            evidence=str(exc), action='fail_task_preserve_files', impact='preparation', retryable=False))
        publish_report()
        raise PreparationFailure(str(exc), dict(preparation_protocol_version=2, strategy=STRATEGY, source_sha256=spec['source']['sha256'],
            error_info=info, report=str(report_path), artifact_sha256={'report': file_sha256(report_path)})) from exc


if __name__ == '__main__':
    import sys
    try:
        result = run_job(json.load(sys.stdin))
    except PreparationFailure as exc:
        Path(sys.argv[1]).write_text(json.dumps({'status': 'failed', 'error': traceback.format_exc(), 'result': exc.result}))
        raise
    else:
        Path(sys.argv[1]).write_text(json.dumps({'status': 'succeeded', 'result': result}))
