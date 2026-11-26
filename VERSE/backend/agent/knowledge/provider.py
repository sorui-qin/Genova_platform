"""In-memory KnowledgeProvider — test / development implementation.

P4.5: Revision-aware ingestion.  Multiple revisions of the same source_id
coexist.  Old chunks are never deleted.  Production uses PostgresKnowledgeProvider.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from backend.agent.knowledge.base import KnowledgeProvider
from backend.agent.knowledge.ingestion import KnowledgeStore, chunk_markdown
from backend.agent.knowledge.retrieval import current_chunks, document_directory
from backend.agent.knowledge.schemas import (
    DocumentMetadata,
    ChunkRecord,
    DocumentRecord,
    EvidenceRef,
    IngestionResult,
    KnowledgeEntry,
)
from backend.agent.knowledge.utils import compute_content_hash


class InMemoryKnowledgeProvider(KnowledgeProvider):
    """KnowledgeProvider backed by an in-memory store with revision history.

    Thread-safety: not guaranteed — use a single instance per process or
    add locking if shared across threads.
    """

    def __init__(self, store: KnowledgeStore | None = None) -> None:
        self._store = store or KnowledgeStore()

    # -- ingestion ------------------------------------------------------------

    async def ingest(self, content: str, metadata: DocumentMetadata) -> IngestionResult:
        """Ingest a Markdown document.  Idempotent for same source_id + content_hash.

        New content_hash creates a new revision; old revisions are preserved.
        """
        content_hash = compute_content_hash(content)

        # Idempotency check
        if self._store.has_hash(metadata.source_id, content_hash):
            # Find the existing revision_id
            revs = self._store.get_revisions_for_source(metadata.source_id)
            existing_rev = next((r for r in revs if r.content_hash == content_hash), None)
            return IngestionResult(
                source_id=metadata.source_id,
                content_hash=content_hash,
                revision_id=existing_rev.revision_id if existing_rev else "",
                chunk_count=0,
                is_new=False,
            )

        # Generate a stable revision_id from source_id + content_hash
        revision_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"knowledge:{metadata.source_id}:{content_hash}"))

        # Chunk
        raw_chunks = chunk_markdown(content, metadata.source_id, content_hash, revision_id)

        # Patch metadata onto each chunk
        now = metadata.updated_at or datetime.now(timezone.utc)
        patched = []
        for chunk in raw_chunks:
            chunk.model = metadata.model
            chunk.document_type = metadata.document_type
            chunk.protocol_version = metadata.protocol_version
            chunk.status = metadata.status
            chunk.updated_at = now
            patched.append(chunk)

        # Store — insert_revision does NOT delete old revisions
        doc = DocumentRecord(
            revision_id=revision_id,
            source_id=metadata.source_id,
            content_hash=content_hash,
            model=metadata.model,
            document_type=metadata.document_type,
            protocol_version=metadata.protocol_version,
            status=metadata.status,
            updated_at=now,
            created_at=now,
        )
        self._store.insert_revision(doc)
        self._store.add_chunks(patched)

        return IngestionResult(
            source_id=metadata.source_id,
            content_hash=content_hash,
            revision_id=revision_id,
            chunk_count=len(patched),
            is_new=True,
        )

    # -- retrieval ------------------------------------------------------------

    async def has_protocol_version(self, protocol_version: str, *, status: str = "validated") -> bool:
        return self._store.has_protocol_version(protocol_version, status=status)

    async def resolve_evidence(self, ref: str) -> EvidenceRef | None:
        source_id, separator, chunk_id = ref.rpartition("#")
        if not separator:
            return None
        chunk = self._store.get_chunk(chunk_id)
        if chunk is None or chunk.source_id != source_id:
            return None
        return EvidenceRef(**{key: getattr(chunk, key) for key in EvidenceRef.model_fields})

    def _current_chunks(self, protocol_version, status, *, model=None, source_ids=None):
        chunks = self._store.get_chunks(model=model, protocol_version=protocol_version, status=status)
        return current_chunks([chunk for chunk in chunks
            if (source_ids is None or chunk.source_id in source_ids)
            and self._store.get_revision(chunk.revision_id).status == status])

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

    # -- diagnostics ----------------------------------------------------------

    @property
    def store(self) -> KnowledgeStore:
        return self._store
