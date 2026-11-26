from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RESIDUE_ALIASES = {'HID': 'HIS', 'HIE': 'HIS', 'HIP': 'HIS', 'CYX': 'CYS'}






def materialize_engine_receptor(protein, context, output_dir, *, inventory=None):
    if context.get('version') != 4:
        raise ValueError('Protein Context version 4 is required')
    from genova_runtime.pdb2pqr_compat import file_sha256
    from genova_runtime.structure_inventory import source_inventory, tool_structure
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / 'model_receptor.pdb'
    inventory = inventory if inventory is not None else source_inventory(protein, {'sha256': file_sha256(protein), 'model_id': '1'})
    aliases = {}
    for component in inventory['components']:
        for atom in component['atoms']:
            if atom['record_type'] == 'ATOM' and atom['residue_name'] in RESIDUE_ALIASES:
                aliases[atom['residue_id']] = {'source_residue_id': atom['residue_id'], 'from': atom['residue_name'], 'to': RESIDUE_ALIASES[atom['residue_name']]}
                atom['residue_name'] = RESIDUE_ALIASES[atom['residue_name']]
    mapping = {**tool_structure(inventory, target), 'residue_aliases': list(aliases.values())}
    (output_dir / 'model_receptor_map.json').write_text(json.dumps({**mapping, 'source_sha256': file_sha256(protein), 'model_input_sha256': file_sha256(target), 'builder_version': 'generation_auto_v1'}))
    return target

def component_usage_artifact(context, engine, output_dir, *, cache=None):
    output_dir = Path(output_dir)
    path = output_dir / 'component_usage.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    if cache is not None or (context.get('capabilities') or {}).get('input_preparation') == 'context_features_v1' and engine not in {'tarpass', 'epso'}:
        if cache is None:
            entry = context['model_inputs'][engine]
            cache = json.loads(Path(entry['manifest_path']).read_text())
        path.write_text(json.dumps(dict(version=3, engine=engine, cache_fingerprint=cache['input_fingerprint'], compatibility=cache['status'], model_scope=cache['model_scope'])))
        return {'component_usage_report':str(path)}
    mapping = output_dir / 'model_receptor_map.json'
    features = [p for pattern in ('**/*.ply', '**/*ecloud*.npy', '**/input_features.npz') for p in output_dir.glob(pattern) if p.is_file()]
    observations = [json.loads(p.read_text()) for p in sorted(output_dir.glob('round_*/input_features.json'))]
    rows = json.loads(mapping.read_text()).get('atoms', []) if mapping.is_file() else []
    observed = {serial for report in observations for serial in report.get('observed_tool_atom_serials', [])}
    usage = {}
    for row in rows:
        item = usage.setdefault(row['source_component_id'], {'component_id': row['source_component_id'], 'feature_status': 'unconfirmed', 'parser_observed_atom_ids': []})
        if row['serial'] in observed:
            item['parser_observed_atom_ids'].append(row['source_atom_id'])
    path.write_text(json.dumps({'version': 2, 'engine': engine, 'effective_receptor_sha256': context['effective_receptor_sha256'],
        'expected_scope': 'ligand_only' if engine == 'epso' else 'method_specific_input', 'actual_component_feature_coverage': 'not_observable',
        'component_usage': 'not_consumed' if engine == 'epso' else 'unknown', 'components': list(usage.values()), 'actual_builder_observations': observations, 'feature_artifacts': [{'path': str(p)} for p in features],
        'builder_version': 'generation_auto_v1'}))
    return {'component_usage_report': str(path), **({'model_receptor_map': str(mapping)} if mapping.is_file() else {})}

def materialize_region_spec_json(
    protein_pdb: Path,
    structure_context: dict[str, Any],
    output_dir: Path,
) -> Path:
    validate_context_snapshot(structure_context, protein_pdb)
    anchors = structure_context['anchor_coordinates']
    if not anchors or any(len(coord) != 3 for coord in anchors):
        raise ValueError("Protein Context does not contain valid region anchor coordinates")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "protein_context.json"
    output_path.write_text(
        json.dumps({"anchor_coordinates": anchors}),
        encoding="utf-8",
    )
    return output_path


def validate_context_snapshot(context, protein):
    import hashlib
    if context.get('version') != 4:
        raise ValueError('Protein Context version 4 is required')
    actual = hashlib.sha256(Path(protein).read_bytes()).hexdigest()
    capabilities = context.get('capabilities') or {}
    if actual != context.get('effective_receptor_sha256') or actual != capabilities.get('effective_receptor_sha256'):
        raise ValueError('Effective receptor artifact integrity mismatch')
    required = {'preparation_strategy': 'generation_auto_v1', 'receptor_policy': 'protein_metals_v1', 'input_preparation': 'context_features_v1'}
    if any(capabilities.get(key) != value for key, value in required.items()):
        raise ValueError('Unsupported Protein Context preparation contract')
    if capabilities.get('structure_validation') != 'passed':
        raise ValueError('Effective receptor structure validation is incomplete')
    if not context.get('anchor_coordinates'):
        raise ValueError('Missing explicit site anchor coordinates')


def validate_context_engine_support(context, engine):
    validate_context_snapshot(context, context['protein_pdb'])
    status = context['capabilities'].get('engine_support', {}).get(engine, {}).get('status')
    if engine != 'tarpass' and status not in {'full', 'limited'}:
        raise ValueError(f'{engine}: model inputs are {status or "unchecked"}; wait for Context input validation')


