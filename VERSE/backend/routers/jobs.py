import json
import logging
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from backend import schemas
from backend.config import settings
from backend.builtin_datasets import BUILTIN_OWNER_ID
from backend.db import get_db
from backend.deps import get_current_user
from backend.models import JobSubmission, Dataset, DatasetFile, Job, JobTask, QueueOutbox, SmallMoleculeResult, User
from backend.realtime import build_job_event, get_sync_redis_client, publish_job_event_sync, publish_user_event_sync
from backend.result_rows import backfill_small_molecule_results_for_job
from backend.services.jobs import create_protein_preparation_job, create_molecule_generation_job, validated_generation_settings, build_molecule_generation_payload, configure_ecloudgen_target, continue_generation, DomainValidationError, resolve_postprocessing_protein_artifact
from backend.services.jobs import validate_delete_submission
from backend.utils import utcnow
from genova_runtime.delete_edits import AUTO_EDIT_MODES, EDIT_MODES, build_candidates, reference_preview
from genova_runtime.generation_rounds import GENERATION_POLICY
from genova_runtime.generation_settings import COUNT_LIMITS, DEFAULT_GENERATION_COUNT, DEFAULTS, sampling_plan


router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = logging.getLogger("backend-jobs")


PROTEIN_PREPARATION_OPTION_NAMES = (
    "repair_structure",
    "add_hydrogens",
    "update_protonation",
    "optimize_hydrogen_bonds",
    "minimize_energy",
)


def _publish_job_event_safely(
    db: Session,
    job_id: uuid.UUID,
    *,
    event: str = "job.updated",
) -> None:
    try:
        publish_job_event_sync(db, job_id, event=event)
    except Exception:
        logger.exception("Failed publishing realtime event for job_id=%s", job_id)


def _publish_user_event_safely(user_id: uuid.UUID, payload: dict[str, Any]) -> None:
    try:
        publish_user_event_sync(user_id, payload)
    except Exception:
        logger.exception("Failed publishing realtime event for user_id=%s", user_id)


def _get_dataset(db: Session, dataset_id: uuid.UUID, user_id: uuid.UUID) -> Dataset:
    dataset = db.scalar(select(Dataset).where(
        Dataset.id == dataset_id,
        or_(Dataset.owner_user_id == user_id, Dataset.owner_user_id == BUILTIN_OWNER_ID),
    ))
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Dataset not found: {dataset_id}")
    return dataset


def _get_dataset_files(db: Session, dataset_id: uuid.UUID) -> list[DatasetFile]:
    return db.scalars(select(DatasetFile).where(DatasetFile.dataset_id == dataset_id)).all()


def _pick_file(files: list[DatasetFile], preferred_roles: list[str], suffixes: set[str]) -> DatasetFile | None:
    for role in preferred_roles:
        for row in files:
            if row.file_role == role and Path(row.original_filename).suffix.lower() in suffixes:
                return row
    for row in files:
        if Path(row.original_filename).suffix.lower() in suffixes:
            return row
    return None


def _resolve_protein_context(db, user_id, protein_context_id):
    if protein_context_id is None:
        return {}
    from backend.services.jobs import validate_protein_context_for_generation, DomainValidationError, ResourceNotFound, ProteinNotReady
    try:
        return validate_protein_context_for_generation(db, user_id, protein_context_id)
    except (ResourceNotFound, ProteinNotReady) as exc:
        raise HTTPException(409, detail={"error_code": "PROTEIN_CONTEXT_STALE", "protein_context_id": str(protein_context_id)}) from exc
    except DomainValidationError as exc:
        raise HTTPException(exc.http_status, exc.message) from exc


def _normalize_num_molecules(params: dict[str, Any], task_code: str) -> int:
    value = params.get("num_molecules", 100 if params.get('engine') == 'epso' else DEFAULT_GENERATION_COUNT)
    limit = COUNT_LIMITS.get(params.get("engine"), COUNT_LIMITS['epso'])
    if type(value) is not int or not 1 <= value <= limit:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{task_code}.num_molecules must be an integer between 1 and {limit}",
        )
    return value


