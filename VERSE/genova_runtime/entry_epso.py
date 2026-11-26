import csv
import json
import os
import platform
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from genova_runtime.epso_objectives import AFFINITY_METRIC, FIXED_PARAMETERS, compile_objective, read_seed, validate_parameters
from genova_runtime.gpu_lock import gpu_lock

ROOT = Path(os.environ.get('ECLOUDGEN_ROOT', '/app'))
CHECKPOINT = ROOT / 'ckpt/ecloudgen_decipher_ckpt'


class EPSOInferenceModel:
    def __init__(self, encoder, tokenizer):
        self.encoder, self.tokenizer = encoder, tokenizer
        self.previous = []
        self.decode_failures = 0
        self.decode_requests = 0
        self.evaluated_particle_record_count = 0

    def seq_to_emb(self, smiles):
        import torch
        from models.ECloudDecipher.generative.coati_purifications import embed_smiles

        strings = [smiles] if isinstance(smiles, str) else smiles
        embeddings = torch.stack([embed_smiles(s, self.encoder, self.tokenizer) for s in strings])
        if embeddings.shape != (len(strings), self.encoder.embed_dim) or not torch.isfinite(embeddings).all():
            raise ValueError('EPSO encoder returned invalid embeddings')
        self.previous = list(strings)
        return embeddings

    def emb_to_seq(self, embeddings):
        import torch
        from models.ECloudDecipher.generative.coati_purifications import force_decode_valid_batch

        if embeddings.ndim != 2 or embeddings.shape[1] != self.encoder.embed_dim or not torch.isfinite(embeddings).all():
            raise ValueError('EPSO decoder received invalid embeddings')
        previous = self.previous * len(embeddings) if len(self.previous) == 1 else self.previous
        if len(previous) != len(embeddings):
            raise ValueError('EPSO particle count changed')
        smiles = []
        for vector, old in zip(embeddings, previous):
            self.decode_requests += 1
            decoded = force_decode_valid_batch(vector, self.encoder, self.tokenizer, strict=True,
                                               batch_size=128, max_attempts=4)
            if decoded is None:
                self.decode_failures += 1
            smiles.append(old if decoded is None else decoded)
        return smiles


def optimize(reference, inference, parameters, device, affinity=None):
    from rdkit import Chem
    from models.ECloudDecipher.optimize.pso_optimizer import BasePSOptimizer

    settings = parameters['optimizer']
    scores = [affinity if spec['metric'] == AFFINITY_METRIC else compile_objective(spec, reference)
              for spec in parameters['objectives']]
    optimizer = BasePSOptimizer.from_query(
        reference, settings['num_particles'], 1, inference, scores,
        device=device, x_min=-10, x_max=10, voice=False,
    )
    evaluated, trajectory = {}, []
    swarm = optimizer.swarms[0]
    optimizer.update_fitness(swarm)
    for step in range(settings['num_steps'] + 1):
        if step and affinity:
            previous = swarm.smiles
            swarm.next_step()
            decoded = inference.emb_to_seq(swarm.x)
            canonical = [Chem.MolToSmiles(Chem.MolFromSmiles(value), isomericSmiles=True) for value in decoded]
            affinity.evaluate(canonical)
            swarm.smiles = [old if 'error' in affinity.cache[value] else new
                            for old, new, value in zip(previous, decoded, canonical)]
            swarm.x = inference.seq_to_emb(swarm.smiles)
            optimizer.update_fitness(swarm)
        elif step:
            optimizer._next_step_and_evaluate(swarm)
        for index, smiles in enumerate(swarm.smiles):
            inference.evaluated_particle_record_count += 1
            canonical = Chem.MolToSmiles(Chem.MolFromSmiles(smiles), isomericSmiles=True)
            if canonical not in evaluated:
                evaluated[canonical] = {'smiles': canonical, 'fitness': float(swarm.fitness[index]),
                                        'generation': step,
                                        **{sf.name: float(swarm.unscaled_scores[sf.name][index]) for sf in scores}}
                if affinity:
                    evaluated[canonical][AFFINITY_METRIC] = affinity.cache[canonical]['energy']
                    evaluated[canonical]['gnina_affinity_improvement'] = (
                        affinity.seed_energy - evaluated[canonical][AFFINITY_METRIC]
                    )
        best = max(evaluated.values(), key=lambda row: row['fitness'])
        trajectory.append({'step': step, 'best_fitness': best['fitness'], 'best_smiles': best['smiles']})
        if affinity:
            best_docked = min(evaluated.values(), key=lambda row: row[AFFINITY_METRIC])
            trajectory[-1].update(best_gnina_affinity=best_docked[AFFINITY_METRIC],
                                  best_gnina_affinity_smiles=best_docked['smiles'])
    rows = sorted(evaluated.values(), key=lambda row: -row['fitness'])[:parameters['num_molecules']]
    return [dict(rank=i + 1, **row) for i, row in enumerate(rows)], trajectory, len(evaluated)


