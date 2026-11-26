"""Align Agent output with backend-owned plan, result and evidence facts."""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from backend.agent.context import TurnContext
from backend.agent.deps import AgentDeps
from backend.agent.schemas import ActiveSkillRef, AgentResponse, WorkflowPlan

def merge_result_queries(queries):
    grouped = {}
    for row in queries:
        key = json.dumps({field: row.get(field) for field in (
            'workflow_id', 'filters', 'sort', 'returned_count', 'summary_scope')}, sort_keys=True)
        previous = grouped.get(key)
        if previous and row.get('summary_scope') == 'matched':
            row = {**row, 'summary': {**row['summary'], 'metric_summaries': {
                **previous['summary']['metric_summaries'], **row['summary']['metric_summaries']}}}
        grouped[key] = row
    return list(grouped.values())


def verify_response(output: AgentResponse, deps: AgentDeps, context: TurnContext, message: str) -> AgentResponse:
    mode = deps.interaction_mode
    current_plan = context.current_plan
    current_workflow_id = context.current_workflow_id
    current_plan_version = context.current_plan_version
    current_plan_hash = context.current_plan_hash
    current_refinement_state = context.current_refinement_state
    skill_warnings = context.skill_warnings
    knowledge_error = deps.knowledge_warning
    evidence_refs = deps.retrieved_evidence
    if deps.results_result and "error" not in deps.results_result:
        if deps.result_queries:
            deps.results_result = merge_result_queries(deps.result_queries)[-1]
        output = output.model_copy(update={"result_queries": merge_result_queries(deps.result_queries) if deps.result_queries else []})
    preview = deps.preview_result
    # In explain mode, if the LLM called preview_workflow but mutation
    # was forbidden, treat it as if the tool wasn't called.  This
    # preserves the explain-mode early return below which correctly
    # returns plan_valid=True with the current persisted plan.
    if preview is not None and preview.get("error_code") == "PLAN_MUTATION_FORBIDDEN" and mode == "explain":
        preview = None
    if preview is None:
        no_preview_warnings = list(skill_warnings)
        if knowledge_error:
            no_preview_warnings.append(knowledge_error)
        if (
            mode == "explain"
            and current_plan is not None
            and current_workflow_id is not None
            and current_plan_version is not None
            and current_plan_hash is not None
        ):
            return output.model_copy(
                update={
                    "plan_valid": True,
                    "plan": current_plan,
                    "workflow_id": current_workflow_id,
                    "plan_version": current_plan_version,
                    "plan_hash": current_plan_hash,
                    "normalized_plan": current_plan,
                    "results": deps.results_result,
                    "evidence_refs": evidence_refs,
                    "evidence_details": deps.retrieved_evidence_details,
                    "warnings": no_preview_warnings,
                    "active_skills": [ActiveSkillRef(name=s.metadata.name, version=s.metadata.version) for s in deps.active_skills],
                    "interaction_type": "explain",
                    "plan_changed": False,
                    "previous_plan_version": current_plan_version,
                    "refinement_state": current_refinement_state or "awaiting_feedback",
                }
            )
        return output.model_copy(
            update={
                "plan_valid": False,
                "plan": None,
                "workflow_id": None,
                "plan_version": None,
                "plan_hash": None,
                "normalized_plan": None,
                "results": deps.results_result,
                "evidence_refs": evidence_refs,
                "evidence_details": deps.retrieved_evidence_details,
                "warnings": no_preview_warnings,
                "active_skills": [ActiveSkillRef(name=s.metadata.name, version=s.metadata.version) for s in deps.active_skills],
                "interaction_type": mode,
                "error_code": "PLAN_MODIFICATION_NOT_PRODUCED" if mode == "modify" else output.error_code,
            }
        )
    warnings = list(preview.get("warnings") or []) + skill_warnings
    if knowledge_error and knowledge_error not in warnings:
        warnings.append(knowledge_error)
    update: dict[str, Any] = {
        "plan_valid": bool(preview.get("valid")),
        "plan": None,
        "missing_requirements": list(preview.get("missing_requirements") or []),
        "warnings": warnings,
        "error_code": preview.get("error_code") or output.error_code,
        "workflow_id": None,
        "plan_version": None,
        "plan_hash": None,
        "normalized_plan": None,
        "results": deps.results_result,
        "evidence_refs": evidence_refs,
        "evidence_details": deps.retrieved_evidence_details,
        "active_skills": [ActiveSkillRef(name=s.metadata.name, version=s.metadata.version) for s in deps.active_skills],
        "interaction_type": mode,
        "plan_changed": False,
        "previous_plan_version": deps.base_plan_version or None,
    }
    if preview.get("valid"):
        normalized = WorkflowPlan.model_validate(preview["normalized_plan"])
        update.update(
            plan=normalized,
            normalized_plan=normalized,
            workflow_id=UUID(str(preview.get("workflow_id"))),
            plan_version=preview.get("plan_version"),
            plan_hash=preview.get("plan_hash"),
            plan_changed=bool(preview.get("plan_changed")),
            previous_plan_version=preview.get("previous_plan_version"),
            refinement_state="awaiting_feedback",
        )
    return output.model_copy(update=update)