def _build_molecule_generation_payload(
    *,
    db: Session,
    mol_gen_params: dict[str, Any],
    job_id: uuid.UUID,
    task_queue_job_id: uuid.UUID,
    ligand_dataset_id: uuid.UUID | None = None,
    structure_context: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    engine = str(mol_gen_params.get("engine", "")).strip().lower()
    if engine not in {"surfgen", "ecloudgen"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="molecule_generation.engine must be surfgen or ecloudgen",
        )
    if engine == 'surfgen':
        return build_molecule_generation_payload(db=db, mol_gen_params=mol_gen_params, job_id=job_id,
            task_queue_job_id=task_queue_job_id, ligand_dataset_id=ligand_dataset_id, structure_context=structure_context)
    base_dir = settings.data_root / "jobs" / str(job_id)
    base_dir.mkdir(parents=True, exist_ok=True)

    if not structure_context:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{engine} requires a prepared Protein Context",
        )
    ecloud_params = {}
    if engine == "ecloudgen":
        if "num_molecules" in mol_gen_params:
            raise HTTPException(status_code=400, detail="ECloudGen now requires target_num_molecules; resubmit the target count")
        target = mol_gen_params.get("target_num_molecules", DEFAULT_GENERATION_COUNT)
        if type(target) is not int or not 1 <= target <= COUNT_LIMITS['ecloudgen']:
            raise HTTPException(status_code=400, detail="molecule_generation.target_num_molecules must be an integer between 1 and 50000")
        ecloud_params = {"target_num_molecules": target}
    sampling = validated_generation_settings(engine, {**mol_gen_params, **ecloud_params})
    if ligand_dataset_id is not None:
        raise HTTPException(422, "Generation uses the reference from Protein Context; create a new binding site to change it")
    output_dir = base_dir / f"{engine}_{task_queue_job_id}"
    reference_ligand = structure_context.get("reference_ligand_path")
    output = {
        "engine": engine,
        "protein_pdb": structure_context["protein_pdb"],
        "structure_context": deepcopy(structure_context or {}),
        "reference_ligand": reference_ligand,
        "output_dir": str(output_dir),
        "output_csv": str(output_dir / "generated_molecules.csv"),
        **ecloud_params,
        **sampling,
        "ph": structure_context["ph"] if structure_context.get("ph") is not None else 7.4,
    }
    configure_ecloudgen_target(output, mol_gen_params)
    return output, {
        "engine": engine,
        "protein_context_id": structure_context["id"],
        "protein_context_file_id": structure_context["protein_file_id"],
        "ligand_dataset_id": str(ligand_dataset_id) if ligand_dataset_id else None,
        "ligand_dataset_file_id": None,
        "prepared_reference_ligand_file_id": structure_context.get("reference_ligand_file_id"),
    }


