"""Canonical JSON and content hashes.

Every hash in evalgate goes through `content_hash`, so the same logical value always
produces the same digest regardless of key order or platform.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    """Serialize with sorted keys, no extra whitespace, and real Unicode (not \\u escapes)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(value: Any) -> str:
    """sha256 of the canonical JSON form, as hex."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
