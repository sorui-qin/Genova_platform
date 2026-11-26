"""Agent dependency injection — typed context passed to every PydanticAI tool."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID, uuid4
from backend.agent.runner import Budget

from sqlalchemy.orm import Session

from backend.agent.catalog import CapabilityCatalog
from backend.agent.knowledge.base import KnowledgeProvider
from backend.agent.knowledge.schemas import EvidenceRef
from backend.agent.skills.schemas import SkillRecord
from backend.agent.skills.registry import SkillRegistry


@dataclass
class AgentDeps:
    """Dependencies injected into every PydanticAI tool call.

    The user_id is always set by the FastAPI auth layer — the LLM can
    never override it.
    """
    user_id: UUID
    db: Session
    catalog: CapabilityCatalog
    planning_request_id: UUID | None = None
    research_task_id: UUID | None = None
    safety_assessment: dict | None = None
    reference_content: list[dict] = field(default_factory=list)
    workflow_id: UUID | None = None
    preview_result: dict[str, Any] | None = None
    results_result: dict[str, Any] | None = None
    result_queries: list[dict[str, Any]] = field(default_factory=list)
    workflow_status_result: dict[str, Any] | None = None
    knowledge: KnowledgeProvider | None = None
    retrieved_evidence: list[str] = field(default_factory=list)
    retrieved_evidence_details: list[EvidenceRef] = field(default_factory=list)
    knowledge_warning: str | None = None
    active_skills: list[SkillRecord] = field(default_factory=list)
    skill_registry: SkillRegistry | None = None
    interaction_mode: Literal["plan", "modify", "explain"] = "plan"
    allow_plan_mutation: bool = True
    protein_context_id: UUID | None = None
    base_plan_version: int = 0
    defer_preview_persistence: bool = False
    allowed_tools: frozenset[str] | None = None
    preview_candidates: list[Any] = field(default_factory=list)
    postprocessing_options: dict[str, Any] | None = None
    tool_audit: list[dict[str, Any]] = field(default_factory=list)
    progress: Any = None
    usage: Any = None
    session_context: dict[str, Any] | None = None

    trace_id: str = field(default_factory=lambda: str(uuid4()))
    deadline: float | None = None
    budget: Budget = field(default_factory=Budget)
    stages: list[dict] = field(default_factory=list)
    committed_effects: list[dict] = field(default_factory=list)
    model_decision: dict | None = None
    decision_validation_errors: list[dict] = field(default_factory=list)
    prompt_composition: dict[str, int] = field(default_factory=dict)

    checkpoint_usage: Any = None
    read_cache: dict[str, Any] = field(default_factory=dict)
    response_facts: list[dict[str, Any]] = field(default_factory=list)
    stalled_tools: set[str] = field(default_factory=set)
    tool_attempts: int = 0
    previous_tool_executions: int = 0
    diagnostic_state: dict[str, Any] = field(default_factory=dict)

    source_read_state: dict[str, Any] = field(default_factory=dict)
    interface_language: Literal["zh", "en"] = "en"