def validate_engine_context(context, engine):
    validate_context_engine_support(context, engine)


def validate_reference_environment(molecule, receptor_atoms, *, allowed_coordination_pairs=()):
    import math
    from itertools import product
    from rdkit import Chem
    table = Chem.GetPeriodicTable()
    cells = {}
    for atom in receptor_atoms:
        if atom.element in {'H', 'D'}:
            continue
        cell = tuple(math.floor(v / 4) for v in atom.coordinates)
        cells.setdefault(cell, []).append(atom)
    for atom in molecule.GetAtoms():
        if atom.GetAtomicNum() <= 1:
            continue
        point = list(molecule.GetConformer().GetAtomPosition(atom.GetIdx()))
        cell = tuple(math.floor(v / 4) for v in point)
        for offset in product((-1, 0, 1), repeat=3):
            for other in cells.get(tuple(a+b for a, b in zip(cell, offset)), []):
                if (atom.GetIdx(), other.atom_id) in allowed_coordination_pairs:
                    continue
                threshold = table.GetRcovalent(atom.GetAtomicNum()) + table.GetRcovalent(other.element.title()) + 0.3
                if math.dist(point, other.coordinates) <= threshold:
                    raise ValueError('Generation reference overlaps or has a possible covalent connection to the retained receptor; dedicated covalent preparation is required')


def reference_contact_diagnostics(molecule, receptor_atoms):
    import math
    from itertools import product
    from rdkit import Chem
    from genova_runtime.structure_identity import METAL_ELEMENTS
    from genova_runtime.automatic_preparation import METAL_DONOR_BOUNDS, WATERS
    cells, result = {}, []
    for atom in receptor_atoms:
        if atom['element'] not in {'H', 'D'}:
            cells.setdefault(tuple(math.floor(v / 4) for v in atom['coordinates']), []).append(atom)
    table = Chem.GetPeriodicTable()
    for atom in molecule.GetAtoms():
        if atom.GetAtomicNum() <= 1:
            continue
        point = list(molecule.GetConformer().GetAtomPosition(atom.GetIdx()))
        cell = tuple(math.floor(v / 4) for v in point)
        for offset in product((-1, 0, 1), repeat=3):
            for other in cells.get(tuple(a+b for a, b in zip(cell, offset)), []):
                distance = math.dist(point, other['coordinates'])
                if other['element'] in METAL_ELEMENTS:
                    low, high = METAL_DONOR_BOUNDS.get(other['element'], (1.4, 3.4))
                    kind = 'clash' if distance < low * 0.65 else 'coordination_candidate' if atom.GetSymbol() in {'N', 'O', 'S'} and distance <= high else 'proximity'
                    threshold = high
                else:
                    threshold = table.GetRcovalent(atom.GetAtomicNum()) + table.GetRcovalent(other['element'].title()) + 0.3
                    kind = 'water_contact' if other['residue_name'] in WATERS else 'clash' if distance < 1.2 else 'unresolved_contact'
                if distance <= threshold:
                    result.append({'code': 'REFERENCE_' + kind.upper(), 'reference_atom_index': atom.GetIdx(),
                        'receptor_atom_id': other['atom_id'], 'evidence': 'distance', 'distance_angstrom': distance,
                        'chemical_type': kind, 'severity': 'error' if kind == 'clash' else 'warning',
                        'action': 'require_valid_reference_pose' if kind == 'clash' else 'preserve_coordinates', 'impact': 'model_initialization'})
    return result


def validate_surface_features(path):
    import math
    from genova_runtime.preparation_errors import PreparationError
    with Path(path).open() as stream:
        if stream.readline().strip() != 'ply' or stream.readline().strip() != 'format ascii 1.0':
            raise PreparationError('MODEL_FEATURE_ENCODING_INVALID', 'Unsupported surface feature encoding')
        columns, count, vertex = [], 0, False
        for line in stream:
            words = line.split()
            if words[:2] == ['element', 'vertex']:
                count, vertex = int(words[2]), True
            elif words[:1] == ['element']:
                vertex = False
            elif vertex and words[:1] == ['property']:
                columns.append(words[-1])
            if words == ['end_header']:
                break
        features = [name for name in columns if name not in {'nx', 'ny', 'nz'}]
        if features != ['x', 'y', 'z', 'charge', 'hbond', 'hphob', 'si'] or count <= 0:
            raise PreparationError('MODEL_FEATURES_MISSING', 'Surface requires coordinates, potential, hydrogen-bond, hydrophobicity and shape features')
        charged = False
        for _ in range(count):
            values = [float(value) for value in stream.readline().split()]
            if len(values) != len(columns) or not all(math.isfinite(value) for value in values):
                raise PreparationError('MODEL_FEATURE_NONFINITE', 'Surface features contain missing or non-finite values')
            charged |= values[columns.index('charge')] != 0
        if not charged:
            raise PreparationError('MODEL_SURFACE_POTENTIAL_ZERO', 'Surface potential is entirely zero; verified electrostatic features are required')
    result = {'builder_version': 'generation_auto_v1', 'vertex_count': count, 'feature_dimension': 4,
              'columns': columns, 'potential_validation': 'passed', 'component_feature_coverage': 'unknown'}
    Path(path).with_suffix('.features.json').write_text(json.dumps(result))
    return result
