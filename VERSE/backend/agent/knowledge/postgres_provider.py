"""PostgreSQL-backed KnowledgeProvider — production implementation.

Uses the project's existing SQLAlchemy Base / Session / engine.
Revision-aware: multiple revisions of the same source_id coexist.
Idempotent for the same (source_id, content_hash).
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.agent.knowledge.base import KnowledgeProvider
from backend.agent.knowledge.ingestion import chunk_markdown
from backend.agent.knowledge.models import KnowledgeChunk, KnowledgeDocumentRevision
from backend.agent.knowledge.retrieval import current_chunks, document_directory
from backend.agent.knowledge.schemas import (
    ChunkRecord,
    DocumentMetadata,
    DocumentRecord,
    EvidenceRef,
    IngestionResult,
    KnowledgeEntry,
)
from backend.agent.knowledge.utils import compute_content_hash


class PostgresKnowledgeProvider(KnowledgeProvider):
    """KnowledgeProvider backed by PostgreSQL via SQLAlchemy.

    Accepts a session factory (same pattern as the project's get_db).
    """

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    # -- helpers --------------------------------------------------------------

    def _revision_to_record(self, rev: KnowledgeDocumentRevision) -> DocumentRecord:
        return DocumentRecord(
            revision_id=str(rev.id),
            source_id=rev.source_id,
            content_hash=rev.content_hash,
            model=rev.model,
            document_type=rev.document_type,
            protocol_version=rev.protocol_version,
            status=rev.status,
            updated_at=rev.updated_at,
            created_at=rev.created_at,
        )

    def _chunk_to_record(self, chunk: KnowledgeChunk) -> ChunkRecord:
        return ChunkRecord(
            chunk_id=chunk.chunk_id,
            revision_id=str(chunk.document_revision_id),
            source_id=chunk.source_id,
            content_hash=chunk.content_hash,
            content=chunk.content,
            section=chunk.section,
            heading_path=chunk.heading_path if isinstance(chunk.heading_path, list) else [],
            model=chunk.model,
            document_type=chunk.document_type,
            protocol_version=chunk.protocol_version,
            status=chunk.status,
            updated_at=chunk.updated_at,
        )

    # -- ingestion ------------------------------------------------------------

    async def ingest(self, content: str, metadata: DocumentMetadata) -> IngestionResult:
        """Ingest a Markdown document.  Idempotent for same source_id + content_hash.

        New content_hash creates a new revision; old revisions are preserved.
        """
        content_hash = compute_content_hash(content)
        now = metadata.updated_at or datetime.now(timezone.utc)

        with self._session_factory() as db:
            # Idempotency check
            existing = db.scalar(
                select(KnowledgeDocumentRevision)
                .where(
                    KnowledgeDocumentRevision.source_id == metadata.source_id,
                    KnowledgeDocumentRevision.content_hash == content_hash,
                )
            )
            if existing is not None:
                return IngestionResult(
                    source_id=metadata.source_id,
                    content_hash=content_hash,
                    revision_id=str(existing.id),
                    chunk_count=0,
                    is_new=False,
                )

            # Generate stable revision_id
            revision_id = _uuid.uuid5(_uuid.NAMESPACE_URL, f"knowledge:{metadata.source_id}:{content_hash}")

            # Chunk
            raw_chunks = chunk_markdown(content, metadata.source_id, content_hash, str(revision_id))

            # Create revision record
            rev = KnowledgeDocumentRevision(
                id=revision_id,
                source_id=metadata.source_id,
                source_path=metadata.source_path,
                logical_source=metadata.logical_source,
                content_hash=content_hash,
                model=metadata.model,
                document_type=metadata.document_type,
                protocol_version=metadata.protocol_version,
                status=metadata.status,
                updated_at=now,
                created_at=now,
            )
            db.add(rev)
            # There is no ORM relationship to order these inserts. Flush the
            # parent before its chunks so an actual FK-enforcing DB accepts it.
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                # A concurrent ingestion may have committed this same revision.
                existing = db.scalar(select(KnowledgeDocumentRevision).where(
                    KnowledgeDocumentRevision.source_id == metadata.source_id,
                    KnowledgeDocumentRevision.content_hash == content_hash,
                ))
                if existing is None:
                    raise
                return IngestionResult(
                    source_id=metadata.source_id, content_hash=content_hash,
                    revision_id=str(existing.id), chunk_count=0, is_new=False,
                )

            # Create chunk records
            for i, chunk in enumerate(raw_chunks):
                chunk.model = metadata.model
                chunk.document_type = metadata.document_type
                chunk.protocol_version = metadata.protocol_version
                chunk.status = metadata.status
                chunk.updated_at = now

                db.add(KnowledgeChunk(
                    document_revision_id=revision_id,
                    chunk_id=chunk.chunk_id,
                    source_id=chunk.source_id,
                    content_hash=chunk.content_hash,
                    chunk_index=i,
                    section=chunk.section,
                    heading_path=chunk.heading_path,
                    content=chunk.content,
                    model=chunk.model,
                    document_type=chunk.document_type,
                    protocol_version=chunk.protocol_version,
                    status=chunk.status,
                    updated_at=chunk.updated_at,
                ))

            db.commit()

        return IngestionResult(
            source_id=metadata.source_id,
            content_hash=content_hash,
            revision_id=str(revision_id),
            chunk_count=len(raw_chunks),
            is_new=True,
        )

    # -- retrieval ------------------------------------------------------------

    async def has_protocol_version(self, protocol_version: str, *, status: str = "validated") -> bool:
        with self._session_factory() as db:
            return db.scalar(select(KnowledgeDocumentRevision.id).where(
                KnowledgeDocumentRevision.protocol_version == protocol_version,
                KnowledgeDocumentRevision.status == status,
            ).limit(1)) is not None

    async def resolve_evidence(self, ref: str) -> EvidenceRef | None:
        source_id, separator, chunk_id = ref.rpartition("#")
        if not separator:
            return None
        with self._session_factory() as db:
            chunk = db.scalar(select(KnowledgeChunk).where(
                KnowledgeChunk.source_id == source_id, KnowledgeChunk.chunk_id == chunk_id,
            ))
            if chunk is None:
                return None
            record = self._chunk_to_record(chunk)
            return EvidenceRef(**{key: getattr(record, key) for key in EvidenceRef.model_fields})

    def _current_chunks(self, protocol_version, status, *, model=None, source_ids=None):
        stmt = select(KnowledgeChunk).join(KnowledgeDocumentRevision,
            KnowledgeChunk.document_revision_id == KnowledgeDocumentRevision.id).where(
                KnowledgeDocumentRevision.protocol_version == protocol_version,
                KnowledgeDocumentRevision.status == status,
                KnowledgeChunk.protocol_version == protocol_version,
                KnowledgeChunk.status == status,
            )
        if model is not None:
            stmt = stmt.where(KnowledgeChunk.model == model)
        if source_ids is not None:
            stmt = stmt.where(KnowledgeChunk.source_id.in_(source_ids))
        with self._session_factory() as db:
            rows = db.scalars(stmt.order_by(KnowledgeChunk.source_id, KnowledgeChunk.chunk_index)).all()
            return current_chunks([self._chunk_to_record(row) for row in rows])

    async def list_entries(
        self,
        *,
        model: str | None = None,
        protocol_version: str,
        status: str = "validated",
        language: str = "en",
    ) -> list[KnowledgeEntry]:
        return document_directory(self._current_chunks(protocol_version, status, model=model), language)

    async def read_entries(
        self,
        source_ids: list[str],
        *,
        protocol_version: str,
        status: str = "validated",
    ) -> list[ChunkRecord]:
        return self._current_chunks(protocol_version, status, source_ids=source_ids)
