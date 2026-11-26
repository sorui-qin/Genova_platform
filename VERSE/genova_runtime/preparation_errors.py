import re
import subprocess


ERROR_TYPES = {
    'MODEL_PROTEIN_UNSUPPORTED': ('input', 'fix_protein'),
    'MODEL_RESIDUE_UNSUPPORTED': ('input', 'fix_protein'),
    'STRUCTURE_INPUT_INVALID': ('input', 'fix_structure'),
    'STRUCTURE_INTEGRITY_FAILED': ('input', 'fix_structure'),
    'RECEPTOR_COMPONENT_UNCLASSIFIED': ('input', 'fix_structure'),
    'CONTEXT_RECEPTOR_EMPTY': ('input', 'fix_protein'),
    'EMPTY_SELECTION': ('input', 'fix_structure'),
    'SEVERE_HEAVY_OVERLAP': ('input', 'fix_structure'),
    'MODEL_COVALENT_BOUNDARY': ('input', 'restore_boundary'),
    'COVALENT_CUT_REQUIRES_TEMPLATE': ('input', 'restore_boundary'),
    'ALTLOC_CONNECTION_CONFLICT': ('input', 'fix_connections'),
    'UNRESOLVED_CONNECTION_SELECTION': ('input', 'fix_connections'),
    'CONTEXT_CONNECTION_UNRESOLVED': ('input', 'fix_connections'),
    'MODEL_ASSEMBLY_REQUIRED': ('input', 'provide_assembly'),
    'COVALENT_RESTORATION_UNSUPPORTED': ('input', 'restore_boundary'),
    'COVALENT_RESTORATION_REQUIRES_PROTONATION': ('input', 'recompute_protonation'),
    'COVALENT_RESTORATION_METAL_ENVIRONMENT_UNSUPPORTED': ('input', 'restore_boundary'),
    'COVALENT_RESTORATION_FAILED': ('input', 'restore_boundary'),
    'COVALENT_RESTORATION_CHANGED_IDENTITY': ('input', 'restore_boundary'),
    'COVALENT_RESTORATION_UNSUPPORTED_RETAINED_BOND': ('input', 'restore_boundary'),
    'REFERENCE_REQUIRED': ('input', 'select_reference'),
    'REFERENCE_INPUT_INVALID': ('input', 'fix_reference'),
    'REFERENCE_MOLECULE_COUNT': ('input', 'fix_reference_count'),
    'REFERENCE_CHEMISTRY_INVALID': ('input', 'fix_reference'),
    'REFERENCE_COORDINATES_REQUIRED': ('input', 'fix_reference_coordinates'),
    'REFERENCE_DISCONNECTED': ('input', 'fix_reference'),
    'REFERENCE_METAL_ION': ('input', 'select_reference'),
    'REFERENCE_HEAVY_CLASH': ('input', 'fix_reference_pose'),
    'MODEL_FEATURE_INVALID': ('runtime', 'check_feature_builder'),
    'MODEL_FEATURE_ENCODING_INVALID': ('runtime', 'check_feature_builder'),
    'MODEL_FEATURES_MISSING': ('runtime', 'check_feature_builder'),
    'MODEL_FEATURE_NONFINITE': ('runtime', 'check_feature_builder'),
    'MODEL_SURFACE_POTENTIAL_ZERO': ('runtime', 'check_feature_builder'),
    'REQUIRED_MODEL_INPUTS_MISSING': ('runtime', 'check_feature_builder'),
    'PREPARATION_TOOL_FAILED': ('runtime', 'check_runtime'),
    'XTB_SCC_NOT_CONVERGED': ('runtime', 'check_runtime'),
    'XTB_EXECUTION_FAILED': ('runtime', 'check_runtime'),
    'XTB_DENSITY_INVALID': ('runtime', 'check_feature_builder'),
    'PREPARATION_TIMEOUT': ('runtime', 'check_runtime'),
    'CONTEXT_CACHE_STALE': ('cache', 'revalidate_context'),
    'CONTEXT_CACHE_CHANGED': ('cache', 'revalidate_context'),
    'CONTEXT_INPUTS_NOT_READY': ('cache', 'revalidate_context'),
    'CANCELED': ('canceled', 'retry_preparation'),
}


class PreparationError(ValueError):
    def __init__(self, code, message, objects=()):
        super().__init__(f'{code}: {message}')
        self.code = code
        self.objects = sorted(set(objects))


def describe_preparation_error(error, stage=''):
    message = str(error)
    prefix, separator, detail = message.partition(':')
    xtb = re.search(r'\b(XTB_SCC_NOT_CONVERGED|XTB_EXECUTION_FAILED|XTB_DENSITY_INVALID):', message)
    if xtb:
        code = xtb.group(1)
    elif separator and re.fullmatch(r'[A-Z][A-Z0-9_]+', prefix):
        code = prefix
        message = detail.strip()
    elif isinstance(error, subprocess.TimeoutExpired):
        code = 'PREPARATION_TIMEOUT'
    elif isinstance(error, ValueError) and stage == 'validating_reference':
        code = 'REFERENCE_INPUT_INVALID'
    elif isinstance(error, ValueError) and stage == 'building_features':
        code = 'MODEL_FEATURE_INVALID'
    elif isinstance(error, ValueError):
        code = 'STRUCTURE_INPUT_INVALID'
    else:
        code = 'PREPARATION_TOOL_FAILED'
    category, recovery = ERROR_TYPES.get(code, ('runtime', 'check_runtime'))
    return dict(error_code=code, error_category=category, message=message, stage=stage,
        objects=error.objects if isinstance(error, PreparationError) else [], recovery_action=recovery)


def residue_label(atom):
    return f"{atom['author_chain_id'] or '_'}:{atom['residue_name']}{atom['author_residue_number']}{atom['insertion_code']}"
