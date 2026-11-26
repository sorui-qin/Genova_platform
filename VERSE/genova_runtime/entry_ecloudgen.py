import argparse
import csv
import json
import math
import os
import random
import shutil
import sys
import time
from pathlib import Path

from genova_runtime.gpu_lock import gpu_lock
from genova_runtime.utils import command_to_string, run_subprocess
from genova_runtime.generation_settings import generation_settings, sampling_plan


ECLOUDGEN_ROOT = Path(os.environ.get("ECLOUDGEN_ROOT", "/app")).resolve()



def diffusion_command(protein, ligand, output, clouds, seed):
    command = [sys.executable, str(ECLOUDGEN_ROOT / "generate_from_pdb.py"),
            "--config", str(ECLOUDGEN_ROOT / "configs/eclouddiff.yml"),
            "--checkpoint", str(ECLOUDGEN_ROOT / "ckpt/32_ldm_4channel_ddpm_100.pt"),
            "--pdb_file", str(protein),
            "--outputs_dir", str(output), "--num_gen", str(clouds), "--batch", "4",
            "--seed", str(seed)]
    if ligand:
        command.extend(["--lig_file", str(ligand)])
    return command


def run_job(payload, dry_run=False, cancel_check=None):
    from genova_runtime.generation_rounds import run_generation
    return run_generation(payload, 'ecloudgen', run_single_job, dry_run, cancel_check)


