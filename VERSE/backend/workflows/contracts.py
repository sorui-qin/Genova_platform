import hashlib
import json
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, Field


class Command(BaseModel):
    model_config = {"extra": "forbid"}
    command_id: UUID
    expected_version: int = Field(ge=0)
    operation: Literal["retry_session", "approve_task_plan", "create_task_plan", "patch_task_plan", "pause_task", "resume_task", "bind", "select_context", "prepare", "save_site", "create_workflow", "patch_workflow", "prepare_postprocessing", "selection", "retry_postprocessing", "approve", "cancel", "stop_continuation", "archive"]
    changes: dict[str, Any] = Field(default_factory=dict)
    approve_after_save: bool = False
    task_plan_version: int | None = None
    proposal_id: UUID | None = None
    action_hash: str | None = None


class OpenEdit(BaseModel):
    model_config = {"extra": "forbid"}
    kind: Literal["protein", "delete", "workflow", "selection"]
    expected_version: int = Field(ge=0)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
