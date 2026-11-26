"""Shared TarPass result query service.

Used by both the HTTP result router (routers/postprocessing.py) and the agent
query_results tool.  Metric/filter/sort validation comes exclusively from the
canonical TarPass registry in tarpass.filters.
"""
from __future__ import annotations

from genova_runtime.artifact_json import read_json

import json
import math
import uuid
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models import Job, JobTask
from backend.services.jobs import DomainValidationError, get_owned_job, resolve_job_artifact
from backend.services.workflows import (
    WorkflowError,
    owned_workflow,
    workflow_steps,
    workflow_step_error,
    workflow_status_dict,
)
from tarpass.filters import FILTER_OPS, METRICS, failed_filters, metric_value, validate_filters


MAX_AGENT_FILTERS = 20
MAX_TOP_K = 100
DEFAULT_TOP_K = 50
MAX_SUMMARY_METRICS = 10


class ResultServiceError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        http_status: int,
        workflow_status: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.workflow_status = workflow_status


# ---------------------------------------------------------------------------
# Loading + canonical query (shared with the HTTP router)
# ---------------------------------------------------------------------------

def load_tarpass_results(
    db: Session,
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    data_root: Path | None = None,
) -> tuple[Job, JobTask, list[dict]]:
    """Ownership check → TarPass task succeeded check → artifact read."""
    try:
        job = get_owned_job(db, user_id, job_id)
    except DomainValidationError as exc:
        raise ResultServiceError(exc.code, exc.message, exc.http_status) from exc
    task = db.scalar(select(JobTask).where(JobTask.job_id == job.id, JobTask.task_code == "tarpass"))
    if task is None or task.status != "succeeded":
        raise ResultServiceError("POSTPROCESSING_NOT_READY", "Postprocessing results are not ready", 409)
    try:
        path = resolve_job_artifact(job, task.output_payload.get("results_json"), data_root=data_root or settings.data_root)
        rows = read_json(path)
        if not isinstance(rows, list):
            raise ValueError("results.json is not a list")
    except DomainValidationError as exc:
        raise ResultServiceError(exc.code, exc.message, exc.http_status) from exc
    except (ValueError, OSError) as exc:
        raise ResultServiceError("RESULTS_UNAVAILABLE", "Result artifact is unreadable", 409) from exc
    return job, task, rows


def apply_query(
    rows: list[dict],
    *,
    filters: Iterable[dict],
    sort_by: str = "molecule_id",
    descending: bool = False,
    include_prefiltered: bool = False,
    include_failed: bool = False,
) -> list[dict]:
    """Canonical TarPass filter → sort.  Raises ResultServiceError on invalid input."""
    try:
        validate_filters(filters)
        if sort_by not in METRICS | {"molecule_id"}:
            raise ValueError("Unsupported sort metric")
    except ValueError as exc:
        raise ResultServiceError("INVALID_FILTER", str(exc), 422) from exc
    rows = [row for row in rows
            if (include_prefiltered or row["status"] != "prefiltered")
            and (include_failed or row["status"] not in {"failed", "invalid"})
            and not failed_filters(row, filters)]
    if sort_by == "molecule_id":
        rows.sort(key=lambda row: row["molecule_id"], reverse=descending)
    else:
        # Stable secondary order for equal scores and for all missing values.
        rows.sort(key=lambda row: row["molecule_id"])
        present = [r for r in rows if metric_value(r, sort_by) is not None]
        missing = [r for r in rows if metric_value(r, sort_by) is None]
        rows = sorted(present, key=lambda r: metric_value(r, sort_by), reverse=descending) + missing
    return rows


