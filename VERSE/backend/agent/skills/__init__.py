"""Skills layer -versioned behavior guidance for the Genova agent.

Skills are HOW-TO guides for specific task types.  They do not add tools,
override backend rules, bypass approval/ownership, or supply protocol evidence.

Public API:
    SkillRegistry -holds loaded skills, provides deterministic selection
    SkillRecord -a loaded skill with metadata and content
    SkillMetadata -frontmatter schema
    SkillStatus, SkillIntent -constrained type aliases
    load_all_skills -load skills from a directory
"""
from backend.agent.skills.loader import load_all_skills
from backend.agent.skills.registry import SkillRegistry
from backend.agent.skills.schemas import SkillIntent, SkillMetadata, SkillRecord, SkillStatus

__all__ = [
    "SkillIntent",
    "SkillMetadata",
    "SkillRecord",
    "SkillRegistry",
    "SkillStatus",
    "load_all_skills",
]
