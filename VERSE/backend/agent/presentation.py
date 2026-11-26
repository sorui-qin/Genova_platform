"""HTTP presentation models for backend-owned evidence provenance."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.agent.errors import AgentErrorSource, RecoveryAction, error_source_for, recovery_action_for, failure_details
from backend.agent.schemas import AgentResponse


_SOURCE_METADATA: dict[str, dict[str, Any]] = {
    "surfgen-protocol-v1": {
        "name": "SurfGen Generation Protocol",
        "category": "molecular_generation",
        "purpose": "Generate candidate molecules",
        "related_workflows": ["surfgen_tarpass_v1"],
        "related_components": ["surfgen"],
        "related_metrics": [],
    },
    "tarpass-interpretation-v1": {
        "name": "TarPass Screening Interpretation",
        "category": "molecular_screening",
        "purpose": "Evaluate and filter generated molecules",
        "related_workflows": ["surfgen_tarpass_v1"],
        "related_components": [],
        "related_metrics": ["qed", "sa_score"],
    },
}


class EvidenceCard(BaseModel):
    """User-facing context layered over one unchanged evidence detail."""

    model_config = {"extra": "forbid"}

    source_id: str
    chunk_id: str
    content_hash: str
    revision_id: str
    section: str
    protocol_version: str
    name: str | None = None
    category: str | None = None
    purpose: str | None = None
    related_workflows: list[str] = Field(default_factory=list)
    related_components: list[str] = Field(default_factory=list)
    related_metrics: list[str] = Field(default_factory=list)
    why_cited: str


class AgentPlanResponse(AgentResponse):
    """Additive HTTP response; the model-facing AgentResponse stays unchanged."""

    evidence_cards: list[EvidenceCard] = Field(default_factory=list)
    error_source: AgentErrorSource | None = None
    recovery_action: RecoveryAction | None = None
    status_code: int | None = None
    upstream_status_code: int | None = None
    upstream_error_code: str | None = None


def present_agent_response(response: AgentResponse) -> AgentPlanResponse:
    """Project retrieved evidence into cards without changing retrieval or refs."""

    plan = response.normalized_plan or response.plan
    current_workflow = plan.template if plan else None
    cards: list[EvidenceCard] = []
    for evidence in response.evidence_details:
        metadata = _SOURCE_METADATA.get(evidence.source_id)
        if metadata:
            workflow = (
                f"the current {current_workflow} workflow"
                if current_workflow in metadata["related_workflows"]
                else f"the {metadata['related_workflows'][0]} workflow"
            )
            why_cited = (
                f'Retrieved section "{evidence.section}" to support '
                f"{metadata['purpose'].lower()} in {workflow}."
            )
        else:
            why_cited = (
                f'Retrieved section "{evidence.section}" for this request; '
                "no curated workflow relationship is registered for this source."
            )
            metadata = {
                "name": None,
                "category": None,
                "purpose": None,
                "related_workflows": [],
                "related_components": [],
                "related_metrics": [],
            }
        cards.append(
            EvidenceCard(
                source_id=evidence.source_id,
                chunk_id=evidence.chunk_id,
                content_hash=evidence.content_hash,
                revision_id=evidence.revision_id,
                section=evidence.section,
                protocol_version=evidence.protocol_version,
                why_cited=why_cited,
                **metadata,
            )
        )
    return AgentPlanResponse.model_validate(
        {**response.model_dump(), "evidence_cards": cards,
         "status_code": getattr(response, "status_code", None) or (failure_details(response.error_code)["status_code"] if response.error_code else None),
         "error_source": getattr(response, "error_source", None) or error_source_for(response.error_code), "recovery_action": recovery_action_for(response.error_code)}
    )