def _build_delete_payload(
    *,
    db: Session,
    user_id: uuid.UUID,
    ligand_dataset_id: uuid.UUID | None,
    property_params: dict[str, Any],
    job_id: uuid.UUID,
    task_queue_job_id: uuid.UUID,
    structure_context: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    protein_pdb = (structure_context or {}).get("protein_pdb")
    if not protein_pdb:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Lead Optimization requires a protein .pdb file")
    if ligand_dataset_id is not None:
        raise HTTPException(422, 'A generation reference is immutable; create a new binding site to change it')
    if not structure_context.get('generation_reference'):
        raise HTTPException(422, 'DELETE requires a generation reference')
    try:
        reference_path = validate_delete_submission(structure_context, property_params.get("edit"))
    except DomainValidationError as exc:
        raise HTTPException(exc.http_status, detail={"error_code": exc.code, "message": exc.message}) from exc
    reference_meta = {'reference_ligand_dataset_id': structure_context.get('context_dataset_id'),
                      'reference_ligand_file_id': structure_context.get('reference_ligand_file_id')}

    num_molecules = _normalize_num_molecules(property_params, "property_optimization")
    sampling = validated_generation_settings('delete', property_params)

    output_dir = settings.data_root / "jobs" / str(job_id) / f"delete_{task_queue_job_id}"
    fragment_path = output_dir / "fragment.sdf"
    edit_meta = {'edit_mode': property_params['edit']['mode'], 'anchor_atom_indices': []}
    payload = {
        "protein_pdb": protein_pdb,
        "ph": structure_context["ph"] if structure_context.get("ph") is not None else 7.4,
        "reference_ligand": str(reference_path) if reference_path else None,
        "edit": dict(property_params["edit"]),
        "structure_context": deepcopy(structure_context or {}),
        "fragment_sdf": str(fragment_path),
        "anchor_atom_indices": edit_meta["anchor_atom_indices"]
        if edit_meta["edit_mode"] == "derivation_site"
        else [],
        "num_molecules": num_molecules,
        "generation_policy": GENERATION_POLICY,
        "output_dir": str(output_dir),
        **sampling,
        "output_csv": str(output_dir / "results.csv"),
        "generated_sdf": str(output_dir / "generated.sdf"),
    }
    return payload, {
        "engine": "delete",
        "protein_context_id": (structure_context or {}).get("id"),
        "ligand_dataset_id": str(ligand_dataset_id) if ligand_dataset_id else None,
        "num_molecules": num_molecules,
        **reference_meta,
        **edit_meta,
    }


def _build_epso_payload(*, db, user_id, ligand_dataset_id, property_params, job_id,
                        task_queue_job_id, structure_context=None):
    from backend.services.jobs import epso_affinity_inputs
    from genova_runtime.epso_objectives import read_seed, validate_parameters, validate_requested_count

    if not structure_context or not structure_context.get('protein_pdb'):
        raise HTTPException(400, 'EPSO requires a prepared Protein Context')
    from genova_runtime.structure_inputs import validate_context_engine_support, validate_context_snapshot
    try:
        if ligand_dataset_id is not None:
            validate_context_snapshot(structure_context, structure_context['protein_pdb'])
        else:
            validate_context_engine_support(structure_context, 'epso')
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _normalize_num_molecules(property_params, "property_optimization")
    try:
        parameters = validate_parameters(property_params)
        validate_requested_count(parameters['num_molecules'], parameters['objectives'])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if ligand_dataset_id is not None:
        _get_dataset(db, ligand_dataset_id, user_id)
        files = _get_dataset_files(db, ligand_dataset_id)
        if len(files) != 1 or Path(files[0].original_filename).suffix.lower() != '.sdf':
            raise HTTPException(400, 'EPSO seed dataset must contain exactly one SDF file')
    reference, source = _resolve_delete_reference(db, user_id, ligand_dataset_id, structure_context, engine="epso")
    try:
        reference_smiles = read_seed(reference) if ligand_dataset_id is not None else None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    ph = structure_context['ph'] if structure_context.get('ph') is not None else 7.4
    try:
        affinity = epso_affinity_inputs(structure_context, parameters, ph)
    except DomainValidationError as exc:
        raise HTTPException(exc.http_status, exc.message) from exc
    output = settings.data_root / 'jobs' / str(job_id) / f'epso_{task_queue_job_id}'
    return {
        'engine': 'epso', **parameters, 'reference_ligand': str(reference) if reference else None,
        **({'seed_reference': source['seed_reference']} if source.get('seed_reference') else {}),
        'reference_smiles': reference_smiles, **source,
        'protein_pdb': structure_context['protein_pdb'],
        'structure_context': deepcopy(structure_context),
        'ph': ph,
        **({'affinity_inputs': affinity} if affinity else {}),
        'output_dir': str(output), 'output_csv': str(output / 'results.csv'),
        'trajectory_csv': str(output / 'trajectory.csv'), 'metadata_json': str(output / 'metadata.json'),
    }, {'engine': 'epso', **source, 'protein_context_id': structure_context['id'],
        'ligand_dataset_id': str(ligand_dataset_id) if ligand_dataset_id else None}


def _resolve_delete_reference(
    db: Session,
    user_id: uuid.UUID,
    ligand_dataset_id: uuid.UUID | None,
    structure_context: dict[str, Any] | None,
    *,
    engine: str = "delete",
) -> tuple[Path, dict[str, Any]]:
    if engine == "delete":
        if ligand_dataset_id is not None:
            raise HTTPException(422, "A v4 generation reference is immutable; create a new binding site to change it")
        from genova_runtime.structure_inputs import validate_engine_context
        try:
            validate_engine_context(structure_context, engine)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        from backend.services.jobs import delete_reference_path
        try:
            reference = delete_reference_path(structure_context)
        except DomainValidationError as exc:
            raise HTTPException(exc.http_status, exc.message) from exc
        return Path(reference), {'reference_ligand_dataset_id': structure_context.get('context_dataset_id'),
                                 'reference_ligand_file_id': structure_context.get('reference_ligand_file_id')}
    if ligand_dataset_id is not None:
        _get_dataset(db, ligand_dataset_id, user_id)
        ligand_file = _pick_file(
            _get_dataset_files(db, ligand_dataset_id),
            preferred_roles=["ligand_input", "attachment"],
            suffixes={".sdf"},
        )
        if ligand_file is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Lead Optimization requires a reference ligand .sdf file",
            )
        path = Path(ligand_file.storage_path)
        meta = {
            "reference_ligand_dataset_id": str(ligand_dataset_id),
            "reference_ligand_file_id": str(ligand_file.id),
            "seed_reference": {"structure": {"dataset_id": str(ligand_dataset_id), "file_id": str(ligand_file.id), "sha256": ligand_file.sha256}, "coordinate_frame_id": structure_context["site"]["anchor"]["coordinate_frame_id"]},
        }
    else:
        if structure_context.get("generation_reference", {}).get("kind") == "source_component":
            return None, {"reference_ligand_dataset_id": structure_context.get("context_dataset_id"), "reference_ligand_file_id": structure_context["generation_reference"]["source_component_id"]}
        value = (structure_context or {}).get("reference_ligand_path")
        if not value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Lead Optimization requires a reference ligand .sdf file",
            )
        path = Path(value)
        meta = {
            "reference_ligand_dataset_id": (structure_context or {}).get("context_dataset_id"),
            "reference_ligand_file_id": (structure_context or {}).get("reference_ligand_file_id"),
        }
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Dataset file missing: {path}",
        )
    return path, meta


def _job_query(summary: bool):
    if not summary:
        return select(Job)
    return select(*[column if column.key != 'params' else
                    column.delete_path(['structure_context', 'reference_source']).label('params')
                    for column in Job.__table__.columns])


