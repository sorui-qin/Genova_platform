"""Current document directories and exact source selection for Agent tools."""
from __future__ import annotations

from backend.agent.knowledge.help_catalog import is_current_help_revision, load_catalog
from backend.agent.knowledge.schemas import ChunkRecord, KnowledgeEntry

MAX_RETRIEVED_CONTEXT_CHARS = 12000


def current_chunks(chunks: list[ChunkRecord]) -> list[ChunkRecord]:
    latest = {}
    eligible = [chunk for chunk in chunks if is_current_help_revision(chunk.source_id, chunk.content_hash)]
    for chunk in eligible:
        revision = (chunk.updated_at, chunk.revision_id)
        latest[chunk.source_id] = max(latest.get(chunk.source_id, revision), revision)
    return [chunk for chunk in eligible
            if (chunk.updated_at, chunk.revision_id) == latest[chunk.source_id]]


def document_directory(chunks: list[ChunkRecord], language: str) -> list[KnowledgeEntry]:
    help_entries = {f"help-{entry['id']}-{lang}": (entry, lang, text)
                    for entry in load_catalog()['entries']
                    for lang, text in entry['translations'].items()}
    preferred = 'zh-CN' if language == 'zh' else 'en-US'
    first_chunks = {}
    for chunk in chunks:
        first_chunks.setdefault(chunk.source_id, chunk)
    entries = []
    for source_id, chunk in sorted(first_chunks.items()):
        help_entry = help_entries.get(source_id)
        if help_entry:
            entry, lang, text = help_entry
            if lang != preferred and f"help-{entry['id']}-{preferred}" in first_chunks:
                continue
            title, summary, fields = text['title'], text['summary'], entry['keys']
        else:
            title = chunk.heading_path[0] if chunk.heading_path else chunk.section
            summary = next((line.strip() for line in chunk.content.splitlines()
                            if line.strip() and not line.lstrip().startswith('#')), '')[:200]
            fields = []
        entries.append(KnowledgeEntry(source_id=source_id, model=chunk.model,
            title=title, summary=summary, fields=fields))
    return entries
