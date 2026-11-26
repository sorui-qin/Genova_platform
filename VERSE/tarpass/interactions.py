import hashlib
import json
import math
from pathlib import Path

import numpy as np
from rdkit import Chem
from rdkit.Chem import rdDepictor


DIAGRAM_VERSION = 2
DETAILS_VERSION = 2
PLIP_VERSION = '2.4.0'

INTERACTION_FIELDS = {
    'H-Bond donor': 'hbonds_ldon', 'H-Bond acceptor': 'hbonds_pdon',
    'Halogen bond': 'halogen_bonds', 'Hydrophobic contact': 'hydrophobic_contacts',
    'Pi-cation lAro': 'pication_laro', 'Pi-cation pAro': 'pication_paro',
    'Pi-stacking': 'pistacking', 'Salt Bridge lneg': 'saltbridge_lneg',
    'Salt Bridge pneg': 'saltbridge_pneg',
}


def molecule_fingerprint(mol):
    heavy = Chem.RemoveHs(mol)
    return hashlib.sha256(json.dumps({
        'atoms': [(a.GetAtomicNum(), a.GetFormalCharge(), a.GetIsotope()) for a in heavy.GetAtoms()],
        'bonds': [(b.GetBeginAtomIdx(), b.GetEndAtomIdx(), str(b.GetBondType())) for b in heavy.GetBonds()],
        'coordinates': np.round(heavy.GetConformer().GetPositions(), 4).tolist(),
    }, sort_keys=True).encode()).hexdigest()


def extract_details(mol, ligand, analyzer, detected, residue_map, protein_sha256):
    heavy = Chem.RemoveHs(mol)
    positions = ligand.GetConformer().GetPositions()
    # PLIP removes receptor hydrogens and renumbers PDB serials. Our unique atom names survive that rewrite.
    serial_to_index = {}
    named = {atom.GetPDBResidueInfo().GetName().strip(): atom.GetIdx() for atom in ligand.GetAtoms()}
    if len(named) != ligand.GetNumAtoms():
        raise ValueError('Ligand atom names are not unique')
    for line in analyzer.corrected_pdb.splitlines():
        if not line.startswith('HETATM') or line[17:20].strip() != 'UNL' or line[21] != 'Z' or int(line[22:26]) != 1:
            continue
        index = named[line[12:16].strip()]
        atom = ligand.GetAtomWithIdx(index)
        serial = int(line[6:11])
        original = analyzer.Mapper.id_to_atom(serial)
        if original.atomicnum != atom.GetAtomicNum() or not np.allclose(original.coords, positions[index], atol=0.001, rtol=0):
            raise ValueError('PLIP ligand atom mapping does not match the input SDF')
        serial_to_index[serial] = index
    if set(serial_to_index.values()) != set(range(ligand.GetNumAtoms())):
        raise ValueError('PLIP did not preserve every ligand atom')

    contacts = []
    for kind, field in INTERACTION_FIELDS.items():
        for item in getattr(detected, field):
            if item.reschain != 'A' or item.resnr not in residue_map:
                continue
            ring = False
            if kind.startswith('H-Bond'):
                ligand_ids = [item.a_orig_idx if item.protisdon else item.d_orig_idx]
                protein_ids = [item.d_orig_idx if item.protisdon else item.a_orig_idx]
                distance = item.distance_ad
            elif kind == 'Hydrophobic contact':
                ligand_ids, protein_ids = [item.ligatom_orig_idx], [item.bsatom_orig_idx]
                distance = item.distance
            elif kind == 'Halogen bond':
                ligand_ids, protein_ids = [item.don_orig_idx], [item.acc_orig_idx]
                distance = item.distance
            elif kind == 'Pi-stacking':
                ligand_ids, protein_ids = item.ligandring.atoms_orig_idx, item.proteinring.atoms_orig_idx
                distance, ring = item.distance, True
            elif kind.startswith('Pi-cation'):
                ligand_group = item.ring if item.protcharged else item.charge
                protein_group = item.charge if item.protcharged else item.ring
                ligand_ids, protein_ids = ligand_group.atoms_orig_idx, protein_group.atoms_orig_idx
                distance, ring = item.distance, item.protcharged
            else:
                ligand_group = item.negative if item.protispos else item.positive
                protein_group = item.positive if item.protispos else item.negative
                ligand_ids, protein_ids = ligand_group.atoms_orig_idx, protein_group.atoms_orig_idx
                distance = item.distance
            indices = sorted({serial_to_index[index] for index in ligand_ids})
            protein_atoms = []
            for serial in protein_ids:
                atom = analyzer.Mapper.id_to_atom(serial)
                protein_atoms.append({'serial': serial, 'name': atom.OBAtom.GetResidue().GetAtomID(atom.OBAtom).strip(),
                                      'coordinates': list(atom.coords)})
            contacts.append({'type': kind, 'residue_id': residue_map[item.resnr],
                             'ligand_atom_ids': indices, 'ligand_ring': ring, 'protein_atoms': protein_atoms,
                             'distance': float(distance)})
    contacts.sort(key=lambda row: (row['type'], row['residue_id'], row['ligand_atom_ids']))
    return {'version': DETAILS_VERSION, 'plip_version': PLIP_VERSION, 'protein_sha256': protein_sha256,
            'input_fingerprint': molecule_fingerprint(mol), 'ligand_molblock': Chem.MolToMolBlock(heavy),
            'contacts': contacts}