def _serialize_job(db: Session, job: Job, with_tasks: bool = False, summary: bool = False) -> schemas.JobOut:
    out = schemas.JobOut.model_validate(job)
    active = job.status in {'pending', 'queued', 'running', 'blocked'}
    automatic = (((job.params or {}).get('structure_context') or {}).get('capabilities') or {}).get('preparation_strategy') == 'generation_auto_v1' or (((job.params or {}).get('prepared_spec') or {}).get('preparation') or {}).get('strategy') == 'generation_auto_v1'
    if with_tasks or active and automatic:
        task_query = select(JobTask) if not summary else select(*[
            column if column.key != 'input_payload' else
            column.delete_path(['structure_context', 'reference_source']).label('input_payload')
            for column in JobTask.__table__.columns])
        task_query = task_query.where(JobTask.job_id == job.id).order_by(JobTask.created_at.asc())
        tasks = db.execute(task_query).all() if summary else db.scalars(task_query).all()
        if with_tasks:
            out.tasks = [schemas.JobTaskOut.model_validate(task) for task in tasks if not task.task_code.startswith("plip2d_")]
        if active and automatic:
            import json
            for task in tasks:
                directory = Path(task.input_payload.get('output_dir', '')).resolve()
                if not directory.is_relative_to((settings.data_root / 'jobs' / str(job.id)).resolve()):
                    continue
                progress = directory / 'generation_progress.json'
                if task.input_payload.get('generation_policy') == GENERATION_POLICY and progress.is_file():
                    try:
                        summary = json.loads(progress.read_text())
                        if summary.get('queue_job_id') == str(task.queue_job_id):
                            out.summary = {**(out.summary or {}), 'generation_progress': summary}
                    except (OSError, ValueError):
                        pass
                path = directory / ('preparation_progress.json' if job.job_type == 'protein_preparation' else 'model_initialization.json')
                if path.is_file():
                    report = json.loads(path.read_text())
                    if job.job_type == 'protein_preparation':
                        bound = report.get('requested_spec') == job.params['prepared_spec']
                        stage = report.get('stage')
                    else:
                        bound = report.get('effective_receptor_sha256') == job.params['structure_context']['effective_receptor_sha256']
                        stage = report.get('stage')
                    if bound and stage:
                        out.summary = {**(out.summary or {}), 'execution_stage': stage}
    return out


def _create_protein_preparation_job(payload: schemas.JobCreateRequest, db: Session, current_user: User) -> schemas.JobOut:
    job = create_protein_preparation_job(payload, db, current_user.id)
    db.flush()
    db.refresh(job)
    return _serialize_job(db, job, with_tasks=True)


def _create_molecule_generation_job(
    payload: schemas.JobCreateRequest,
    db: Session,
    current_user: User,
) -> schemas.JobOut:
    params = dict(payload.params or {})
    mol_gen_params = dict(params["molecule_generation"])
    engine = str(mol_gen_params.get("engine", "")).strip().lower()
    if engine not in {"surfgen", "ecloudgen"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="molecule_generation.engine must be surfgen or ecloudgen")
    structure_context = _resolve_protein_context(
        db,
        current_user.id,
        payload.protein_context_id,
    )
    if structure_context:
        if payload.ligand_dataset_id is not None:
            raise HTTPException(422, "A v4 generation reference is immutable; create a new binding site to change it")
        params["structure_context"] = deepcopy(structure_context)
        params["protein_context_id"] = str(payload.protein_context_id)
    if not structure_context:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{engine} requires a prepared Protein Context",
        )
    from genova_runtime.structure_inputs import validate_engine_context
    try:
        validate_engine_context(structure_context, engine)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    if engine == 'surfgen':
        job = create_molecule_generation_job(db, owner_user_id=current_user.id,
            protein_context_id=payload.protein_context_id, params=params,
            ligand_dataset_id=payload.ligand_dataset_id, structure_context=structure_context)
        db.flush()
        db.refresh(job)
        return _serialize_job(db, job, with_tasks=True)

    job = Job(
        owner_user_id=current_user.id,
        job_type=payload.job_type,
        status="pending",
        input_dataset_id=payload.protein_context_id or payload.pocket_dataset_id or payload.ligand_dataset_id,
        params=params,
    )
    db.add(job)
    db.flush()

    now = utcnow()
    task = JobTask(
        id=uuid.uuid4(),
        job_id=job.id,
        task_code="molecule_generation",
        runtime_task=engine,
        status="pending",
        queue_job_id=uuid.uuid4(),
        depends_on=[],
        input_payload={},
        output_payload={},
        created_at=now,
        updated_at=now,
    )
    db.add(task)

    task_payload, task_meta = _build_molecule_generation_payload(
        db=db,
        mol_gen_params=mol_gen_params,
        job_id=job.id,
        task_queue_job_id=task.queue_job_id,
        ligand_dataset_id=payload.ligand_dataset_id,
        structure_context=structure_context,
    )
    task.input_payload = task_payload
    task.updated_at = utcnow()

    # Recorded so dataset deletion can see the extra ligand this queued job still reads.
    job.params = {**params, "molecule_generation": {
        **mol_gen_params, "engine": engine, "ligand_dataset_id": task_meta["ligand_dataset_id"],
        **{key: task_payload[key] for key in DEFAULTS[engine]},
        **({"target_num_molecules": task_payload["target_num_molecules"]}
           if engine == "ecloudgen" else {"num_molecules": task_payload["num_molecules"]}),
        **({'num_clouds': None} if mol_gen_params.get('num_clouds') is None else {}),
    }}

    dispatch_message = {
        "job_id": str(task.queue_job_id),
        "task": task.runtime_task,
        "payload": task_payload,
        "result_queue": settings.redis_result_queue,
        "meta": {"job_id": str(job.id), **task_meta},
    }
    db.add(
        QueueOutbox(
            job_task_id=task.id,
            queue_name=settings.redis_dispatch_queue,
            payload=dispatch_message,
            status="pending",
        )
    )

    job.summary = {
        "tasks": {
            "molecule_generation": {
                "queue_job_id": str(task.queue_job_id),
                "status": task.status,
                "runtime_task": task.runtime_task,
            }
        }
    }

    db.flush()
    db.refresh(job)
    return _serialize_job(db, job, with_tasks=True)


