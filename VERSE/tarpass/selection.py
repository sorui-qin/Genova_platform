import math

import numpy as np
from rdkit import Chem, DataStructs
from rdkit.Chem import rdDepictor
from rdkit.Chem.rdFingerprintGenerator import GetMorganGenerator
from rdkit.Chem.Scaffolds import MurckoScaffold
from rdkit.ML.Cluster import Butina

from tarpass.filters import metric_value


CLUSTER_FIELDS = ('cluster_id', 'cluster_size', 'cluster_record_count', 'is_representative')
FP = GetMorganGenerator(radius=2, fpSize=2048)
MAX_CLUSTER_STRUCTURES = 2000


def cluster_rows(rows, options, sort_by):
    structures, row_keys = {}, {}
    for row in rows:
        row.update(cluster_id=None, cluster_size=None, cluster_record_count=None, is_representative=False)
        if row.get('status') == 'invalid':
            continue
        mol = Chem.MolFromSmiles(row['smiles']) if row['smiles'] else None
        if mol is None or not mol.GetNumAtoms():
            continue
        mol = Chem.RemoveHs(mol)
        key = Chem.MolToSmiles(mol)
        structures.setdefault(key, mol)
        row_keys[row['molecule_id']] = key
        if len(structures) > MAX_CLUSTER_STRUCTURES:
            raise ValueError('Clustering supports at most 2000 distinct structures; narrow the result filters first')

    keys, fingerprints, groups = [], [], []
    for key, mol in sorted(structures.items()):
        if options['basis'] == 'scaffold':
            mol = MurckoScaffold.GetScaffoldForMol(mol)
        if not mol.GetNumAtoms():
            groups.append([key])
        else:
            keys.append(key)
            fingerprints.append(FP.GetFingerprint(mol))
    if keys:
        # ponytail: quadratic distances capped at 2000 structures; use background clustering for larger sets.
        distances = np.concatenate([
            1 - np.asarray(DataStructs.BulkTanimotoSimilarity(fp, fingerprints[:i]))
            for i, fp in enumerate(fingerprints) if i
        ]) if len(keys) > 1 else []
        groups.extend([keys[i] for i in group] for group in Butina.ClusterData(
            distances, len(keys), 1 - options['similarity_threshold'], isDistData=True, reordering=True,
        ))
    groups.sort(key=lambda group: min(group))
    memberships = {key: index for index, group in enumerate(groups, 1) for key in group}
    members = {index: [] for index in range(1, len(groups) + 1)}
    for row in rows:
        key = row_keys.get(row['molecule_id'])
        if key is not None:
            members[memberships[key]].append(row)
    for index, group in enumerate(groups, 1):
        chosen = set()
        for row in members[index]:
            row.update(cluster_id=index, cluster_size=len(group), cluster_record_count=len(members[index]))
            value = metric_value(row, sort_by) if sort_by != 'molecule_id' else 0
            key = row_keys[row['molecule_id']]
            if (isinstance(value, (int, float)) and math.isfinite(value)
                    and key not in chosen and len(chosen) < options['representatives_per_cluster']):
                row['is_representative'] = True
                chosen.add(key)
    summary = {
        **options, 'cluster_count': len(groups), 'structure_count': len(structures),
        'record_count': len(rows), 'unclustered_count': len(rows) - len(row_keys),
        'representative_count': sum(row['is_representative'] for row in rows),
    }
    return ([row for row in rows if row['is_representative']] if options['representatives_only'] else rows), summary


def edit_preview(fragment, molecule):
    fragment, molecule = Chem.RemoveHs(Chem.Mol(fragment)), Chem.RemoveHs(Chem.Mol(molecule))
    for mol in (fragment, molecule):
        if not mol.GetNumConformers() or not mol.GetConformer().Is3D():
            raise ValueError('Edit comparison requires original 3D coordinates')
    source, target = fragment.GetConformer().GetPositions(), molecule.GetConformer().GetPositions()
    distances = np.linalg.norm(source[:, None, :] - target[None, :, :], axis=2)
    elements = np.array([atom.GetAtomicNum() for atom in molecule.GetAtoms()])
    matches = [np.flatnonzero((distances[i] <= 0.01) & (elements == atom.GetAtomicNum()))
               for i, atom in enumerate(fragment.GetAtoms())]
    if any(len(match) != 1 for match in matches):
        raise ValueError('Retained fragment has no unambiguous coordinate mapping')
    retained = [int(match[0]) for match in matches]
    if len(set(retained)) != len(retained):
        raise ValueError('Retained fragment coordinate mapping is not one-to-one')
    reverse = {target: source for source, target in enumerate(retained)}
    expected = {(min(b.GetBeginAtomIdx(), b.GetEndAtomIdx()), max(b.GetBeginAtomIdx(), b.GetEndAtomIdx()), str(b.GetBondType()))
                for b in fragment.GetBonds()}
    actual = {(min(reverse[b.GetBeginAtomIdx()], reverse[b.GetEndAtomIdx()]),
               max(reverse[b.GetBeginAtomIdx()], reverse[b.GetEndAtomIdx()]), str(b.GetBondType()))
              for b in molecule.GetBonds() if b.GetBeginAtomIdx() in reverse and b.GetEndAtomIdx() in reverse}
    if expected != actual:
        raise ValueError('Retained fragment bonds do not match')
    rdDepictor.Compute2DCoords(molecule)
    return {'molfile': Chem.MolToMolBlock(molecule), 'retained_atom_indices': retained,
            'changed_atom_indices': sorted(set(range(molecule.GetNumAtoms())) - set(retained))}
