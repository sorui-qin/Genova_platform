"""Heading-aware Markdown chunker + idempotent ingestion logic.

Chunking strategy:
  1. Parse lines tracking heading hierarchy (# … ######)
  2. Split sections at paragraph boundaries (double newline)
  3. Never split inside fenced code blocks (```…```)
  4. Merge tiny paragraphs (< MIN_CHUNK_SIZE) with their predecessor
  5. Force-split oversized paragraphs at MAX_CHUNK_SIZE boundary

Chunk IDs are deterministic for the same (source_id, section_index, content_hash).

P4.5: KnowledgeStore now preserves revision history.
Multiple DocumentRecords can coexist for the same source_id with different
content_hash values.  Old chunks are never deleted when a new revision is
ingested.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from backend.agent.knowledge.schemas import (
    ChunkRecord,
    DocumentMetadata,
    DocumentRecord,
    IngestionResult,
)
from backend.agent.knowledge.utils import compute_content_hash, make_chunk_id

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

MAX_CHUNK_SIZE = 2000  # characters
MIN_CHUNK_SIZE = 80   # characters — merge smaller blocks with predecessor


# ---------------------------------------------------------------------------
# Heading parser
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _opening_fence(line: str) -> str | None:
    match = _FENCE_RE.match(line)
    return match.group(1) if match else None


def _closes_fence(line: str, fence: str) -> bool:
    stripped = line.strip()
    return len(stripped) >= len(fence) and set(stripped) == {fence[0]}


def _parse_heading(line: str) -> tuple[int, str] | None:
    """Return (level, title) if *line* is a Markdown heading, else None."""
    m = _HEADING_RE.match(line.strip())
    if m:
        return len(m.group(1)), m.group(2).strip()
    return None


# ---------------------------------------------------------------------------
# Paragraph grouper
# ---------------------------------------------------------------------------

def _group_paragraphs(lines: list[str]) -> list[list[str]]:
    """Group lines into paragraphs separated by blank lines.

    Fenced code blocks (```…```) are kept as a single paragraph.
    """
    paragraphs: list[list[str]] = []
    current: list[str] = []
    fence: str | None = None

    for line in lines:
        stripped = line.strip()
        if fence is not None:
            current.append(line)
            if _closes_fence(line, fence):
                paragraphs.append(current)
                current = []
                fence = None
        elif (opening := _opening_fence(line)) is not None:
            if current:
                paragraphs.append(current)
                current = []
            current.append(line)
            fence = opening
        elif stripped == "":
            if current:
                paragraphs.append(current)
                current = []
        else:
            current.append(line)

    if current:
        paragraphs.append(current)
    return paragraphs


# ---------------------------------------------------------------------------
# Chunk builder
# ---------------------------------------------------------------------------

def _build_chunks(
    sections: list[tuple[list[str], list[str]]],  # (heading_path, lines)
    source_id: str,
    content_hash: str,
    revision_id: str,
) -> list[ChunkRecord]:
    """Build ChunkRecords from parsed sections."""
    chunks: list[ChunkRecord] = []
    now = datetime.now(timezone.utc)
    section_index = 0

    for heading_path, lines in sections:
        paragraphs = _group_paragraphs(lines)

        # Merge tiny paragraphs and split oversized ones
        merged: list[str] = []
        for para_lines in paragraphs:
            text = "\n".join(para_lines)
            if _opening_fence(para_lines[0]) is not None:
                # Code is atomic even when it exceeds the prose size target.
                merged.append(text)
            elif merged and len(text) < MIN_CHUNK_SIZE:
                # Merge with previous
                merged[-1] += "\n\n" + text
            elif len(text) > MAX_CHUNK_SIZE:
                # Force split at line boundaries
                if merged:
                    merged.append("")  # separator
                # Split roughly at MAX_CHUNK_SIZE
                buf = ""
                for pline in para_lines:
                    if buf and len(buf) + len(pline) + 1 > MAX_CHUNK_SIZE:
                        merged.append(buf)
                        buf = pline
                    else:
                        buf = buf + "\n" + pline if buf else pline
                if buf:
                    merged.append(buf)
            else:
                merged.append(text)

        # Build one chunk per merged paragraph (or one if section is tiny)
        if not merged:
            section_index += 1
            continue

        # If the whole section fits in one chunk, keep it together
        full_text = "\n\n".join(merged)
        if len(full_text) <= MAX_CHUNK_SIZE:
            chunk_id = make_chunk_id(source_id, section_index, content_hash)
            section_name = heading_path[-1] if heading_path else "(root)"
            chunks.append(ChunkRecord(
                chunk_id=chunk_id,
                revision_id=revision_id,
                source_id=source_id,
                content_hash=content_hash,
                content=full_text.strip(),
                section=section_name,
                heading_path=list(heading_path),
                model="common",  # overridden by caller
                document_type="overview",  # overridden by caller
                protocol_version="",  # overridden by caller
                status="validated",  # overridden by caller
                updated_at=now,
            ))
            section_index += 1
        else:
            for i, text in enumerate(merged):
                if not text.strip():
                    continue
                chunk_id = make_chunk_id(source_id, section_index + i, content_hash)
                section_name = heading_path[-1] if heading_path else "(root)"
                chunks.append(ChunkRecord(
                    chunk_id=chunk_id,
                    revision_id=revision_id,
                    source_id=source_id,
                    content_hash=content_hash,
                    content=text.strip(),
                    section=section_name,
                    heading_path=list(heading_path),
                    model="common",
                    document_type="overview",
                    protocol_version="",
                    status="validated",
                    updated_at=now,
                ))
            section_index += len(merged)

    return chunks


# ---------------------------------------------------------------------------
# Top-level chunker
# ---------------------------------------------------------------------------

def chunk_markdown(
    content: str,
    source_id: str,
    content_hash: str,
    revision_id: str,
) -> list[ChunkRecord]:
    """Split *content* into heading-aware Markdown chunks.

    Returns ChunkRecords with placeholder model/document_type/status —
    the caller patches those from DocumentMetadata.
    """
    lines = content.split("\n")
    sections: list[tuple[list[str], list[str]]] = []
    heading_path: list[str] = []
    current_lines: list[str] = []
    headings: list[tuple[int, str]] = []
    fence: str | None = None

    for line in lines:
        if fence is not None:
            current_lines.append(line)
            if _closes_fence(line, fence):
                fence = None
            continue
        if (opening := _opening_fence(line)) is not None:
            fence = opening
            current_lines.append(line)
            continue
        parsed = _parse_heading(line)
        if parsed is not None:
            level, title = parsed
            # Flush current section
            if current_lines:
                sections.append((list(heading_path), current_lines))
                current_lines = []

            # Update heading hierarchy
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, title))
            heading_path = [title for _, title in headings]
        current_lines.append(line)

    # Flush last section
    if current_lines:
        sections.append((list(heading_path), current_lines))

    return _build_chunks(sections, source_id, content_hash, revision_id)


# ---------------------------------------------------------------------------
# Store — revision-aware in-memory storage
# ---------------------------------------------------------------------------

class KnowledgeStore:
    """In-memory document + chunk store with revision history.

    Multiple revisions of the same source_id coexist.
    Old chunks are never deleted when a new revision is ingested.

    Production implementations can back this with PostgreSQL while keeping
    the same logical interface.
    """

    def __init__(self) -> None:
        # revision_id → DocumentRecord
        self._documents: dict[str, DocumentRecord] = {}
        # (source_id, content_hash) → revision_id (for idempotency check)
        self._revision_index: dict[tuple[str, str], str] = {}
        # chunk_id → ChunkRecord
        self._chunks: dict[str, ChunkRecord] = {}

    # -- writers ---------------------------------------------------------------

    def insert_revision(self, doc: DocumentRecord) -> bool:
        """Insert a new document revision.  Returns True if this is a new
        (source_id, content_hash) combination; False if idempotent repeat."""
        key = (doc.source_id, doc.content_hash)
        if key in self._revision_index:
            return False
        self._documents[doc.revision_id] = doc
        self._revision_index[key] = doc.revision_id
        return True

    def add_chunks(self, chunks: list[ChunkRecord]) -> None:
        for chunk in chunks:
            self._chunks[chunk.chunk_id] = chunk

    def has_hash(self, source_id: str, content_hash: str) -> bool:
        return (source_id, content_hash) in self._revision_index

    # -- readers ---------------------------------------------------------------

    def has_protocol_version(self, protocol_version: str, *, status: str = "validated") -> bool:
        return any(doc.protocol_version == protocol_version and doc.status == status
                   for doc in self._documents.values())

    def get_chunk(self, chunk_id: str) -> ChunkRecord | None:
        return self._chunks.get(chunk_id)

    def get_chunks(
        self,
        *,
        model: str | None = None,
        document_type: str | None = None,
        protocol_version: str | None = None,
        status: str | None = None,
    ) -> list[ChunkRecord]:
        """Return all chunks matching the metadata filters."""
        result: list[ChunkRecord] = []
        for chunk in self._chunks.values():
            if model is not None and chunk.model != model:
                continue
            if document_type is not None and chunk.document_type != document_type:
                continue
            if protocol_version is not None and chunk.protocol_version != protocol_version:
                continue
            if status is not None and chunk.status != status:
                continue
            result.append(chunk)
        return result

    def get_revision(self, revision_id: str) -> DocumentRecord | None:
        return self._documents.get(revision_id)

    def get_revisions_for_source(self, source_id: str) -> list[DocumentRecord]:
        """All revisions for a given source_id, ordered by created_at."""
        revs = [d for d in self._documents.values() if d.source_id == source_id]
        revs.sort(key=lambda d: d.created_at)
        return revs

    def document_count(self) -> int:
        return len(self._documents)

    def chunk_count(self) -> int:
        return len(self._chunks)