def build_diagram(details):
    mol = Chem.MolFromMolBlock(details['ligand_molblock'], removeHs=False)
    if mol is None:
        raise ValueError('Cannot read ligand for the interaction diagram')
    rdDepictor.Compute2DCoords(mol)
    Chem.Kekulize(mol, clearAromaticFlags=True)
    Chem.WedgeMolBonds(mol, mol.GetConformer())
    positions = mol.GetConformer().GetPositions()[:, :2] * [12, -12]
    center = positions.mean(axis=0)
    positions -= center
    atoms = [{'id': a.GetIdx(), 'element': a.GetSymbol(), 'label': None if a.GetSymbol() == 'C' else a.GetSymbol(),
              'charge': a.GetFormalCharge(), 'hydrogenCount': a.GetTotalNumHs(),
              'coordinates': dict(zip(('x', 'y'), positions[a.GetIdx()].tolist()))} for a in mol.GetAtoms()]
    bonds = []
    for bond in mol.GetBonds():
        kind = {Chem.BondType.SINGLE: 'single', Chem.BondType.DOUBLE: 'double', Chem.BondType.TRIPLE: 'triple'}[bond.GetBondType()]
        if bond.GetBondDir() == Chem.BondDir.BEGINWEDGE:
            kind = 'stereoFront'
        elif bond.GetBondDir() == Chem.BondDir.BEGINDASH:
            kind = 'stereoBack'
        bonds.append({'id': bond.GetIdx(), 'from': bond.GetBeginAtomIdx(), 'to': bond.GetEndAtomIdx(), 'type': kind})
    structures = [{'id': 0, 'structureName': 'Ligand', 'structureType': 'ligand', 'atoms': atoms, 'bonds': bonds}]
    residue_anchors = {}
    contacts = []
    for raw in details['contacts']:
        ids = raw['ligand_atom_ids']
        if not ids or any(type(index) is not int or index < 0 or index >= len(positions) for index in ids):
            raise ValueError('Interaction contains an invalid ligand atom endpoint')
        start = positions[ids].mean(axis=0)
        residue_anchors.setdefault(raw['residue_id'], []).append(start)
        contacts.append({**raw, 'start': dict(zip(('x', 'y'), start.tolist()))})
    residues = sorted(residue_anchors, key=lambda key: (math.atan2(*np.mean(residue_anchors[key], axis=0)[::-1]), key))
    radius = max(float(np.linalg.norm(positions, axis=1).max()) + 65, len(residues) * 48 / (2 * math.pi))
    offset = math.atan2(*np.mean(residue_anchors[residues[0]], axis=0)[::-1]) if residues else 0
    residue_positions = {}
    # ponytail: fixed perimeter layout avoids label overlaps; optimize edge crossings if crowded diagrams require it.
    for index, key in enumerate(residues):
        angle = offset + index * 2 * math.pi / len(residues)
        x, y = radius * math.cos(angle), radius * math.sin(angle)
        residue_positions[key] = np.array([x, y])
        chain, name, number, insertion = key.split('|')
        atom_id = len(atoms) + index
        structures.append({'id': index + 1, 'structureName': key, 'structureLabel': f'{name}{number}{insertion} {chain or "∅"}',
                           'structureType': 'residue', 'representation': 2, 'additionalInformation': {'residue_id': key},
                           'atoms': [{'id': atom_id, 'element': 'C', 'label': '', 'hydrogenCount': 0, 'coordinates': {'x': x, 'y': y}}],
                           'bonds': []})
    for contact in contacts:
        start = np.array(list(contact['start'].values()))
        end = residue_positions[contact['residue_id']]
        # Stop at the residue circle edge, preserving the exact ligand atom/group endpoint.
        end = end + (start - end) / np.linalg.norm(start - end) * 20
        contact['end'] = dict(zip(('x', 'y'), end.tolist()))
    return {'version': DIAGRAM_VERSION, 'plip_version': details['plip_version'],
            'scene': {'structures': structures}, 'interactions': contacts}


def diagram_cache_key(protein_hash, fingerprint, molecule_id, pose, details=None):
    signature = [DIAGRAM_VERSION, PLIP_VERSION, protein_hash, fingerprint, molecule_id, pose]
    if details:
        signature.extend([DETAILS_VERSION, details['input_fingerprint']])
    return hashlib.sha256(json.dumps(signature).encode()).hexdigest()


def write_diagram(payload, details):
    diagram = build_diagram(details)
    path = Path(payload['output_dir']) / f"{payload['cache_key']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(diagram, ensure_ascii=False, allow_nan=False))
    temporary.replace(path)
    return {'engine': 'tarpass', 'interaction_diagram': str(path), 'interaction_details': details}


def run_preview(payload):
    from genova_runtime.pdb2pqr_compat import file_sha256
    from tarpass.poses import PoseEvaluator, has_3d
    from genova_runtime.structure_index import named_record, molecule

    mol = molecule(named_record(payload['input_sdf'], payload['molecule_id']))
    if not has_3d(mol):
        raise ValueError('The selected record requires a valid 3D pose')
    protein_hash = file_sha256(payload['protein_pdb'])
    fingerprint = molecule_fingerprint(mol)
    if protein_hash != payload['protein_sha256'] or fingerprint != payload['input_fingerprint']:
        raise ValueError('The input structure changed; reopen the interaction diagram')
    Path(payload['output_dir']).mkdir(parents=True, exist_ok=True)
    details = payload.get('details')
    if not details:
        evaluator = PoseEvaluator(payload['protein_pdb'], None, [], payload['output_dir'])
        output = evaluator.interactions(mol)
        if not output.get('interaction_details'):
            raise ValueError(output.get('diagram_error', 'PLIP atom mapping is unavailable'))
        details = output['interaction_details']
    result = write_diagram(payload, details)
    key = diagram_cache_key(protein_hash, fingerprint, payload['molecule_id'], payload['pose'], details)
    if key != payload['cache_key']:
        # Publish both keys before result writeback so an in-flight poll can use either snapshot.
        write_diagram({**payload, 'cache_key': key}, details)
    return result
