import csv
import importlib.metadata
import json
import math
import os
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from rdkit import Chem, rdBase
from rdkit.Chem import rdMolDescriptors, AllChem

from tarpass.filters import POSE_METRICS, METRICS, failed_filters, metric_value
from tarpass.contracts import gnina_command
from tarpass.poses import PoseEvaluator, has_3d
from tarpass.interactions import molecule_fingerprint
from tarpass.properties import properties, reference_fingerprints, nearest_reference
from tarpass.sdf import records, source_records
from genova_runtime.gpu_lock import gpu_lock


def initialize(payload):
    global EVALUATOR, REFERENCES, PAYLOAD
    PAYLOAD, EVALUATOR = payload, None
    REFERENCES = reference_fingerprints(payload.get('reference_dataset_path'))


def evaluator():
    global EVALUATOR
    if EVALUATOR is None:
        EVALUATOR = PoseEvaluator(PAYLOAD['protein_pdb'], PAYLOAD.get('reference_ligand'), PAYLOAD['key_interactions'], PAYLOAD['output_dir'])
    return EVALUATOR


def generate_conformation(mol):
    from openbabel import pybel
    from rdkit.Chem.MolStandardize.rdMolStandardize import Uncharger

    # TarPass LigPrep: RDKit/MMFF first, then Open Babel MMFF94.
    mol = Uncharger().uncharge(Chem.RemoveHs(mol))
    mol.RemoveAllConformers()
    mol = Chem.AddHs(mol)
    try:
        if AllChem.EmbedMolecule(mol, randomSeed=42, useRandomCoords=True, maxAttempts=1000) != 0:
            raise ValueError('RDKit embedding failed')
        if AllChem.MMFFOptimizeMolecule(mol, maxIters=200) != 0:
            raise ValueError('RDKit MMFF optimization failed')
    except Exception:
        mol.RemoveAllConformers()
        ligand = pybel.readstring('mol', Chem.MolToMolBlock(mol))
        ligand.make3D(forcefield='MMFF94', steps=50)
        ligand.localopt(forcefield='MMFF94', steps=200)
        mol = Chem.MolFromMolBlock(ligand.write('mol'), removeHs=False)
    if not has_3d(mol):
        raise ValueError('Conformation generation failed')
    return mol


def evaluate_volume(block):
    try:
        mol = Chem.MolFromMolBlock(block, removeHs=False)
        if not has_3d(mol):
            mol = generate_conformation(mol)
        block = Chem.MolToMolBlock(mol)
    except Exception as exc:
        return None, None, str(exc)
    try:
        return block, AllChem.ComputeMolVolume(Chem.AddHs(mol, addCoords=True)), None
    except Exception as exc:
        return block, None, str(exc)


def evaluate_properties(smiles):
    errors = {}
    try:
        mol = Chem.MolFromSmiles(smiles)
        values = properties(mol, errors)
        if REFERENCES:
            try:
                values.update(nearest_reference(mol, REFERENCES))
            except Exception as exc:
                errors['reference_similarity'] = str(exc)
        return values, errors
    except Exception as exc:
        return {}, {'properties': str(exc)}


