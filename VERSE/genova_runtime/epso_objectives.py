import math

from genova_runtime.generation_settings import COUNT_LIMITS

AFFINITY_METRIC = 'gnina_affinity'
AFFINITY_COUNT_LIMIT = 500
AFFINITY_MODE = 'seed_relative'
AFFINITY_REFERENCE = -8.0
AFFINITY_MIN_SCALE = 0.5
AFFINITY_WORSE_MULTIPLIER = 2.0

METRICS = {
    'qed': (0, 1, 0.1), 'sa': (0, 1, 0.1), 'mw': (0, None, 50),
    'logp': (None, None, 0.5), 'lipinski': (0, 5, 1), 'hba': (0, None, 1),
    'hbd': (0, None, 1), 'heavy_atom_count': (0, None, 1), 'similarity': (0, 1, 0.1),
    AFFINITY_METRIC: (None, None, None),
}
MODE_FIELDS = {
    'lower_bound': {'lower'}, 'upper_bound': {'upper'}, 'range': {'lower', 'upper'},
    'target': {'target'}, 'maximize': {'lower', 'upper'}, 'minimize': {'lower', 'upper'},
    AFFINITY_MODE: set(),
}
DEFAULT_OBJECTIVES = [
    {'metric': 'qed', 'mode': 'lower_bound', 'lower': 0.6, 'weight': 1.0},
    {'metric': 'sa', 'mode': 'lower_bound', 'lower': 0.6, 'weight': 1.0},
    {'metric': 'mw', 'mode': 'range', 'lower': 250, 'upper': 500, 'weight': 1.0},
]
DEFAULT_OPTIMIZER = {'num_particles': 200, 'num_swarms': 1, 'num_steps': 20, 'seed': 2024}
OPTIMIZER_LIMITS = {'num_particles': 1000, 'num_steps': 1000, 'evaluations': 20_000}
FIXED_PARAMETERS = {'x_min': -10, 'x_max': 10, 'inertia_weight': 0.9,
                    'phi1': 2, 'phi2': 2, 'phi3': 2, 'v_min': -0.6, 'v_max': 0.6,
                    'decode_batch_size': 128, 'decode_max_attempts': 4, 'gpu': 0}


def validate_objectives(objectives):
    if not isinstance(objectives, list) or not objectives:
        raise ValueError('EPSO requires at least one objective')
    result, seen = [], set()
    for raw in objectives:
        if not isinstance(raw, dict):
            raise ValueError('ObjectiveSpec must be an object')
        metric, mode = raw.get('metric'), raw.get('mode')
        if not isinstance(metric, str) or not isinstance(mode, str) or metric not in METRICS or mode not in MODE_FIELDS or metric in seen:
            raise ValueError('Unsupported or duplicate EPSO metric/mode')
        if (metric == AFFINITY_METRIC) != (mode == AFFINITY_MODE):
            raise ValueError('gnina_affinity requires seed_relative mode and vice versa')
        seen.add(metric)
        low, high, softness = METRICS[metric]
        fields = MODE_FIELDS[mode]
        normalized = mode in {'maximize', 'minimize'}
        allowed = {'metric', 'mode', 'weight'} | fields
        if not normalized and softness is not None:
            allowed.add('softness')
        if raw.keys() - allowed:
            raise ValueError('Unknown ObjectiveSpec fields')
        spec = dict(raw)
        spec.setdefault('weight', 1.0)
        if normalized and high is not None:
            spec.setdefault('lower', low)
            spec.setdefault('upper', high)
        if not normalized and softness is not None:
            spec.setdefault('softness', softness)
        if not fields <= spec.keys():
            raise ValueError(f'{mode} requires {sorted(fields)}')
        for key, value in spec.items():
            if key in {'metric', 'mode'}:
                continue
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f'{key} must be finite')
            if key in {'weight', 'softness'}:
                if value <= 0:
                    raise ValueError(f'{key} must be positive')
            elif (low is not None and value < low) or (high is not None and value > high):
                raise ValueError(f'{metric}.{key} outside natural bounds')
        if {'lower', 'upper'} <= spec.keys() and spec['lower'] >= spec['upper']:
            raise ValueError('lower must be less than upper')
        result.append(spec)
    return result