def run_job(payload, dry_run=False):
    if payload.get('operation') == 'prepare_context_inputs':
        from genova_runtime.context_features import prepare_context_inputs
        return prepare_context_inputs(payload, 'epso', dry_run=dry_run)
    from genova_runtime.model_initialization import initialize_model_task, update_model_stage
    payload = initialize_model_task(payload, 'epso', dry_run=dry_run)
    from genova_runtime.structure_inputs import validate_engine_context
    if not payload.get('seed_reference'):
        validate_engine_context(payload.get('structure_context') or {}, 'epso')
    if dry_run:
        return _run_job(payload, dry_run=True)
    update_model_stage(payload, 'waiting_for_gpu')
    with gpu_lock() as descriptor, tempfile.TemporaryDirectory(prefix='epso-job-') as directory:
        update_model_stage(payload, 'generating')
        result_path = Path(directory) / 'result.json'
        try:
            subprocess.run([sys.executable, '-m', 'genova_runtime.entry_epso', str(result_path), str(descriptor)],
                           input=json.dumps(payload), text=True, stderr=subprocess.PIPE, check=True,
                           pass_fds=(descriptor,))
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f'EPSO inference exited with code {exc.returncode}:\n{exc.stderr[-8000:]}') from exc
        update_model_stage(payload, 'completed')
        return json.loads(result_path.read_text())


def _run_job(payload, dry_run=False, descriptor=None):
    params = validate_parameters({key: payload[key] for key in ('num_molecules', 'objectives', 'optimizer') if key in payload})
    output = Path(payload['output_dir'])
    paths = {key: str(payload.get(key, output / name)) for key, name in
             [('output_csv', 'results.csv'), ('trajectory_csv', 'trajectory.csv'), ('metadata_json', 'metadata.json')]}
    result = {'engine': 'epso', 'task': 'epso', **paths, 'generated_structure_source': 'none',
              'epso_optimizes_3d_pose': False, 'requested_count': params['num_molecules'],
              'protein_path': payload.get('protein_pdb'), 'ligand_path': payload['reference_ligand']}
    affinity_spec = next((spec for spec in params['objectives'] if spec['metric'] == AFFINITY_METRIC), None)
    if affinity_spec:
        from genova_runtime.context_features import load_shared_receptor
        from genova_runtime.epso_affinity import SCORER_PYTHON

        inputs = payload.get('affinity_inputs')
        if not inputs:
            raise ValueError('EPSO affinity requires a validated Protein Context receptor and docking box')
        receptor = load_shared_receptor(inputs['receptor'], os.environ.get('DATA_ROOT', '/app/data'))
        if receptor['files']['protein_pdb'] != inputs['protein_pdb']:
            raise ValueError('EPSO affinity receptor binding changed')
        result['protein_path'] = inputs['protein_pdb']['path']
    if dry_run:
        return {**result, 'dry_run': True, 'checkpoint': str(CHECKPOINT), 'parameters': params,
                'fixed_parameters': FIXED_PARAMETERS,
                **({'affinity_inputs': inputs, 'affinity_command': [SCORER_PYTHON, '-m', 'tarpass.affinity']}
                   if affinity_spec else {})}
    started = time.monotonic()
    reference = read_seed(payload['reference_ligand'])
    import numpy as np
    import torch
    from rdkit import rdBase
    from models.ECloudDecipher.models.io.coati import load_ecloud_smiles_clip_e2e

    affinity = None
    if affinity_spec:
        from genova_runtime.epso_affinity import AffinityObjective

        affinity = AffinityObjective(affinity_spec, inputs, reference, descriptor)
    seed = params['optimizer']['seed']
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    encoder, tokenizer = load_ecloud_smiles_clip_e2e(doc_url=str(CHECKPOINT), device='cpu', freeze=True)
    encoder.to('cuda:0')
    encoder.device = 'cuda:0'
    encoder.eval()
    inference = EPSOInferenceModel(encoder, tokenizer)
    with torch.no_grad():
        rows, trajectory, unique_count = optimize(reference, inference, params, 'cuda:0', affinity)
    output.mkdir(parents=True, exist_ok=True)
    from genova_runtime.structure_inputs import component_usage_artifact
    result.update(component_usage_artifact(payload.get('structure_context') or {}, 'epso', output, cache=payload.get('prepared_input_cache')))
    for key, values in [('output_csv', rows), ('trajectory_csv', trajectory)]:
        with Path(paths[key]).open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(values[0]))
            writer.writeheader()
            writer.writerows(values)
    result.update(result_count=len(rows), unique_evaluated_count=unique_count,
                  decode_failures=inference.decode_failures, shortfall=max(0, params['num_molecules'] - len(rows)),
                  no_new_molecules=unique_count == 1,
                  no_fitness_improvement=trajectory[-1]['best_fitness'] <= trajectory[0]['best_fitness'])
    result.update(reached_target=len(rows) >= params['num_molecules'], stop_reason='optimization_completed',
                  generation_stats=dict(decode_request_count=inference.decode_requests,
                                        failed_decode_request_count=inference.decode_failures,
                                        evaluated_particle_record_count=inference.evaluated_particle_record_count,
                                        unique_evaluated_count=unique_count,
                                        optimization_steps=params['optimizer']['num_steps']))
    metadata = {**result, 'checkpoint': str(CHECKPOINT),
                'parameters': params, 'fixed_parameters': FIXED_PARAMETERS, 'seed': seed,
                'reference_smiles': reference, 'elapsed_seconds': time.monotonic() - started,
                'versions': {'python': platform.python_version(), 'torch': torch.__version__,
                             'cuda': torch.version.cuda, 'rdkit': rdBase.rdkitVersion, 'numpy': np.__version__}}
    if affinity:
        metadata['affinity'] = affinity.metadata()
    Path(paths['metadata_json']).write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    Path(sys.argv[1]).write_text(json.dumps(_run_job(json.load(sys.stdin), descriptor=int(sys.argv[2]))), encoding='utf-8')
