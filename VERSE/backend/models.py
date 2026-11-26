import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    is_admin: Mapped[bool] = mapped_column(nullable=False, default=False)
    is_guest: Mapped[bool] = mapped_column(nullable=False, default=False)
    guest_code_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    guest_code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    guest_code_last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class AgentProxySettings(Base):
    __tablename__ = "agent_proxy_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    proxy_url: Mapped[str | None] = mapped_column(String(2048))


class AgentLLMProfile(Base):
    __tablename__ = "agent_llm_profiles"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    base_url: Mapped[str] = mapped_column(String(2048))
    model: Mapped[str] = mapped_column(String(256))
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auth_type: Mapped[str] = mapped_column(String(16), default="api_key", server_default="api_key")
    encrypted_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_oauth_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AgentUserSettings(Base):
    __tablename__ = "agent_user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    active_profile_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_llm_profiles.id", ondelete="SET NULL"))
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    model: Mapped[str] = mapped_column(String(256), nullable=False)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class AgentWorkPreference(Base):
    """A standing work preference the researcher asked the assistant to remember (user level, one row per statement)."""
    __tablename__ = "agent_work_preferences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class AuthRefreshToken(Base):
    __tablename__ = "auth_refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("idx_refresh_user_id", "user_id"),
        Index("idx_refresh_expires_at", "expires_at"),
    )


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("idx_dataset_owner", "owner_user_id", "created_at"),
    )


class DatasetFile(Base):
    __tablename__ = "dataset_files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_role: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("idx_dataset_files_dataset_id", "dataset_id"),
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    input_dataset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=True)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    is_deleted: Mapped[bool] = mapped_column(nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("idx_jobs_owner_created", "owner_user_id", "created_at"),
    )


class DatasetUploadAttempt(Base):
    __tablename__ = "dataset_upload_attempts"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    # A null dataset id is a canceled attempt, never a pending upload.
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class JobSubmission(Base):
    __tablename__ = "job_submissions"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    # Keep the submission identity even if the original job is later removed.
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


class JobTask(Base):
    __tablename__ = "job_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_code: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_task: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    queue_job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4)
    depends_on: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list, server_default=text("'{}'::text[]"))
    input_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    output_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("job_id", "task_code", name="uniq_job_task_code"),
        Index("idx_job_tasks_job_status", "job_id", "status"),
        Index("idx_job_tasks_queue_job_id", "queue_job_id"),
    )


class QueueOutbox(Base):
    __tablename__ = "queue_outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("job_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    queue_name: Mapped[str] = mapped_column(String(128), nullable=False, default="genova:queue:dispatch")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("idx_outbox_status_created", "status", "created_at"),
    )


class ResearchTask(Base):
    __tablename__ = "agent_research_tasks"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="unassessed")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pending_turn_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    assessment: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    workflow_preferences: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    task_plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class WorkflowRun(Base):
    research_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_research_tasks.id"), index=True)
    execution_binding: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    action_proposal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_action_proposals.id", use_alter=True, name="fk_workflow_action_proposal"), nullable=True)
    __tablename__ = "workflow_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    refinement_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="awaiting_feedback", server_default="awaiting_feedback"
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="awaiting_approval")
    approved_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        CheckConstraint(
            "refinement_state IN ('awaiting_feedback', 'approved', 'running', 'closed')",
            name="ck_workflow_refinement_state",
        ),
        Index("idx_workflow_owner_created", "owner_user_id", "created_at"),
        Index("idx_workflow_status_updated", "status", "updated_at"),
    )


class WorkflowPlanningRequest(Base):
    research_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_research_tasks.id"), index=True)
    __tablename__ = "workflow_planning_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    protein_context_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="planning")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    last_error: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        CheckConstraint(
            "status IN ('planning', 'interrupted', 'failed', 'linked')",
            name="ck_workflow_planning_status",
        ),
        CheckConstraint("attempt >= 1 AND attempt <= 1000", name="ck_workflow_planning_attempt"),
        CheckConstraint(
            "(status = 'linked') = (workflow_id IS NOT NULL)",
            name="ck_workflow_planning_link",
        ),
        UniqueConstraint(
            "owner_user_id",
            "client_request_id",
            name="uq_workflow_planning_owner_client_request",
        ),
        Index("idx_workflow_planning_owner_updated", "owner_user_id", "updated_at"),
    )