def prepare_and_evaluate(item):
    molecule_id, block, ph, has_original_pose = item
    try:
        from openbabel import pybel
        if block is None:
            raise ValueError('No valid 3D conformation for ligand preparation')
        original = Chem.MolFromMolBlock(block, removeHs=False)
        ligand = pybel.readstring('mol', block)
        ligand.OBMol.AddHydrogens(False, True, ph)
        prepared = Chem.MolFromMolBlock(ligand.write('mol'), removeHs=False)
        if not has_3d(prepared):
            raise ValueError('Ligand preparation failed')
        before = Chem.RemoveHs(original).GetConformer().GetPositions()
        after = Chem.RemoveHs(prepared).GetConformer().GetPositions()
        if before.shape != after.shape or not np.allclose(before, after, atol=0.001):
            raise ValueError('Ligand preparation changed original heavy-atom coordinates')
        if [(a.GetAtomicNum(), a.GetIsotope()) for a in Chem.RemoveHs(original).GetAtoms()] != [(a.GetAtomicNum(), a.GetIsotope()) for a in Chem.RemoveHs(prepared).GetAtoms()]:
            raise ValueError('Ligand preparation changed original heavy-atom identities')
        prepared.SetProp('_Name', molecule_id)
        metrics = evaluator().evaluate(prepared) if has_original_pose else {}
        if metrics.get('interaction_details'):
            metrics['interaction_details']['source_input_fingerprint'] = molecule_fingerprint(original)
        return Chem.MolToMolBlock(prepared), metrics, None
    except Exception as exc:
        return None, {}, str(exc)


def evaluate_pose(block):
    return evaluator().evaluate(Chem.MolFromMolBlock(block, removeHs=False))


def clean(value):
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    return None if isinstance(value, float) and not math.isfinite(value) else value


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(clean(value), ensure_ascii=False, allow_nan=False, indent=2))
    temporary.replace(path)


def read_docking(path, expected, *, allow_unscored=False):
    result, seen = {}, set()
    for mol in records(path, remove_hs=False):
        if mol is None:
            raise ValueError('Gnina produced an unreadable SDF record')
        molecule_id = mol.GetProp('_Name')
        if molecule_id not in expected or molecule_id in seen:
            raise ValueError('Gnina returned an unexpected or duplicate molecule ID')
        seen.add(molecule_id)
        if allow_unscored:
            try:
                energy = float(mol.GetProp('minimizedAffinity'))
            except (KeyError, ValueError):
                continue
            if math.isfinite(energy):
                result[molecule_id] = (mol, {'affinity': energy})
            continue
        scores = {}
        for prop, key in [('minimizedAffinity', 'affinity'), ('CNNscore', 'cnn_score'), ('CNNaffinity', 'cnn_affinity')]:
            scores[key] = float(mol.GetProp(prop)) if mol.HasProp(prop) else None
        if scores['affinity'] is None or not math.isfinite(scores['affinity']):
            raise ValueError('Gnina did not return a finite affinity')
        score = scores['affinity']
        scores['le_heavyatom'] = abs(score) / mol.GetNumHeavyAtoms() if score < 0 else None
        scores['le_mw'] = abs(score) / rdMolDescriptors.CalcExactMolWt(mol) if score < 0 else None
        mol.SetProp('molecule_id', molecule_id)
        result[molecule_id] = (mol, scores)
    return result


