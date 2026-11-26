"""Interaction 2D preview service.

Encapsulates the domain logic for requesting and checking 2D interaction
diagram previews.  Used by the postprocessing router.

This service creates JobTask and QueueOutbox entries within the caller's
transaction (same pattern as services/jobs.py).
"""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models import Job, JobTask, QueueOutbox
from backend.services.jobs import (
    DomainValidationError,
    InvalidParameter,
    ResourceConflict,
    ResourceNotFound,
    get_owned_job,
    resolve_job_artifact,
)


class PreviewServiceError(DomainValidationError):
    """Raised when preview service validation fails."""
    pass


def _artifact_path(job: Job, value: Any, *, data_root: Path | None = None) -> Path:
    """Resolve and validate an artifact path within the job workspace."""
    return resolve_job_artifact(job, value, data_root=data_root)


def _source_task(db: Session, job: Job) -> JobTask:
    """Get the tarpass task for a postprocessing job."""
    task = db.scalar(select(JobTask).where(JobTask.job_id == job.id, JobTask.task_code == "tarpass"))
    if task is None or task.status != "succeeded":
        raise ResourceConflict("Postprocessing results are not ready")
    return task


def get_interaction_preview_input(
    db: Session,
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    molecule_id: str,
    pose: str,
    data_root: Path | None = None,
) -> tuple[Job, dict[str, Any]]:
    """Prepare the input payload for a 2D interaction preview request.

    Returns (job, payload_dict).  The payload contains all information needed
    to dispatch the preview task.

    Raises PreviewServiceError on any validation failure.
    """
    from tarpass.interactions import DETAILS_VERSION, DIAGRAM_VERSION, PLIP_VERSION, diagram_cache_key

    if pose not in ("original", "docked"):
        raise InvalidParameter("pose must be 'original' or 'docked'")

    try:
        job = get_owned_job(db, user_id, job_id)
    except DomainValidationError as exc:
        raise PreviewServiceError(exc.code, exc.message, exc.http_status) from exc

    task = _source_task(db, job)

    # Ensure tarpass rows are materialized
    from backend.result_rows import ensure_tarpass_rows
    ensure_tarpass_rows(db, task)

    from backend.models import SmallMoleculeResult
    row = db.scalar(
        select(SmallMoleculeResult.extra).where(
            SmallMoleculeResult.job_task_id == task.id,
            SmallMoleculeResult.extra.contains({"molecule_id": molecule_id}),
        )
    )
    if row is None:
        raise ResourceNotFound("Molecule record not found")

    root = data_root or settings.data_root
    sdf = _artifact_path(job, task.output_payload.get(f"{pose}_sdf"), data_root=root)

    # Validate the SDF record has a valid 3D pose
    try:
        from genova_runtime.structure_index import file_digest, file_version, named_record, molecule
        mol = molecule(named_record(sdf, molecule_id))
        if (
            mol is None
            or not mol.GetNumAtoms()
            or not mol.GetNumConformers()
            or not mol.GetConformer().Is3D()
            or not all(
                math.isfinite(float(v))
                for point in mol.GetConformer().GetPositions()
                for v in point
            )
        ):
            raise ValueError("The selected record requires a valid 3D pose")
        from tarpass.interactions import molecule_fingerprint
        fingerprint = molecule_fingerprint(mol)
    except ValueError as exc:
        raise ResourceConflict(str(exc)) from exc

    # Get protein path
    protein = Path(str(task.input_payload.get("protein_pdb") or "")).resolve()
    if not protein.is_relative_to(root.resolve()) or not protein.is_file():
        raise ResourceConflict("The prepared receptor is unavailable")
    protein_hash = file_digest(protein)

    # Check for cached details in the row
    details = row["metrics"].get(pose, {}).get("interaction_details")
    if details and (
        details.get("version"),
        details.get("plip_version"),
        details.get("protein_sha256"),
        details.get("source_input_fingerprint", details.get("input_fingerprint")),
    ) != (DETAILS_VERSION, PLIP_VERSION, protein_hash, fingerprint):
        details = None

    key = diagram_cache_key(protein_hash, fingerprint, molecule_id, pose, details)
    payload = {
        "operation": "interactions_2d",
        "molecule_id": molecule_id,
        "pose": pose,
        "input_sdf": str(sdf),
        "protein_pdb": str(protein),
        "protein_sha256": protein_hash,
        "input_fingerprint": fingerprint,
        "cache_key": key,
        "details": details,
        "output_dir": str(root / "jobs" / str(job.id) / "interactions-2d"),
    }
    return job, payload