def filter_guide(detail: str) -> dict[str, Any]:
    """An INVALID_FILTER answer that carries the allowed forms, so a model corrects the query in the same turn."""
    return {'error': 'INVALID_FILTER', 'detail': detail,
            'filter_shape': 'each filter is exactly {"metric": one of allowed_metrics, "op": one of filter_ops, "value": a finite number} with no other keys; '
                            'a boolean metric needs op "eq" and value 0 or 1',
            'filter_ops': sorted(FILTER_OPS), 'allowed_metrics': sorted(METRICS), 'allowed_sort_by': sorted(METRICS | {'molecule_id'}),
            'retry': 'Call again once with corrected filters and sort_by. To read the record at a rank, send no filters (null keeps the current view) '
                     'and use offset = rank - 1 with limit = 1.'}


# ---------------------------------------------------------------------------
# Workflow → TarPass Job resolution (spec §14)
# ---------------------------------------------------------------------------

def resolve_workflow_result_job(
    db: Session,
    *,
    user_id: uuid.UUID,
    workflow_id: uuid.UUID,
) -> Job:
    """WorkflowRun → postprocessing WorkflowStep → real TarPass Job.

    Only a succeeded postprocessing step yields results; every other state
    raises an explicit error code so the agent never has to infer.
    """
    try:
        run = owned_workflow(db, workflow_id, user_id)
    except WorkflowError as exc:
        raise ResultServiceError(exc.code, exc.message, exc.http_status) from exc
    return _resolve_result_job(db, run)


def _resolve_result_job(db: Session, run: Any) -> Job:
    """Step state machine for an already-ownership-checked workflow run."""
    steps = {step.step_key: step for step in workflow_steps(db, run.id)}
    post = steps.get("postprocessing")
    if post is None:
        raise ResultServiceError("WORKFLOW_FAILED", "Workflow has no postprocessing step", 409)

    if run.status == "failed":
        failed_step = next((s for s in steps.values() if s.error_code), None)
        detail = workflow_step_error(failed_step)["message"] if failed_step else "Workflow failed"
        raise ResultServiceError("WORKFLOW_FAILED", detail, 409)
    if run.status == "canceled":
        raise ResultServiceError("WORKFLOW_CANCELED", "Workflow was canceled", 409)

    if post.job_id is None:
        if run.status == "succeeded":
            raise ResultServiceError("WORKFLOW_FAILED", "Workflow finished without a TarPass postprocessing job", 409)
        raise ResultServiceError("WORKFLOW_NOT_READY", "Postprocessing has not started yet", 409)
    if post.status == "failed":
        raise ResultServiceError("WORKFLOW_FAILED", workflow_step_error(post)["message"], 409)
    if post.status == "canceled":
        raise ResultServiceError("WORKFLOW_CANCELED", "Postprocessing was canceled", 409)
    if post.status != "succeeded":
        raise ResultServiceError("WORKFLOW_NOT_READY", "Postprocessing is still running", 409)

    job = db.get(Job, post.job_id)
    if job is None:
        raise ResultServiceError("WORKFLOW_FAILED", "Postprocessing Job is missing", 409)
    return job


# ---------------------------------------------------------------------------
# Agent-facing query: filter → sort → top_k → projection + summary
# ---------------------------------------------------------------------------

def project_row(row: dict) -> dict[str, Any]:
    """Expose only canonical, finite metrics; retain each metric's pose."""
    metrics: dict[str, Any] = {}
    for key, value in row.get("metrics", {}).items():
        if key in {"original", "docked"} and isinstance(value, dict):
            metrics[key] = {k: metric_value(row, f"{key}.{k}") for k in value if f"{key}.{k}" in METRICS}
        elif key in METRICS:
            metrics[key] = metric_value(row, key)
    return {
        "result_id": row.get("result_id"),
        "molecule_id": row.get("molecule_id"),
        "smiles": row.get("smiles"),
        "status": row.get("status"),
        "metrics": metrics,
    }


