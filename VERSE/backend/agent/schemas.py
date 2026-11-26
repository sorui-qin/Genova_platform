from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from tarpass.filters import DEFAULT_PREFILTERS
from pydantic import BaseModel, Field, field_validator, model_validator
from genova_runtime.generation_settings import COUNT_LIMITS, DEFAULT_GENERATION_COUNT, ROUND_TARGET
from genova_runtime.epso_objectives import DEFAULT_OBJECTIVES, DEFAULT_OPTIMIZER, validate_parameters, validate_requested_count

from backend.agent.knowledge.schemas import EvidenceRef


# ---------------------------------------------------------------------------
# Page context (sent by frontend, not trusted for authorization)
# ---------------------------------------------------------------------------

class AgentPageContext(BaseModel):
    """Frontend page context hints — only used as resource references."""
    model_config = {"extra": "forbid"}

    page: Literal[
        "dashboard",
        "protein_context",
        "surfgen",
        "delete",
        "ecloudgen",
        "epso",
        "tarpass",
        "results",
    ] = "dashboard"
    protein_context_id: str | None = None
    job_id: str | None = None
    workflow_id: str | None = None
    dataset_ids: list[str] = Field(default_factory=list)

    @field_validator("protein_context_id", "job_id", "workflow_id", mode="before")
    @classmethod
    def _ensure_str_or_none(cls, v: Any) -> str | None:
        if v is None:
            return None
        return str(v)


# ---------------------------------------------------------------------------
# Generator configs (discriminated union via engine literal)
# ---------------------------------------------------------------------------

class SurfGenConfig(BaseModel):
    """SurfGen generation parameters."""
    model_config = {"extra": "forbid"}

    engine: Literal["surfgen"] = "surfgen"
    num_molecules: int = Field(default=DEFAULT_GENERATION_COUNT, ge=1, le=COUNT_LIMITS['surfgen'], strict=True)
    beam_size: int = Field(default=500, ge=1, le=5000, strict=True)
    max_steps: int = Field(default=50, ge=1, le=500, strict=True)
    element_threshold: Literal[0.3] = 0.3
    bond_threshold: Literal[0.4] = 0.4
    seed: int = Field(default=2020, ge=0, le=4294967295, strict=True)

    @model_validator(mode='before')
    @classmethod
    def use_platform_seed_for_large_jobs(cls, values):
        if isinstance(values, dict) and type(values.get('num_molecules')) is int and values['num_molecules'] > ROUND_TARGET:
            return {key: value for key, value in values.items() if key != 'seed'}
        return values


class ECloudGenConfig(BaseModel):
    """ECloudGen target-count generation parameters."""
    model_config = {"extra": "forbid"}

    engine: Literal["ecloudgen"] = "ecloudgen"
    target_num_molecules: int = Field(default=DEFAULT_GENERATION_COUNT, ge=1, le=COUNT_LIMITS['ecloudgen'], strict=True)
    noise: float = Field(default=0.1, ge=0, allow_inf_nan=False)
    inv_temp: float = Field(default=2, gt=0, allow_inf_nan=False)
    num_clouds: int | None = Field(default=None, ge=4, le=256, multiple_of=4, strict=True)
    decodes_per_cloud: int = Field(default=100, ge=1, le=1024, strict=True)
    seed: int = Field(default=42, ge=0, le=4294967295, strict=True)
    budget_multiplier: Literal[3] = 3


class DeleteEditConfig(BaseModel):
    """Explicit DELETE edit selection; no edit site is guessed by the Agent."""
    model_config = {"extra": "forbid"}

    mode: Literal[
        "r_group", "side_chain", "linker", "scaffold_hopping",
        "custom", "derivation_site",
    ]
    edit_spec_id: UUID | None = None
    candidate_id: str | None = None
    edited_molfile: str | None = None
    anchor_atom_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_target(self):
        if self.edit_spec_id:
            if self.candidate_id or self.edited_molfile or self.anchor_atom_index is not None:
                raise ValueError("Use either a saved edit specification or an inline edit")
            return self
        auto = {"r_group", "side_chain", "linker", "scaffold_hopping"}
        if self.mode in auto and not self.candidate_id:
            raise ValueError(f"{self.mode} requires candidate_id")
        if self.mode == "custom" and not self.edited_molfile:
            raise ValueError("custom DELETE edit requires edited_molfile")
        if self.mode == "derivation_site" and self.anchor_atom_index is None:
            raise ValueError("derivation_site requires anchor_atom_index")
        return self


