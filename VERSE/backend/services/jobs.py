"""Shared domain validation for Job-related operations.

This module contains validation logic that must be shared between:
  - The jobs router (POST /jobs)
  - The agent preview_workflow tool

By centralizing validation here, we guarantee that agent-validated plans
use the exact same rules as the actual job creation path.

The creation helpers add Jobs, JobTasks, and QueueOutbox entries to the
caller's transaction without committing it.
"""
from __future__ import annotations

import uuid
import math
import csv
from copy import deepcopy
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.builtin_datasets import BUILTIN_OWNER_ID
from backend.config import settings
from backend.models import Dataset, DatasetFile, Job, JobTask, QueueOutbox
from genova_runtime.generation_rounds import GENERATION_POLICY
from genova_runtime.generation_settings import COUNT_LIMITS, DEFAULT_GENERATION_COUNT, DEFAULTS, ROUND_TARGET, generation_settings, sampling_plan
from genova_runtime.pdb2pqr_compat import file_sha256
from tarpass.contracts import protein_residues, validate_interactions
from tarpass.filters import DEFAULT_PREFILTERS, validate_filters


# ---------------------------------------------------------------------------
# Error types 鈥?not HTTPExceptions, so both router and agent can use them
# ---------------------------------------------------------------------------

class DomainValidationError(Exception):
    """Raised when domain validation fails."""

    def __init__(self, message: str, *, code: str = "VALIDATION_ERROR", http_status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status


class ResourceNotFound(DomainValidationError):
    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__(message, code="RESOURCE_NOT_FOUND", http_status=404)


class ResourceConflict(DomainValidationError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="RESOURCE_CONFLICT", http_status=409)


class InvalidParameter(DomainValidationError):
    def __init__(self, message: str, *, http_status: int = 400) -> None:
        super().__init__(message, code="INVALID_PARAMETER", http_status=http_status)


class ProteinFileNotFound(DomainValidationError):
    def __init__(self, message: str = "The prepared protein file is unavailable") -> None:
        super().__init__(message, code="PROTEIN_FILE_NOT_FOUND", http_status=409)


class ProteinNotReady(DomainValidationError):
    def __init__(self, message: str = "Protein Context preparation is not ready") -> None:
        super().__init__(message, code="PROTEIN_NOT_READY", http_status=409)


# ---------------------------------------------------------------------------
# Dataset resolution
# ---------------------------------------------------------------------------

def get_owned_dataset(
    db: Session,
    dataset_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Dataset:
    """Fetch a dataset owned by the user (or built-in).

    Raises ResourceNotFound if not found.
    """
    dataset = db.scalar(
        select(Dataset).where(
            Dataset.id == dataset_id,
            or_(Dataset.owner_user_id == user_id, Dataset.owner_user_id == BUILTIN_OWNER_ID),
        )
    )
    if dataset is None:
        raise ResourceNotFound(f"Dataset not found: {dataset_id}")
    return dataset


def get_dataset_files(db: Session, dataset_id: uuid.UUID) -> list[DatasetFile]:
    """Fetch all files for a dataset."""
    return db.scalars(select(DatasetFile).where(DatasetFile.dataset_id == dataset_id)).all()


# ---------------------------------------------------------------------------
# Protein Context validation
# ---------------------------------------------------------------------------

def validate_protein_context_ready(db, user_id, protein_context_id):
    from backend.services.binding_sites import resolve_v4_context
    dataset = get_owned_dataset(db, protein_context_id, user_id)
    if dataset.kind != "protein_context":
        raise ResourceNotFound("Protein Context not found")
    try:
        context = resolve_v4_context(dataset, db, user_id)
    except HTTPException as exc:
        raise ProteinNotReady(str(exc.detail)) from exc
    return {"id": context["id"], "name": context["name"], "status": "ready", "version": 4,
            "is_prepared": True, "has_reference_ligand": bool(context["generation_reference"]),
            "has_docking_box": True, "box": context["box"], "capabilities": context["capabilities"]}


def validate_protein_context_for_generation(db, user_id, protein_context_id):
    dataset = get_owned_dataset(db, protein_context_id, user_id)
    if dataset.kind != "protein_context":
        raise ResourceNotFound("Protein Context not found")
    if dataset.status != "ready" or (dataset.meta or {}).get("version") != 4:
        raise ProteinNotReady("A ready v4 Protein Context is required")
    from backend.services.binding_sites import resolve_v4_context
    try:
        context = resolve_v4_context(dataset, db, user_id)
        if (context.get('capabilities') or {}).get('input_preparation') != 'context_features_v1':
            raise ProteinNotReady('Save the Context again to prepare and validate reusable model inputs')
        if context.get('capabilities', {}).get('receptor_policy') != 'protein_metals_v1':
            raise ProteinNotReady('CONTEXT_RECEPTOR_UPDATE_REQUIRED: update the protein/metal receptor and save the Context')
        return context
    except HTTPException as exc:
        raise ProteinNotReady(str(exc.detail)) from exc


# ---------------------------------------------------------------------------
# SurfGen parameter validation
# ---------------------------------------------------------------------------

def validate_surfgen_num_molecules(value: Any, engine: str = "surfgen") -> int:
    """Validate and normalize num_molecules for SurfGen.

    Returns the validated integer.

    Raises InvalidParameter on failure.
    """
    if value in (None, ""):
        return DEFAULT_GENERATION_COUNT
    try:
        num = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidParameter("num_molecules must be a positive integer") from exc
    from genova_runtime.generation_rounds import validate_count
    try:
        return validate_count(engine, num)
    except ValueError as exc:
        raise InvalidParameter(str(exc)) from exc


def validate_generation_engine(engine: str, expected: str = "surfgen") -> None:
    """Validate that the generation engine matches the expected value.

    Raises InvalidParameter on mismatch.
    """
    if str(engine or "").strip().lower() != expected:
        raise InvalidParameter(f"Generation engine must be '{expected}'")


def pick_dataset_file(
    files: list[DatasetFile],
    preferred_roles: list[str],
    suffixes: set[str],
) -> DatasetFile | None:
    for role in preferred_roles:
        for row in files:
            if row.file_role == role and Path(row.original_filename).suffix.lower() in suffixes:
                return row
    return next((row for row in files if Path(row.original_filename).suffix.lower() in suffixes), None)


# ponytail: platform caps at about 10x the model defaults; raise them after measuring larger runs on the GPU.
GENERATION_LIMITS = {"beam_size": 5000, "max_steps": 500, "budget_multiplier": 10, "decodes_per_cloud": 1024, "num_clouds": 256}
ECLOUDGEN_MAX_SAMPLES = 200000


def validated_generation_settings(engine: str, params: dict[str, Any]) -> dict[str, Any]:
    if engine == 'ecloudgen' and 'target_num_molecules' not in params:
        params = {**params, 'target_num_molecules': DEFAULT_GENERATION_COUNT}
    if engine == 'surfgen' and type(params.get('num_molecules')) is int and params['num_molecules'] > ROUND_TARGET:
        params = {key: value for key, value in params.items() if key != 'seed'}
    try:
        sampling = generation_settings(engine, params)
    except ValueError as exc:
        raise InvalidParameter(str(exc)) from exc
    for key, limit in GENERATION_LIMITS.items():
        if (sampling.get(key) or 0) > limit:
            raise InvalidParameter(f"{key} must be at most {limit}")
    if engine == "ecloudgen" and sampling["budget_multiplier"] * sampling["num_clouds"] * sampling["decodes_per_cloud"] > ECLOUDGEN_MAX_SAMPLES:
        raise InvalidParameter(f"ECloudGen sampling budget exceeds {ECLOUDGEN_MAX_SAMPLES} samples")
    return sampling


def use_ecloudgen_full_target(target, sampling):
    defaults = DEFAULTS['ecloudgen']
    return (settings.ecloudgen_full_target and target > ROUND_TARGET
            and sampling.get('num_clouds') is None
            and all(sampling.get(key, defaults[key]) == defaults[key]
                    for key in ('noise', 'inv_temp', 'budget_multiplier', 'decodes_per_cloud')))


def configure_ecloudgen_target(payload, submitted):
    payload['generation_policy'] = GENERATION_POLICY
    if use_ecloudgen_full_target(payload['target_num_molecules'], submitted):
        payload['num_clouds'] = sampling_plan(payload['target_num_molecules'], full_target=True)['num_clouds']
        payload['ecloudgen_full_target'] = True


def build_molecule_generation_payload(
    *,
    db: Session,
    mol_gen_params: dict[str, Any],
    job_id: uuid.UUID,
    task_queue_job_id: uuid.UUID,
    ligand_dataset_id: uuid.UUID | None,
    structure_context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_generation_engine(mol_gen_params.get("engine"))
    from genova_runtime.structure_inputs import validate_context_engine_support
    try:
        validate_context_engine_support(structure_context, 'surfgen')
    except ValueError as exc:
        raise InvalidParameter(str(exc)) from exc
    num_molecules = validate_surfgen_num_molecules(mol_gen_params.get("num_molecules"))
    try:
        sampling = validated_generation_settings("surfgen", {**mol_gen_params, 'num_molecules': num_molecules})
    except ValueError as exc:
        raise InvalidParameter(str(exc)) from exc
    if ligand_dataset_id is not None:
        raise InvalidParameter("Generation uses the reference from Protein Context; create a new binding site to change it")
    output_dir = settings.data_root / "jobs" / str(job_id) / f"surfgen_{task_queue_job_id}"
    if num_molecules > ROUND_TARGET:
        sampling['seed'] = job_id.int & 0xffffffff
    return {
        "engine": "surfgen",
        "protein_pdb": structure_context["protein_pdb"],
        "structure_context": deepcopy(structure_context),
        "reference_ligand": structure_context.get("reference_ligand_path"),
        "output_dir": str(output_dir),
        "output_csv": str(output_dir / "generated_molecules.csv"),
        "num_molecules": num_molecules,
        "generation_policy": GENERATION_POLICY,
        **sampling,
        "ph": structure_context["ph"] if structure_context.get("ph") is not None else 7.4,
    }, {
        "engine": "surfgen",
        "protein_context_id": structure_context["id"],
        "protein_context_file_id": structure_context["protein_file_id"],
        "ligand_dataset_id": str(ligand_dataset_id) if ligand_dataset_id else None,
        "ligand_dataset_file_id": None,
        "prepared_reference_ligand_file_id": structure_context.get("reference_ligand_file_id"),
    }


def create_molecule_generation_job(
    db: Session,
    *,
    owner_user_id: uuid.UUID,
    protein_context_id: uuid.UUID,
    params: dict[str, Any],
    ligand_dataset_id: uuid.UUID | None = None,
    structure_context: dict[str, Any] | None = None,
) -> Job:
    """Add SurfGen Job, task, and outbox rows without committing."""
    from backend.services.resources import check_admission
    check_admission(db, owner_user_id)
    stored_params = deepcopy(params or {})
    mol_gen_params = dict(stored_params["molecule_generation"])
    validate_generation_engine(mol_gen_params.get("engine"))
    structure_context = structure_context or validate_protein_context_for_generation(db, owner_user_id, protein_context_id)
    if ligand_dataset_id is not None:
        get_owned_dataset(db, ligand_dataset_id, owner_user_id)
    stored_params["structure_context"] = deepcopy(structure_context)
    stored_params["protein_context_id"] = str(protein_context_id)

    job = Job(
        id=uuid.uuid4(),
        owner_user_id=owner_user_id,
        job_type="molecule_generation",
        status="pending",
        input_dataset_id=protein_context_id,
        params=stored_params,
        summary={},
    )
    task = JobTask(
        id=uuid.uuid4(),
        job_id=job.id,
        task_code="molecule_generation",
        runtime_task="surfgen",
        status="pending",
        queue_job_id=uuid.uuid4(),
        depends_on=[],
        input_payload={},
        output_payload={},
    )
    task_payload, task_meta = build_molecule_generation_payload(
        db=db,
        mol_gen_params=mol_gen_params,
        job_id=job.id,
        task_queue_job_id=task.queue_job_id,
        ligand_dataset_id=ligand_dataset_id,
        structure_context=structure_context,
    )
    task.input_payload = task_payload
    stored_params["molecule_generation"] = {
        **mol_gen_params,
        **{key: task_payload[key] for key in DEFAULTS['surfgen']},
        "num_molecules": task_payload["num_molecules"],
        **task_meta,
    }
    job.params = stored_params
    job.summary = {"tasks": {"molecule_generation": {
        "queue_job_id": str(task.queue_job_id),
        "status": task.status,
        "runtime_task": task.runtime_task,
    }}}
    db.add(job)
    db.add(task)
    db.add(
        QueueOutbox(
            job_task_id=task.id,
            queue_name=settings.redis_dispatch_queue,
            payload={
                "job_id": str(task.queue_job_id),
                "task": "surfgen",
                "payload": task_payload,
                "result_queue": settings.redis_result_queue,
                "meta": {"job_id": str(job.id), **task_meta},
            },
            status="pending",
        )
    )
    db.flush()
    return job



def create_agent_source_job(
    db: Session,
    *,
    owner_user_id: uuid.UUID,
    protein_context_id: uuid.UUID,
    generation: dict[str, Any],
    workflow_id: uuid.UUID,
) -> Job:
    """Create the approved workflow source job without committing.

    SurfGen uses the established service path. New perf engines use the same
    validated Protein Context and queue contracts as the production jobs API.
    """
    from backend.services.resources import check_admission
    check_admission(db, owner_user_id)
    config = deepcopy(generation or {})
    engine = str(config.get("engine") or "").strip().lower()
    if engine == "surfgen":
        return create_molecule_generation_job(
            db,
            owner_user_id=owner_user_id,
            protein_context_id=protein_context_id,
            params={
                "molecule_generation": config,
                "job_name": f"Workflow {str(workflow_id)[:8]} SurfGen",
                "system_tags": {"workflow_id": str(workflow_id)},
            },
        )
    if engine not in {"ecloudgen", "delete", "epso"}:
        raise InvalidParameter(f"Unsupported Agent source engine '{engine}'")

    context = validate_protein_context_for_generation(
        db, owner_user_id, protein_context_id
    )
    seed_dataset_id = (config.get('ligand_dataset_id') or (config.get('seed_source') or {}).get('dataset_id')) if engine == 'epso' else None
    from genova_runtime.structure_inputs import validate_context_engine_support, validate_context_snapshot
    try:
        if seed_dataset_id:
            validate_context_snapshot(context, context['protein_pdb'])
        else:
            validate_context_engine_support(context, engine)
    except ValueError as exc:
        raise InvalidParameter(str(exc)) from exc
    reference = context.get("reference_ligand_path")
    if engine in {"delete", "epso"} and not seed_dataset_id and not context.get("generation_reference") and (not reference or not Path(reference).is_file()):
        raise InvalidParameter(
            f"{engine} requires a prepared reference ligand in Protein Context"
        )

    job_id = uuid.uuid4()
    task_id = uuid.uuid4()
    queue_job_id = uuid.uuid4()
    try:
        sampling = validated_generation_settings(engine, config) if engine in {"ecloudgen", "delete"} else {}
    except ValueError as exc:
        raise InvalidParameter(str(exc)) from exc
    if engine == "ecloudgen":
        if "num_molecules" in config:
            raise InvalidParameter(
                "ECloudGen requires target_num_molecules; num_molecules is not accepted"
            )
        target = config.get("target_num_molecules", DEFAULT_GENERATION_COUNT)
        if type(target) is not int or not 1 <= target <= COUNT_LIMITS['ecloudgen']:
            raise InvalidParameter("target_num_molecules must be between 1 and 50000")
        output = settings.data_root / "jobs" / str(job_id) / f"ecloudgen_{queue_job_id}"
        payload = {
            "engine": "ecloudgen",
            "protein_pdb": context["protein_pdb"],

            "structure_context": deepcopy(context),
            "reference_ligand": reference,
            "output_dir": str(output),
            "output_csv": str(output / "generated_molecules.csv"),
            "target_num_molecules": target,
            "noise": 0.1,
            "ph": context["ph"] if context.get("ph") is not None else (context.get("preparation") or {}).get("ph", 7.4),
        }
        job_type = task_code = "molecule_generation"
        normalized = {
            "engine": "ecloudgen",
            "target_num_molecules": target,
            "noise": 0.1,
        }
    elif engine == "delete":
        count = validate_surfgen_num_molecules(config.get("num_molecules"), "delete")
        edit = config.get("edit")
        if not isinstance(edit, dict):
            raise InvalidParameter("DELETE requires an explicit edit configuration")

        reference = validate_delete_submission(context, edit)
        output = settings.data_root / "jobs" / str(job_id) / f"delete_{queue_job_id}"
        fragment = output / "fragment.sdf"
        edit_meta = {'edit_mode': edit['mode'], 'anchor_atom_indices': []}
        payload = {
            "engine": "delete",
            "protein_pdb": context["protein_pdb"],
            "structure_context": deepcopy(context),

            "reference_ligand": reference,
            "fragment_sdf": str(fragment),
            "edit": deepcopy(edit),
            "anchor_atom_indices": (
                edit_meta["anchor_atom_indices"]
                if edit_meta["edit_mode"] == "derivation_site"
                else []
            ),
            "num_molecules": count,
            "generation_policy": GENERATION_POLICY,
            "ph": context["ph"] if context.get("ph") is not None else (context.get("preparation") or {}).get("ph", 7.4),
            "output_dir": str(output),
            "output_csv": str(output / "results.csv"),
            "generated_sdf": str(output / "generated.sdf"),
        }
        job_type = task_code = "property_optimization"
        normalized = {
            "engine": "delete",
            "num_molecules": count,
            "edit": deepcopy(edit),
            "edit_metadata": edit_meta,
        }
    else:
        from genova_runtime.epso_objectives import read_seed, validate_parameters, validate_requested_count

        try:
            parameters = validate_parameters({key: config[key] for key in ("engine", "num_molecules", "objectives", "optimizer") if key in config})
            validate_requested_count(parameters['num_molecules'], parameters['objectives'])
            reference_smiles = None
        except ValueError as exc:
            raise InvalidParameter(str(exc)) from exc
        seed_reference = None
        if seed_dataset_id:
            try:
                seed_dataset_id = uuid.UUID(str(seed_dataset_id))
            except (TypeError, ValueError) as exc:
                raise InvalidParameter("EPSO seed dataset is invalid") from exc
            get_owned_dataset(db, seed_dataset_id, owner_user_id)
            seed_files = get_dataset_files(db, seed_dataset_id)
            if len(seed_files) != 1 or Path(seed_files[0].original_filename).suffix.lower() != ".sdf":
                raise InvalidParameter("EPSO seed dataset must contain exactly one SDF file")
            seed_file = seed_files[0]
            if not Path(seed_file.storage_path).is_file() or file_sha256(seed_file.storage_path) != seed_file.sha256:
                raise ResourceConflict("EPSO seed artifact changed or is unavailable")
            try:
                reference_smiles = read_seed(seed_file.storage_path)
            except ValueError as exc:
                raise InvalidParameter(str(exc)) from exc
            reference = seed_file.storage_path
            seed_reference = {"structure": {"dataset_id": str(seed_dataset_id), "file_id": str(seed_file.id), "sha256": seed_file.sha256},
                              "coordinate_frame_id": context["site"]["anchor"]["coordinate_frame_id"]}
        output = settings.data_root / "jobs" / str(job_id) / f"epso_{queue_job_id}"
        payload = {
            "engine": "epso",
            **parameters,
            "reference_ligand": reference,

            "reference_smiles": reference_smiles,
            **({"seed_reference": seed_reference} if seed_reference else {}),
            "protein_pdb": context["protein_pdb"],
            "structure_context": deepcopy(context),
            "ph": context["ph"] if context.get("ph") is not None else (context.get("preparation") or {}).get("ph", 7.4),
            "output_dir": str(output),
            "output_csv": str(output / "results.csv"),
            "trajectory_csv": str(output / "trajectory.csv"),
            "metadata_json": str(output / "metadata.json"),
        }
        if binding := epso_affinity_inputs(context, parameters, payload['ph']):
            payload['affinity_inputs'] = binding
        job_type = task_code = "property_optimization"
        normalized = {"engine": "epso", **parameters, **({"ligand_dataset_id": str(seed_dataset_id), "seed_source": deepcopy(config.get("seed_source") or {})} if seed_dataset_id else {})}

    source_meta = {
        "reference_ligand_dataset_id": context.get("context_dataset_id"),
        "reference_ligand_file_id": context.get("reference_ligand_file_id"),
    }
    if engine == "epso" and seed_dataset_id:
        source_meta.update({"ligand_dataset_id": str(seed_dataset_id),
                            "reference_ligand_dataset_id": str(seed_dataset_id),
                            "reference_ligand_file_id": payload.get("seed_reference", {}).get("structure", {}).get("file_id")})
    payload.update(sampling)
    if engine == 'ecloudgen':
        configure_ecloudgen_target(payload, config)
    payload.update(source_meta)
    normalized.update(sampling)
    if engine == 'ecloudgen' and config.get('num_clouds') is None:
        normalized['num_clouds'] = None
    normalized.update(source_meta)
    params_key = (
        "molecule_generation"
        if job_type == "molecule_generation"
        else "property_optimization"
    )
    job = Job(
        id=job_id,
        owner_user_id=owner_user_id,
        job_type=job_type,
        status="pending",
        input_dataset_id=protein_context_id,
        params={
            params_key: normalized,
            "structure_context": deepcopy(context),
            "protein_context_id": str(protein_context_id),
            "job_name": f"Workflow {str(workflow_id)[:8]} {engine.upper()}",
            "system_tags": {"workflow_id": str(workflow_id)},
        },
        summary={},
    )

    task = JobTask(
        id=task_id,
        job_id=job.id,
        task_code=task_code,
        runtime_task=engine,
        status="pending",
        queue_job_id=queue_job_id,
        depends_on=[],
        input_payload=payload,
        output_payload={},
    )
    job.summary = {
        "tasks": {
            task_code: {
                "queue_job_id": str(queue_job_id),
                "status": task.status,
                "runtime_task": engine,
            }
        }
    }
    db.add(job)
    db.add(task)
    db.add(
        QueueOutbox(
            job_task_id=task.id,
            queue_name=settings.redis_dispatch_queue,
            payload={
                "job_id": str(queue_job_id),
                "task": engine,
                "payload": payload,

                "result_queue": settings.redis_result_queue,
                "meta": {
                    "job_id": str(job.id),
                    "engine": engine,
                    "protein_context_id": str(protein_context_id),
                },
            },
            status="pending",
        )
    )
    db.flush()
    return job


def get_owned_job(db: Session, owner_user_id: uuid.UUID, job_id: uuid.UUID) -> Job:
    job = db.scalar(select(Job).where(Job.id == job_id, Job.owner_user_id == owner_user_id, Job.is_deleted.is_(False)))
    if job is None:
        raise ResourceNotFound("Job not found")
    return job


def get_postprocessing_source_task(db: Session, source: Job) -> JobTask:
    if source.job_type not in {"molecule_generation", "property_optimization"} or source.status != "succeeded":
        raise ResourceConflict("A succeeded generation or lead optimization job is required")
    task = db.scalar(select(JobTask).where(JobTask.job_id == source.id, JobTask.task_code == source.job_type))
    if task is None or task.status != "succeeded":
        raise ResourceConflict("A succeeded generation or lead optimization task is required")
    return task


def resolve_job_artifact(job: Job, value: Any, *, data_root: Path | None = None) -> Path:
    root = ((data_root or settings.data_root) / "jobs" / str(job.id)).resolve()
    path = Path(str(value or "")).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise InvalidParameter("Required artifact is missing or outside the job workspace")
    return path


def delete_reference_path(context):
    """Use the same prepared ligand for editing and DELETE inference."""
    if (context.get('capabilities') or {}).get('input_preparation') == 'context_features_v1':
        from genova_runtime.context_features import consume_context_inputs
        try:
            prepared = consume_context_inputs({'structure_context': context}, 'delete', dry_run=True)
            return prepared['reference_ligand']
        except (ValueError, KeyError, OSError) as exc:
            raise ResourceConflict('DELETE reference input is unavailable or changed; save the Context again') from exc
    reference = context.get('reference_ligand_path')
    if not reference or not Path(reference).is_file():
        raise ResourceConflict('DELETE requires a prepared reference ligand')
    return reference


def validate_delete_submission(context, edit):
    """Check DELETE inputs before task registration and return the reference path."""
    from genova_runtime.delete_edits import DeleteEditValidationError, validate_delete_edit, validate_edit_request

    try:
        if isinstance(edit, dict) and edit.get("mode") == "custom":
            reference = delete_reference_path(context)
            validate_delete_edit(reference, edit)
            return reference
        validate_edit_request(edit)
    except DeleteEditValidationError as exc:
        raise DomainValidationError(str(exc), code=exc.code, http_status=422) from exc
    except ValueError as exc:
        raise InvalidParameter(str(exc), http_status=422) from exc
    return context.get("reference_ligand_path")


def source_reference_ligand(task, job, *, data_root=None):
    import json
    from genova_runtime.pdb2pqr_compat import file_sha256
    data_root = data_root or settings.data_root
    inputs = task.input_payload
    context = inputs.get('structure_context') or {}
    if task.runtime_task == 'epso' and inputs.get('seed_reference') and not context.get('generation_reference'):
        return None
    if (context.get('capabilities') or {}).get('input_preparation') == 'context_features_v1':
        from genova_runtime.context_features import context_fingerprint
        try:
            entry = context['model_inputs'][task.runtime_task]
            manifest = Path(entry['manifest_path']).resolve()
            if entry['status'] not in {'full', 'limited'} or not manifest.is_relative_to(data_root.resolve()) or not manifest.is_file() or file_sha256(manifest) != entry['manifest_sha256']:
                raise ValueError('Prepared reference cache is unavailable or changed')
            cache = json.loads(manifest.read_text())
            if cache['version'] != 1 or cache['contract'] != 'context_features_v1' or cache['status'] not in {'full', 'limited'} or cache['engine'] != task.runtime_task or cache['context_id'] != context['context_dataset_id'] or cache['input_fingerprint'] != context_fingerprint(context, context['input_parameters']):
                raise ValueError('Prepared reference cache binding mismatch')
            reference = cache['files'].get('reference_ligand')
            if reference is None:
                return None
            path = Path(reference['path']).resolve()
            if not path.is_relative_to(data_root.resolve()) or not path.is_file() or file_sha256(path) != reference['sha256']:
                raise ValueError('Prepared reference ligand is unavailable or changed')
            return str(path)
        except (ValueError, KeyError, TypeError) as exc:
            raise ResourceConflict(str(exc)) from exc
    value = inputs.get('reference_ligand')
    if not value:
        value = task.output_payload.get('ligand_path')
        return str(resolve_job_artifact(job, value, data_root=data_root)) if value else None
    path = Path(value).resolve()
    if not path.is_relative_to(data_root.resolve()) or not path.is_file():
        raise ResourceConflict('Reference ligand is unavailable')
    return str(path)


def _shared_receptor_inputs(context, engine, *, data_root=None):
    from genova_runtime.context_features import context_fingerprint, load_shared_receptor
    if context.get('capabilities', {}).get('input_preparation') != 'context_features_v1':
        raise ResourceConflict('SHARED_RECEPTOR_REQUIRED: postprocessing requires a current validated Protein Context')
    if engine == 'epso':
        engine = next((name for name in ('ecloudgen', 'surfgen', 'delete')
            if (context.get('model_inputs', {}).get(name) or {}).get('status') in {'full', 'limited'}), None)
    entry = (context.get('model_inputs') or {}).get(engine)
    if not entry or entry.get('status') not in {'full', 'limited'}:
        raise ResourceConflict('SHARED_RECEPTOR_REQUIRED: validate a protein input when saving the Context; postprocessing does not prepare a receptor')
    binding = {**entry, 'engine': engine, 'context_id': context['context_dataset_id'],
        'input_fingerprint': context_fingerprint(context, context['input_parameters']),
        'effective_receptor_sha256': context['effective_receptor_sha256']}
    try:
        cache = load_shared_receptor(binding, data_root or settings.data_root)
    except (ValueError, KeyError) as exc:
        raise ResourceConflict(str(exc)) from exc
    return binding, cache


def _validate_docking_box(box):
    if not isinstance(box, dict) or any(
        not isinstance(box.get(key), list)
        or len(box[key]) != 3
        or any(type(value) not in (int, float) or not math.isfinite(value) or (key == 'size' and value <= 0) for value in box[key])
        for key in ('center', 'size')
    ):
        raise ValueError('Invalid source docking box')


def epso_affinity_inputs(context, parameters, ph):
    from genova_runtime.epso_objectives import AFFINITY_METRIC
    if not any(spec['metric'] == AFFINITY_METRIC for spec in parameters['objectives']):
        return None
    box = context.get('box')
    try:
        _validate_docking_box(box)
        if type(ph) not in (int, float) or not math.isfinite(ph):
            raise ValueError('Invalid Protein Context pH')
    except ValueError as exc:
        raise InvalidParameter(str(exc), http_status=422) from exc
    binding, cache = _shared_receptor_inputs(context, 'epso')
    return {'receptor': binding, 'protein_pdb': cache['files']['protein_pdb'],
            'box': deepcopy(box), 'ph': ph}


def source_postprocessing_inputs(task, *, data_root=None):
    context = task.input_payload.get('structure_context') or {}
    affinity = task.input_payload.get('affinity_inputs') if task.runtime_task == 'epso' else None
    if affinity:
        from genova_runtime.context_features import load_shared_receptor
        binding = deepcopy(affinity['receptor'])
        try:
            cache = load_shared_receptor(binding, data_root or settings.data_root)
            if cache['files']['protein_pdb'] != affinity['protein_pdb']:
                raise ValueError('Shared receptor differs from the protein used for EPSO affinity scoring')
        except (ValueError, KeyError) as exc:
            raise ResourceConflict(str(exc)) from exc
    else:
        binding, cache = _shared_receptor_inputs(context, task.runtime_task, data_root=data_root)
    if task.runtime_task != 'epso' and Path(task.output_payload.get('protein_path') or '').resolve() != Path(cache['files']['protein_pdb']['path']).resolve():
        raise ResourceConflict('Shared receptor differs from the protein used for generation')
    return binding, cache


def resolve_postprocessing_protein_artifact(db, owner_user_id, job, task, *, data_root=None):
    if job.job_type != 'molecule_postprocessing' or job.status != 'succeeded' or task.task_code != 'tarpass' or task.status != 'succeeded':
        raise ResourceConflict('A succeeded postprocessing protein artifact is required')
    source_id = ((job.params or {}).get('postprocessing') or {}).get('source_job_id')
    try:
        source_id = uuid.UUID(str(source_id))
    except (ValueError, TypeError) as exc:
        raise ResourceConflict('Postprocessing source binding is unavailable') from exc
    source = get_owned_job(db, owner_user_id, source_id)
    source_task = get_postprocessing_source_task(db, source)
    _, cache = source_postprocessing_inputs(source_task, data_root=data_root)
    protein = cache['files']['protein_pdb']
    path = Path(protein['path']).resolve()
    expected = Path(task.output_payload.get('protein_path') or '').resolve()
    if not expected.is_file() or expected != path:
        raise ResourceConflict('Postprocessing protein does not match its source generation input')
    source_input = Path(task.input_payload.get('protein_pdb') or '').resolve()
    if source_input != path:
        raise ResourceConflict('Postprocessing protein input does not match its source generation input')
    if source_task.runtime_task != 'epso' and source_task.output_payload.get('protein_path'):
        if Path(source_task.output_payload['protein_path']).resolve() != path:
            raise ResourceConflict('Source protein does not match the generation input')
    root = (data_root or settings.data_root).resolve() / 'jobs'
    try:
        relative = path.relative_to(root)
        producer_id = uuid.UUID(relative.parts[0])
    except (ValueError, IndexError) as exc:
        raise ResourceConflict('Postprocessing protein producer is unavailable') from exc
    producer = get_owned_job(db, owner_user_id, producer_id)
    if producer.job_type != 'protein_preparation' or producer.status != 'succeeded':
        raise ResourceConflict('Postprocessing protein producer is unavailable')
    resolved = resolve_job_artifact(producer, path, data_root=data_root)
    if file_sha256(resolved) != protein['sha256']:
        raise ResourceConflict('Postprocessing protein changed')
    return resolved


def resolve_postprocessing_context(db, owner_user_id, inputs, context_id=None):
    original = inputs.get('structure_context') or {}
    context = original
    if context_id is None and (not inputs.get('protein_pdb') or inputs.get('protein_pdb') != original.get('protein_pdb')):
        raise ResourceConflict('Source receptor binding is missing or inconsistent')
    if context_id is not None:
        try:
            identity = uuid.UUID(str(context_id))
        except (ValueError, TypeError) as exc:
            raise InvalidParameter('Invalid postprocessing protein_context_id', http_status=422) from exc
        dataset = get_owned_dataset(db, identity, owner_user_id)
        if dataset.kind != 'protein_context':
            raise ResourceNotFound('Protein Context not found')
        from backend.services.binding_sites import resolve_v4_context
        try:
            context = resolve_v4_context(dataset, db, owner_user_id)
        except HTTPException as exc:
            raise ResourceConflict(str(exc.detail)) from exc
        if (original.get('prepared_complex') or {}).get('sha256') != (context.get('prepared_complex') or {}).get('sha256') or not original.get('prepared_complex'):
            raise ResourceConflict('Postprocessing Context must reuse the same prepared structure and coordinates')
        if original.get('generation_reference') != context.get('generation_reference') or original['site']['anchor']['coordinate_frame_id'] != context['site']['anchor']['coordinate_frame_id']:
            raise ResourceConflict('Postprocessing Context must preserve the source coordinate frame and reference')
    if context.get('capabilities', {}).get('receptor_policy') != 'protein_metals_v1':
        raise ResourceConflict('CONTEXT_RECEPTOR_UPDATE_REQUIRED: update the source Context and bind its new Context for postprocessing')
    return context


def create_postprocessing_job(
    db: Session,
    *,
    owner_user_id: uuid.UUID,
    params: dict[str, Any],
    runtime_settings: Any = settings,
) -> Job:
    """Add TarPass Job, task, and outbox rows without committing."""
    from backend.services.resources import check_admission
    check_admission(db, owner_user_id)
    raw = (params or {}).get("postprocessing")
    if not isinstance(raw, dict):
        raise InvalidParameter("params.postprocessing is required", http_status=422)
    try:
        source_id = uuid.UUID(str(raw.get("source_job_id")))
        filters = validate_filters(raw.get("prefilters", deepcopy(DEFAULT_PREFILTERS)), pre=True)
    except (ValueError, TypeError) as exc:
        raise InvalidParameter(str(exc), http_status=422) from exc
    source = get_owned_job(db, owner_user_id, source_id)
    source_task = get_postprocessing_source_task(db, source)
    selected_input = None
    if raw.get("input_sdf_dataset_id"):
        try:
            selected_dataset_id = uuid.UUID(str(raw["input_sdf_dataset_id"]))
        except (ValueError, TypeError) as exc:
            raise InvalidParameter("input_sdf_dataset_id must be a valid dataset UUID", http_status=422) from exc
        selected_dataset = get_owned_dataset(db, selected_dataset_id, owner_user_id)
        selected_files = get_dataset_files(db, selected_dataset.id)
        if len(selected_files) != 1 or Path(selected_files[0].original_filename).suffix.lower() != ".sdf":
            raise InvalidParameter("input_sdf_dataset_id must contain exactly one SDF file", http_status=422)
        selected_input = selected_files[0]
        if not Path(selected_input.storage_path).is_file() or file_sha256(selected_input.storage_path) != selected_input.sha256:
            raise ResourceConflict("Selected pose input changed or is unavailable")
        input_key, artifact_key = "input_sdf", None
        source_artifact = Path(selected_input.storage_path)
    elif source_task.output_payload.get("generated_sdf"):
        input_key, artifact_key = "input_sdf", "generated_sdf"
        source_artifact = resolve_job_artifact(source, source_task.output_payload.get(artifact_key), data_root=runtime_settings.data_root)
    elif source_task.output_payload.get("output_csv"):
        input_key, artifact_key = "input_csv", "output_csv"
        source_artifact = resolve_job_artifact(source, source_task.output_payload.get(artifact_key), data_root=runtime_settings.data_root)
    else:
        raise InvalidParameter("Source task has no generated SDF or molecule CSV")
    if input_key == "input_csv":
        with source_artifact.open(newline="", encoding="utf-8-sig") as stream:
            if "smiles" not in (csv.DictReader(stream).fieldnames or []):
                raise InvalidParameter("Source CSV requires a smiles column", http_status=422)
    inputs = source_task.input_payload
    reference_ligand = source_reference_ligand(source_task, source, data_root=runtime_settings.data_root)
    shared_binding, shared_cache = source_postprocessing_inputs(source_task, data_root=runtime_settings.data_root)
    shared_binding['reference_ligand'] = {'path': reference_ligand, 'sha256': file_sha256(Path(reference_ligand))} if reference_ligand else None
    context = resolve_postprocessing_context(db, owner_user_id, inputs, raw.get('protein_context_id'))
    protein = context.get('protein_pdb')
    box = context.get("box")
    if not protein or not Path(protein).is_file() or not isinstance(box, dict):
        raise ResourceConflict("Source job requires a prepared Protein Context with docking box")
    from genova_runtime.structure_inputs import validate_context_snapshot, validate_context_engine_support
    try:
        validate_context_snapshot(context, protein)
        validate_context_engine_support(context, 'tarpass')
    except ValueError as exc:
        raise ResourceConflict(str(exc)) from exc
    try:
        _validate_docking_box(box)
        rules = validate_interactions(raw.get("key_interactions", []), protein_residues(protein))
        reference_id = uuid.UUID(str(raw["reference_dataset_id"])) if raw.get("reference_dataset_id") else None
    except (ValueError, TypeError) as exc:
        raise InvalidParameter(str(exc), http_status=422) from exc
    reference_file = None
    if reference_id:
        get_owned_dataset(db, reference_id, owner_user_id)
        reference_file = pick_dataset_file(get_dataset_files(db, reference_id), ["attachment"], {".sdf", ".smi", ".txt"})
        if reference_file is None:
            raise InvalidParameter("Reference dataset requires SDF or SMILES text", http_status=422)
    if not reference_file and any(rule["metric"] in {"reference_similarity", "scaffold_similarity"} for rule in filters):
        raise InvalidParameter("Reference similarity filters require reference_dataset_id", http_status=422)
    normalized = {
        "source_job_id": str(source.id),
        "prefilters": filters,
        "key_interactions": rules,
        "reference_dataset_id": str(reference_id) if reference_id else None,
        "protein_context_id": context.get('id'),
        **({"input_sdf_dataset_id": str(selected_input.dataset_id)} if selected_input else {}),
    }
    name = (params or {}).get("job_name", "")
    if not isinstance(name, str) or len(name) > 200:
        raise InvalidParameter("job_name must be a string of at most 200 characters", http_status=422)
    default_name = f"Postprocessing {source.params.get('job_name') or source.params.get('name') or str(source.id)[:8]}"[:200]
    job = Job(
        id=uuid.uuid4(),
        owner_user_id=owner_user_id,
        job_type="molecule_postprocessing",
        status="pending",
        params={"postprocessing": normalized, "job_name": name.strip() or default_name, "protein_context_id": context.get('id'), 'source_protein_context_id': source.params.get('protein_context_id'), 'structure_context': deepcopy(context)},
        summary={},
    )
    task = JobTask(
        id=uuid.uuid4(),
        job_id=job.id,
        task_code="tarpass",
        runtime_task="tarpass",
        status="pending",
        queue_job_id=uuid.uuid4(),
        depends_on=[],
        input_payload={
            "source_job_id": str(source.id),
            "structure_context": deepcopy(context),
            input_key: str(source_artifact),
            "protein_pdb": shared_cache['files']['protein_pdb']['path'],
            "postprocessing_inputs": shared_binding,
            "reference_ligand": reference_ligand,
            "box": deepcopy(box),
            "ph": inputs.get("ph", 7.4),
            "output_dir": str(runtime_settings.data_root / "jobs" / str(job.id) / "tarpass"),
            "prefilters": filters,
            "key_interactions": rules,
            "reference_dataset_path": reference_file.storage_path if reference_file else None,
        },
        output_payload={},
    )
    if inputs.get("fragment_sdf"):
        task.input_payload["fragment_sdf"] = str(resolve_job_artifact(source, inputs["fragment_sdf"], data_root=runtime_settings.data_root))
    db.add(job)
    db.add(task)
    db.add(
        QueueOutbox(
            job_task_id=task.id,
            queue_name=runtime_settings.redis_dispatch_queue,
            payload={
                "job_id": str(task.queue_job_id),
                "task": "tarpass",
                "payload": task.input_payload,
                "result_queue": runtime_settings.redis_result_queue,
                "meta": {"job_id": str(job.id)},
            },
            status="pending",
        )
    )
    db.flush()
    return job


def create_protein_preparation_job(payload, db, user_id):
    if payload.prepared_receptor_id is None:
        raise HTTPException(422, "Protein preparation requires prepared_receptor_id")
    from backend.services.prepared_receptors import submit_preparation
    return submit_preparation(payload.prepared_receptor_id, db, user_id)


def cancel_owned_job(db: Session, owner_user_id: uuid.UUID, job_id: uuid.UUID):
    from backend.utils import utcnow
    from backend.worker import _update_protein_preparation_context
    job = get_owned_job(db, owner_user_id, job_id)
    if job.status in {"succeeded", "failed", "canceled", "partial_succeeded"}:
        return []

    outbox = list(db.scalars(select(QueueOutbox).where(QueueOutbox.job_task_id.in_(select(JobTask.id).where(JobTask.job_id == job.id)), QueueOutbox.status == 'pending').order_by(QueueOutbox.id).with_for_update()))
    tasks = db.scalars(select(JobTask).where(JobTask.job_id == job.id).order_by(JobTask.id).with_for_update().execution_options(populate_existing=True)).all()
    db.refresh(job,with_for_update=True)
    if job.status in {"succeeded","failed","canceled","partial_succeeded"}:
        return []
    for row in outbox:
        row.status = 'canceled'
    now = utcnow()
    canceled = []
    for task in tasks:
        if task.status not in {"succeeded", "failed", "skipped", "canceled"}:
            task.status = "canceled"
            task.finished_at = now
            task.updated_at = now
            canceled.append(task.queue_job_id)
            if task.task_code == "protein_preparation" or task.task_code.startswith("context_compatibility_"):
                # The worker ignores results of canceled tasks, so release the Context here.
                try:
                    _update_protein_preparation_context(db, task, status_value="failed",
                        error_message="Protein preparation was canceled")
                except ValueError:
                    pass  # The Context was edited or re-prepared since; it no longer waits on this Job.

    job.status = "canceled"
    job.finished_at = now
    job.updated_at = now
    return canceled


def continue_generation(db: Session, owner_user_id: uuid.UUID, job_id: uuid.UUID) -> Job:
    from backend.services.resources import check_admission
    from backend.utils import utcnow

    job = get_owned_job(db, owner_user_id, job_id)
    check_admission(db, owner_user_id)
    task = db.scalar(select(JobTask).where(JobTask.job_id == job.id, JobTask.task_code == 'molecule_generation')
                     .with_for_update().execution_options(populate_existing=True))
    db.refresh(job, with_for_update=True)
    if job.is_deleted:
        raise ResourceNotFound('Job not found')
    if (job.status != 'succeeded' or task is None or task.status != 'succeeded'
            or task.runtime_task != 'surfgen'
            or task.input_payload.get('generation_policy') != GENERATION_POLICY
            or task.input_payload.get('generation_window', 1) != 1
            or not task.output_payload.get('can_continue_generation')):
        raise ResourceConflict('This generation job cannot be continued')

    workspace = Path(task.input_payload['output_dir']).resolve()
    previous_output = Path(task.output_payload.get('output_csv', '')).resolve()
    job_root = (settings.data_root / 'jobs' / str(job.id)).resolve()
    if (not workspace.is_relative_to(job_root) or not previous_output.is_relative_to(workspace)
            or not previous_output.is_file() or not (workspace / 'generation_rounds.json').is_file()):
        raise ResourceConflict('Saved generation results are unavailable')

    now = utcnow()
    task.queue_job_id = uuid.uuid4()
    task.input_payload = {**task.input_payload, 'generation_window': 2, 'previous_output_csv': str(previous_output)}
    task.status = 'pending'
    task.started_at = task.finished_at = None
    task.updated_at = now
    task.error_message = None
    job.status = 'pending'
    job.finished_at = None
    job.updated_at = now
    job.summary = {**job.summary, 'tasks': {task.task_code: {
        'queue_job_id': str(task.queue_job_id), 'runtime_task': task.runtime_task, 'status': task.status,
    }}}
    db.add(QueueOutbox(job_task_id=task.id, queue_name=settings.redis_dispatch_queue, payload={
        'job_id': str(task.queue_job_id), 'task': task.runtime_task, 'payload': task.input_payload,
        'result_queue': settings.redis_result_queue, 'meta': {'job_id': str(job.id), 'engine': task.runtime_task},
    }))
    return job
