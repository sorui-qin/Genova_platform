"""Strict Pydantic schemas for the knowledge layer.

Every schema uses extra="forbid" to reject unknown fields.
Status, model, and document_type are constrained literals.

P4.5 changes:
- DocumentRecord gains revision_id and created_at
- ChunkRecord gains revision_id
- EvidenceRef gains content_hash for revision traceability
- IngestionResult gains revision_id
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Constrained type aliases
# ---------------------------------------------------------------------------

DocumentStatus = Literal["validated", "draft", "deprecated"]

ModelName = Literal["common", "surfgen", "delete", "ecloudgen", "tarpass", "epso", "protein_preparation"]

DocumentType = Literal[
    "overview",
    "inputs",
    "outputs",
    "generation_protocol",
    "parameters",
    "troubleshooting",
    "result_interpretation",
]


# ---------------------------------------------------------------------------
# Ingestion metadata (user-provided at ingest time)
# ---------------------------------------------------------------------------

class DocumentMetadata(BaseModel):
    """Metadata supplied when ingesting a document.  extra=forbid."""
    model_config = {"extra": "forbid"}

    source_id: str = Field(min_length=1, max_length=256)
    source_path: str | None = None
    logical_source: str | None = None
    model: ModelName = "common"
    document_type: DocumentType
    protocol_version: str = Field(min_length=1, max_length=64)
    status: DocumentStatus = "validated"
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Persisted records
# ---------------------------------------------------------------------------

class DocumentRecord(BaseModel):
    """Stored document-level metadata — one per (source_id, content_hash) revision.
    extra=forbid.
    """
    model_config = {"extra": "forbid"}

    revision_id: str  # unique identifier for this revision
    source_id: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model: ModelName
    document_type: DocumentType
    protocol_version: str
    status: DocumentStatus
    updated_at: datetime
    created_at: datetime


class ChunkRecord(BaseModel):
    """A single knowledge chunk with full metadata.  extra=forbid."""
    model_config = {"extra": "forbid"}

    chunk_id: str
    revision_id: str  # FK to the document revision
    source_id: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: str
    section: str
    heading_path: list[str]
    model: ModelName
    document_type: DocumentType
    protocol_version: str
    status: DocumentStatus
    updated_at: datetime


# ---------------------------------------------------------------------------
# Retrieval output
# ---------------------------------------------------------------------------

class EvidenceRef(BaseModel):
    """Machine-readable reference to a knowledge chunk.

    Includes content_hash so old Workflow evidence can be traced back to
    the exact revision that produced it.  extra=forbid.
    """
    model_config = {"extra": "forbid"}

    source_id: str
    chunk_id: str
    section: str
    protocol_version: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision_id: str

    def __str__(self) -> str:
        return f"{self.source_id}#{self.chunk_id}"

    def to_display(self) -> str:
        """Human-readable evidence label."""
        return f"{self.source_id} | {self.section} | {self.protocol_version}"


class KnowledgeEntry(BaseModel):
    """A current document's directory entry, without its full text."""
    model_config = {"extra": "forbid"}

    source_id: str
    model: ModelName
    title: str
    summary: str
    fields: list[str] = Field(default_factory=list)


class IngestionResult(BaseModel):
    """Returned after an ingestion attempt.  extra=forbid."""
    model_config = {"extra": "forbid"}

    source_id: str
    content_hash: str
    revision_id: str
    chunk_count: int
    is_new: bool
