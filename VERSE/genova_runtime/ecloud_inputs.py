import argparse
import json
import os
import random
import sys
from pathlib import Path


def build_inputs(protein, reference, target, seed, *, center=None):
    import numpy as np
    from rdkit import Chem
    root = Path(os.environ.get('ECLOUDGEN_ROOT', '/app'))
    sys.path.insert(0, str(root))
    from utils.chem import pocket_trunction
    from utils.protein_ligand import get_pocket_channel, protocol
    random.seed(seed)
    np.random.seed(seed)
    if reference:
        from genova_runtime.entry_protein_preparation import _load_ligand
        ligand = _load_ligand(Path(reference), sanitize=False)
        centroid = ligand.GetConformer().GetPositions()[[a.GetIdx() for a in ligand.GetAtoms() if a.GetAtomicNum() > 1]].mean(axis=0)
    else:
        centroid = np.asarray(center)
    pocket_path = Path(pocket_trunction(str(protein), centroid=centroid, outname=str(Path(target).parent / 'pocket_input.pdb')))
    molecule = Chem.MolFromPDBFile(str(pocket_path))
    if molecule is None or not molecule.GetNumHeavyAtoms():
        raise ValueError('ECloudGen pocket parser did not produce a valid heavy-atom structure')
    channel, _, _ = get_pocket_channel(molecule, grid_protocol=protocol(32))
    if channel.shape != (32, 32, 32, 5):
        raise ValueError('ECloudGen feature dimensions differ from the installed builder contract')
    if not np.isfinite(channel).all() or not np.any(channel[:, :, :, 4]):
        raise ValueError('ECloudGen pocket occupancy is missing or non-finite')
    np.savez(target, pkt_channel=channel)
    serials = [atom.GetPDBResidueInfo().GetSerialNumber() for atom in molecule.GetAtoms() if atom.GetPDBResidueInfo()]
    report = dict(version=1, builder_version='generation_auto_v1', occupancy_shape=list(channel.shape),
        pocket_center=centroid.tolist(), center_source='reference_ligand' if reference else 'binding_site',
        pocket_path=str(pocket_path), observed_tool_atom_serials=serials,
        feature_validation='passed', seed=seed)
    Path(target).with_suffix('.json').write_text(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--protein', required=True)
    location = parser.add_mutually_exclusive_group(required=True)
    location.add_argument('--reference')
    location.add_argument('--center', type=float, nargs=3)
    parser.add_argument('--output', required=True)
    parser.add_argument('--seed', type=int, required=True)
    args = parser.parse_args()
    build_inputs(args.protein, args.reference, args.output, args.seed, center=args.center)