def summarize_metric(rows: list[dict], key: str) -> dict[str, Any]:
    """count/mean/min/max over finite values; missing counted, never zero-filled."""
    values: list[float] = []
    missing = 0
    for row in rows:
        value = metric_value(row, key)
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            missing += 1
        else:
            values.append(value)
    summary: dict[str, Any] = {"count": len(values), "missing": missing}
    if values:
        summary.update(mean=sum(values) / len(values), min=min(values), max=max(values))
    else:
        summary.update(mean=None, min=None, max=None)
    return summary


def query_workflow_results(
    db: Session,
    *,
    user_id: uuid.UUID,
    workflow_id: uuid.UUID,
    filters: list[dict] | None = None,
    sort_by: str | None = None,
    descending: bool = False,
    top_k: int = DEFAULT_TOP_K,
    summary_metrics: list[str] | None = None,
    summary_scope: str = "matched",
    data_root: Path | None = None,
) -> dict[str, Any]:
    """Full agent query: resolve workflow → load → filter → sort → top_k → summarize."""
    filters = list(filters or [])
    summary_metrics = list(summary_metrics or [])
    if not isinstance(top_k, int) or not 1 <= top_k <= MAX_TOP_K:
        raise ResultServiceError("INVALID_PARAMETER", f"top_k must be between 1 and {MAX_TOP_K}", 422)
    if len(filters) > MAX_AGENT_FILTERS:
        raise ResultServiceError("INVALID_FILTER", f"At most {MAX_AGENT_FILTERS} filters are allowed", 422)
    if len(summary_metrics) > MAX_SUMMARY_METRICS:
        raise ResultServiceError("INVALID_PARAMETER", f"At most {MAX_SUMMARY_METRICS} summary metrics are allowed", 422)
    if summary_scope not in {"matched", "returned"}:
        raise ResultServiceError("INVALID_PARAMETER", "summary_scope must be 'matched' or 'returned'", 422)

    sort = sort_by or "molecule_id"
    keys = set(summary_metrics) | {item.get("metric") for item in filters if isinstance(item, dict)}
    if sort in METRICS:
        keys.add(sort)
    if len(keys) > MAX_SUMMARY_METRICS:
        raise ResultServiceError("INVALID_PARAMETER", f"At most {MAX_SUMMARY_METRICS} summary metrics are allowed", 422)
    unknown = keys - METRICS
    if unknown:
        raise ResultServiceError("INVALID_FILTER", f"Unsupported summary metric(s): {', '.join(sorted(unknown))}", 422)

    try:
        run = owned_workflow(db, workflow_id, user_id)
    except WorkflowError as exc:
        raise ResultServiceError(exc.code, exc.message, exc.http_status) from exc
    try:
        job = _resolve_result_job(db, run)
        _, _, all_rows = load_tarpass_results(db, user_id=user_id, job_id=job.id, data_root=data_root)
        matched = apply_query(all_rows, filters=filters, sort_by=sort, descending=descending)
    except ResultServiceError as exc:
        # Attach DB-truth state once so the agent can narrate accurately.
        exc.workflow_status = workflow_status_dict(db, run)
        raise

    returned = matched[:top_k]
    scope = returned if summary_scope == "returned" else matched

    counts = {
        "total_count": len(all_rows),
        "matched_count": len(matched),
        "returned_count": len(returned),
    }
    generation = (run.execution_binding or {}).get("effective_generation", run.plan_json.get("generation", {}))
    return {
        "workflow_id": str(workflow_id),
        "postprocessing_job_id": str(job.id),
        "requested_count": generation.get("target_num_molecules", generation.get("num_molecules")),
        "status_counts": {status: sum(row["status"] == status for row in all_rows)
            for status in ("succeeded", "partial", "failed", "invalid", "prefiltered")},
        **counts,
        "filters": [dict(item) for item in filters],
        "sort": {"by": sort, "descending": descending},
        "rows": [project_row(row) for row in returned],
        "summary_scope": summary_scope,
        "summary": {
            "scope": summary_scope,
            **counts,
            "metric_summaries": {key: summarize_metric(scope, key) for key in sorted(keys)},
        },
    }
