"""Map explicit requirement IDs to the platform's input cards."""
from typing import get_args

from backend.agent.session_schemas import CLARIFICATION_ALIASES, CLARIFICATION_IDS, StructureField


def presentation_fields(requirements, fields=()):
    structure_fields = set(get_args(StructureField))
    explicit = {field['requirement']: field['id'] for field in fields
                if field['requirement'] in requirements and field['id'] in CLARIFICATION_IDS}
    result = []
    for requirement in dict.fromkeys(requirements):
        field_id = CLARIFICATION_ALIASES.get(requirement, explicit.get(requirement, 'text'))
        kind = ('structure' if field_id in structure_fields else 'engine' if field_id == 'engine'
                else 'confirmation' if field_id == 'postprocessing' else 'delete' if field_id == 'delete_edit_spec_id'
                else 'count' if field_id in {'num_molecules', 'target_num_molecules'} else 'text')
        result.append({'requirement': requirement, 'id': field_id, 'type': kind})
    return result


def validate_clarification_state(output, state, *, answer_only=False):
    if answer_only and output.missing_requirements:
        raise ValueError('This is an informational request. Answer in message without missing_requirements or input cards.')
    assets = {**state.get('assets', {}), **getattr(output, 'assets', {})}
    prepared = bool(assets.get('protein_context_id') or assets.get('prepared_receptor_id'))
    for field in presentation_fields(output.missing_requirements, [f.model_dump() for f in output.clarification_fields]):
        if field['id'] in {'site', 'generation_reference'} and not prepared:
            raise ValueError('Site and reference controls require a prepared structure. Ask for the current missing protein/preparation input and preserve future site requirements in site_request.')
        if field['id'] in {'protein_file_id', 'prepared_spec', 'preparation_defaults'} and not (assets.get('protein_dataset_id') or prepared):
            raise ValueError('Protein file and preparation controls require a bound protein source. Ask for protein_dataset_id or valid_structure_selection first.')
        if field['id'] == 'delete_edit_spec_id' and not assets.get('protein_context_id'):
            raise ValueError('The DELETE editor requires a prepared Protein Context. Ask for the missing structure/site input first.')
