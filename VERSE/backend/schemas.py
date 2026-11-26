from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, model_validator


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    access_token_expires_in: int


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: SecretStr = Field(min_length=8, max_length=72)


class LogoutRequest(BaseModel):
    refresh_token: str


class GuestSessionOut(TokenPair):
    guest_code: str
    is_guest: bool = True
    username: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(max_length=2048)
    password: SecretStr = Field(max_length=128)
    confirm_password: SecretStr = Field(max_length=128)


class ClaimGuestRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    username: str
    is_active: bool
    is_admin: bool
    is_guest: bool
    created_at: datetime


class AdminMonitorStatsOut(BaseModel):
    current_jobs: int
    total_jobs: int
    total_users: int


class AdminMonitorJobOut(BaseModel):
    id: UUID
    owner_user_id: UUID
    owner_email: EmailStr
    owner_username: str
    job_type: str
    status: str
    priority: int
    params: dict[str, Any]
    summary: dict[str, Any]
    is_deleted: bool
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AdminMonitorResponseOut(BaseModel):
    stats: AdminMonitorStatsOut
    total_matched: int
    items: list[AdminMonitorJobOut]


class DatasetFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    file_role: str
    original_filename: str
    content_type: str | None = None
    size_bytes: int
    sha256: str | None = None
    created_at: datetime


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_user_id: UUID
    name: str
    kind: str
    description: str | None = None
    status: str
    meta: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    files: list[DatasetFileOut] = Field(default_factory=list)


class DatasetRenameRequest(BaseModel):
    name: str = Field(min_length=1)
    file_id: UUID | None = None


class JobCreateRequest(BaseModel):
    job_type: str
    ligand_dataset_id: UUID | None = None
    pocket_dataset_id: UUID | None = None
    protein_context_id: UUID | None = None
    prepared_receptor_id: UUID | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_by_job_type(self):
        job_type = (self.job_type or "").strip().lower()
        if job_type not in {
            "molecule_generation",
            "molecule_postprocessing",
            "property_optimization",
            "protein_preparation",
        }:
            raise ValueError(
                "job_type must be one of: molecule_generation, molecule_postprocessing, property_optimization, protein_preparation"
            )
        parameter_key = {"molecule_generation": "molecule_generation", "property_optimization": "property_optimization",
                         "molecule_postprocessing": "postprocessing"}.get(job_type)
        if parameter_key and not isinstance(self.params.get(parameter_key), dict):
            raise ValueError(f"params.{parameter_key} must be an object")
        if job_type == "property_optimization" and self.protein_context_id is None:
            raise ValueError("protein_context_id is required when job_type=property_optimization")
        if job_type == "protein_preparation":
            if self.prepared_receptor_id is None or self.protein_context_id is not None:
                raise ValueError("Protein preparation requires prepared_receptor_id and does not accept protein_context_id")
            if self.prepared_receptor_id and (self.ligand_dataset_id or self.pocket_dataset_id or self.params):
                raise ValueError("Prepared receptor execution uses its saved specification; overrides are not accepted")
        elif self.prepared_receptor_id is not None:
            raise ValueError("prepared_receptor_id is only valid for protein_preparation")
        self.job_type = job_type
        return self


class JobTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    task_code: str
    runtime_task: str | None = None
    status: str
    queue_job_id: UUID
    depends_on: list[str]
    input_payload: dict[str, Any]
    output_payload: dict[str, Any]
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class JobListOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_type: str
    status: str
    params: dict[str, Any]
    summary: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ProteinContextListOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    status: str
    ready: bool


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_user_id: UUID
    job_type: str
    status: str
    priority: int
    input_dataset_id: UUID | None = None
    params: dict[str, Any]
    summary: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    tasks: list[JobTaskOut] = Field(default_factory=list)


class SmallMoleculeResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    job_task_id: UUID
    task_code: str
    smiles: str
    smiles_canonical: str
    extra: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class JobDeletionPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_ids: list[UUID] = Field(min_length=1, max_length=100)


class JobDeletionRequest(JobDeletionPreviewRequest):
    confirmation_token: str = Field(min_length=1, max_length=262144)
