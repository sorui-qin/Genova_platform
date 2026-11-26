"""Batch scoring shared with EPSO's TarPass environment."""

import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from rdkit import Chem, rdBase

from tarpass.contracts import gnina_command
from tarpass.pipeline import evaluate_volume, prepare_and_evaluate, read_docking


def prepare(item):
    identity, smiles, ph = item
    mol = Chem.MolFromSmiles(smiles)
    block, _, error = evaluate_volume(Chem.MolToMolBlock(mol))
    if block is None:
        return None, error
    prepared, _, error = prepare_and_evaluate((identity, block, ph, False))
    return prepared, error


def score_batch(smiles, inputs, descriptor):
    cpus = min(8, len(os.sched_getaffinity(0)))
    items = [(f'epso-{index}', value, inputs['ph']) for index, value in enumerate(smiles)]
    scores = {}
    with tempfile.TemporaryDirectory(prefix='epso-docking-') as directory:
        work = Path(directory)
        input_path, output_path = work / 'input.sdf', work / 'output.sdf'
        log_path = work / 'gnina.log'
        for offset in range(0, len(items), 64):
            batch = items[offset:offset + 64]
            ready = {}
            with ProcessPoolExecutor(max_workers=min(cpus, len(batch))) as pool, Chem.SDWriter(str(input_path)) as writer:
                for (identity, value, _), (block, error) in zip(batch, pool.map(prepare, batch)):
                    if error:
                        scores[value] = {'error': f'Ligand preparation failed: {error}'}
                        continue
                    mol = Chem.MolFromMolBlock(block, removeHs=False)
                    mol.SetProp('_Name', identity)
                    mol.SetProp('molecule_id', identity)
                    writer.write(mol)
                    ready[identity] = value
            if not ready:
                continue
            output_path.unlink(missing_ok=True)
            command = gnina_command(inputs, input_path, output_path, 'docked', cpus)
            with log_path.open('w') as log:
                completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, pass_fds=descriptor)
            if completed.returncode:
                raise RuntimeError(f'Gnina exited with code {completed.returncode}: {log_path.read_text()[-4000:]}')
            if not output_path.is_file():
                raise RuntimeError('Gnina did not create a batch output file')
            results = read_docking(output_path, ready, allow_unscored=True)
            for identity, value in ready.items():
                scores[value] = (
                    {'energy': results[identity][1]['affinity']} if identity in results
                    else {'error': 'Gnina did not return a finite minimizedAffinity'}
                )
    return {'scores': scores}


def main():
    request = json.load(sys.stdin)
    descriptor = (int(sys.argv[1]),) if len(sys.argv) > 1 else ()
    result = score_batch(request['smiles'], request['inputs'], descriptor)
    if request.get('include_versions'):
        from openbabel import openbabel

        command = gnina_command(request['inputs'], 'input.sdf', 'output.sdf', 'docked', min(8, len(os.sched_getaffinity(0))))
        result['versions'] = {
            'gnina': subprocess.check_output([command[0], '--version'], text=True).strip(),
            'rdkit': rdBase.rdkitVersion,
            'openbabel': openbabel.OBReleaseVersion(),
        }
        result['gnina_options'] = command[7:]
    json.dump(result, sys.stdout, allow_nan=False)


if __name__ == '__main__':
    main()