def validate_parameters(params):
    if not isinstance(params, dict) or params.keys() - {'engine', 'num_molecules', 'objectives', 'optimizer'}:
        raise ValueError('Unknown EPSO parameters')
    count = params.get('num_molecules', 100)
    if type(count) is not int or count <= 0:
        raise ValueError('num_molecules must be a positive integer')
    raw = params.get('optimizer', {})
    if not isinstance(raw, dict) or raw.keys() - DEFAULT_OPTIMIZER.keys():
        raise ValueError('Unknown EPSO optimizer parameters')
    optimizer = {**DEFAULT_OPTIMIZER, **raw}
    for name, value in optimizer.items():
        if type(value) is not int or (name != 'seed' and value <= 0):
            raise ValueError(f'{name} must be a positive integer')
    if not 0 <= optimizer['seed'] <= 2**32 - 1:
        raise ValueError('seed must be between 0 and 2^32-1')
    if optimizer['num_swarms'] != 1:
        raise ValueError('num_swarms is fixed at 1')
    for name in ('num_particles', 'num_steps'):
        if optimizer[name] > OPTIMIZER_LIMITS[name]:
            raise ValueError(f'{name} must be at most {OPTIMIZER_LIMITS[name]}')
    if optimizer['num_particles'] * (optimizer['num_steps'] + 1) > OPTIMIZER_LIMITS['evaluations']:
        raise ValueError(f"EPSO optimizer budget exceeds {OPTIMIZER_LIMITS['evaluations']} evaluations")
    return {'num_molecules': count, 'optimizer': optimizer,
            'objectives': validate_objectives(params.get('objectives', DEFAULT_OBJECTIVES))}


def validate_requested_count(count, objectives):
    affinity = any(objective['metric'] == AFFINITY_METRIC for objective in objectives)
    limit = AFFINITY_COUNT_LIMIT if affinity else COUNT_LIMITS['epso']
    if count > limit:
        suffix = ' when GNINA affinity is enabled' if affinity else ''
        raise ValueError(f'EPSO num_molecules must be at most {limit}{suffix}')


def affinity_scale(seed_energy):
    return max(seed_energy - AFFINITY_REFERENCE, AFFINITY_MIN_SCALE)


def affinity_desirability(energy, seed_energy, scale):
    z = math.log(3) * ((seed_energy - energy) / scale)
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    exp_z = math.exp(AFFINITY_WORSE_MULTIPLIER * z)
    return exp_z / (1 + exp_z)


def compile_desirability(spec):
    spec = validate_objectives([spec])[0]
    mode = spec['mode']
    lo, hi, soft = spec.get('lower'), spec.get('upper'), spec.get('softness')
    if mode == 'lower_bound':
        points = [(lo - soft, 0), (lo, 1)]
    elif mode == 'upper_bound':
        points = [(hi, 1), (hi + soft, 0)]
    elif mode == 'range':
        points = [(lo - soft, 0), (lo, 1), (hi, 1), (hi + soft, 0)]
    elif mode == 'target':
        target = spec['target']
        points = [(target - soft, 0), (target, 1), (target + soft, 0)]
    else:
        points = [(lo, int(mode == 'minimize')), (hi, int(mode == 'maximize'))]
    if any(not math.isfinite(x) for x, _ in points):
        raise ValueError('Objective curve endpoints must be finite')
    return [{'x': x, 'y': y} for x, y in points]


def compile_objective(spec, reference_smiles):
    from functools import partial
    from rdkit import Chem
    from rdkit.Chem import Lipinski
    from models.ECloudDecipher.optimize import mol_functions as mf
    from models.ECloudDecipher.optimize.scoring import ScoringFunction

    spec = validate_objectives([spec])[0]
    functions = {'qed': mf.qed_score, 'sa': mf.sa_score, 'mw': mf.get_weight,
                 'logp': mf.logp_score, 'lipinski': mf.obey_lipinski, 'hba': mf.get_HAcceptors,
                 'hbd': Lipinski.NumHDonors, 'heavy_atom_count': mf.heavy_atom_count,
                 'similarity': partial(mf.sim_score, ref_mol=Chem.MolFromSmiles(reference_smiles))}
    return ScoringFunction(functions[spec['metric']], spec['metric'], weight=spec['weight'],
                           desirability=compile_desirability(spec), is_mol_func=True)


def read_seed(path):
    from pathlib import Path
    from rdkit import Chem

    if Path(path).suffix.lower() != '.sdf' or not Path(path).is_file():
        raise ValueError('EPSO requires an existing single-molecule .sdf file')
    try:
        molecules = list(Chem.SDMolSupplier(str(path)))
    except OSError as exc:
        raise ValueError('EPSO seed SDF cannot be read') from exc
    if len(molecules) != 1 or molecules[0] is None or not molecules[0].GetNumAtoms():
        raise ValueError('EPSO seed SDF must contain exactly one valid molecule')
    return Chem.MolToSmiles(molecules[0], isomericSmiles=True)
