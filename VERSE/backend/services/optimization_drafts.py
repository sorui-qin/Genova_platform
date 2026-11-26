from __future__ import annotations

import shutil
import uuid
from copy import deepcopy

from rdkit import Chem
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models import CandidateSet, Dataset, DatasetFile, Job, JobTask, ResearchTask, SmallMoleculeResult
from backend.services.jobs import DomainValidationError, get_owned_dataset, get_owned_job, resolve_job_artifact
from backend.services.results import load_tarpass_results
from backend.services.workflows import WorkflowError
from backend.workflows.contracts import digest
from genova_runtime.pdb2pqr_compat import file_sha256
from genova_runtime.structure_index import molecule, read_record, structure_index


POSE_PREPARATION_PROTOCOL_VERSION = "tarpass-pose-2026-09"


def _pose_preparation_contract(session, job, task, row, molecule_id, pose, source_index,
                               candidate_set_id, seed_dataset, seed_file, pose_source_job_id):
    target = {
        "source_job_id": str(job.id),
        "source_task_id": str(task.id),
        "source_result_id": str(row.id),
        "molecule_id": molecule_id,
        "pose": pose,
        "source_index": source_index,
        "candidate_set_id": str(candidate_set_id) if candidate_set_id else None,
    }
    effective = {
        "protocol_version": POSE_PREPARATION_PROTOCOL_VERSION,
        "source_job_id": str(pose_source_job_id),
        "input_sdf_dataset_id": str(seed_dataset.id),
        "input_sdf_sha256": seed_file.sha256,
        "protein_context_id": str(session.assets["protein_context_id"]),
        "prefilters": [],
        "key_interactions": [],
        "reference_dataset_id": None,
        "scope": {"kind": "single_molecule", "count": 1},
    }
    approval_hash = digest({"protocol_version": POSE_PREPARATION_PROTOCOL_VERSION,
                            "target": target, "effective_postprocessing": effective})
    return target, effective, approval_hash


def _pose_source_job(db: Session, user_id, job, task):
    if task.task_code != "tarpass":
        return job.id
    source_id = (task.input_payload or {}).get("source_job_id")
    try:
        source_job_id = uuid.UUID(str(source_id))
    except (TypeError, ValueError) as exc:
        raise WorkflowError("POSE_STEP_UNAVAILABLE", "The selected TarPass result has no recoverable generation source", 409) from exc
    source_job = get_owned_job(db, user_id, source_job_id)
    if source_job.status != "succeeded":
        raise WorkflowError("POSE_STEP_UNAVAILABLE", "The selected TarPass result source is not ready", 409)
    return source_job.id


