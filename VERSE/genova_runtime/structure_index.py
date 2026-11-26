"""Rebuildable offsets into immutable job SDF artifacts."""
import fcntl
import io
import json
import os
from functools import lru_cache
from pathlib import Path

from rdkit import Chem


def file_version(path):
    stat = Path(path).stat()
    return (stat.st_ino, stat.st_size, stat.st_mtime_ns)


@lru_cache(maxsize=16)
def _digest(path, version):
    from genova_runtime.pdb2pqr_compat import file_sha256
    return file_sha256(path)


def file_digest(path):
    return _digest(str(path), file_version(path))


def molecule(block):
    return next(Chem.ForwardSDMolSupplier(io.BytesIO(block), removeHs=False), None)


@lru_cache(maxsize=4)
def _index(path, version):
    # ponytail: four in-process manifests; move metadata to indexed storage if artifacts grow beyond tens of thousands of records.
    source = Path(path)
    sidecar = source.with_name(source.name + '.index.json')
    signature = [1, *version]
    with open(str(sidecar) + '.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if sidecar.is_file():
            stored = json.loads(sidecar.read_text())
            if stored['version'] == signature:
                return stored
        entries, names, smiles = [], {}, {}
        with source.open('rb') as stream:
            start, chunks = 0, []
            while line := stream.readline():
                chunks.append(line)
                if line.strip() != b'$$$$':
                    continue
                block = b''.join(chunks)
                mol = molecule(block)
                key = Chem.MolToSmiles(Chem.RemoveHs(mol)) if mol is not None else ''
                name = mol.GetProp('_Name') if mol is not None else block.splitlines()[0].decode('utf-8', errors='replace')
                index = len(entries)
                entries.append({'source_index': index, 'offset': start, 'length': stream.tell() - start, 'name': name, 'smiles': key})
                names.setdefault(name, []).append(index)
                if key:
                    smiles.setdefault(key, []).append(index)
                start, chunks = stream.tell(), []
            if chunks and b''.join(chunks).strip():
                block = b''.join(chunks)
                mol = molecule(block)
                key = Chem.MolToSmiles(Chem.RemoveHs(mol)) if mol is not None else ''
                name = mol.GetProp('_Name') if mol is not None else ''
                index = len(entries)
                entries.append({'source_index': index, 'offset': start, 'length': len(block), 'name': name, 'smiles': key})
                names.setdefault(name, []).append(index)
                if key:
                    smiles.setdefault(key, []).append(index)
        if file_version(source) != version:
            raise ValueError('The structure artifact changed while indexing; retry')
        stored = {'version': signature, 'records': entries, 'names': names, 'smiles': smiles}
        temporary = sidecar.with_suffix('.tmp')
        temporary.write_text(json.dumps(stored, separators=(',', ':')))
        os.replace(temporary, sidecar)
        return stored


def structure_index(path):
    return _index(str(Path(path).resolve()), file_version(path))


def read_record(path, source_index):
    records = structure_index(path)['records']
    if source_index < 0 or source_index >= len(records):
        raise ValueError('Structure record not found')
    entry = records[source_index]
    with open(path, 'rb') as stream:
        stream.seek(entry['offset'])
        return stream.read(entry['length'])


def named_record(path, name):
    indices = structure_index(path)['names'].get(name, [])
    if len(indices) != 1:
        raise ValueError('The selected structure record is missing or ambiguous')
    return read_record(path, indices[0])