class WorkflowInteraction(Base):
    """Bounded planning-session context; never a general chat history."""

    __tablename__ = "workflow_interactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    interaction_type: Mapped[str] = mapped_column(String(16), nullable=False)
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    assistant_message: Mapped[str] = mapped_column(Text, nullable=False)
    base_plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    resulting_plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    resulting_plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        CheckConstraint(
            "interaction_type IN ('plan', 'modify', 'explain')",
            name="ck_workflow_interaction_type",
        ),
        Index("idx_workflow_interactions_workflow_created", "workflow_id", "created_at"),
    )


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_key: Mapped[str] = mapped_column(String(64), nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("workflow_id", "step_key", name="uniq_workflow_step_key"),
        Index("idx_workflow_steps_workflow", "workflow_id", "step_index"),
    )


class SmallMoleculeResult(Base):
    __tablename__ = "small_molecule_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("job_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_code: Mapped[str] = mapped_column(String(64), nullable=False)
    smiles: Mapped[str] = mapped_column(Text, nullable=False)
    smiles_canonical: Mapped[str] = mapped_column(Text, nullable=False)
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("idx_smr_job_id", "job_id", "created_at"),
        Index("idx_smr_task_id", "job_task_id"),
        Index("idx_smr_task_smiles", "job_task_id", "smiles_canonical"),
        Index("idx_smr_task_code_created", "task_code", "created_at"),
        Index("idx_smr_smiles_canonical", "smiles_canonical"),
        Index("idx_smr_extra_gin", "extra", postgresql_using="gin"),
    )


class AgentSession(Base):
    research_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_research_tasks.id"), index=True)
    __tablename__ = "agent_sessions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False, default="")
    phase: Mapped[str] = mapped_column(String(40), nullable=False, default="awaiting_upload")
    input_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assets: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    confirmed_fields: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    pending_requirements: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    preparation_job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id"))
    active_workflow_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflow_runs.id"))
    last_error: Mapped[str | None] = mapped_column(String(128))
    last_user_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AgentTurn(Base):
    research_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_research_tasks.id"), index=True)
    __tablename__ = "agent_turns"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_sessions.id"), nullable=False, index=True)
    client_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request: Mapped[dict] = mapped_column(JSONB, nullable=False)
    response: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planning_request_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflow_planning_requests.id"))
    audit: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (UniqueConstraint("session_id", "client_request_id", name="uq_agent_turn_request"),
        Index("idx_agent_turn_session_created", "session_id", "created_at", "id"))


class ActionProposal(Base):
    __tablename__ = "agent_action_proposals"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_sessions.id"), nullable=False, index=True)
    turn_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_turns.id"), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    input_fingerprint: Mapped[dict] = mapped_column(JSONB, nullable=False)
    action_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    execution: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CandidateSet(Base):
    __tablename__ = "agent_candidate_sets"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_sessions.id"), nullable=False, index=True)
    proposal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_action_proposals.id"), nullable=False, unique=True)
    postprocessing_job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    artifact_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    selection_spec: Mapped[dict] = mapped_column(JSONB, nullable=False)
    molecule_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DesignDraft(Base):
    condition_ids: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    __tablename__ = "design_drafts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assets: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    values: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    provenance: Mapped[str] = mapped_column(String(32), nullable=False, default="verified")


class WorkflowCommand(Base):
    __tablename__ = "workflow_commands"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    response: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    event_key: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EditSession(Base):
    __tablename__ = "workflow_edit_sessions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    inputs: Mapped[dict] = mapped_column(JSONB, nullable=False)
    state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DeleteEditSpec(Base):
    __tablename__ = "delete_edit_specs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    reference_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    spec_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    specification: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DataRetentionPolicy(Base):
    __tablename__ = "data_retention_policy"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_enabled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DataRetentionDeletion(Base):
    __tablename__ = "data_retention_deletions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default='retention', server_default='retention')
    paths: Mapped[list] = mapped_column(JSONB, nullable=False)
    queue_job_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