def resolve_pose_approval(db: Session, session, request):
    pending = (session.assets or {}).get("optimization_pose_draft")
    if not isinstance(pending, dict) or not pending.get("approval_hash"):
        raise WorkflowError("POSE_APPROVAL_REQUIRED", "Refresh the selected molecule and approve its current pose parameters", 409)
    if pending["approval_hash"] != request.approval_hash:
        raise WorkflowError("ACTION_CHANGED", "Pose parameters changed; approve the current displayed configuration", 409)
    job, task, row, molecule_id, _ = _resolve_result(db, session.owner_user_id, request)
    pose, _, resolved_source_index = _pose_molecule(job, task, molecule_id, request.pose, request.source_index, row.smiles)
    pending_source = pending.get("source") or {}
    pending_target = pending.get("target") or {}
    source_index = resolved_source_index if resolved_source_index is not None else pending_source.get("source_index")
    seed = get_owned_dataset(db, request.seed_dataset_id, session.owner_user_id)
    try:
        seed_file_id = uuid.UUID(str((pending.get("seed") or {})["file_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkflowError("POSE_INPUT_MISMATCH", "The selected pose input is invalid", 409) from exc
    seed_file = db.scalar(select(DatasetFile).where(
        DatasetFile.id == seed_file_id,
        DatasetFile.dataset_id == seed.id,
    ))
    try:
        current_seed_sha = file_sha256(seed_file.storage_path) if seed_file and seed_file.storage_path else None
    except (OSError, TypeError, ValueError):
        current_seed_sha = None
    if (seed_file is None or seed_file.sha256 != (pending.get("seed") or {}).get("sha256")
            or current_seed_sha != seed_file.sha256):
        raise WorkflowError("INPUT_CHANGED", "The selected pose input changed; prepare it again", 409)
    target, effective, approval_hash = _pose_preparation_contract(
        session, job, task, row, molecule_id, pose, source_index, request.candidate_set_id,
        seed, seed_file,
        _pose_source_job(db, session.owner_user_id, job, task),
    )
    if target != pending_target or target.get("pose") != request.pose:
        raise WorkflowError("POSE_INPUT_MISMATCH", "The selected pose target changed; refresh the approval card", 409)
    seed_source = (seed.meta or {}).get("derived_from") or {}
    if any(seed_source.get(key) != target.get(key) for key in (
            "source_job_id", "source_task_id", "source_result_id", "molecule_id", "pose", "source_index", "candidate_set_id")):
        raise WorkflowError("POSE_INPUT_MISMATCH", "The one-molecule pose input does not match the selected result", 409)
    if approval_hash != request.approval_hash or effective != pending.get("effective_postprocessing"):
        raise WorkflowError("ACTION_CHANGED", "Pose parameters changed; approve the current displayed configuration", 409)
    return {
        "job": job, "task": task, "row": row, "molecule_id": molecule_id, "pose": pose,
        "pose_source_job_id": uuid.UUID(effective["source_job_id"]), "seed": seed, "seed_file": seed_file,
        "target": target, "effective_postprocessing": effective, "approval_hash": approval_hash,
    }


def _task_for_job(db: Session, job: Job) -> JobTask:
    task = db.scalar(select(JobTask).where(
        JobTask.job_id == job.id,
        JobTask.status == "succeeded",
        JobTask.task_code.in_(("tarpass", "molecule_generation", "property_optimization")),
    ).order_by(JobTask.created_at.desc()))
    if task is None:
        raise WorkflowError("RESULT_NOT_READY", "A succeeded molecular result is required", 409)
    return task


def _valid_3d(value):
    return value is not None and value.GetNumAtoms() > 0 and value.GetNumConformers() > 0 and value.GetConformer().Is3D() and all(
        float(coordinate) == float(coordinate) and abs(float(coordinate)) != float("inf")
        for point in value.GetConformer().GetPositions() for coordinate in point
    )


def _canonical(value):
    if value is None:
        return None
    try:
        return Chem.MolToSmiles(Chem.RemoveHs(value))
    except (ValueError, RuntimeError):
        return None


def _pose_molecule(job: Job, task: JobTask, molecule_id: str, pose: str | None, source_index: int | None,
                   smiles: str | None = None):
    selected_pose = pose or ("docked" if task.task_code == "tarpass" else "generated")
    artifact_key = "generated_sdf" if selected_pose == "generated" else f"{selected_pose}_sdf"
    value = (task.output_payload or {}).get(artifact_key)
    if not value:
        return selected_pose, None, None
    try:
        path = resolve_job_artifact(job, value)
        index = structure_index(path)
        if source_index is None:
            indices = index["names"].get(molecule_id, [])
            if len(indices) != 1 and smiles:
                key = _canonical(Chem.MolFromSmiles(smiles))
                indices = index["smiles"].get(key, [])
            if len(indices) != 1:
                return selected_pose, None, None
            source_index = indices[0]
        return selected_pose, molecule(read_record(path, source_index)), source_index
    except (DomainValidationError, OSError, ValueError, KeyError):
        return selected_pose, None, None


def _resolve_result(db: Session, user_id: uuid.UUID, request):
    job = get_owned_job(db, user_id, request.source_job_id)
    task = _task_for_job(db, job)
    rows = None
    artifact_hash = None
    if task.task_code == "tarpass":
        _, _, rows = load_tarpass_results(db, user_id=user_id, job_id=job.id)
        artifact_hash = file_sha256(resolve_job_artifact(job, task.output_payload["results_json"]))
        from backend.result_rows import ensure_tarpass_rows
        ensure_tarpass_rows(db, task)

    result_row = None
    if request.result_id is not None:
        result_row = db.scalar(select(SmallMoleculeResult).where(
            SmallMoleculeResult.id == request.result_id,
            SmallMoleculeResult.job_id == job.id,
            SmallMoleculeResult.job_task_id == task.id,
        ))
    if result_row is None and request.molecule_id:
        result_row = db.scalar(select(SmallMoleculeResult).where(
            SmallMoleculeResult.job_id == job.id,
            SmallMoleculeResult.job_task_id == task.id,
            SmallMoleculeResult.extra["molecule_id"].astext == request.molecule_id,
        ))
    if result_row is None and request.source_index is not None:
        _, pose_mol, _ = _pose_molecule(job, task, request.molecule_id or "", request.pose, request.source_index)
        if pose_mol is not None:
            smiles = _canonical(pose_mol)
            result_row = db.scalar(select(SmallMoleculeResult).where(
                SmallMoleculeResult.job_id == job.id,
                SmallMoleculeResult.job_task_id == task.id,
                SmallMoleculeResult.smiles_canonical == smiles,
            ).order_by(SmallMoleculeResult.created_at.asc()))
            if result_row is None and smiles:
                result_row = next((candidate for candidate in db.scalars(select(SmallMoleculeResult).where(
                    SmallMoleculeResult.job_id == job.id,
                    SmallMoleculeResult.job_task_id == task.id,
                )).all() if _canonical(Chem.MolFromSmiles(candidate.smiles)) == smiles), None)
    if result_row is None:
        raise WorkflowError("RESULT_NOT_FOUND", "The selected molecular result is unavailable", 404)
    molecule_id = str((result_row.extra or {}).get("molecule_id") or result_row.id)
    if request.molecule_id and request.molecule_id != molecule_id:
        raise WorkflowError("RESULT_NOT_FOUND", "The selected molecular result is unavailable", 404)
    if request.source_index is not None:
        _, pose_mol, _ = _pose_molecule(job, task, molecule_id, request.pose, request.source_index, result_row.smiles)
        if _canonical(pose_mol) != _canonical(Chem.MolFromSmiles(result_row.smiles)):
            raise WorkflowError("RESULT_POSE_MISMATCH", "The selected structure record does not belong to this result", 409)
    if rows is not None and not any(str(row.get("molecule_id")) == molecule_id for row in rows):
        raise WorkflowError("RESULT_NOT_FOUND", "The selected molecular result is unavailable", 404)
    if request.candidate_set_id is not None:
        candidate_set = db.scalar(select(CandidateSet).where(
            CandidateSet.id == request.candidate_set_id,
            CandidateSet.owner_user_id == user_id,
            CandidateSet.postprocessing_job_id == job.id,
        ))
        if candidate_set is None or molecule_id not in {str(item) for item in (candidate_set.molecule_ids or [])}:
            raise WorkflowError("RESULT_NOT_IN_SET", "The selected molecule is outside this candidate set", 409)
        if artifact_hash != candidate_set.artifact_hash:
            raise WorkflowError("RESULT_INTEGRITY_ERROR", "Candidate set source artifact changed", 409)
    return job, task, result_row, molecule_id, artifact_hash


def _write_seed_dataset(db: Session, user_id: uuid.UUID, job: Job, task: JobTask, row: SmallMoleculeResult,
                        molecule_id: str, pose: str, pose_mol, source_index: int | None, artifact_hash: str | None,
                        candidate_set_id: uuid.UUID | None):
    from backend.services.resources import check_admission
    check_admission(db, user_id, compute=False)
    seed_mol = pose_mol if pose_mol is not None else Chem.MolFromSmiles(row.smiles)
    if seed_mol is None or seed_mol.GetNumAtoms() == 0:
        raise WorkflowError("INVALID_SEED", "The selected result has no valid molecular structure", 422)
    dataset_id, file_id = uuid.uuid4(), uuid.uuid4()
    directory = settings.data_root / "datasets" / str(dataset_id)
    target = directory / f"{file_id}_selected_seed.sdf"
    source = {"kind": "result", "source_job_id": str(job.id), "source_task_id": str(task.id),
              "source_result_id": str(row.id), "molecule_id": molecule_id, "pose": pose,
              "source_index": source_index, "artifact_hash": artifact_hash,
              "candidate_set_id": str(candidate_set_id) if candidate_set_id else None, "smiles": row.smiles}
    try:
        directory.mkdir(parents=True, exist_ok=False)
        seed_mol.SetProp("_Name", molecule_id)
        writer = Chem.SDWriter(str(target))
        writer.write(seed_mol)
        writer.close()
        if not target.is_file() or target.stat().st_size == 0:
            raise WorkflowError("INVALID_SEED", "The selected result has no valid molecular structure", 422)
        digest = file_sha256(target)
        from backend.utils import utcnow
        now = utcnow()
        dataset = Dataset(id=dataset_id, owner_user_id=user_id, name=f"Selected molecule {molecule_id}"[:255],
                          kind="agent_ligand", status="ready", meta={"derived_from": source, "seed_source": "agent_result_v1"},
                          created_at=now, updated_at=now)
        file = DatasetFile(id=file_id, dataset_id=dataset_id, file_role="ligand_input",
                           storage_path=str(target), original_filename="selected_seed.sdf",
                           content_type="chemical/x-mdl-sdfile", size_bytes=target.stat().st_size, sha256=digest,
                           created_at=now)
        db.add_all([dataset, file])
        db.flush()
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return dataset, file, source, _valid_3d(seed_mol)


def _reuse_pending_seed(db: Session, session, job: Job, row: SmallMoleculeResult, molecule_id: str,
                        pose: str, source_index: int | None, request):
    draft = (session.assets or {}).get("optimization_pose_draft")
    if not isinstance(draft, dict) or draft.get("engine") != request.engine:
        return None
    source = draft.get("source") or {}
    if (source.get("source_job_id") != str(job.id)
            or source.get("source_result_id") != str(row.id)
            or source.get("molecule_id") != molecule_id
            or source.get("pose") != pose
            or source.get("source_index") != source_index
            or source.get("candidate_set_id") != (str(request.candidate_set_id) if request.candidate_set_id else None)):
        return None
    seed = draft.get("seed") or {}
    try:
        dataset_id = uuid.UUID(str(seed["dataset_id"]))
        file_id = uuid.UUID(str(seed["file_id"]))
        dataset = get_owned_dataset(db, dataset_id, session.owner_user_id)
        file = db.scalar(select(DatasetFile).where(DatasetFile.id == file_id, DatasetFile.dataset_id == dataset.id))
    except (KeyError, ValueError, DomainValidationError):
        return None
    if file is None or not file.storage_path or not file.sha256 or file.sha256 != seed.get("sha256"):
        return None
    return dataset, file, source, bool(seed.get("has_3d"))


def derive_optimization_draft(db: Session, session, request):
    if session.phase in {"preparing", "executing", "awaiting_workflow_approval", "awaiting_postprocessing_approval", "cancel_requested"}:
        raise WorkflowError("WORKFLOW_ACTIVE", "Wait for the current workflow step to finish before deriving an optimization", 409)
    if session.active_workflow_id:
        from backend.services.workflows import owned_workflow
        active = owned_workflow(db, session.active_workflow_id, session.owner_user_id)
        if active.status in {"awaiting_approval", "approved", "running", "cancel_requested"}:
            raise WorkflowError("WORKFLOW_ACTIVE", "Wait for the current workflow step to finish before deriving an optimization", 409)
    job, task, row, molecule_id, artifact_hash = _resolve_result(db, session.owner_user_id, request)
    pose, pose_mol, source_index = _pose_molecule(job, task, molecule_id, request.pose, request.source_index, row.smiles)
    if artifact_hash is None:
        artifact_key = "generated_sdf" if pose == "generated" else f"{pose}_sdf"
        artifact_value = (task.output_payload or {}).get(artifact_key)
        if artifact_value:
            artifact_hash = file_sha256(resolve_job_artifact(job, artifact_value))
    expected = _canonical(Chem.MolFromSmiles(row.smiles))
    if request.source_index is not None and _canonical(pose_mol) != expected:
        raise WorkflowError("RESULT_POSE_MISMATCH", "The selected structure record does not belong to this result", 409)
    if request.engine == "delete" and not session.assets.get("protein_context_id"):
        raise WorkflowError("PROTEIN_CONTEXT_REQUIRED", "DELETE requires a prepared Protein Context", 409)
    if request.engine == "delete" and not _valid_3d(pose_mol):
        reused = _reuse_pending_seed(db, session, job, row, molecule_id, pose, source_index, request)
        if reused:
            dataset, file, source, has_3d = reused
        else:
            dataset, file, source, has_3d = _write_seed_dataset(db, session.owner_user_id, job, task, row, molecule_id,
                                                                pose, None, source_index, artifact_hash,
                                                                request.candidate_set_id)
        pose_source_job_id = _pose_source_job(db, session.owner_user_id, job, task)
        target, effective_postprocessing, approval_hash = _pose_preparation_contract(
            session, job, task, row, molecule_id, pose, source_index, request.candidate_set_id,
            dataset, file, pose_source_job_id,
        )
        next_step = {"kind": "tarpass", "requires_approval": True, "source_job_id": str(job.id),
                     "molecule_id": molecule_id, "result_id": str(row.id),
                     "seed_dataset_id": str(dataset.id),
                     "candidate_set_id": str(request.candidate_set_id) if request.candidate_set_id else None,
                     "pose": pose, "source_index": source_index,
                     "protein_context_id": session.assets.get("protein_context_id"),
                     "effective_postprocessing": effective_postprocessing,
                     "approval_hash": approval_hash,
                     "protocol_version": POSE_PREPARATION_PROTOCOL_VERSION,
                     "approval_endpoint": f"/api/v1/agent/sessions/{session.id}/optimization-drafts/approve-pose",
                     "engine": request.engine}
        pending = {"engine": request.engine, "source": source,
                   "candidate_set_id": str(request.candidate_set_id) if request.candidate_set_id else None,
                   "seed": {"dataset_id": str(dataset.id), "file_id": str(file.id), "sha256": file.sha256,
                            "smiles": row.smiles, "has_3d": has_3d},
                   "target": target, "effective_postprocessing": effective_postprocessing,
                   "approval_hash": approval_hash, "next_step": next_step}
        session.assets = {**(session.assets or {}), "optimization_pose_draft": pending}
        return {"requires_pose": True, "status": "needs_tarpass", "engine": request.engine,
                "source_job_id": str(job.id),
                "result_id": str(row.id), "molecule_id": molecule_id, "pose": pose,
                "approval_hash": approval_hash,
                "effective_postprocessing": effective_postprocessing,
                "message": "DELETE requires a valid 3D pose; run TarPass explicitly before continuing.",
                "seed": {"dataset_id": str(dataset.id), "file_id": str(file.id), "sha256": file.sha256,
                         "smiles": row.smiles, "has_3d": has_3d},
                "next_step": next_step, "pose_preparation_draft": next_step}
    dataset, file, source, has_3d = _write_seed_dataset(db, session.owner_user_id, job, task, row, molecule_id,
                                                        pose, pose_mol, source_index, artifact_hash,
                                                        request.candidate_set_id)
    seed_source = {"dataset_id": str(dataset.id), "file_id": str(file.id), "sha256": file.sha256,
                   "source_result_id": str(row.id), "source_job_id": str(job.id), "molecule_id": molecule_id,
                   "pose": pose, "source_index": source_index, "artifact_hash": artifact_hash,
                   "candidate_set_id": str(request.candidate_set_id) if request.candidate_set_id else None,
                   "has_3d": has_3d, "engine": request.engine}
    result = {"status": "ready", "requires_pose": False, "engine": request.engine,
              "source": source, "seed": {"dataset_id": str(dataset.id), "file_id": str(file.id),
              "sha256": file.sha256, "smiles": row.smiles, "has_3d": has_3d}, "seed_source": seed_source,
              "protein_context_id": session.assets.get("protein_context_id")}
    if request.engine == "delete":
        context_id = session.assets.get("protein_context_id")
        if not context_id:
            raise WorkflowError("PROTEIN_CONTEXT_REQUIRED", "DELETE requires a prepared Protein Context", 409)
        context = get_owned_dataset(db, uuid.UUID(context_id), session.owner_user_id)
        meta = deepcopy(context.meta or {})
        from backend.services.binding_sites import create_site
        try:
            derived = create_site({
                "version": 4,
                "name": f"{context.name} - {molecule_id}"[:255],
                "prepared_receptor_id": meta["prepared_receptor_id"],
                "prepared_artifact_sha256": meta["prepared_artifact_sha256"],
                "site": meta["site"],
                "generation_reference": {"structure": {"dataset_id": str(dataset.id), "file_id": str(file.id), "sha256": file.sha256},
                                          "coordinate_frame_id": meta["site"]["anchor"]["coordinate_frame_id"]},
                "input_parameters": meta.get("input_parameters"),
                "derived_from_context_id": context.id,
            }, db, session.owner_user_id)
        except BaseException:
            shutil.rmtree(settings.data_root / "datasets" / str(dataset.id), ignore_errors=True)
            raise
        result["protein_context_id"] = derived["id"]
        result["derived_context_id"] = derived["id"]
        result["derived_context_status"] = derived.get("status")
    if result.get("status") == "ready":
        try:
            from backend.workflows.commands import design
            draft = design(db, session)
            assets = dict(session.assets or {})
            assets.pop("optimization_pose_draft", None)
            if result.get("derived_context_id"):
                assets = {"protein_context_id": result["derived_context_id"]}
            assets["optimization_seed"] = deepcopy(seed_source)
            if result.get("derived_context_id") and result.get("derived_context_status") == "ready":
                derived_meta = (db.get(Dataset, uuid.UUID(result["derived_context_id"])).meta or {})
                if (derived_meta.get("compatibility") or {}).get("job_id"):
                    assets["context_validation_job_id"] = derived_meta["compatibility"]["job_id"]
            draft.assets = assets
            draft.revision += 1
            session.assets = assets
            session.confirmed_fields = {}
            session.input_revision = draft.revision
            session.active_workflow_id = None
            session.phase = "preparing" if assets.get("context_validation_job_id") else "ready_for_planning"
            session.pending_requirements = []
            task = db.get(ResearchTask, session.research_task_id)
            if task is not None:
                preferences = deepcopy(task.workflow_preferences or {})
                generation = deepcopy(preferences.get("generation") or {})
                if generation.get("engine") != request.engine:
                    generation = {"engine": request.engine}
                else:
                    generation["engine"] = request.engine
                if request.engine == "delete":
                    generation.pop("edit", None)
                preferences.update({
                    "generation": generation,
                    "generation_source": "optimization_draft",
                    "generation_source_version": (task.task_plan or {}).get("version", 0),
                    "seed_source": deepcopy(seed_source),
                })
                task.workflow_preferences = preferences
            result["version"] = session.input_revision
        except BaseException:
            shutil.rmtree(settings.data_root / "datasets" / str(dataset.id), ignore_errors=True)
            raise
    return result