def _create_property_optimization_job(
    payload: schemas.JobCreateRequest,
    db: Session,
    current_user: User,
) -> schemas.JobOut:
    params = dict(payload.params or {})
    raw = params["property_optimization"]
    if not isinstance(raw, dict):
        raise HTTPException(400, "property_optimization must be an object")
    property_params = dict(raw)
    engine = str(property_params.get("engine", "")).strip().lower()
    if engine not in {"delete", "epso"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="property_optimization.engine must be delete or epso")
    property_params["engine"] = engine
    params["property_optimization"] = property_params
    structure_context = _resolve_protein_context(
        db,
        current_user.id,
        payload.protein_context_id,
    )
    if payload.ligand_dataset_id is None and not (structure_context or {}).get("reference_ligand_path") and not (structure_context or {}).get("generation_reference"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lead Optimization requires a prepared reference ligand or ligand_dataset_id",
        )
    if structure_context:
        params["structure_context"] = deepcopy(structure_context)
        params["protein_context_id"] = str(payload.protein_context_id)

    job = Job(
        id=uuid.uuid4(),
        owner_user_id=current_user.id,
        job_type=payload.job_type,
        status="pending",
        input_dataset_id=payload.ligand_dataset_id or payload.protein_context_id or payload.pocket_dataset_id,
        params=deepcopy(params),
    )
    now = utcnow()
    task = JobTask(
        id=uuid.uuid4(),
        job_id=job.id,
        task_code="property_optimization",
        runtime_task=engine,
        status="pending",
        queue_job_id=uuid.uuid4(),
        depends_on=[],
        input_payload={},
        output_payload={},
        created_at=now,
        updated_at=now,
    )
    builder = _build_epso_payload if engine == "epso" else _build_delete_payload
    task_payload, task_meta = builder(
        db=db,
        user_id=current_user.id,
        ligand_dataset_id=payload.ligand_dataset_id,
        structure_context=structure_context,
        property_params=property_params,
        job_id=job.id,
        task_queue_job_id=task.queue_job_id,
    )
    if engine == "epso":
        property_params.update({key: task_payload[key] for key in ("num_molecules", "objectives", "optimizer")})
        params["seed_source"] = {key: task_meta[key] for key in ("reference_ligand_dataset_id", "reference_ligand_file_id", "ligand_dataset_id")}
    else:
        property_params.update({key: task_payload[key] for key in ('num_molecules', *DEFAULTS['delete'])})
    job.params = dict(params)
    task.input_payload = task_payload
    task.updated_at = utcnow()

    db.add(job)
    db.flush()
    db.add(task)
    dispatch_message = {
        "job_id": str(task.queue_job_id),
        "task": engine,
        "payload": task_payload,
        "result_queue": settings.redis_result_queue,
        "meta": {"job_id": str(job.id), **task_meta},
    }
    db.add(
        QueueOutbox(
            job_task_id=task.id,
            queue_name=settings.redis_dispatch_queue,
            payload=dispatch_message,
            status="pending",
        )
    )

    job.summary = {
        "tasks": {
            "property_optimization": {
                "queue_job_id": str(task.queue_job_id),
                "status": task.status,
                "runtime_task": task.runtime_task,
            }
        }
    }

    db.flush()
    db.refresh(job)
    return _serialize_job(db, job, with_tasks=True)


