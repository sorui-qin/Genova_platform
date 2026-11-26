from pathlib import Path
import os
from tarpass.contracts import gnina_command


def run_job(payload, dry_run=False):
    if payload.get('operation') == 'interactions_2d':
        if dry_run:
            return {'engine': 'tarpass', 'dry_run': True, 'operation': 'interactions_2d',
                    'input_sdf': payload['input_sdf'], 'protein_pdb': payload['protein_pdb'],
                    'molecule_id': payload['molecule_id'], 'pose': payload['pose'], 'output_dir': payload['output_dir']}
        from tarpass.interactions import run_preview
        return run_preview(payload)
    from genova_runtime.model_initialization import initialize_model_task, update_model_stage
    payload = initialize_model_task(payload, 'tarpass', dry_run=dry_run)
    from genova_runtime.structure_inputs import validate_engine_context
    validate_engine_context(payload['structure_context'], 'tarpass')
    if dry_run:
        output = Path(payload['output_dir'])
        cpus = min(max(1, int(os.environ.get('TARPASS_CPUS', '8'))), len(os.sched_getaffinity(0)))
        input_key = 'input_sdf' if payload.get('input_sdf') else 'input_csv'
        modes = ('original', 'docked') if input_key == 'input_sdf' else ('docked',)
        return {'engine': 'tarpass', 'dry_run': True, input_key: payload[input_key],
                'original_requires_3d': True, 'protein_pdb': payload['protein_pdb'], 'box': payload['box'],
                'modes': ['score_only' if mode == 'original' else 'dock' for mode in modes], 'output_csv': str(output / 'results.csv'),
                'commands': [gnina_command(payload, output / ('batch-000000-original-input.sdf' if mode == 'original' else 'batch-000000.sdf'), output / f'batch-000000-{mode}.sdf', mode, cpus) for mode in modes]}
    from tarpass.pipeline import run
    from genova_runtime.structure_inputs import component_usage_artifact
    update_model_stage(payload, 'postprocessing')
    result = run(payload)
    update_model_stage(payload, 'completed')
    result['protein_path'] = payload['protein_pdb']
    result['protein_context_id'] = (payload.get('structure_context') or {}).get('id')
    result['effective_receptor_sha256'] = (payload.get('structure_context') or {}).get('effective_receptor_sha256')
    result['postprocessing_scope'] = payload['postprocessing_input_cache']['model_scope']
    result.update(component_usage_artifact(payload.get('structure_context') or {}, 'tarpass', payload['output_dir'], cache=payload['postprocessing_input_cache']))
    return result
