"""Input Guardrail: фильтр текста со стороны перед передачей в LLM (отзывы, транскрипты)."""
from __future__ import annotations

import re

_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"забудь.{0,20}инструкци", re.IGNORECASE),
    re.compile(r"ты теперь", re.IGNORECASE),
    re.compile(r"действуй как", re.IGNORECASE),
    re.compile(r"ignore.{0,10}(previous|prior|all).{0,10}instructions", re.IGNORECASE),
    re.compile(r"\bsystem\s*:", re.IGNORECASE),
    re.compile(r"\[INST\]", re.IGNORECASE),
    re.compile(r"\bact as\b", re.IGNORECASE),
]

_MAX_LENGTH = 20000


class GuardrailViolation(ValueError):
    pass


def sanitize_input(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text)
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(normalized):
            raise GuardrailViolation("Potential prompt injection detected")
    return text


def truncate_to_limit(text: str, limit: int = _MAX_LENGTH) -> str:
    return text[:limit] if len(text) > limit else text