@router.post("/property-optimization/edit-candidates")
def property_optimization_edit_candidates(
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        context_id = uuid.UUID(str(payload.get("protein_context_id")))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="protein_context_id is required",
        ) from exc
    ligand_dataset_id = None
    if payload.get("ligand_dataset_id"):
        try:
            ligand_dataset_id = uuid.UUID(str(payload["ligand_dataset_id"]))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ligand_dataset_id must be a UUID",
            ) from exc
    structure_context = _resolve_protein_context(db, current_user.id, context_id)
    reference_path, _ = _resolve_delete_reference(
        db,
        current_user.id,
        ligand_dataset_id,
        structure_context,
    )
    mode = str(payload.get("mode") or "").strip()
    if mode not in EDIT_MODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="property_optimization.edit.mode is invalid",
        )
    try:
        return {
            **reference_preview(reference_path),
            "candidates": build_candidates(reference_path, mode) if mode in AUTO_EDIT_MODES else [],
        }
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("", response_model=schemas.JobOut)
def create_job(
    payload: schemas.JobCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    idempotency_key: Annotated[uuid.UUID | None, Header(alias="Idempotency-Key")] = None,
):
    from backend.services.resources import check_admission
    import hashlib

    fingerprint = None
    db.scalar(select(User).where(User.id == current_user.id).with_for_update())
    if idempotency_key is not None:
        fingerprint = hashlib.sha256(json.dumps(payload.model_dump(mode="json"), sort_keys=True,
                                                 separators=(",", ":")).encode()).hexdigest()
        # Serialize submissions for this account, including the admission check.
        # The existing admission lock uses the same user row.
        previous = db.get(JobSubmission, (current_user.id, idempotency_key))
        if previous is not None:
            if previous.fingerprint != fingerprint:
                raise HTTPException(409, detail={"error_code": "IDEMPOTENCY_KEY_CONFLICT"})
            job = db.get(Job, previous.job_id)
            if job is None or job.is_deleted:
                raise HTTPException(410, detail={"error_code": "SUBMITTED_JOB_GONE"})
            return _serialize_job(db, job, with_tasks=True)

    # Validate an explicitly selected input before admitting or creating the job.
    context_id = payload.protein_context_id
    if payload.job_type == "molecule_postprocessing":
        raw = payload.params.get("postprocessing") or {}
        if isinstance(raw, dict) and raw.get("protein_context_id"):
            try:
                context_id = uuid.UUID(str(raw["protein_context_id"]))
            except (ValueError, TypeError):
                raise HTTPException(422, "Invalid protein_context_id")
    if context_id is not None:
        context = db.scalar(select(Dataset).where(
            Dataset.id == context_id, Dataset.owner_user_id == current_user.id,
            Dataset.kind == "protein_context", Dataset.status == "ready",
        ).with_for_update())
        if context is None:
            raise HTTPException(409, detail={"error_code": "PROTEIN_CONTEXT_STALE", "protein_context_id": str(context_id)})
    check_admission(db, current_user.id)
    created: schemas.JobOut | None = None
    if payload.job_type == "molecule_generation":
        created = _create_molecule_generation_job(payload, db, current_user)
    elif payload.job_type == "molecule_postprocessing":
        from backend.routers.postprocessing import create_postprocessing_job
        created = create_postprocessing_job(payload, db, current_user)
    elif payload.job_type == "property_optimization":
        created = _create_property_optimization_job(payload, db, current_user)
    elif payload.job_type == "protein_preparation":
        created = _create_protein_preparation_job(payload, db, current_user)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported job_type")
    if idempotency_key is not None:
        db.add(JobSubmission(owner_user_id=current_user.id, key=idempotency_key,
                             fingerprint=fingerprint, job_id=created.id))
    db.commit()
    _publish_job_event_safely(db, created.id, event="job.created")
    return created


@router.get('/molecule-generation/sampling-plan')
def get_generation_sampling_plan(target_num_molecules: int = Query(..., gt=0, le=COUNT_LIMITS['ecloudgen']),
                                 decodes_per_cloud: int = Query(100, ge=1, le=1024),
                                 noise: float = Query(0.1, ge=0, allow_inf_nan=False),
                                 inv_temp: float = Query(2, gt=0, allow_inf_nan=False),
                                 num_clouds: int | None = Query(None, ge=4, le=256, multiple_of=4),
                                 budget_multiplier: int = Query(3, ge=1, le=10),
                                 current_user: User = Depends(get_current_user)):
    from backend.services.jobs import use_ecloudgen_full_target

    based_on = {'decodes_per_cloud': decodes_per_cloud, 'noise': noise, 'inv_temp': inv_temp,
                'num_clouds': num_clouds, 'budget_multiplier': budget_multiplier}
    try:
        validated_generation_settings('ecloudgen', {'target_num_molecules': target_num_molecules, **based_on})
    except DomainValidationError as exc:
        raise HTTPException(exc.http_status, exc.message) from exc
    return sampling_plan(target_num_molecules, decodes_per_cloud=decodes_per_cloud, num_clouds=num_clouds,
                         budget_multiplier=budget_multiplier,
                         full_target=use_ecloudgen_full_target(target_num_molecules, based_on))


