"""Validate prompt text; research_safety assesses meaning in context."""
from __future__ import annotations

import unicodedata


class PromptBlocked(ValueError):
    def __init__(self, category: str, reason: str) -> None:
        super().__init__(reason)
        self.category = category
        self.reason = reason


def inspection_text(value: str) -> str:
    checked = unicodedata.normalize("NFKC", value)
    checked = "".join(ch for ch in checked if unicodedata.category(ch) != "Cf")
    return ' '.join(checked.split())


def normalize_and_check_prompt(value: str) -> str:
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        raise PromptBlocked('invalid_input', 'The request contains invalid Unicode text.') from None
    if not inspection_text(value):
        raise PromptBlocked("invalid_input", "A non-empty molecular workflow request is required.")
    # Preserve user evidence and identifiers. Keyword matches cannot establish intent.
    return value.strip()
