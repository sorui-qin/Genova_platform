"""Ingestion service — CLI and programmatic interface for loading documents.

Usage (CLI):
    python -m backend.agent.knowledge.ingestion_service \\
        --file path/to/protocol.md \\
        --source-id surfgen-protocol-v2 \\
        --model surfgen \\
        --document-type generation_protocol \\
        --protocol-version generation-2026-09 \\
        --status validated --backend postgres

Usage (programmatic):
    from backend.agent.knowledge.ingestion_service import ingest_protocol
    result = ingest_protocol(provider, "path/to/doc.md", metadata)

Fixtures are NEVER auto-loaded.  They exist only for tests.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from backend.agent.knowledge.base import KnowledgeProvider
from backend.agent.knowledge.schemas import DocumentMetadata, IngestionResult


def ingest_bundled_protocols(provider: KnowledgeProvider) -> None:
    """Install the versioned platform protocols shipped with this backend."""
    from backend.agent.catalog import PROTOCOL_VERSION

    bundled_version = "generation-2026-09"
    if PROTOCOL_VERSION != bundled_version:
        raise RuntimeError("BUNDLED_PROTOCOL_VERSION_MISMATCH: update the bundled documents with the catalog version")
    protocol_dir = Path(__file__).resolve().parent / "protocols"
    for filename, source_id, model, document_type in (
        ("platform_help_2026_09.md", "bundled-platform-help-2026-09", "common", "overview"),
        ("protein_preparation_2026_09.md", "bundled-protein-preparation-2026-09", "protein_preparation", "inputs"),
        ("ecloudgen_generation_2026_09.md", "bundled-ecloudgen-generation-2026-09", "ecloudgen", "generation_protocol"),
        ("epso_2026_09.md", "bundled-epso-2026-09", "epso", "parameters"),
        ("surfgen_generation_2026_09.md", "bundled-surfgen-generation-2026-09", "surfgen", "generation_protocol"),
        ("tarpass_interpretation_2026_09.md", "bundled-tarpass-interpretation-2026-09", "tarpass", "result_interpretation"),
    ):
        ingest_protocol(
            provider,
            protocol_dir / filename,
            DocumentMetadata(
                source_id=source_id,
                source_path=f"backend/agent/knowledge/protocols/{filename}",
                model=model,
                document_type=document_type,
                protocol_version=bundled_version,
                status="validated",
            ),
        )

    from backend.agent.knowledge.help_catalog import knowledge_documents

    for entry, language, content in knowledge_documents():
        asyncio.run(provider.ingest(content, DocumentMetadata(
            source_id=f"help-{entry['id']}-{language}",
            source_path=f"/help?article={entry['id']}&lang={language}",
            model=entry['model'],
            document_type='result_interpretation' if entry['group'] in {'properties', 'poses'} or entry['model'] == 'tarpass' else 'parameters' if entry['group'] == 'parameters' else 'overview',
            protocol_version=bundled_version,
            status='validated',
        )))


def ingest_protocol(
    provider: KnowledgeProvider,
    file_path: str | Path,
    metadata: DocumentMetadata,
) -> IngestionResult:
    """Ingest a Markdown document from a file path.

    Args:
        provider: KnowledgeProvider instance (in-memory or Postgres).
        file_path: Path to the Markdown document.
        metadata: Document metadata (source_id, model, etc. — content_hash
                  is computed automatically).

    Returns:
        IngestionResult with source_id, content_hash, revision_id, chunk_count, is_new.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Document not found: {path}")
    if not path.suffix.lower() in {".md", ".markdown", ".txt"}:
        raise ValueError(f"Unsupported file type: {path.suffix}. Use .md, .markdown, or .txt")

    content = path.read_text(encoding="utf-8")
    if not content.strip():
        raise ValueError(f"Document is empty: {path}")

    return asyncio.run(provider.ingest(content, metadata))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ingest a protocol document into the knowledge base.",
    )
    parser.add_argument("--file", required=True, help="Path to the Markdown document")
    parser.add_argument("--source-id", required=True, help="Unique source identifier")
    parser.add_argument("--source-path", default=None, help="Original file path (optional)")
    parser.add_argument(
        "--model",
        default="common",
        choices=["common", "surfgen", "delete", "ecloudgen", "tarpass", "epso", "protein_preparation"],
        help="Model this document relates to",
    )
    parser.add_argument(
        "--document-type",
        required=True,
        choices=["overview", "inputs", "outputs", "generation_protocol",
                 "parameters", "troubleshooting", "result_interpretation"],
        help="Type of document",
    )
    parser.add_argument("--protocol-version", required=True, help="Protocol version string")
    parser.add_argument(
        "--status",
        default="validated",
        choices=["validated", "draft", "deprecated"],
        help="Document status",
    )
    parser.add_argument(
        "--backend",
        default=None,
        choices=["memory", "postgres"],
        help="Storage backend (defaults to configured KNOWLEDGE_BACKEND)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for document ingestion."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    from backend.config import settings
    backend = args.backend or settings.knowledge_backend
    if backend == "none":
        parser.error("Ingestion requires a memory or postgres knowledge backend")
    if settings.environment in {"prod", "production"} and backend != "postgres":
        parser.error("Production ingestion requires the postgres knowledge backend")

    metadata = DocumentMetadata(
        source_id=args.source_id,
        source_path=args.source_path or args.file,
        model=args.model,
        document_type=args.document_type,
        protocol_version=args.protocol_version,
        status=args.status,
    )

    if backend == "memory":
        from backend.agent.knowledge.provider import InMemoryKnowledgeProvider
        provider = InMemoryKnowledgeProvider()
    elif backend == "postgres":
        from backend.db import SessionLocal
        from backend.agent.knowledge.postgres_provider import PostgresKnowledgeProvider
        provider = PostgresKnowledgeProvider(SessionLocal)
    else:
        parser.error(f"Unknown backend: {backend}")

    try:
        result = ingest_protocol(provider, args.file, metadata)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"source_id:      {result.source_id}")
    print(f"content_hash:   {result.content_hash}")
    print(f"revision_id:    {result.revision_id}")
    print(f"chunk_count:    {result.chunk_count}")
    print(f"is_new:         {result.is_new}")


if __name__ == "__main__":
    main()
