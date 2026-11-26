import json
import os
import subprocess
import time
from collections import Counter

from genova_runtime.epso_objectives import (
    AFFINITY_METRIC, AFFINITY_MIN_SCALE, AFFINITY_REFERENCE, AFFINITY_WORSE_MULTIPLIER,
    affinity_desirability, affinity_scale,
)

SCORER_PYTHON = '/opt/conda/envs/tarpass/bin/python'


class AffinityObjective:
    name = AFFINITY_METRIC
    is_mol_func = True

    def __init__(self, spec, inputs, reference, descriptor):
        self.weight = spec['weight']
        self.inputs = inputs
        self.descriptor = descriptor
        self.cache = {}
        self.cache_hits = 0
        self.elapsed = 0.0
        self.versions = None
        self.evaluate([reference])
        seed = self.cache[reference]
        if 'error' in seed:
            raise ValueError(f"EPSO could not score the seed ligand: {seed['error']}")
        self.seed_energy = seed['energy']
        self.scale = affinity_scale(self.seed_energy)

    def evaluate(self, smiles):
        missing = [value for value in dict.fromkeys(smiles) if value not in self.cache]
        self.cache_hits += len(smiles) - len(missing)
        if not missing:
            return
        payload = {'smiles': missing, 'include_versions': self.versions is None,
                   'inputs': {**self.inputs, 'protein_pdb': self.inputs['protein_pdb']['path']}}
        start = time.monotonic()
        command = [SCORER_PYTHON, '-m', 'tarpass.affinity', str(self.descriptor)]
        process = subprocess.run(command, input=json.dumps(payload), capture_output=True,
                                 text=True, pass_fds=(self.descriptor,))
        if process.returncode:
            raise RuntimeError(f'EPSO affinity scoring failed: {process.stderr[-4000:]}')
        result = json.loads(process.stdout)
        if set(result['scores']) != set(missing):
            raise RuntimeError('EPSO affinity results do not match the submitted molecules')
        self.cache.update(result['scores'])
        if self.versions is None:
            self.versions = result['versions']
            self.gnina_options = result['gnina_options']
        self.elapsed += time.monotonic() - start

    def __call__(self, mols):
        from rdkit import Chem

        energies = [self.cache[Chem.MolToSmiles(mol, isomericSmiles=True)]['energy'] for mol in mols]
        scores = [affinity_desirability(energy, self.seed_energy, self.scale) for energy in energies]
        return energies, [self.weight * score for score in scores], scores

    def metadata(self):
        failures = Counter(item['error'] for item in self.cache.values() if 'error' in item)
        return {
            'seed_energy': self.seed_energy, 'scale': self.scale, 'reference_energy': AFFINITY_REFERENCE,
            'min_scale': AFFINITY_MIN_SCALE, 'lambda': AFFINITY_WORSE_MULTIPLIER,
            'protein_sha256': self.inputs['protein_pdb']['sha256'], 'box': self.inputs['box'], 'ph': self.inputs['ph'],
            'unique_scored_count': len(self.cache) - sum(failures.values()),
            'cache_hit_count': self.cache_hits, 'failed_count': sum(failures.values()), 'failure_reasons': failures,
            'scoring_seconds': self.elapsed, 'gnina_options': self.gnina_options, 'versions': self.versions,
        }
