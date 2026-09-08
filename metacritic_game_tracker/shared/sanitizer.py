"""Output Sanitizer: маскирование секретов перед отправкой в веб-интерфейс."""
from __future__ import annotations

import re

_MASK = "***"

_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{20,}", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}", re.IGNORECASE),
    re.compile(r"glpat-[A-Za-z0-9_\-]{10,}", re.IGNORECASE),
    re.compile(r"AIza[A-Za-z0-9_\-]{20,}", re.IGNORECASE),  # Google/YouTube API key
]


def mask_secrets(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(_MASK, text)
    return text
