import csv
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict

from genova_runtime.gpu_lock import gpu_lock
from genova_runtime.generation_settings import generation_settings
from genova_runtime.structure_inputs import component_usage_artifact

CHECKPOINT = Path(os.environ.get("DELETE_CHECKPOINT", "/opt/delete/delete.pt"))


def run_job(payload: Dict, dry_run: bool = False, cancel_check=None) -> Dict:
    from genova_runtime.generation_rounds import run_generation
    return run_generation(payload, 'delete', run_single_job, dry_run, cancel_check)


def run_single_job(payload: Dict, dry_run: bool = False) -> Dict:
    if payload.get('operation') == 'prepare_context_inputs':
        from genova_runtime.context_features import prepare_context_inputs
        return prepare_context_inputs(payload, 'delete', dry_run=dry_run)
    from genova_runtime.model_initialization import initialize_model_task, update_model_stage
    payload = initialize_model_task(payload, 'delete', dry_run=dry_run)
    from genova_runtime.structure_inputs import validate_engine_context
    validate_engine_context(payload.get('structure_context') or {}, 'delete')
    if dry_run:
        return _run_job(payload, dry_run=True)
    # CUDA context and model memory are released when the per-job process exits.
    update_model_stage(payload, 'waiting_for_gpu')
    with gpu_lock() as descriptor, tempfile.TemporaryDirectory(prefix="delete-job-") as directory:
        update_model_stage(payload, 'generating')
        result_path = Path(directory) / "result.json"
        try:
            subprocess.run(
                [sys.executable, "-m", "genova_runtime.entry_delete", str(result_path)],
                input=json.dumps(payload), text=True, stderr=subprocess.PIPE, check=True,
                pass_fds=(descriptor,),
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"DELETE inference exited with code {exc.returncode}:\n{exc.stderr[-8000:]}") from exc
        update_model_stage(payload, 'completed')
        return json.loads(result_path.read_text(encoding="utf-8"))


def _run_job(payload: Dict, dry_run: bool = False) -> Dict:
    protein = Path(str(payload.get("protein_pdb", "")))
    output_dir = Path(str(payload.get("output_dir", "")))
    ligand_value = payload.get("reference_ligand")
    ligand = Path(str(ligand_value or ""))
    fragment = Path(str(payload.get("fragment_sdf", "")))
    output_csv = Path(str(payload.get("output_csv", output_dir / "results.csv")))
    generated_sdf = Path(str(payload.get("generated_sdf", output_dir / "generated.sdf")))
    metadata = output_dir / 'generation_metadata.json'
    num_molecules = payload.get("num_molecules", 100)
    sampling = generation_settings('delete', payload)
    ph = float(payload.get("ph", 7.4))
    anchor_atom_indices = payload.get("anchor_atom_indices") or []

    if protein.suffix.lower() != ".pdb":
        raise ValueError("DELETE requires a .pdb protein")
    if not ligand_value or ligand.suffix.lower() != ".sdf" or fragment.suffix.lower() != ".sdf":
        raise ValueError("DELETE requires .sdf reference ligand and fragment files")
    if type(num_molecules) is not int or num_molecules <= 0:
        raise ValueError("DELETE num_molecules must be a positive integer")
    if not 0 <= ph <= 14:
        raise ValueError("DELETE ph must be between 0 and 14")
    if len(anchor_atom_indices) > 1 or any(not isinstance(index, int) or index < 0 for index in anchor_atom_indices):
        raise ValueError("DELETE anchor_atom_indices must contain at most one non-negative integer")

    if dry_run:
        return {
            "task": "delete",
            "engine": "delete",
            "dry_run": True,
            "checkpoint": str(CHECKPOINT),
            "output_csv": str(output_csv),
            "generated_sdf": str(generated_sdf),
            "num_molecules": num_molecules,
            "ph": ph,
            "anchor_atom_indices": anchor_atom_indices,
            "sampling": sampling,
            "generation_metadata": str(metadata), "requested_count": num_molecules,
        }

    for path in (protein, ligand, fragment, CHECKPOINT):
        if not path.is_file():
            raise FileNotFoundError(path)

    from rdkit import Chem
    output_dir.mkdir(parents=True, exist_ok=True)
    model_protein = protein
    molecules = []
    stats = {}
    generator = _anchored_generator(
        model_protein.read_bytes(),
        ligand.read_bytes(),
        fragment.read_bytes(),
        str(CHECKPOINT),
        anchor_atom_indices[0] if anchor_atom_indices else None,
        ph,
        sampling=sampling,
        surface_ply=payload.get('surface_ply'),
        generation_stats=stats,
    )
    try:
        for molecule in generator:
            if molecule is None:
                continue
            if (not molecule.GetNumAtoms() or not molecule.GetNumConformers() or not molecule.GetConformer().Is3D()
                    or not all(math.isfinite(value) for point in molecule.GetConformer().GetPositions() for value in point)):
                raise ValueError("DELETE generated a molecule without finite 3D coordinates")
            molecules.append(molecule)
            if len(molecules) >= num_molecules:
                break
    finally:
        generator.close()

    generation = dict(requested_count=num_molecules, result_count=len(molecules),
                      shortfall=max(0, num_molecules - len(molecules)),
                      reached_target=len(molecules) >= num_molecules,
                      stop_reason='target_reached' if len(molecules) >= num_molecules else stats.get('stop_reason'),
                      generation_stats=stats)
    metadata.write_text(json.dumps(generation, indent=2), encoding='utf-8')
    if not molecules and not payload.get('_allow_empty_generation'):
        raise ValueError("DELETE generated no valid molecules")

    with output_csv.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["smiles"])
        writer.writerows([[Chem.MolToSmiles(molecule)] for molecule in molecules])

    writer = Chem.SDWriter(str(generated_sdf))
    try:
        for molecule in molecules:
            writer.write(molecule)
    finally:
        writer.close()

    result = {
        "task": "delete",
        "engine": "delete",
        "protein_path": str(protein),
        "ligand_path": str(ligand),
        "fragment_path": str(fragment),
        "anchor_atom_indices": anchor_atom_indices,
        "output_csv": str(output_csv),
        "generated_sdf": str(generated_sdf),
        "result_count": len(molecules),
        "sampling": sampling,
        **generation, "generation_metadata": str(metadata),
        "ph": ph,
        **component_usage_artifact(payload.get('structure_context') or {}, 'delete', output_dir),
    }
    from genova_runtime.context_features import generation_context_report
    return result if payload.get('_defer_context_report') else generation_context_report(payload, result)