def run_single_job(payload, dry_run=False):
    if payload.get('operation') == 'prepare_context_inputs':
        from genova_runtime.context_features import prepare_context_inputs
        return prepare_context_inputs(payload, 'ecloudgen', dry_run=dry_run)
    from genova_runtime.model_initialization import initialize_model_task, update_model_stage
    payload = initialize_model_task(payload, 'ecloudgen', dry_run=dry_run)
    from genova_runtime.structure_inputs import validate_engine_context
    validate_engine_context(payload.get('structure_context') or {}, 'ecloudgen')
    protein = Path(str(payload.get("protein_pdb", "")))
    ligand = Path(payload['reference_ligand']) if payload.get('reference_ligand') else None
    output_dir = Path(payload["output_dir"])
    output_csv = Path(payload.get("output_csv", output_dir / "generated_molecules.csv"))
    if "num_molecules" in payload:
        raise ValueError("ECloudGen now requires target_num_molecules; resubmit the target count")
    target = payload.get("target_num_molecules", 100)
    sampling = generation_settings('ecloudgen', payload)
    plan = sampling_plan(target, budget_multiplier=sampling['budget_multiplier'],
                         num_clouds=sampling['num_clouds'], decodes_per_cloud=sampling['decodes_per_cloud'],
                         full_target=payload.get('full_target_round', False))
    plan['calibration_matches'] = sampling['noise'] == 0.1 and sampling['inv_temp'] == 2
    if protein.suffix.lower() != ".pdb" or ligand and ligand.suffix.lower() != ".sdf":
        raise ValueError("ECloudGen requires a prepared .pdb protein and an optional .sdf reference ligand")
    seed = sampling['seed']
    inputs = output_dir / "inputs"
    metadata = output_dir / "generation_metadata.json"
    decoder = ECLOUDGEN_ROOT / "ckpt/ecloudgen_decipher_ckpt"
    result = {"engine": "ecloudgen", "protein_path": str(protein), "ligand_path": str(ligand) if ligand else None,
              "output_csv": str(output_csv), "requested_count": target, **sampling,
              "sampling_plan": plan, "generation_metadata": str(metadata),
              "unique_pool_csv": str(output_dir / 'unique_pool.csv'),
              "commands": [], "rounds": [], "generated_clouds": 0, "decoded_clouds": 0,
              "sampled_count": 0, "valid_count": 0, "new_unique_count": 0, "duplicate_count": 0, "result_count": 0}
    count = plan["num_clouds"]
    if not dry_run:
        for path in (protein, *([ligand] if ligand else []), decoder, ECLOUDGEN_ROOT / "ckpt/32_ldm_4channel_ddpm_100.pt"):
            if not path.is_file():
                raise FileNotFoundError(path)
        inputs.mkdir(parents=True, exist_ok=True)
        model_protein = protein
        shutil.copyfile(model_protein, inputs / "protein.pdb")
        if ligand:
            shutil.copyfile(ligand, inputs / "reference.sdf")
    if not dry_run and 'GENOVA_POCKET_INPUTS_V2' not in (ECLOUDGEN_ROOT / 'generate_from_pdb.py').read_text():
        raise RuntimeError('ECLOUD_INPUT_BUILDER_UPGRADE_REQUIRED: rebuild the ECloudGen image with the task input builder patch')
    # Separate processes release diffusion memory before loading the decoder.
    def run_round(descriptor=None):
        number = len(result["rounds"])
        round_dir = output_dir / f"round_{number:03d}"
        clouds_dir = round_dir / "eclouds"
        generated = clouds_dir / "reference_ecouldgen.npy"
        round_csv = round_dir / "molecules.csv"
        round_seed = (seed + number * 100000) % 2**32
        commands = [diffusion_command(inputs / "protein.pdb", inputs / "reference.sdf" if ligand else None,
                                      clouds_dir, count, round_seed),
                    [sys.executable, "-m", "genova_runtime.entry_ecloudgen",
                     "--input_ecloud", str(generated), "--model", str(decoder),
                     "--target", str(target), "--decodes-per-cloud", str(plan["decodes_per_cloud"]),
                     "--seed", str(round_seed), "--selection-seed", str(seed), "--output", str(round_csv),
                     "--noise", str(sampling['noise']), "--inv-temp", str(sampling['inv_temp']),
                     "--pool-output", result['unique_pool_csv']]]
        if number:
            commands[1].extend(["--previous", result['unique_pool_csv']])
        result["commands"].extend(command_to_string(cmd) for cmd in commands)
        if dry_run:
            return
        round_dir.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        feature_inputs = Path(payload['input_features'])
        def execute_commands(descriptor):
            for index, command in enumerate(commands):
                if feature_inputs:
                    run_subprocess(command, cwd=output_dir, dry_run=False, pass_fds=(descriptor,),
                        env={**os.environ, 'GENOVA_ECLOUD_INPUTS': str(feature_inputs)} if index == 0 else None)
                else:
                    run_subprocess(command, cwd=output_dir, dry_run=False, pass_fds=(descriptor,))
        update_model_stage(payload, 'waiting_for_gpu')
        with gpu_lock() as locked:
            update_model_stage(payload, 'generating')
            execute_commands(locked)
        stats = json.loads(round_csv.with_suffix(".json").read_text())
        stats["elapsed_seconds"] = time.perf_counter() - started
        shutil.copyfile(round_csv, output_csv)
        result["rounds"].append({**stats, "generated_eclouds": str(generated), "generated_clouds": count, **({"input_features": str(feature_inputs), "input_features_report": str(feature_inputs.with_suffix('.json'))} if feature_inputs else {})})
        result["generated_clouds"] += count
        for key in ("decoded_clouds", "sampled_count", "valid_count", "new_unique_count", "duplicate_count"):
            result[key] += stats[key]
        result["result_count"] = stats["result_count"]
        metadata.write_text(json.dumps(result, indent=2) + "\n")

    if dry_run:
        run_round()
        return {**result, "dry_run": True}
    def generate_rounds(descriptor=None):
        nonlocal count
        while count:
            previous_count = result["result_count"]
            run_round(descriptor)
            if result["result_count"] >= target:
                break
            remaining_clouds = plan["max_clouds"] - result["generated_clouds"]
            remaining_samples = plan["max_samples"] - result["sampled_count"]
            available = min(remaining_clouds, remaining_samples // plan["decodes_per_cloud"])
            observed = result["result_count"] / result["decoded_clouds"]
            count = 4 * math.ceil((target - result["result_count"]) / observed / 4) if result["result_count"] > previous_count else plan["num_clouds"]
            count = min(count, 4 * (available // 4))
    generate_rounds()
    result['rounds'] = [{key: value for key, value in row.items()
                         if key not in {'generated_eclouds', 'input_features_report'}} for row in result['rounds']]
    result["reached_target"] = result["result_count"] == target
    result["stop_reason"] = "target_reached" if result["reached_target"] else "budget_exhausted"
    result['shortfall'] = max(0, target - result['result_count'])
    result['generation_stats'] = dict(sampled_count=result['sampled_count'], valid_count=result['valid_count'],
                                      invalid_count=result['sampled_count'] - result['valid_count'],
                                      decoded_clouds=result['decoded_clouds'], unique_pool_count=result['new_unique_count'],
                                      duplicate_count=result['duplicate_count'])
    metadata.write_text(json.dumps(result, indent=2) + "\n")
    if not result["result_count"] and not payload.get('_allow_empty_generation'):
        raise RuntimeError(f"ECloudGen generated no valid unique molecules within the sampling budget; {metadata}")
    update_model_stage(payload, 'completed')
    from genova_runtime.structure_inputs import component_usage_artifact
    result.update(component_usage_artifact(payload.get('structure_context') or {}, 'ecloudgen', output_dir))
    from genova_runtime.context_features import generation_context_report
    return result if payload.get('_defer_context_report') else generation_context_report(payload, result)


def decode_batches(input_ecloud, model, decodes_per_cloud, seed, noise=0.1, inv_temp=2):
    import numpy as np
    import torch
    from models.ECloudDecipher.models.io.coati import load_ecloud_smiles_clip_e2e

    encoder, tokenizer = load_ecloud_smiles_clip_e2e(freeze=True, device="cpu", doc_url=str(model))
    encoder.to("cuda:0")
    encoder.device = "cuda:0"
    clouds = np.load(input_ecloud)
    if clouds.ndim == 3:
        clouds = clouds[None]
    with torch.no_grad():
        for index, cloud in enumerate(clouds):
            torch.manual_seed((seed + index) % 2**32)
            np.random.seed((seed + index) % 2**32)
            random.seed((seed + index) % 2**32)
            pocket = torch.randn(1, 256).to("cuda:0")
            tensor = torch.as_tensor(cloud, dtype=torch.float32, device="cuda:0")
            for offset in range(0, decodes_per_cloud, 32):
                batch_size = min(32, decodes_per_cloud - offset)
                started = time.perf_counter()
                decoded, stats = encoder.decipher_eclouds_to_mols(
                    eclouds_batch=tensor, p_e3gnn=pocket, tokenizer=tokenizer,
                    fill_in_from="[SMILES]", noise_scale=noise, inv_temp=inv_temp, batch_repeat=batch_size,
                    total_gen=batch_size + 1, max_attempts=1, return_stats=True)
                yield {"cloud_id": index, "decode_count": offset + batch_size,
                       "smiles": [smile for smile in decoded if smile], **stats,
                       "seconds": time.perf_counter() - started}


def decode_clouds(input_ecloud, model, target, output, decodes_per_cloud, seed, previous=None, noise=0.1, inv_temp=2, *, selection_seed, pool_output=None):
    smiles = set()
    if previous:
        with Path(previous).open(newline="") as file:
            smiles.update(row["smiles"] for row in csv.DictReader(file))
    stats = {"sampled_count": 0, "valid_count": 0, "decoded_clouds": 0, "seed": seed, "selection_seed": selection_seed}
    previous_unique_count = len(smiles)
    batches = decode_batches(input_ecloud, model, decodes_per_cloud, seed, noise, inv_temp)
    try:
        for batch in batches:
            smiles.update(batch["smiles"])
            stats["sampled_count"] += batch["sampled_count"]
            stats["valid_count"] += batch["valid_count"]
            stats["decoded_clouds"] = batch["cloud_id"] + 1
    finally:
        batches.close()
    stats["unique_pool_count"] = len(smiles)
    stats['new_unique_count'] = len(smiles) - previous_unique_count
    stats['duplicate_count'] = stats['valid_count'] - stats['new_unique_count']
    selected = sorted(smiles)
    if pool_output:
        with Path(pool_output).open('w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(['smiles'])
            writer.writerows([smile] for smile in selected)
    if len(selected) > target:
        selected = sorted(random.Random(selection_seed).sample(selected, target))
    stats["result_count"] = len(selected)
    with Path(output).open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["smiles"])
        writer.writerows([smile] for smile in selected)
    Path(output).with_suffix(".json").write_text(json.dumps(stats, indent=2) + "\n")
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Decode EClouds toward a global unique molecule target")
    parser.add_argument("--input_ecloud", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--target", type=int, required=True)
    parser.add_argument("--decodes-per-cloud", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--selection-seed", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--previous")
    parser.add_argument("--pool-output")
    parser.add_argument("--noise", type=float, default=0.1)
    parser.add_argument("--inv-temp", type=float, default=2)
    args = parser.parse_args()
    if args.target <= 0 or args.decodes_per_cloud <= 0:
        parser.error("target and decodes-per-cloud must be positive")
    generation_settings('ecloudgen', {'seed': args.seed, 'noise': args.noise, 'inv_temp': args.inv_temp})
    decode_clouds(args.input_ecloud, args.model, args.target, args.output,
                  args.decodes_per_cloud, args.seed, args.previous, args.noise, args.inv_temp,
                  selection_seed=args.selection_seed, pool_output=args.pool_output)
