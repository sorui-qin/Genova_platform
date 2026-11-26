import csv
import io
from rdkit import Chem


def source_records(payload):
    if payload.get('input_sdf'):
        yield from records(payload['input_sdf'], remove_hs=False)
    else:
        with open(payload['input_csv'], newline='', encoding='utf-8-sig') as stream:
            reader = csv.DictReader(stream)
            if 'smiles' not in (reader.fieldnames or []):
                raise ValueError('Source CSV requires a smiles column')
            for row in reader:
                yield Chem.MolFromSmiles((row.get('smiles') or '').strip())


def records(path, remove_hs=True):
    # Enumerate physical records: RDKit can silently omit short malformed records.
    with open(path, 'rb') as stream:
        block = bytearray()
        for line in stream:
            block.extend(line)
            if line.strip() == b'$$$$':
                yield next(Chem.ForwardSDMolSupplier(io.BytesIO(block), removeHs=remove_hs), None)
                block = bytearray()
        if block.strip():
            yield next(Chem.ForwardSDMolSupplier(io.BytesIO(block), removeHs=remove_hs), None)
