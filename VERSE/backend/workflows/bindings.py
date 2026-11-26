"""Execution integrity uses persisted resources, never the conversation."""
import uuid
from pathlib import Path
from backend.services.jobs import get_owned_dataset, get_dataset_files
from backend.services.workflows import WorkflowError
from genova_runtime.pdb2pqr_compat import file_sha256


def validate_resources(db, owner_id, resources):
    if not resources:
        raise WorkflowError("INPUT_UNVERIFIED", "Input provenance must be confirmed again", 409)
    for resource in resources:
        dataset = get_owned_dataset(db, uuid.UUID(resource["id"]), owner_id)
        if dataset.status == "archived":
            raise WorkflowError("RESOURCE_ARCHIVED", "The bound dataset has been archived", 409)
        if resource.get("context") is not None and dataset.meta != resource["context"]:
            raise WorkflowError("INPUT_CHANGED", "Prepared Context changed", 409)
        files = {str(f.id): f for f in get_dataset_files(db, dataset.id)}
        expected_ids = {f['id'] for f in resource['files']}
        if not expected_ids <= files.keys() or (not resource.get('pinned_files') and set(files) != expected_ids):
            raise WorkflowError("INPUT_CHANGED", "Input files changed", 409)
        for expected in resource["files"]:
            row = files[expected["id"]]
            if not Path(row.storage_path).is_file() or row.sha256 != expected["sha256"] or file_sha256(row.storage_path) != expected["sha256"]:
                raise WorkflowError("INPUT_CHANGED", "Input artifact changed or is unavailable", 409)


def workflow_binding(db, run):
    bound = run.execution_binding
    if bound is None:
        raise WorkflowError("ACTION_APPROVAL_REQUIRED", "A current approved execution binding is required", 409)
    payload = bound["payload"]
    if payload["plan_hash"] != run.plan_hash or payload["plan_version"] != run.plan_version:
        raise WorkflowError("PLAN_INTEGRITY_ERROR", "Execution plan changed", 409)
    validate_resources(db, run.owner_user_id, bound["inputs"]["resources"])
    return payload


def snapshot_inputs(db, owner_user_id, assets, values, revision, payload=None):
    ids = {uuid.UUID(assets[key]) for key in ("protein_dataset_id", "ligand_dataset_id", "protein_context_id", "prepared_receptor_id") if assets.get(key)}
    values = {**values, **(payload or {})}
    pinned = {}

    def pin(value):
        if isinstance(value, dict):
            if {"dataset_id", "file_id", "sha256"} <= value.keys():
                resource_id = uuid.UUID(str(value["dataset_id"]))
                ids.add(resource_id)
                pinned.setdefault(resource_id, set()).add(str(value["file_id"]))
            for item in value.values():
                pin(item)
        elif isinstance(value, list):
            for item in value:
                pin(item)

    if values.get("prepared_spec"):
        pin(values["prepared_spec"])
    visited = set()
    while ids - visited:
        resource_id = next(iter(ids - visited))
        visited.add(resource_id)
        dataset = get_owned_dataset(db, resource_id, owner_user_id)
        meta = dataset.meta or {}
        if dataset.status == "archived" or dataset.kind == "protein_context" and meta.get("version") != 4:
            raise WorkflowError("INPUT_UNVERIFIED", "Use a ready current Context", 409)
        if dataset.kind == "prepared_receptor" or (dataset.kind == "protein_context" and meta.get("version") == 4):
            pinned.setdefault(resource_id, set())
            pin(meta)
            if meta.get("prepared_receptor_id"):
                ids.add(uuid.UUID(meta["prepared_receptor_id"]))
    if values.get("reference_dataset_id"):
        ids.add(uuid.UUID(str(values["reference_dataset_id"])))
    if isinstance(values.get("seed_source"), dict) and values["seed_source"].get("dataset_id"):
        pin(values["seed_source"])
    resources = []
    for resource_id in sorted(ids, key=str):
        dataset = get_owned_dataset(db, resource_id, owner_user_id)
        db.refresh(dataset, with_for_update=True)
        if dataset.status == "archived":
            raise WorkflowError("RESOURCE_ARCHIVED", "The bound dataset has been archived", 409)
        files = []
        for row in sorted(get_dataset_files(db, dataset.id), key=lambda row: str(row.id)):
            if resource_id in pinned and str(row.id) not in pinned[resource_id]:
                continue
            if not Path(row.storage_path).is_file():
                raise WorkflowError("INPUT_UNAVAILABLE", "An input artifact is unavailable", 409)
            files.append({"id": str(row.id), "sha256": row.sha256})
        if resource_id in pinned and {row["id"] for row in files} != pinned[resource_id]:
            raise WorkflowError("INPUT_UNAVAILABLE", "A bound file is unavailable", 409)
        resources.append({"id": str(dataset.id), "files": files,
                          "context": dataset.meta if dataset.kind in {"protein_context", "prepared_receptor"} else None,
                          **({"pinned_files": True} if resource_id in pinned else {})})
    return {"revision": revision, "resources": resources, "values": values}
