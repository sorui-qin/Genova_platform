import tempfile
from pathlib import Path

import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem, rdShapeHelpers
from rdkit.Chem.MolStandardize.rdMolStandardize import Uncharger
from scipy.spatial.distance import cdist
from posebusters import check_intermolecular_distance
from plip.structure.preparation import PDBComplex

from tarpass.electrostatics import GaussInt
from tarpass.sucos import get_sucos_score, FACTORY, KEEP
from tarpass.contracts import residue_id
from tarpass.interactions import INTERACTION_FIELDS
from genova_runtime.pdb2pqr_compat import file_sha256





def read_ligand(path):
    path = Path(path)
    if path.suffix.lower() == '.sdf':
        mol = next(iter(Chem.SDMolSupplier(str(path), removeHs=False)), None)
    elif path.suffix.lower() == '.mol2':
        mol = Chem.MolFromMol2File(str(path), removeHs=False)
    else:
        mol = Chem.MolFromMolFile(str(path), removeHs=False)
    if mol is None or not has_3d(mol):
        raise ValueError('Reference ligand requires a valid 3D conformation')
    return mol


def has_3d(mol):
    return bool(mol is not None and mol.GetNumAtoms() and mol.GetNumConformers() and mol.GetConformer().Is3D() and np.isfinite(mol.GetConformer().GetPositions()).all())


def charge_data(mol):
    charged = Chem.AddHs(Uncharger().uncharge(Chem.RemoveHs(mol)), addCoords=True)
    props = AllChem.MMFFGetMoleculeProperties(charged)
    if props is None:
        raise ValueError('MMFF charges unavailable')
    coords = charged.GetConformer().GetPositions()
    charges = np.array([props.GetMMFFPartialCharge(i) for i in range(charged.GetNumAtoms())])
    return coords, charges, GaussInt(cdist(coords, coords), charges, charges)