def run(payload):
    started = time.perf_counter()
    work = Path(payload['output_dir'])
    work.mkdir(parents=True, exist_ok=True)
    cpus = min(max(1, int(os.environ.get('TARPASS_CPUS', '8'))), len(os.sched_getaffinity(0)))
    batch_size = max(1, int(os.environ.get('TARPASS_BATCH_SIZE', '64')))
    rows, molecules = [], {}
    original_path, docked_path = work / 'original.sdf', work / 'docked.sdf'
    with Chem.SDWriter(str(original_path)) as writer:
        for index, mol in enumerate(source_records(payload)):
            molecule_id = f'm{index:08d}'
            row = {'molecule_id': molecule_id, 'source_index': index, 'smiles': '', 'status': 'invalid', 'has_original_pose': False, 'metrics': {}, 'errors': {}}
            rows.append(row)
            if mol is None or not mol.GetNumAtoms():
                row['errors']['input'] = 'Invalid molecule record'
                continue
            row['smiles'] = Chem.MolToSmiles(Chem.RemoveHs(mol))
            mol.SetProp('_Name', molecule_id)
            mol.SetProp('molecule_id', molecule_id)
            row['has_original_pose'] = has_3d(mol)
            if row['has_original_pose']:
                writer.write(mol)
            else:
                mol.RemoveAllConformers()
            row['status'] = 'pending'
            molecules[molecule_id] = mol
    if not molecules:
        write_json(work / 'results.json', rows)
        raise ValueError('No valid molecules in source artifact')
    timings = {'read_seconds': time.perf_counter() - started}
    commands = []
    submitted_to_docking = 0
    with ProcessPoolExecutor(max_workers=cpus, initializer=initialize, initargs=(payload,)) as pool:
        stage_start = time.perf_counter()
        smiles = list(dict.fromkeys(row['smiles'] for row in rows if row['status'] == 'pending'))
        computed = dict(zip(smiles, pool.map(evaluate_properties, smiles, chunksize=16)))
        volumes = dict(zip(molecules, pool.map(evaluate_volume, [Chem.MolToMolBlock(mol) for mol in molecules.values()], chunksize=16)))
        candidates = []
        for row in rows:
            if row['status'] != 'pending':
                continue
            values, error = computed[row['smiles']]
            row['metrics'] = dict(values)
            _, volume, volume_error = volumes[row['molecule_id']]
            if not row['has_original_pose']:
                row['metrics']['original'] = {**dict.fromkeys(POSE_METRICS), 'unavailable': {key: 'No original 3D pose' for key in POSE_METRICS}}
            row['metrics']['molecular_volume'] = volume
            if volume_error:
                row['errors']['molecular_volume'] = volume_error
            row['errors'].update(error)
            if not values:
                row['status'] = 'failed'
                continue
            row['prefilter_reasons'] = failed_filters(row, payload['prefilters'])
            row['status'] = 'prefiltered' if row['prefilter_reasons'] else 'pending'
            if row['status'] == 'pending':
                candidates.append(row)
        timings['properties_seconds'] = time.perf_counter() - stage_start
        timings.update(preparation_original_seconds=0, docking_seconds=0, docked_evaluation_seconds=0)
        with Chem.SDWriter(str(docked_path)) as docked_writer:
            for offset in range(0, len(candidates), batch_size):
                batch = candidates[offset:offset + batch_size]
                stage_start = time.perf_counter()
                items = [(row['molecule_id'], volumes[row['molecule_id']][0], payload['ph'], row['has_original_pose']) for row in batch]
                prepared = list(pool.map(prepare_and_evaluate, items, chunksize=1))
                input_path = work / f'batch-{offset:06d}.sdf'
                original_input = work / f'batch-{offset:06d}-original-input.sdf'
                ready = {}
                with Chem.SDWriter(str(input_path)) as writer, Chem.SDWriter(str(original_input)) as original_writer:
                    for row, (block, metrics, error) in zip(batch, prepared):
                        if error:
                            row['status'], row['errors']['preparation'] = 'failed', error
                            continue
                        mol = Chem.MolFromMolBlock(block, removeHs=False)
                        mol.SetProp('_Name', row['molecule_id'])
                        mol.SetProp('molecule_id', row['molecule_id'])
                        writer.write(mol)
                        if row['has_original_pose']:
                            original_writer.write(mol)
                            row['metrics']['original'] = metrics
                        ready[row['molecule_id']] = row
                timings['preparation_original_seconds'] += time.perf_counter() - stage_start
                if not ready:
                    continue
                submitted_to_docking += len(ready)
                for mode in ('original', 'docked'):
                    expected = {key: row for key, row in ready.items() if row['has_original_pose']} if mode == 'original' else ready
                    if not expected:
                        continue
                    output = work / f'batch-{offset:06d}-{mode}.sdf'
                    cmd = gnina_command(payload, original_input if mode == 'original' else input_path, output, mode, cpus)
                    commands.append(cmd)
                    stage_start = time.perf_counter()
                    with gpu_lock() as descriptor, (work / f'batch-{offset:06d}-{mode}.log').open('w') as log:
                        subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True, pass_fds=(descriptor,))
                    timings['docking_seconds'] += time.perf_counter() - stage_start
                    results = read_docking(output, expected)
                    stage_start = time.perf_counter()
                    evaluations = list(pool.map(evaluate_pose, [Chem.MolToMolBlock(mol) for mol, _ in results.values()], chunksize=1)) if mode == 'docked' else [{} for _ in results]
                    for (molecule_id, (mol, scores)), evaluation in zip(results.items(), evaluations):
                        row = ready[molecule_id]
                        row['metrics'].setdefault(mode, {}).update({**evaluation, **scores})
                        if mode == 'docked':
                            docked_writer.write(mol)
                    for molecule_id in expected.keys() - results.keys():
                        ready[molecule_id]['errors'][mode] = 'Gnina returned no pose'
                    timings['docked_evaluation_seconds'] += time.perf_counter() - stage_start
                for row in ready.values():
                    errors = row['errors'] or any(row['metrics'].get(mode, {}).get('errors') for mode in ('original', 'docked'))
                    row['status'] = 'partial' if errors else 'succeeded'
                write_json(work / 'results.json', rows)
    rows = clean(rows)
    write_json(work / 'results.json', rows)
    fields = ['molecule_id', 'source_index', 'smiles', 'status', 'has_original_pose', *sorted(METRICS), 'errors', 'prefilter_reasons']
    with (work / 'results.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{key: row[key] for key in fields[:5]}, **{key: metric_value(row, key) for key in METRICS}, 'errors': json.dumps(row['errors']), 'prefilter_reasons': json.dumps(row.get('prefilter_reasons', []))})
    timings['total_seconds'] = time.perf_counter() - started
    version = subprocess.run([os.environ.get('GNINA_BIN', 'gnina'), '--version'], capture_output=True, text=True, check=True).stdout.strip() if commands else None
    manifest = {'source_job_id': payload['source_job_id'], 'ph': payload['ph'], 'box': payload['box'], 'prefilters': payload['prefilters'], 'key_interactions': payload['key_interactions'], 'gnina_version': version, 'commands': commands, 'timings': timings, 'cpus': cpus, 'batch_size': batch_size}
    manifest['versions'] = {'tarpass_source': 'aaf59c876eb2681d788a55ca46fcb629c7901fa5', 'platform_metrics': 3, 'rdkit': rdBase.rdkitVersion, 'plip': importlib.metadata.version('plip'), 'posebusters': importlib.metadata.version('posebusters')}
    manifest['prefilter_counts'] = {'evaluated': len(molecules), 'passed': len(candidates), 'filtered': sum(row['status'] == 'prefiltered' for row in rows), 'submitted_to_docking': submitted_to_docking}
    manifest['conformation_generation'] = {'rdkit_seed': 42, 'max_attempts': 1000, 'mmff_iterations': 200, 'fallback': 'Open Babel MMFF94 (50 + 200 steps)'}
    manifest['inputs'] = {}
    for key in ('input_sdf', 'input_csv', 'protein_pdb', 'reference_ligand', 'reference_dataset_path'):
        if payload.get(key):
            manifest['inputs'][key] = {'path': payload[key]}
    write_json(work / 'manifest.json', manifest)
    if not any(row['status'] in {'succeeded', 'partial', 'prefiltered'} for row in rows):
        raise ValueError('All candidate molecules failed evaluation')
    return {'engine': 'tarpass', 'output_csv': str(work / 'results.csv'), 'results_json': str(work / 'results.json'), 'original_sdf': str(original_path), 'docked_sdf': str(docked_path), 'manifest_json': str(work / 'manifest.json'), 'result_count': len(rows), 'counts': {status: sum(row['status'] == status for row in rows) for status in ('invalid', 'prefiltered', 'failed', 'partial', 'succeeded')}, 'prefilter_counts': manifest['prefilter_counts'], 'timings': timings}