class DeleteConfig(BaseModel):
    """DELETE lead-optimization parameters."""
    model_config = {"extra": "forbid"}

    engine: Literal["delete"] = "delete"
    num_molecules: int = Field(default=DEFAULT_GENERATION_COUNT, ge=1, le=COUNT_LIMITS['delete'], strict=True)
    edit: DeleteEditConfig


class EPSOConfig(BaseModel):
    """EPSO property-optimization parameters."""
    model_config = {"extra": "forbid"}

    engine: Literal["epso"] = "epso"
    num_molecules: int = Field(default=100, ge=1, le=COUNT_LIMITS['epso'], strict=True)
    objectives: list[dict[str, Any]] = Field(default_factory=lambda: [dict(item) for item in DEFAULT_OBJECTIVES], min_length=1)
    optimizer: dict[str, Any] = Field(default_factory=lambda: dict(DEFAULT_OPTIMIZER))

    @model_validator(mode="after")
    def runtime_parameters(self):
        params = validate_parameters(self.model_dump(mode="json"))
        validate_requested_count(params['num_molecules'], params['objectives'])
        return self


SourceConfig = Annotated[
    SurfGenConfig | ECloudGenConfig | DeleteConfig | EPSOConfig,
    Field(discriminator="engine"),
]

# ---------------------------------------------------------------------------
# TarPass postprocessing config
# ---------------------------------------------------------------------------

class MetricFilter(BaseModel):
    """Single metric filter condition."""
    model_config = {"extra": "forbid"}

    metric: str
    op: Literal["gt", "lt", "gte", "lte", "eq"]
    value: float = Field(allow_inf_nan=False)


class TarPassConfig(BaseModel):
    """TarPass postprocessing configuration."""
    model_config = {"extra": "forbid"}

    enabled: bool = True
    prefilters: list[MetricFilter] = Field(default_factory=lambda: [MetricFilter(**rule) for rule in DEFAULT_PREFILTERS])


# ---------------------------------------------------------------------------
# Result selection
# ---------------------------------------------------------------------------

class ResultSelection(BaseModel):
    """How to select and sort results after postprocessing."""
    model_config = {"extra": "forbid"}

    sort_by: str | None = None
    descending: bool = False
    top_k: int | None = Field(default=None, ge=1, le=10000)


# ---------------------------------------------------------------------------
# WorkflowPlan — the core structured output
# ---------------------------------------------------------------------------

class WorkflowPlan(BaseModel):
    """Structured workflow plan generated by the agent.

    This is a DRAFT — it must go through preview_workflow validation
    before it can become an executable workflow.
    """
    model_config = {"extra": "forbid"}

    template: Literal[
        "surfgen_tarpass_v1", "ecloudgen_tarpass_v1",
        "delete_tarpass_v1", "epso_tarpass_v1",
    ] = "surfgen_tarpass_v1"
    protocol_version: Literal["generation-2026-09"] = "generation-2026-09"
    protein_context_id: str

    generator: Literal["surfgen", "ecloudgen", "delete", "epso"] = "surfgen"

    generation: SourceConfig = Field(default_factory=SurfGenConfig, discriminator="engine")
    postprocessing: TarPassConfig = Field(default_factory=TarPassConfig)
    selection: ResultSelection = Field(default_factory=ResultSelection)
    seed_source: dict[str, Any] | None = None

    warnings: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_engine_template(self):
        expected = {
            "surfgen": "surfgen_tarpass_v1",
            "ecloudgen": "ecloudgen_tarpass_v1",
            "delete": "delete_tarpass_v1",
            "epso": "epso_tarpass_v1",
        }[self.generator]
        if self.generation.engine != self.generator:
            raise ValueError("generation.engine must match generator")
        if self.template != expected:
            raise ValueError(f"template must be {expected} for {self.generator}")
        return self


# ---------------------------------------------------------------------------
# API request / response
# ---------------------------------------------------------------------------

