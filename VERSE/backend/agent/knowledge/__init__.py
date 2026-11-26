"""Generation Protocol RAG 鈥?knowledge retrieval for the Genova agent.

Public API:
    KnowledgeProvider 鈥?abstract interface for retrieval
    InMemoryKnowledgeProvider 鈥?test/dev in-memory implementation
    PostgresKnowledgeProvider 鈥?production PostgreSQL-backed implementation
    IngestionService 鈥?idempotent document ingestion with heading-aware chunking
    DocumentMetadata, ChunkRecord, EvidenceRef, KnowledgeEntry 鈥?schemas

The KnowledgeProvider is injected via AgentDeps and used for on-demand document
reading.  It is NOT a permission layer, validation layer, or execution layer.
All hard rules (ownership, approval, metric whitelists, capability gating) remain
in backend code and cannot be overridden by RAG content.
"""
from backend.agent.knowledge.base import KnowledgeProvider
from backend.agent.knowledge.provider import InMemoryKnowledgeProvider
from backend.agent.knowledge.schemas import (
    ChunkRecord,
    DocumentMetadata,
    DocumentRecord,
    DocumentStatus,
    DocumentType,
    EvidenceRef,
    IngestionResult,
    ModelName,
    KnowledgeEntry,
)

# PostgresKnowledgeProvider is imported lazily in the router to avoid
# importing sqlalchemy models at module level.

__all__ = [
    "ChunkRecord",
    "DocumentMetadata",
    "DocumentRecord",
    "DocumentStatus",
    "DocumentType",
    "EvidenceRef",
    "InMemoryKnowledgeProvider",
    "IngestionResult",
    "KnowledgeProvider",
    "ModelName",
    "KnowledgeEntry",
]
