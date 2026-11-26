"""Registry of reviewed task methodology, loaded by name through read_skill."""
from __future__ import annotations

import logging
from pathlib import Path

from backend.agent.skills.loader import load_all_skills
from backend.agent.skills.schemas import SkillIntent, SkillRecord, SkillStatus

logger = logging.getLogger("backend-skills")

# Precedence: higher index = higher priority
_INTENT_PRECEDENCE: dict[SkillIntent, int] = {
    "help": 0,
    "preparation": 1,
    "metrics": 1,
    "planning": 0,
    "results": 1,
    "failure": 2,
}

# Only these reviewed names may supply guidance for each intent.
_SKILL_INTENTS: dict[str, SkillIntent] = {
    "platform-help": "help",
    "context-preparation": "preparation",
    "metric-selection": "metrics",
    "generation-planning": "planning",
    "tarpass-analysis": "results",
    "failure-triage": "failure",
}

MAX_SKILLS_PER_REQUEST = 1
MAX_SKILLS_FOR_MULTI_INTENT = 2


class SkillRegistry:
    """Holds loaded skills and provides deterministic selection."""

    def __init__(self, records: list[SkillRecord]) -> None:
        self._records = records
        self._by_name: dict[str, SkillRecord] = {}
        self._by_intent: dict[SkillIntent, list[SkillRecord]] = {
            intent: [] for intent in _INTENT_PRECEDENCE
        }
        for record in records:
            self._by_name[record.metadata.name] = record
            intent = _SKILL_INTENTS.get(record.metadata.name)
            if record.metadata.status == "validated" and record.metadata.applies_to == [intent]:
                self._by_intent[intent].append(record)
            else:
                logger.warning("SKILL_UNAVAILABLE: Unregistered name, intent or status: %s", record.metadata.name)

    @classmethod
    def from_directory(
        cls,
        skills_root: Path,
        *,
        allowed_statuses: tuple[SkillStatus, ...] = ("validated",),
    ) -> SkillRegistry:
        """Load skills from the skills root directory and build a registry."""
        records = load_all_skills(skills_root, allowed_statuses=allowed_statuses)
        logger.info("Loaded %d skill(s): %s", len(records), [r.metadata.name for r in records])
        return cls(records)

    @property
    def all_skills(self) -> list[SkillRecord]:
        return list(self._records)

    def get_by_name(self, name: str) -> SkillRecord | None:
        return self._by_name.get(name)

    def select(
        self,
        *,
        intents: list[SkillIntent] | None = None,
        max_skills: int = MAX_SKILLS_PER_REQUEST,
    ) -> list[SkillRecord]:
        """Select skills for the given intents, respecting precedence.

        Args:
            intents: List of detected intents. If None or empty, returns [].
            max_skills: Maximum number of skills to return.

        Returns:
            List of SkillRecords sorted by precedence (highest first).
        """
        if not intents or max_skills <= 0:
            return []
        max_skills = min(max_skills, MAX_SKILLS_FOR_MULTI_INTENT)

        # Deduplicate while preserving order
        seen_intents: set[SkillIntent] = set()
        unique_intents: list[SkillIntent] = []
        for intent in intents:
            if intent not in seen_intents:
                seen_intents.add(intent)
                unique_intents.append(intent)

        # Sort by precedence (highest first)
        unique_intents.sort(key=lambda i: _INTENT_PRECEDENCE.get(i, 0), reverse=True)

        # Collect skills for each intent, deduplicating by name
        selected: list[SkillRecord] = []
        seen_names: set[str] = set()
        for intent in unique_intents:
            for record in self._by_intent.get(intent, []):
                if record.metadata.name not in seen_names:
                    seen_names.add(record.metadata.name)
                    selected.append(record)
                    if len(selected) >= max_skills:
                        return selected

        return selected
