import tempfile
from pathlib import Path


def source_ligand_from_ccd(component, connections, cache_root):
    import hashlib
    import re
    from io import StringIO
    from urllib.request import urlopen
    from Bio.PDB.MMCIF2Dict import MMCIF2Dict
    from rdkit import Chem

    atoms = component['atoms']
    name = atoms[0]['residue_name']
    if not re.fullmatch(r'[A-Z0-9]{1,5}', name) or any(a['residue_name'] != name for a in atoms):
        raise ValueError('Source component has no unambiguous CCD identifier')
    url = f'https://files.rcsb.org/ligands/download/{name}.cif'
    cache = Path(cache_root)
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f'{name}.cif'
    content = path.read_bytes() if path.is_file() else None
    if content is None:
        with urlopen(url, timeout=20) as response:
            content = response.read(2 * 1024 * 1024 + 1)
        if len(content) > 2 * 1024 * 1024:
            raise ValueError('CCD definition exceeds size limit')
    data = MMCIF2Dict(StringIO(content.decode('utf-8')))
    if data.get('_chem_comp.id') != [name]:
        raise ValueError('CCD component identity mismatch')
    if not {'_chem_comp_atom.atom_id', '_chem_comp_atom.type_symbol', '_chem_comp_atom.charge'} <= data.keys():
        raise ValueError('CCD definition has no complete atom chemistry')
    atom_columns = [data[key] for key in ('_chem_comp_atom.atom_id', '_chem_comp_atom.type_symbol', '_chem_comp_atom.charge')]
    if len({len(column) for column in atom_columns}) != 1:
        raise ValueError('CCD atom columns have inconsistent lengths')
    definitions = {key: (element.upper(), int(charge)) for key, element, charge in zip(*atom_columns)}
    names = {a['atom_name']: i for i, a in enumerate(atoms)}
    if len(names) != len(atoms):
        raise ValueError('Duplicate source atom names prevent CCD mapping')
    if {a['atom_name'] for a in atoms if a['element'] not in {'H', 'D'}} != {key for key, (element, _) in definitions.items() if element not in {'H', 'D'}}:
        raise ValueError('Source ligand heavy atom coverage differs from CCD definition')
    molecule = Chem.RWMol()
    conformer = Chem.Conformer(len(atoms))
    conformer.Set3D(True)
    for i, source in enumerate(atoms):
        if source['atom_name'] not in definitions or definitions[source['atom_name']][0] != source['element']:
            raise ValueError('Source atom name or element mismatch with CCD definition')
        element, charge = definitions[source['atom_name']]
        atom = Chem.Atom(element.title())
        atom.SetFormalCharge(charge)
        atom.SetNoImplicit(True)
        molecule.AddAtom(atom)
        conformer.SetAtomPosition(i, source['coordinates'])
    orders = {'SING': Chem.BondType.SINGLE, 'DOUB': Chem.BondType.DOUBLE, 'TRIP': Chem.BondType.TRIPLE,
              'AROM': Chem.BondType.AROMATIC}
    bond_columns = [data.get(key, []) for key in ('_chem_comp_bond.atom_id_1', '_chem_comp_bond.atom_id_2', '_chem_comp_bond.value_order')]
    if len({len(column) for column in bond_columns}) != 1:
        raise ValueError('CCD bond columns have inconsistent lengths')
    for left, right, order in zip(*bond_columns):
        if order not in orders:
            raise ValueError(f'Unsupported CCD bond order: {order}')
        if left in names and right in names:
            molecule.AddBond(names[left], names[right], orders[order])
        else:
            for present, missing in ((left, right), (right, left)):
                if present in names and definitions[missing][0] == 'H':
                    atom = molecule.GetAtomWithIdx(names[present])
                    atom.SetNumExplicitHs(atom.GetNumExplicitHs() + 1)
    source_indices = {a['atom_id']: i for i, a in enumerate(atoms)}
    for link in connections:
        if all(key in source_indices for key in link['atom_ids']):
            if molecule.GetBondBetweenAtoms(*(source_indices[key] for key in link['atom_ids'])) is None:
                raise ValueError('Source connection disagrees with CCD definition')
    molecule.AddConformer(conformer)
    molecule = molecule.GetMol()
    Chem.SanitizeMol(molecule)
    Chem.AssignStereochemistryFrom3D(molecule)
    if not path.is_file():
        with tempfile.TemporaryDirectory(dir=cache) as temporary:
            downloaded = Path(temporary) / path.name
            downloaded.write_bytes(content)
            downloaded.replace(path)
    return molecule, {'component_id': name, 'url': url, 'sha256': hashlib.sha256(content).hexdigest()}