def get_interaction_preview_status(
    job: Job,
    payload: dict[str, Any],
    *,
    db: Session,
) -> dict[str, Any]:
    """Check the status of an interaction preview.

    Returns a dict with 'status' key and optional 'diagram' or 'error'.
    """
    cache = Path(payload["output_dir"]) / f"{payload['cache_key']}.json"
    if cache.is_file():
        return {
            "status": "succeeded",
            "diagram": json.loads(_artifact_path(job, cache).read_text()),
        }
    task = db.scalar(
        select(JobTask).where(
            JobTask.job_id == job.id,
            JobTask.task_code == f"plip2d_{payload['cache_key'][:48]}",
        )
    )
    if task is None:
        return {"status": "not_requested"}
    if task.status == "succeeded":
        return {
            "status": "failed",
            "error": "The cached diagram is missing; retry to regenerate it",
        }
    return {
        "status": task.status,
        "error": task.error_message.splitlines()[0] if task.error_message else None,
    }


def request_interaction_preview(
    db: Session,
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    molecule_id: str,
    pose: str,
    data_root: Path | None = None,
) -> dict[str, Any]:
    """Request a 2D interaction preview, creating a JobTask and QueueOutbox.

    Uses SELECT ... FOR UPDATE on the Job row to serialize concurrent requests
    for the same job.

    Returns a status dict.
    """
    # Serialize requests for this owned Job
    job = db.scalar(
        select(Job).where(
            Job.id == job_id,
            Job.owner_user_id == user_id,
            Job.is_deleted.is_(False),
        ).with_for_update()
    )
    if job is None:
        raise ResourceNotFound("Job not found")

    job, payload = get_interaction_preview_input(
        db,
        user_id=user_id,
        job_id=job_id,
        molecule_id=molecule_id,
        pose=pose,
        data_root=data_root,
    )

    # Re-lock to prevent races
    db.execute(select(Job.id).where(Job.id == job.id).with_for_update())

    state = get_interaction_preview_status(job, payload, db=db)
    if state["status"] in ("succeeded", "pending", "queued", "running"):
        return state

    # If we have valid cached details, generate the diagram synchronously
    if payload["details"]:
        from tarpass.interactions import write_diagram

        write_diagram(payload, payload["details"])
        db.commit()
        return get_interaction_preview_status(job, payload, db=db)

    code = f"plip2d_{payload['cache_key'][:48]}"
    task = db.scalar(select(JobTask).where(JobTask.job_id == job.id, JobTask.task_code == code))
    if task is None:
        task = JobTask(
            id=uuid.uuid4(),
            job_id=job.id,
            task_code=code,
            runtime_task="tarpass",
            depends_on=[],
        )
        db.add(task)
    else:
        task.retry_count += 1

    task.queue_job_id = uuid.uuid4()
    task.status = "pending"
    task.input_payload = payload
    task.output_payload = {}
    task.error_message = None
    task.started_at = None
    task.finished_at = None
    task.updated_at = None

    db.add(
        QueueOutbox(
            job_task_id=task.id,
            queue_name=settings.redis_dispatch_queue,
            payload={
                "job_id": str(task.queue_job_id),
                "task": "tarpass",
                "payload": payload,
                "result_queue": settings.redis_result_queue,
                "meta": {"job_id": str(job.id)},
            },
            status="pending",
        )
    )
    db.commit()
    return {"status": "pending"}
