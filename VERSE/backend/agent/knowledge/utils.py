"""Stable content hashes and document chunk identifiers."""
from __future__ import annotations

import hashlib


# ---------------------------------------------------------------------------
# Content hashing
# ---------------------------------------------------------------------------

def compute_content_hash(content: str) -> str:
    """SHA-256 of the normalised content (stripped, CRLF → LF)."""
    normalised = content.strip().replace("\r\n", "\n")
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Deterministic chunk ID
# ---------------------------------------------------------------------------

def make_chunk_id(source_id: str, section_index: int, content_hash: str) -> str:
    """Deterministic 16-hex-char chunk identifier.

    Same (source_id, section_index, content_hash) always yields the same ID.
    """
    seed = f"{source_id}:{section_index}:{content_hash[:16]}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
