import math


PROPERTY_METRICS = {
    'qed', 'sa_score', 'logp', 'molecular_weight', 'tpsa', 'hbd', 'hba',
    'rotatable_bonds', 'heavy_atoms', 'heteroatoms', 'csp3', 'ring_count',
    'largest_ring', 'unusual_rings', 'fused_systems', 'lipinski_violations',
    'pains_alert', 'surechembl_alert', 'glaxo_alert', 'complete',
    'reference_similarity', 'scaffold_similarity',
    'exact_molecular_weight', 'molecular_volume', 'spiro_atoms', 'chiral_atoms',
    'all_common', 'heteroatom_ratio', 'flexibility', 'morgan_fragments',
    'bertz_ct', 'spacial_score', 'highly_fused', 'rings_in_fused_system',
    'unusual_ring_present', 'fused_ring_present', 'torsion_count',
}
POSE_METRICS = {
    'affinity', 'cnn_score', 'cnn_affinity', 'no_clashes', 'sucos',
    'shape_similarity', 'electrostatic_similarity', 'centroid_shift',
    'le_heavyatom', 'le_mw', 'matched_rate', 'fully_matched', 'volume',
}
METRICS = PROPERTY_METRICS | {f'{pose}.{key}' for pose in ('original', 'docked') for key in POSE_METRICS}
BOOLEAN_METRICS = {'complete', 'all_common', 'highly_fused', 'unusual_ring_present', 'fused_ring_present', 'pains_alert', 'surechembl_alert', 'glaxo_alert', 'no_clashes', 'fully_matched'}
FILTER_OPS = {'gt', 'lt', 'gte', 'lte', 'eq'}
DEFAULT_PREFILTERS = [
    {'metric': 'qed', 'op': 'gt', 'value': 0.4},
    {'metric': 'sa_score', 'op': 'lt', 'value': 5},
    {'metric': 'highly_fused', 'op': 'eq', 'value': 0},
]
METRIC_INFO = {key: {
    'label': key.replace('_', ' ').replace('.', ' / ').title(),
    'type': 'boolean' if key.split('.')[-1] in BOOLEAN_METRICS else 'number',
    'unit': {'molecular_weight': 'Da', 'exact_molecular_weight': 'Da', 'molecular_volume': 'Å³', 'volume': 'Å³', 'tpsa': 'Å²', 'affinity': 'kcal/mol', 'centroid_shift': 'Å'}.get(key.split('.')[-1], ''),
} for key in METRICS}


def validate_filters(filters, *, pre=False):
    if not isinstance(filters, list) or len(filters) > 100:
        raise ValueError('filters must be a list of at most 100 conditions')
    allowed = PROPERTY_METRICS if pre else METRICS
    bounds = {}
    for rule in filters:
        if not isinstance(rule, dict) or set(rule) != {'metric', 'op', 'value'}:
            raise ValueError('Each filter requires metric, op, value')
        if not isinstance(rule['metric'], str) or not isinstance(rule['op'], str) or rule['metric'] not in allowed or rule['op'] not in FILTER_OPS:
            raise ValueError('Unsupported filter metric or operator')
        if not isinstance(rule['value'], (int, float)) or not math.isfinite(rule['value']):
            raise ValueError('Filter value must be finite')
        if rule['metric'].split('.')[-1] in BOOLEAN_METRICS:
            if rule['op'] != 'eq' or rule['value'] not in (0, 1):
                raise ValueError('Boolean filters require eq and a value of 0 or 1')
            continue
        if isinstance(rule['value'], bool):
            raise ValueError('Numeric filters require a numeric threshold')
        lower, upper = bounds.get(rule['metric'], ((-math.inf, False), (math.inf, False)))
        value, op = rule['value'], rule['op']
        if op in {'gt', 'gte', 'eq'}:
            lower = max(lower, (value, op == 'gt'))
        if op in {'lt', 'lte', 'eq'}:
            upper = min(upper, (value, op != 'lt'))
        bounds[rule['metric']] = lower, upper
        if lower[0] > upper[0] or (lower[0] == upper[0] and (lower[1] or not upper[1])):
            raise ValueError('Filter lower bound must not exceed upper bound or exclude the same endpoint')
    return filters


def metric_value(row, key):
    value = row.get('metrics', {})
    for part in key.split('.'):
        value = value.get(part) if isinstance(value, dict) else None
    return value if isinstance(value, (int, float)) and math.isfinite(value) else None
def failed_filters(row, filters):
    failed = []
    for rule in filters:
        value = metric_value(row, rule['metric'])
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            failed.append(rule['metric'])
            continue
        threshold = rule['value']
        passed = {'gt': value > threshold, 'lt': value < threshold, 'gte': value >= threshold, 'lte': value <= threshold, 'eq': value == threshold}[rule['op']]
        if not passed:
            failed.append(rule['metric'])
    return failed
