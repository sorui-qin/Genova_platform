import uuid
from sqlalchemy import select
from backend.models import CandidateSet
from backend.agent.session_schemas import SelectionSpec
from backend.services.results import load_tarpass_results
from backend.services.jobs import resolve_job_artifact
from backend.services.workflows import WorkflowError
from genova_runtime.pdb2pqr_compat import file_sha256
from tarpass.filters import METRICS


def save_candidate_set(db, owner_user_id, proposal, job_id):
    from backend.services.results import load_tarpass_results, apply_query, summarize_metric
    old = db.scalar(select(CandidateSet).where(CandidateSet.proposal_id == proposal.id))
    if old:
        return old
    job, task, rows = load_tarpass_results(db, user_id=owner_user_id, job_id=job_id)
    spec = SelectionSpec.model_validate(proposal.payload["selection"])
    keys = set(spec.summary_metrics) | {f.metric for f in spec.filters}
    if spec.sort_by and spec.sort_by != "molecule_id":
        keys.add(spec.sort_by)
    if keys - METRICS:
        raise WorkflowError("INVALID_METRIC", "Unknown selection metric", 422)
    matched = apply_query(rows, filters=[f.model_dump() for f in spec.filters], sort_by=spec.sort_by or "molecule_id", descending=spec.descending)
    selected = matched if spec.top_k is None else matched[:spec.top_k]
    ids = [r["molecule_id"] for r in selected]
    if len(ids) != len(set(ids)):
        raise WorkflowError("RESULT_INTEGRITY_ERROR", "Physical molecule IDs are not unique", 409)
    path = resolve_job_artifact(job, task.output_payload["results_json"])
    if proposal.payload.get("artifact_hash") and file_sha256(path) != proposal.payload["artifact_hash"]:
        raise WorkflowError("RESULT_INTEGRITY_ERROR", "Result artifact changed after preview", 409)
    summary = {"name": (spec.name or '').strip() or f"Candidates {str(proposal.id)[:8]}",
        "total_count": len(rows), "succeeded_count": sum(r["status"] == "succeeded" for r in rows),
        "partial_count": sum(r["status"] == "partial" for r in rows), "matched_count": len(matched), "selected_count": len(selected),
        "artifacts": {key: file_sha256(resolve_job_artifact(job, task.output_payload[key])) for key in ("original_sdf", "docked_sdf") if task.output_payload.get(key)},
        "scope": "selected", "metric_summaries": {k: summarize_metric(selected, k) for k in sorted(keys)}}
    row = CandidateSet(owner_user_id=owner_user_id, session_id=proposal.session_id, proposal_id=proposal.id,
        postprocessing_job_id=job.id, artifact_hash=file_sha256(path), selection_spec=spec.model_dump(mode="json"), molecule_ids=ids, summary=summary)
    db.add(row)
    db.flush()
    proposal.execution = {**proposal.execution, "candidate_set_id": str(row.id)}
    return row