@router.get("", response_model=list[schemas.JobListOut])
def list_jobs(
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    source_job_id: uuid.UUID | None = Query(default=None),
    job_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(
        Job.id, Job.job_type, Job.status, Job.created_at, Job.updated_at,
        func.jsonb_build_object(
            'job_name', Job.params['job_name'], 'name', Job.params['name'],
            'system_tags', func.jsonb_build_object('hidden_in_dashboard', Job.params['system_tags']['hidden_in_dashboard']),
            'molecule_generation', func.jsonb_build_object('engine', Job.params['molecule_generation']['engine']),
            'property_optimization', func.jsonb_build_object('engine', Job.params['property_optimization']['engine']),
        ).label('params'),
        func.jsonb_build_object('execution_stage', Job.summary['execution_stage']).label('summary'),
    ).where(Job.owner_user_id == current_user.id, Job.is_deleted.is_(False))
    if search and search.strip():
        pattern = '%' + search.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        stmt = stmt.where(or_(Job.params['job_name'].astext.ilike(pattern), Job.params['name'].astext.ilike(pattern),
                              cast(Job.id, String).ilike(pattern)))
    if job_type:
        stmt = stmt.where(Job.job_type == job_type)
    if status:
        stmt = stmt.where(Job.status == status)
    if source_job_id:
        stmt = stmt.where(Job.params['postprocessing']['source_job_id'].astext == str(source_job_id))
    stmt = stmt.order_by(Job.created_at.desc(), Job.id.desc()).limit(limit).offset(offset)
    rows = db.execute(stmt).all()
    result = [schemas.JobListOut.model_validate(row) for row in rows]
    active_ids = [row.id for row in rows if row.status in {'pending', 'queued', 'running', 'blocked'}]
    if active_ids:
        automatic = select(Job).where(Job.id.in_(active_ids), or_(
            Job.params['structure_context']['capabilities']['preparation_strategy'].astext == 'generation_auto_v1',
            Job.params['prepared_spec']['preparation']['strategy'].astext == 'generation_auto_v1',
        ))
        stages = {job.id: _serialize_job(db, job, summary=True).summary.get('execution_stage')
                  for job in db.scalars(automatic)}
        for item in result:
            if item.id in stages:
                item.summary = {'execution_stage': stages[item.id]}
    return result


@router.get("/{job_id}", response_model=schemas.JobOut)
def get_job(job_id: uuid.UUID, summary: bool = False, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    stmt = _job_query(summary).where(Job.id == job_id, Job.owner_user_id == current_user.id, Job.is_deleted.is_(False))
    row = db.execute(stmt).first() if summary else db.scalar(stmt)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return _serialize_job(db, row, with_tasks=True, summary=summary)


@router.get("/{job_id}/tasks", response_model=list[schemas.JobTaskOut])
def get_job_tasks(job_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = db.scalar(select(Job).where(Job.id == job_id, Job.owner_user_id == current_user.id, Job.is_deleted.is_(False)))
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    rows = db.scalars(select(JobTask).where(JobTask.job_id == job.id).order_by(JobTask.created_at.asc())).all()
    return [schemas.JobTaskOut.model_validate(row) for row in rows if not row.task_code.startswith("plip2d_")]


@router.post("/{job_id}/cancel")
def cancel_job(job_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from backend.services.jobs import cancel_owned_job, ResourceNotFound
    try:
        canceled = cancel_owned_job(db, current_user.id, job_id)
    except ResourceNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    db.commit()
    _skip_queued_runtime_work(canceled)
    _publish_job_event_safely(db, job_id, event="job.updated")
    job = db.get(Job, job_id)
    return {"job_id": str(job.id), "status": job.status, "ok": True}


@router.post("/{job_id}/continue", response_model=schemas.JobOut, status_code=202)
def continue_generation_job(job_id: uuid.UUID, db: Session = Depends(get_db),
                            current_user: User = Depends(get_current_user)):
    try:
        job = continue_generation(db, current_user.id, job_id)
    except DomainValidationError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.message) from exc
    db.commit()
    _publish_job_event_safely(db, job_id)
    return _serialize_job(db, job, with_tasks=True)


def _skip_queued_runtime_work(queue_job_ids: list[uuid.UUID]) -> None:
    # Runtime workers publish a stored "failed" status instead of executing, so queued work is dropped.
    # ponytail: work already running keeps running; stopping it needs a kill signal in queue_worker.
    if not queue_job_ids:
        return
    try:
        with get_sync_redis_client().pipeline(transaction=False) as pipe:
            for queue_job_id in queue_job_ids:
                key = f"genova:job:{queue_job_id}"
                pipe.hset(key, mapping={"status": "failed", "error": "CANCELED: the task was canceled before it ran"})
                pipe.expire(key, 172800)
            pipe.execute()
    except Exception:
        logger.exception("Failed to mark canceled tasks in the runtime queue")


@router.post("/deletions/preview")
def preview_job_deletion(payload: schemas.JobDeletionPreviewRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from backend.services.job_deletions import preview_deletion
    return preview_deletion(db, current_user.id, payload.job_ids)


@router.post("/deletions")
def confirm_job_deletion(payload: schemas.JobDeletionRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from backend.services.job_deletions import confirm_deletion
    owner_id = current_user.id
    db.rollback()
    result = confirm_deletion(owner_id, payload.job_ids, payload.confirmation_token)
    for job_id in result['deleted_job_ids']:
        _publish_user_event_safely(owner_id, build_job_event(db.get(Job, uuid.UUID(job_id)), event='job.deleted', deleted=True))
    return result


@router.delete("/{job_id}")
def delete_job(job_id: uuid.UUID, payload: schemas.JobDeletionRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if set(payload.job_ids) != {job_id}:
        raise HTTPException(422, 'job_ids must contain only the requested job')
    return confirm_job_deletion(payload, db, current_user)


@router.get("/{job_id}/results", response_model=list[schemas.SmallMoleculeResultOut])
def get_job_results(
    job_id: uuid.UUID,
    response: Response,
    task_code: str | None = Query(default=None),
    smiles: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None, max_length=200),
    sort_by: str = Query(default='created_at'),
    descending: bool = Query(default=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = db.execute(select(Job.id, Job.job_type, Job.params['property_optimization']['engine'].astext.label('engine'))
                     .where(Job.id == job_id, Job.owner_user_id == current_user.id, Job.is_deleted.is_(False))).first()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    backfilled = backfill_small_molecule_results_for_job(db, job_id=job.id, task_code=task_code)
    if backfilled:
        db.commit()

    from backend.result_query import GENERATION_METRICS, generation_metric, generation_query, numeric

    epso = job.job_type == 'property_optimization' and job.engine == 'epso'
    if epso and sort_by == 'created_at':
        sort_by, descending = 'fitness', True
    if sort_by not in {'created_at', 'smiles', *GENERATION_METRICS, *({'fitness'} if epso else set())}:
        raise HTTPException(422, 'Unsupported sort metric')
    stmt = generation_query(job.id, task_code, smiles, search)
    response.headers['X-Total-Count'] = str(db.scalar(select(func.count()).select_from(stmt.subquery())))
    column = numeric(SmallMoleculeResult.extra['fitness'].astext) if sort_by == 'fitness' else (generation_metric(sort_by) if sort_by in GENERATION_METRICS else getattr(SmallMoleculeResult, sort_by))
    order = column.desc() if descending else column.asc()
    rows = db.scalars(stmt.order_by(order.nulls_last(), *([numeric(SmallMoleculeResult.extra['rank'].astext)] if epso else []), SmallMoleculeResult.id).limit(limit).offset(offset)).all()
    results = [schemas.SmallMoleculeResultOut.model_validate(row) for row in rows]
    if job.job_type == 'property_optimization' and not epso and results:
        from rdkit import Chem
        from genova_runtime.structure_index import molecule, read_record, structure_index
        from tarpass.selection import edit_preview

        task = db.get(JobTask, results[0].job_task_id)
        fragment_path = (task.input_payload or {}).get('fragment_sdf')
        sdf = (task.output_payload or {}).get('generated_sdf')
        if fragment_path and sdf:
            try:
                fragment = molecule(read_record(fragment_path, 0))
                index = structure_index(sdf)
                for result in results:
                    preview = None
                    try:
                        key = Chem.MolToSmiles(Chem.RemoveHs(Chem.MolFromSmiles(result.smiles)))
                        records = index['smiles'].get(key, [])
                        if records:
                            preview = edit_preview(fragment, molecule(read_record(sdf, records[0])))
                    except (ValueError, RuntimeError):
                        pass
                    result.extra = {**result.extra, 'edit_preview': preview}
            except (OSError, ValueError, RuntimeError):
                pass
    return results


@router.get('/{job_id}/results/summary')
def result_summary(job_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from backend.result_query import GENERATION_METRICS, generation_metric
    owned_id = db.scalar(select(Job.id).where(Job.id == job_id, Job.owner_user_id == current_user.id, Job.is_deleted.is_(False)))
    if owned_id is None:
        raise HTTPException(404, 'Job not found')
    if backfill_small_molecule_results_for_job(db, job_id=owned_id):
        db.commit()
    values = db.execute(select(*[func.avg(generation_metric(key)) for key in GENERATION_METRICS])
                        .where(SmallMoleculeResult.job_id == owned_id)).one()
    return dict(zip(GENERATION_METRICS, values))


@router.get("/{job_id}/artifact")
def download_job_artifact(
    job_id: uuid.UUID,
    task_code: str = Query(..., description="Task code, e.g. molecule_generation/property_optimization/tarpass"),
    key: str = Query(..., description="Artifact key in task output payload, e.g. output_sdf/output_csv"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = db.scalar(select(Job).where(Job.id == job_id, Job.owner_user_id == current_user.id))
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    task = db.scalar(
        select(JobTask)
        .where(JobTask.job_id == job.id, JobTask.task_code == task_code)
        .order_by(JobTask.created_at.desc())
    )
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task not found: {task_code}")

    output_payload = task.output_payload or {}
    artifact_path_raw = output_payload.get(key)
    if not isinstance(artifact_path_raw, str) or not artifact_path_raw.strip():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Artifact not found in output payload: {key}")

    if job.job_type == "molecule_postprocessing" and task_code == "tarpass" and key == "protein_path":
        try:
            artifact_path = resolve_postprocessing_protein_artifact(db, current_user.id, job, task)
        except DomainValidationError as exc:
            raise HTTPException(status_code=exc.http_status, detail="Postprocessing protein is unavailable") from exc
    else:
        artifact_path = Path(artifact_path_raw).resolve()
        job_root = (settings.data_root / "jobs" / str(job.id)).resolve()
        try:
            artifact_path.relative_to(job_root)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Artifact path is outside job workspace") from exc
        if not artifact_path.exists() or not artifact_path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Artifact file not found: {artifact_path}")

    media_type = "application/octet-stream"
    suffix = artifact_path.suffix.lower()
    if suffix == ".csv":
        media_type = "text/csv"
    elif suffix == ".sdf":
        media_type = "chemical/x-mdl-sdfile"
    elif suffix == ".pdb":
        media_type = "chemical/x-pdb"
    elif suffix == ".json":
        media_type = "application/json"
    elif suffix == ".txt":
        media_type = "text/plain"

    from backend.artifact_downloads import artifact_response
    return artifact_response(artifact_path, media_type=media_type)
