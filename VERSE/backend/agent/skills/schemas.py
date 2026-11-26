"""Pydantic schemas for the Skills layer.

Every schema uses extra="forbid" to reject unknown fields.
Status and applies_to are constrained literals.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


SkillStatus = Literal["validated", "draft", "deprecated"]

SkillIntent = Literal["planning", "results", "failure", "help", "preparation", "metrics"]


class SkillMetadata(BaseModel):
    """Frontmatter from a SKILL.md file.  extra=forbid."""
    model_config = {"extra": "forbid"}

    schema_version: Literal["1", "2"] = "1"
    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=32)
    description: str = Field(min_length=1, max_length=512)
    status: SkillStatus
    applies_to: list[SkillIntent] = Field(min_length=1)


class SkillRecord(BaseModel):
    """A loaded skill with its metadata and text content.  extra=forbid."""
    model_config = {"extra": "forbid"}

    metadata: SkillMetadata
    content: str
    content_hash: str = ""
    source_path: str
