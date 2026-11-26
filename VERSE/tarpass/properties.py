import importlib.util
from itertools import combinations
from pathlib import Path
import networkx as nx
from rdkit import Chem, DataStructs, RDConfig
from rdkit.Chem import Crippen, Descriptors, QED, rdMolDescriptors, FilterCatalog, GraphDescriptors, SpacialScore
from rdkit.Chem.rdFingerprintGenerator import GetMorganGenerator
from rdkit.Chem.Scaffolds import MurckoScaffold
from tarpass.sdf import records as sdf_records

_spec = importlib.util.spec_from_file_location('sascorer', Path(RDConfig.RDContribDir) / 'SA_Score' / 'sascorer.py')
sascorer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sascorer)


FP = GetMorganGenerator(radius=2, fpSize=2048)
CATALOGS = {}
for name, kind in [('pains_alert', 'PAINS'), ('surechembl_alert', 'CHEMBL_SureChEMBL'), ('glaxo_alert', 'CHEMBL_Glaxo')]:
    params = FilterCatalog.FilterCatalogParams()
    params.AddCatalog(getattr(FilterCatalog.FilterCatalogParams.FilterCatalogs, kind))
    CATALOGS[name] = FilterCatalog.FilterCatalog(params)


def properties(mol, errors=None):
    mol = Chem.MolFromSmiles(Chem.MolToSmiles(Chem.RemoveHs(mol)))
    ring_info = mol.GetRingInfo()
    rings = ring_info.AtomRings()
    fused = nx.Graph()
    fused.add_edges_from((i, j) for i, j in combinations(range(len(rings)), 2) if ring_info.AreRingsFused(i, j))
    fused_sizes = [len(component) for component in nx.connected_components(fused)]
    values = {
        'ring_count': len(rings),
        'largest_ring': max(map(len, rings), default=0), 'unusual_rings': sum(not 5 <= len(ring) <= 7 for ring in rings),
        'fused_systems': nx.number_connected_components(fused), 'complete': len(Chem.GetMolFrags(mol)) == 1,
        'all_common': all(atom.GetSymbol() in {'C', 'H', 'O', 'N', 'F', 'Cl', 'Br', 'I', 'P', 'S', 'B'} for atom in mol.GetAtoms()),
        'highly_fused': max(fused_sizes, default=0) >= 3,
        'rings_in_fused_system': sum(fused_sizes),
        'unusual_ring_present': any(not 5 <= len(ring) <= 7 for ring in rings),
        'fused_ring_present': bool(fused_sizes),
    }
    checks = {
        'qed': QED.qed, 'sa_score': sascorer.calculateScore,
        'logp': Crippen.MolLogP, 'molecular_weight': Descriptors.MolWt,
        'exact_molecular_weight': rdMolDescriptors.CalcExactMolWt,
        'tpsa': rdMolDescriptors.CalcTPSA, 'hbd': rdMolDescriptors.CalcNumHBD,
        'hba': rdMolDescriptors.CalcNumHBA, 'rotatable_bonds': rdMolDescriptors.CalcNumRotatableBonds,
        'heavy_atoms': lambda m: m.GetNumHeavyAtoms(), 'heteroatoms': rdMolDescriptors.CalcNumHeteroatoms,
        'csp3': rdMolDescriptors.CalcFractionCSP3, 'spiro_atoms': rdMolDescriptors.CalcNumSpiroAtoms,
        'chiral_atoms': lambda m: len(Chem.FindMolChiralCenters(m, includeUnassigned=True)),
        'morgan_fragments': lambda m: len(FP.GetSparseCountFingerprint(m).GetNonzeroElements()),
        'bertz_ct': GraphDescriptors.BertzCT, 'spacial_score': SpacialScore.SPS, 'torsion_count': torsion_count,
        **{name: catalog.HasMatch for name, catalog in CATALOGS.items()},
        'lipinski_violations': lambda m: sum([values['molecular_weight'] > 500, values['logp'] > 5, values['hbd'] > 5, values['hba'] > 10]),
        'heteroatom_ratio': lambda m: values['heteroatoms'] / values['heavy_atoms'],
        'flexibility': lambda m: values['rotatable_bonds'] / max(1, values['heavy_atoms'] - 1 - values['rotatable_bonds']),
    }
    for name, calculate in checks.items():
        try:
            values[name] = calculate(mol)
        except Exception as exc:
            values[name] = None
            if errors is not None:
                errors[name] = str(exc)
    return values


def torsion_count(mol):
    count = 0
    for j, k in mol.GetSubstructMatches(Chem.MolFromSmarts('[!$(*#*)&!D1]-&!@[!$(*#*)&!D1]')):
        first = next(atom.GetIdx() for atom in mol.GetAtomWithIdx(j).GetNeighbors() if atom.GetIdx() != k)
        count += any(atom.GetIdx() not in (j, first) for atom in mol.GetAtomWithIdx(k).GetNeighbors())
    return count


def reference_fingerprints(path):
    if not path:
        return []
    if str(path).lower().endswith('.sdf'):
        records = sdf_records(path)
    else:
        with open(path) as stream:
            records = [Chem.MolFromSmiles(line.split()[0]) if line.strip() else None for line in stream]
    result = []
    for index, mol in enumerate(records):
        if mol is None or not mol.GetNumAtoms():
            continue
        scaffold = MurckoScaffold.GetScaffoldForMol(mol)
        result.append((index, Chem.MolToSmiles(mol), FP.GetFingerprint(mol), FP.GetFingerprint(scaffold) if scaffold.GetNumAtoms() else None))
    if not result:
        raise ValueError('Reference dataset contains no valid molecules')
    return result


def nearest_reference(mol, references):
    scaffold = MurckoScaffold.GetScaffoldForMol(mol)
    query = [FP.GetFingerprint(mol), FP.GetFingerprint(scaffold) if scaffold.GetNumAtoms() else None]
    result = {}
    for slot, name in enumerate(('reference_similarity', 'scaffold_similarity')):
        best, match = -1.0, None
        if query[slot] is not None:
            for offset in range(0, len(references), 4096):
                chunk = [r for r in references[offset:offset + 4096] if r[slot + 2] is not None]
                if not chunk:
                    continue
                scores = DataStructs.BulkTanimotoSimilarity(query[slot], [r[slot + 2] for r in chunk])
                index = max(range(len(scores)), key=scores.__getitem__)
                if scores[index] > best:
                    best, match = scores[index], chunk[index]
        result[name] = best if match else None
        result[name + '_match'] = {'index': match[0], 'smiles': match[1]} if match else None
    return result
