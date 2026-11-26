"""SQLAlchemy ORM models for the knowledge layer.

Tables:
  knowledge_document_revisions — one row per (source_id, content_hash)
  knowledge_chunks — one row per chunk, FK to revision

Follows the project's existing SQLAlchemy 2.0 declarative style.
Migration note: tables are auto-created via Base.metadata.create_all at
startup (same as existing tables).  Production should migrate to Alembic
before multi-instance deployment — tracked as technical debt.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeDocumentRevision(Base):
    """One revision of a knowledge document.

    Unique on (source_id, content_hash) — same content is never stored twice.
    Multiple revisions of the same source_id coexist (history preservation).
    """
    __tablename__ = "knowledge_document_revisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(String(256), nullable=False)
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    logical_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(32), nullable=False)
    document_type: Mapped[str] = mapped_column(String(64), nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="validated")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("source_id", "content_hash", name="uniq_knowledge_source_hash"),
        Index("idx_knowledge_rev_source", "source_id", "created_at"),
        Index("idx_knowledge_rev_hash", "content_hash"),
        Index("idx_knowledge_rev_protocol", "protocol_version", "status"),
    )


class KnowledgeChunk(Base):
    """A single chunk from a knowledge document revision.

    FK to KnowledgeDocumentRevision.  chunk_id is deterministic for the same
    (source_id, section_index, content_hash).
    """
    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_document_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_id: Mapped[str] = mapped_column(String(16), nullable=False)
    source_id: Mapped[str] = mapped_column(String(256), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[str] = mapped_column(Text, nullable=False)
    heading_path: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(32), nullable=False)
    document_type: Mapped[str] = mapped_column(String(64), nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="validated")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("document_revision_id", "chunk_id", name="uniq_knowledge_chunk_rev"),
        Index("idx_knowledge_chunk_revision", "document_revision_id"),
        Index("idx_knowledge_chunk_source", "source_id", "content_hash"),
        Index("idx_knowledge_chunk_protocol", "protocol_version", "status"),
    )
