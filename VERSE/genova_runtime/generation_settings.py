import math
import json
from pathlib import Path


COUNT_LIMITS = {'surfgen': 50_000, 'ecloudgen': 50_000, 'delete': 10_000, 'epso': 1000}
DEFAULT_GENERATION_COUNT = 1000
ROUND_TARGET = 1000
TASK_SECONDS = 12 * 60 * 60


DEFAULTS = {
    'surfgen': {'beam_size': 500, 'max_steps': 50, 'element_threshold': 0.3, 'bond_threshold': 0.4, 'seed': 2020},
    'delete': {'beam_size': 500, 'max_steps': 50, 'element_threshold': 0.3, 'bond_threshold': 0.4, 'seed': 2023},
    'ecloudgen': {'noise': 0.1, 'inv_temp': 2, 'budget_multiplier': 3, 'seed': 42,
                  'num_clouds': None, 'decodes_per_cloud': 100},
}


def sampling_plan(target, calibration=None, budget_multiplier=3, num_clouds=None, decodes_per_cloud=100,
                  *, full_target=True):
    if type(target) is not int or target <= 0:
        raise ValueError('ECloudGen target_num_molecules must be a positive integer')
    if type(decodes_per_cloud) is not int or decodes_per_cloud <= 0:
        raise ValueError('decodes_per_cloud must be a positive integer')
    if num_clouds is not None and (type(num_clouds) is not int or num_clouds < 4 or num_clouds % 4):
        raise ValueError('num_clouds must be a positive multiple of 4')
    table = calibration if calibration is not None else json.loads(Path(__file__).with_name('ecloudgen_calibration.json').read_text())
    yields = sorted((row['decodes_per_cloud'], row['unique_p20'] / 32)
                    for row in table['rows'] if row['num_clouds'] == 32)
    # ponytail: interpolate measured yields; outside the table use linear scaling below and a conservative cap above.
    unique_per_cloud = yields[0][1] * decodes_per_cloud / yields[0][0] if decodes_per_cloud < yields[0][0] else yields[-1][1]
    for (low, low_yield), (high, high_yield) in zip(yields, yields[1:]):
        if low <= decodes_per_cloud <= high:
            unique_per_cloud = low_yield + (high_yield - low_yield) * (decodes_per_cloud - low) / (high - low)
            break
    round_target = target if full_target else min(target, ROUND_TARGET)
    clouds = num_clouds if num_clouds is not None else max(4, 4 * math.ceil(round_target / unique_per_cloud / 4))
    return {'num_clouds': clouds, 'decodes_per_cloud': decodes_per_cloud,
            'max_clouds': budget_multiplier * clouds, 'max_samples': budget_multiplier * clouds * decodes_per_cloud,
            'estimated_unique_per_cloud': unique_per_cloud, 'calibration_version': table['version'],
            'extrapolated': clouds > 32 or not yields[0][0] <= decodes_per_cloud <= yields[-1][0],
            'round_target': round_target}


def generation_settings(engine, params):
    result = {key: params.get(key, default) for key, default in DEFAULTS[engine].items()}
    for key, value in result.items():
        if key == 'seed':
            if type(value) is not int or not 0 <= value < 2**32:
                raise ValueError('seed must be an integer between 0 and 4294967295')
        elif key == 'num_clouds':
            if value is not None and (type(value) is not int or value < 4 or value % 4):
                raise ValueError('num_clouds must be a positive multiple of 4')
        elif key in ('beam_size', 'max_steps', 'budget_multiplier', 'decodes_per_cloud'):
            if type(value) is not int or value < 1:
                raise ValueError(f'{key} must be a positive integer')
        elif type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f'{key} must be a finite number')
        elif key.endswith('_threshold'):
            if value != DEFAULTS[engine][key]:
                raise ValueError(f'{key} is fixed at {DEFAULTS[engine][key]}')
        elif value < 0 or (key == 'inv_temp' and value == 0):
            raise ValueError(f'{key} must be {"positive" if key == "inv_temp" else "non-negative"}')
    if engine == 'ecloudgen' and result['num_clouds'] is None:
        result['num_clouds'] = sampling_plan(params.get('target_num_molecules', 100),
                                            decodes_per_cloud=result['decodes_per_cloud'],
                                            full_target=False)['num_clouds']
    return result
