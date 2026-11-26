import csv
import json
import os
import shutil
from pathlib import Path
from typing import Dict

from genova_runtime.utils import command_to_string, run_subprocess
from genova_runtime.structure_inputs import materialize_region_spec_json, component_usage_artifact
from genova_runtime.gpu_lock import gpu_lock
from genova_runtime.generation_settings import generation_settings


SURFGEN_ROOT = Path(os.environ.get("SURFGEN_ROOT", "/app")).resolve()
CHECKPOINT = Path(os.environ.get("SURFGEN_CHECKPOINT", SURFGEN_ROOT / "ckpt" / "surfgen.pt")).resolve()
CONDA = os.environ.get("SURFGEN_CONDA_BIN") or shutil.which("conda") or "conda"


def run_job(payload: Dict, dry_run: bool = False, cancel_check=None) -> Dict:
    from genova_runtime.generation_rounds import run_generation
    return run_generation(payload, 'surfgen', run_single_job, dry_run, cancel_check)


def run_single_job(payload: Dict, dry_run: bool = False) -> Dict:
    if payload.get('operation') == 'prepare_context_inputs':
        from genova_runtime.context_features import prepare_context_inputs
        return prepare_context_inputs(payload, 'surfgen', dry_run=dry_run)
    from genova_runtime.model_initialization import initialize_model_task, update_model_stage
    payload = initialize_model_task(payload, 'surfgen', dry_run=dry_run)
    from genova_runtime.structure_inputs import validate_engine_context
    validate_engine_context(payload.get('structure_context') or {}, 'surfgen')
    protein = Path(str(payload.get("protein_pdb", "")))
    ligand_value = payload.get("reference_ligand")
    ligand = Path(str(ligand_value)) if ligand_value else None
    structure_context = payload.get("structure_context") or {}
    output_dir = Path(str(payload.get("output_dir", "")))
    output_csv = Path(str(payload.get("output_csv", output_dir / "generated_molecules.csv")))
    num_molecules = payload.get("num_molecules", 100)
    sampling = generation_settings('surfgen', payload)
    sample_config = output_dir / 'sampling.yml'
    results_json = output_dir / "results.json"
    metadata = output_dir / 'generation_metadata.json'
    surface_ply = Path(payload["surface_ply"])
    generated_sdf = output_dir / surface_ply.stem / f"{surface_ply.stem}_gen.sdf"

    if protein.suffix.lower() != ".pdb":
        raise ValueError("SurfGen requires a .pdb protein")
    if ligand and ligand.suffix.lower() not in {".sdf", ".mol", ".mol2"}:
        raise ValueError("SurfGen reference ligand must be .sdf/.mol/.mol2")
    if type(num_molecules) is not int or num_molecules <= 0:
        raise ValueError("SurfGen num_molecules must be a positive integer")

    generation_cmd = [
        CONDA, "run", "--no-capture-output", "-n", "surfgen",
        "python", str(SURFGEN_ROOT / "gen.py"),
        "--outdir", str(output_dir), "--check_point", str(CHECKPOINT),
        "--ply_file", str(surface_ply), "--num_samples", str(num_molecules),
        "--results_json", str(results_json),
        "--config", str(sample_config),
    ]
    gpu_check_cmd = [
        CONDA, "run", "--no-capture-output", "-n", "surfgen", "python", "-c",
        "import torch; "
        "assert torch.cuda.is_available(), 'SurfGen GPU unavailable: CUDA is not accessible inside worker-surfgen. Recreate the GPU worker and verify container GPU access.'; "
        "torch.zeros(1, device='cuda'); torch.cuda.synchronize()",
    ]
    commands = [command_to_string(cmd) for cmd in (gpu_check_cmd, generation_cmd)]
    if dry_run:
        return {
            "task": "surfgen", "engine": "surfgen", "dry_run": True,
            "output_csv": str(output_csv), "generated_sdf": str(generated_sdf),
            "surface_ply": str(surface_ply), "commands": commands,
            "sampling": sampling,
            "generation_metadata": str(metadata), "requested_count": num_molecules,
        }

    commands = [command_to_string(cmd) for cmd in (gpu_check_cmd, generation_cmd)]
    run_subprocess(gpu_check_cmd, cwd=SURFGEN_ROOT, dry_run=False)
    output_dir.mkdir(parents=True, exist_ok=True)
    import yaml
    config = yaml.safe_load((SURFGEN_ROOT / 'configs/sample.yml').read_text())
    config['sample'].update({key: sampling[key] for key in ('seed', 'beam_size', 'max_steps')})
    config['sample']['threshold'].update({key: sampling[key] for key in ('element_threshold', 'bond_threshold')})
    sample_config.write_text(yaml.safe_dump(config))
    update_model_stage(payload, 'waiting_for_gpu')
    with gpu_lock() as descriptor:
        update_model_stage(payload, 'generating')
        run_subprocess(generation_cmd, cwd=SURFGEN_ROOT, dry_run=False, pass_fds=(descriptor,))
    generated = json.loads(results_json.read_text(encoding="utf-8"))
    generated = [item for item in generated if str(item.get('smiles') or '').strip()]
    model_metadata = Path(str(results_json) + '.metadata.json')
    generation = json.loads(model_metadata.read_text()) if model_metadata.is_file() else {}
    generation.update(requested_count=num_molecules, result_count=len(generated),
                      shortfall=max(0, num_molecules - len(generated)),
                      reached_target=len(generated) >= num_molecules)
    if generation['reached_target']:
        generation['stop_reason'] = 'target_reached'
    metadata.write_text(json.dumps(generation, indent=2), encoding='utf-8')
    if not generated and not payload.get('_allow_empty_generation'):
        raise RuntimeError('SurfGen generated no valid molecules within the sampling budget')
    with output_csv.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["smiles", "smiles_canonical"])
        writer.writeheader()
        writer.writerows(
            {
                "smiles": str(item.get("smiles") or "").strip(),
                "smiles_canonical": str(item.get("smiles_canonical") or item.get("smiles") or "").strip(),
            }
            for item in generated
        )
    update_model_stage(payload, 'completed')
    result = {
        "task": "surfgen", "engine": "surfgen",
        "protein_path": str(protein), "ligand_path": str(ligand) if ligand else None,
        "surface_ply": str(surface_ply), "output_csv": str(output_csv),
        "generated_sdf": str(generated_sdf), "result_count": len(generated),
        "commands": commands,
        "sampling": sampling,
        **generation, "generation_metadata": str(metadata),
        **component_usage_artifact(structure_context, 'surfgen', output_dir),
    }
    from genova_runtime.context_features import generation_context_report
    return result if payload.get('_defer_context_report') else generation_context_report(payload, result)


def prepare_surface(payload):
    output = Path(payload['output_dir'])
    surface_dir = output / 'surface'
    command = [CONDA, 'run', '--no-capture-output', '-n', 'surf_maker', 'python', str(SURFGEN_ROOT / 'surface_cli.py'), '--pdb_file', payload['protein_pdb'], '--outdir', str(surface_dir), '--ph', str(payload.get('ph',7.4))]
    if payload.get('reference_ligand'):
        command += ['--ligand_file', payload['reference_ligand']]
    else:
        region = materialize_region_spec_json(Path(payload['structure_context']['protein_pdb']), payload['structure_context'], output)
        command += ['--region_json', str(region)]
    run_subprocess(command, SURFGEN_ROOT, False, timeout=7200, log_path=output/'surface_builder.log')
    surface = surface_dir / 'surface_pocket_8.0.ply'
    from genova_runtime.structure_inputs import validate_surface_features
    validate_surface_features(surface)
    return {'surface_ply':str(surface)}
