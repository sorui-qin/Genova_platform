"""Deterministic Skill loader.

Reads SKILL.md files from a fixed directory under backend/agent/skills/.
Parses YAML frontmatter, validates with strict Pydantic schema, and
returns SkillRecords.

Safety:
  - Paths are resolved and must stay under the skills root directory.
  - No recursive scanning — only named subdirectories are checked.
  - No code execution — SKILL.md files are plain text.
  - Invalid files are logged and skipped (never crash the app).
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Sequence

from backend.agent.skills.schemas import SkillMetadata, SkillRecord, SkillStatus

logger = logging.getLogger("backend-skills")

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict[str, str | list[str]], str] | None:
    """Parse the supported flat frontmatter subset; reject ambiguous syntax.

    No YAML tags, aliases, nested objects, duplicate keys, or ignored lines.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None
    metadata: dict[str, str | list[str]] = {}
    current_key: str | None = None
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line[:1].isspace():
            if not stripped.startswith("- ") or current_key != "applies_to":
                return None
            values = metadata[current_key]
            if not isinstance(values, list):
                return None
            value = stripped[2:].strip()
        else:
            pair = re.fullmatch(r"([a-z_]+):[ \t]*(.*)", line)
            if not pair or pair[1] in metadata:
                return None
            current_key, value = pair[1], pair[2].strip()
            if not value:
                if current_key != "applies_to":
                    return None
                metadata[current_key] = []
                continue
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0] or value[0] in value[1:-1]:
                return None
            value = value[1:-1]
        elif any(char in value for char in "{}[]&*!|>'\""):
            return None
        if line[:1].isspace():
            values.append(value)
        else:
            metadata[current_key] = value
    return metadata, match.group(2).strip()


def _validate_path(file_path: Path, root: Path) -> bool:
    """Ensure file_path is under root after resolution."""
    try:
        resolved = file_path.resolve()
        root_resolved = root.resolve()
        # Check both Unix and Windows path separators
        return resolved == root_resolved or str(resolved).startswith(str(root_resolved) + "/") or str(resolved).startswith(str(root_resolved) + "\\")
    except (OSError, ValueError, RuntimeError):
        return False


def load_skill(file_path: Path, root: Path) -> SkillRecord | None:
    """Load a single SKILL.md file.

    Returns SkillRecord on success, None on any validation/parsing failure.
    """
    if file_path.name != "SKILL.md" or not _validate_path(file_path, root):
        logger.warning("Skill path rejected (not SKILL.md or outside root): %s", file_path)
        return None

    if not file_path.exists():
        logger.warning("SKILL_UNAVAILABLE: Skill file not found: %s", file_path)
        return None

    try:
        text = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        logger.warning("Cannot read skill file %s: %s", file_path, exc)
        return None

    parsed = _parse_frontmatter(text)
    if parsed is None:
        logger.warning("No valid frontmatter in %s", file_path)
        return None

    raw_meta, body = parsed

    # applies_to may be a YAML list or a single string
    applies_to = raw_meta.get("applies_to")
    if isinstance(applies_to, str):
        applies_to = [applies_to]
    if isinstance(applies_to, list):
        raw_meta["applies_to"] = applies_to

    try:
        metadata = SkillMetadata.model_validate(raw_meta)
    except Exception as exc:
        logger.warning("Invalid metadata in %s: %s", file_path, exc)
        return None

    if not body:
        logger.warning("Empty skill body in %s", file_path)
        return None

    return SkillRecord(
        metadata=metadata,
        content=body,
        content_hash=hashlib.sha256(body.encode()).hexdigest(),
        source_path=str(file_path),
    )


def load_all_skills(
    skills_root: Path,
    *,
    allowed_statuses: Sequence[SkillStatus] = ("validated",),
) -> list[SkillRecord]:
    """Load all valid skills from the skills root directory.

    Only loads SKILL.md files from immediate subdirectories of skills_root.
    Only loads skills whose status is in allowed_statuses.
    """
    try:
        skills_root = skills_root.resolve()
        subdirectories = sorted(skills_root.iterdir())
    except (OSError, ValueError, RuntimeError) as exc:
        logger.warning("SKILL_UNAVAILABLE: Cannot enumerate skills root %s: %s", skills_root, exc)
        return []

    records: list[SkillRecord] = []
    for sub in subdirectories:
        if not sub.is_dir():
            continue
        skill_file = sub / "SKILL.md"
        # Ignore auxiliary directories (for example tests) that do not provide a skill.
        # They are not registry candidates and should not generate production warnings.
        if not skill_file.exists():
            continue
        record = load_skill(skill_file, skills_root)
        if record is None:
            continue
        if record.metadata.status not in allowed_statuses:
            logger.debug(
                "Skipping skill %s (status=%s not in %s)",
                record.metadata.name,
                record.metadata.status,
                allowed_statuses,
            )
            continue
        records.append(record)

    return records
