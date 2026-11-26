"""Abstract KnowledgeProvider interface.

Backend code depends only on this interface; concrete implementations
(in-memory, PostgreSQL, vector store) are injected at construction time.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from backend.agent.knowledge.schemas import (
    DocumentMetadata,
    ChunkRecord,
    EvidenceRef,
    IngestionResult,
    KnowledgeEntry,
)


class KnowledgeProvider(ABC):
    """Protocol-document retrieval abstraction.

    Retrieve validated protocol knowledge for the agent.
    The provider never enforces ownership, approval, or capability gating —
    those remain in backend code.
    """

    @abstractmethod
    async def ingest(self, content: str, metadata: DocumentMetadata) -> IngestionResult:
        """Ingest a document.  Idempotent for the same source_id + content_hash."""
        ...

    @abstractmethod
    async def has_protocol_version(self, protocol_version: str, *, status: str = "validated") -> bool:
        """Check document metadata independently of lexical query matches."""
        ...

    @abstractmethod
    async def resolve_evidence(self, ref: str) -> EvidenceRef | None:
        """Resolve a stored source_id#chunk_id to its exact historical revision."""
        ...

    @abstractmethod
    async def list_entries(
        self,
        *,
        model: str | None = None,
        protocol_version: str,
        status: str = "validated",
        language: str = "en",
    ) -> list[KnowledgeEntry]:
        """List current document titles and summaries for semantic selection."""
        ...

    @abstractmethod
    async def read_entries(
        self,
        source_ids: list[str],
        *,
        protocol_version: str,
        status: str = "validated",
    ) -> list[ChunkRecord]:
        """Read exact source IDs from the requested version and review status."""
        ...