class AgentRequest(BaseModel):
    """Incoming planning request from the frontend."""
    model_config = {"extra": "forbid"}

    message: str = Field(min_length=1, max_length=4000)
    context: AgentPageContext | None = None
    client_request_id: UUID
    retry: bool = False


class WorkflowInteractionRequest(BaseModel):
    """One bounded follow-up against an existing workflow draft."""
    model_config = {"extra": "forbid"}

    message: str = Field(min_length=1, max_length=4000)
    intent: Literal["modify", "explain"]


class ActiveSkillRef(BaseModel):
    """Behavior provenance only; never protocol evidence or skill body text."""
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=32)


class AgentResponse(BaseModel):
    """Structured response from the agent planning endpoint."""
    model_config = {"extra": "forbid"}

    message: str
    diagnostic_notes: str = Field(default='', max_length=8000, description="Leave empty; the backend supplies verified evidence and state records.")
    plan: WorkflowPlan | None = None
    plan_valid: bool = False
    missing_requirements: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None
    workflow_id: UUID | None = None
    plan_version: int | None = None
    plan_hash: str | None = None
    normalized_plan: WorkflowPlan | None = None
    results: dict[str, Any] | None = None
    result_queries: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    # Additive response field; stored WorkflowPlan refs retain their hash contract.
    evidence_details: list[EvidenceRef] = Field(default_factory=list)
    # Skills loaded for this request (additive, informational only).
    active_skills: list[ActiveSkillRef] = Field(default_factory=list)
    interaction_type: Literal["plan", "modify", "explain"] | None = None
    plan_changed: bool = False
    previous_plan_version: int | None = None
    refinement_state: str | None = None
    client_request_id: UUID | None = None
    planning_status: Literal[
        "planning", "interrupted", "draft", "approved", "running", "failed", "succeeded", "cancel_requested", "canceled"
    ] | None = None
    attempt: int | None = None
    retryable: bool = False


class WorkflowApproveRequest(BaseModel):
    model_config = {"extra": "forbid"}

    plan_version: int = Field(ge=1)
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class WorkflowStepOut(BaseModel):
    model_config = {"from_attributes": True}

    step_key: str
    status: str
    job_id: UUID | None = None
    error_code: str | None = None
    error_message: str | None = None


class WorkflowInteractionOut(BaseModel):
    model_config = {"from_attributes": True}

    interaction_type: Literal["plan", "modify", "explain"]
    user_message: str
    assistant_message: str
    base_plan_version: int
    resulting_plan_version: int
    resulting_plan_hash: str
    created_at: datetime


class WorkflowOut(BaseModel):
    workflow_id: UUID
    status: str
    template: str
    protocol_version: str
    plan_version: int
    plan_hash: str
    plan: WorkflowPlan
    refinement_state: str
    approved_version: int | None = None
    approved_hash: str | None = None
    approved_at: datetime | None = None
    steps: list[WorkflowStepOut]
    interactions: list[WorkflowInteractionOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class WorkflowListItem(BaseModel):
    """Compact durable history row for resume-after-refresh."""
    model_config = {"from_attributes": True}

    client_request_id: UUID | None = None
    workflow_id: UUID | None = None
    status: str
    template: str | None = None
    plan_version: int | None = None
    refinement_state: str | None = None
    title: str
    message: str
    protein_context_id: UUID
    attempt: int | None = None
    retryable: bool = False
    last_error: str | None = None
    updated_at: datetime
    created_at: datetime


class AgentRuntimeOut(BaseModel):
    runtime_mode: Literal["production"] = "production"
    execution_enabled: bool = True
    refinement_enabled: bool = True
    max_interactions: int
    recent_context_interactions: int
    gpu_policy: Literal["single_host_shared_lock"] = "single_host_shared_lock"


def canonicalize_workflow_plan(plan: WorkflowPlan | dict[str, Any]) -> dict[str, Any]:
    """Return the one validated JSON representation used for storage and hashing."""
    return WorkflowPlan.model_validate(plan).model_dump(mode="json")


def calculate_plan_hash(plan: WorkflowPlan | dict[str, Any]) -> str:
    canonical = canonicalize_workflow_plan(plan)
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