def _prepare_surface(payload):
    import shutil
    root = Path('/code/components/Delete')
    pocket = root / 'src/online/pocket.pdb'
    ligand = root / 'src/online/ligand.sdf'
    pocket.write_bytes(Path(payload['protein_pdb']).read_bytes())
    ligand.write_bytes(Path(payload['reference_ligand']).read_bytes())
    from genova_runtime.utils import run_subprocess
    run_subprocess(['/opt/conda/envs/surfmaker/bin/python', str(root / 'get_ply.py'), 'make_ply',
        f'{pocket}|{ligand}', str(payload.get('ph', 7.4))], cwd=Path.cwd(), dry_run=False, timeout=7200,
        log_path=Path(payload['output_dir']) / 'surface_builder.log')
    target = Path(payload['output_dir']) / 'surface.ply'
    shutil.copy2(root / 'delete_input/src/outputs/ply/pocket_ligand.ply', target)
    from genova_runtime.structure_inputs import validate_surface_features
    validate_surface_features(target)
    return target


def _anchored_generator(
    pdb_bytes: bytes,
    ligand_bytes: bytes,
    fragment_bytes: bytes,
    checkpoint: str,
    reference_anchor_index: int,
    ph: float,
    sampling=None,
    surface_ply=None,
    generation_stats=None,
):
    from components.Delete import main as delete_main
    from src.main_gen import TaskProcessor

    root = Path(delete_main.__file__).parent
    pocket_path = root / "src/online/pocket.pdb"
    ligand_path = root / "src/online/ligand.sdf"
    fragment_path = root / "src/online/frag.sdf"
    pocket_path.write_bytes(pdb_bytes)
    ligand_path.write_bytes(ligand_bytes)
    fragment_path.write_bytes(fragment_bytes)
    processor = TaskProcessor(
        {
            "surf_path_bytes": Path(surface_ply).read_bytes(),
            "frag_path_bytes": fragment_bytes,
            "ligand_path_bytes": ligand_bytes,
            "ckpt_path": checkpoint,
            "activity_file_bytes": None,
            "frag_smis": "",
            "sampling": sampling,
            "generation_stats": generation_stats,
        }
    )
    if reference_anchor_index is None:
        return processor.process()
    manager = processor.growth_point_manager
    fragment_anchor = next(
        (
            fragment_index
            for fragment_index, reference_index in manager.fragment_to_reference.items()
            if reference_index == reference_anchor_index
        ),
        None,
    )
    if fragment_anchor is None:
        raise ValueError("DELETE derivation anchor could not be mapped to the reference ligand")
    manager.fragment_growth_indices = {fragment_anchor}
    return processor.process()


if __name__ == "__main__":
    result = _run_job(json.load(sys.stdin))
    Path(sys.argv[1]).write_text(json.dumps(result), encoding="utf-8")
