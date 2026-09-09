"""Locate and resolve Metacritic's embedded Nuxt SSR state payload (research.md §9).

The page ships a `<script id="__NUXT_DATA__">` tag containing a flat JSON array.
Every element is either a leaf primitive or a container (dict/list) whose member
values are integers indexing back into the same array — a devalue-style flattened
serialization, not a ready-made object. `resolve()` walks it back into a normal
nested structure.
"""
from __future__ import annotations

import json
import re
from typing import Any

_NUXT_DATA_RE = re.compile(
    r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)

# Vue reactivity wrappers show up as a 2-element list `[tag, target_index]`;
# the real value is at the target, not the tag string.
_REACTIVE_TAGS = {"ShallowReactive", "Reactive", "Ref", "ShallowRef"}


class PayloadNotFoundError(Exception):
    """Raised when the page has no `__NUXT_DATA__` script — likely a markup change."""


def extract_payload_array(html: str) -> list[Any]:
    match = _NUXT_DATA_RE.search(html)
    if match is None:
        raise PayloadNotFoundError("No __NUXT_DATA__ script tag found in page")
    return json.loads(match.group(1))


def resolve(data: list[Any], index: int, _depth: int = 0, _max_depth: int = 12) -> Any:
    if _depth > _max_depth:
        return None
    raw = data[index]
    if isinstance(raw, list):
        if len(raw) == 2 and raw[0] in _REACTIVE_TAGS and isinstance(raw[1], int):
            return resolve(data, raw[1], _depth, _max_depth)
        return [
            resolve(data, v, _depth + 1, _max_depth) if isinstance(v, int) else v
            for v in raw
        ]
    if isinstance(raw, dict):
        return {
            k: (resolve(data, v, _depth + 1, _max_depth) if isinstance(v, int) else v)
            for k, v in raw.items()
        }
    return raw