class PoseEvaluator:
    def __init__(self, protein_path, reference_path, rules, work_dir):
        self.protein_sha256 = file_sha256(protein_path)
        self.protein = Chem.MolFromPDBFile(str(protein_path), sanitize=False, removeHs=False)
        if self.protein is None:
            raise ValueError('Cannot read prepared receptor')
        self.rules, self.work_dir = rules, work_dir
        self.reference = read_ligand(reference_path) if reference_path else None
        self.reference_heavy = Chem.RemoveHs(self.reference) if self.reference is not None else None
        self.reference_features = [f for f in FACTORY.GetFeaturesForMol(self.reference_heavy) if f.GetFamily() in KEEP] if self.reference is not None else None
        self.reference_shape = Uncharger().uncharge(self.reference_heavy) if self.reference is not None else None
        self.reference_center = self.reference_heavy.GetConformer().GetPositions().mean(0) if self.reference is not None else None
        self.ref_charge, self.ref_charge_error = None, None
        if self.reference is not None:
            try:
                self.ref_charge = charge_data(self.reference)
            except ValueError as exc:
                self.ref_charge_error = str(exc)
        # PLIP omits insertion codes: uniquely renumber its private receptor copy.
        self.residue_map, indices, lines = {}, {}, []
        for line in Path(protein_path).read_text().splitlines():
            if not line.startswith(('ATOM  ', 'HETATM')):
                continue
            key = f'{line[21:22].strip()}|{line[17:20].strip()}|{int(line[22:26])}|{line[26:27].strip()}'
            index = indices.setdefault(key, len(indices) + 1)
            if index > 9999:
                raise ValueError('PLIP receptor exceeds PDB residue numbering capacity')
            self.residue_map[index] = key
            lines.append(line[:21] + 'A' + f'{index:4d}' + ' ' + line[27:])
        self.protein_text = '\n'.join(lines) + '\nTER\n'

    def interactions(self, mol):
        ligand = Uncharger().uncharge(Chem.RemoveHs(mol))
        for index, atom in enumerate(ligand.GetAtoms()):
            info = Chem.AtomPDBResidueInfo()
            info.SetName(f'{atom.GetSymbol()}{index + 1}'.rjust(4)[:4])
            info.SetResidueName('UNL')
            info.SetResidueNumber(1)
            info.SetChainId('Z')
            info.SetIsHeteroAtom(True)
            atom.SetMonomerInfo(info)
        ligand_lines = [line for line in Chem.MolToPDBBlock(ligand).splitlines() if line.startswith(('HETATM', 'CONECT'))]
        # Let OpenBabel assign unique atom serials across the combined complex.
        protein_lines = self.protein_text.splitlines()
        max_serial = max(int(line[6:11]) for line in protein_lines if line.startswith(('ATOM  ', 'HETATM')))
        adjusted = []
        for line in ligand_lines:
            if line.startswith('HETATM'):
                serial = int(line[6:11]) + max_serial
                if serial > 99999:
                    raise ValueError('Complex exceeds PDB atom numbering capacity')
                adjusted.append(line[:6] + f'{serial:5d}' + line[11:])
            else:
                adjusted.append('CONECT' + ''.join(f'{int(line[i:i+5]) + max_serial:5d}' for i in range(6, len(line), 5) if line[i:i+5].strip()))
        with tempfile.TemporaryDirectory(dir=self.work_dir, prefix='plip-') as tmp:
            pdb = Path(tmp) / 'complex.pdb'
            pdb.write_text(self.protein_text + '\n'.join(adjusted) + '\nEND\n')
            analyzer = PDBComplex()
            analyzer.output_path = tmp
            analyzer.load_pdb(str(pdb))
            target = next((lig for lig in analyzer.ligands if lig.hetid == 'UNL' and lig.chain == 'Z' and int(lig.position) == 1), None)
            if target is None:
                raise ValueError('PLIP could not identify the evaluated ligand')
            analyzer.characterize_complex(target)
            detected = analyzer.interaction_sets[f'{target.hetid}:{target.chain}:{target.position}']
            interactions = {name: sorted({self.residue_map[item.resnr] for item in getattr(detected, field) if item.reschain == 'A' and item.resnr in self.residue_map}) for name, field in INTERACTION_FIELDS.items()}
            from tarpass.interactions import extract_details
            try:
                diagram = {'interaction_details': extract_details(mol, ligand, analyzer, detected, self.residue_map, self.protein_sha256)}
            except Exception as exc:
                diagram = {'diagram_error': str(exc)}
        interactions['H-Bond'] = sorted(set(interactions['H-Bond donor'] + interactions['H-Bond acceptor'] + interactions['Salt Bridge lneg'] + interactions['Salt Bridge pneg']))
        interactions['Hydrophobic contact'] = sorted(set(interactions['Hydrophobic contact'] + interactions['Pi-stacking']))
        matched = []
        for rule in self.rules:
            wanted = {residue_id(r) for r in rule['residues']}
            found = set(interactions[rule['interaction_type']])
            matched.append(wanted <= found if rule['match_mode'] == 'all' else bool(wanted & found))
        return {**diagram, 'detected_interactions': interactions, 'matched_details': matched,
                'matched_rate': sum(matched) / len(matched) if matched else None,
                'fully_matched': all(matched) if matched else None}

    def evaluate(self, mol):
        result, errors = {}, {}
        checks = {
            'no_clashes': lambda: check_intermolecular_distance(mol, mol_cond=self.protein)['results']['no_clashes'],
            'volume': lambda: AllChem.ComputeMolVolume(Chem.AddHs(mol, addCoords=True)),
        }
        if self.reference is not None:
            checks.update({
                'sucos': lambda: get_sucos_score(self.reference_heavy, Chem.RemoveHs(mol), heavy_only=None, reference_features=self.reference_features),
                'shape_similarity': lambda: 1 - rdShapeHelpers.ShapeTanimotoDist(Uncharger().uncharge(Chem.RemoveHs(mol)), self.reference_shape),
                'centroid_shift': lambda: float(np.linalg.norm(Chem.RemoveHs(mol).GetConformer().GetPositions().mean(0) - self.reference_center)),
                'electrostatic_similarity': lambda: self.esp(mol),
            })
        for name, fn in checks.items():
            try:
                result[name] = fn()
            except Exception as exc:
                result[name], errors[name] = None, str(exc)
        if self.reference is None:
            result['unavailable'] = {key: 'Missing reference ligand' for key in ('sucos', 'shape_similarity', 'centroid_shift', 'electrostatic_similarity')}
            result.update({key: None for key in result['unavailable']})
        try:
            result.update(self.interactions(mol))
        except Exception as exc:
            errors['interactions'] = str(exc)
            result.update(matched_rate=None, fully_matched=None)
        result['errors'] = errors
        return result

    def esp(self, mol):
        if self.ref_charge is None:
            raise ValueError(self.ref_charge_error)
        coords, charges, own = charge_data(mol)
        ref_coords, ref_charges, ref_own = self.ref_charge
        denominator = np.sqrt(own * ref_own)
        return float((GaussInt(cdist(coords, ref_coords), charges, ref_charges) / denominator + 1) / 2) if denominator else None
