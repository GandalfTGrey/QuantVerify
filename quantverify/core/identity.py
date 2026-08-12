"""Canonical serialization and content-addressed identity helpers."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def canonicalize(value: Any) -> Any:
    """Convert supported values into a deterministic JSON-compatible structure."""
    if isinstance(value, BaseModel):
        return canonicalize(value.model_dump(mode="python", exclude_none=False))
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("Canonical mappings must use string keys")
        return {key: canonicalize(value[key]) for key in sorted(value)}
    if isinstance(value, (set, frozenset)):
        canonical_items = [canonicalize(item) for item in value]
        return sorted(canonical_items, key=_canonical_json)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [canonicalize(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Canonical identity cannot contain a non-finite Decimal")
        return format(value, "f")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Canonical identity cannot contain a non-finite float")
        return value
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    raise TypeError(f"Unsupported canonical identity value: {type(value).__name__}")


def stable_hash(value: Any, *, namespace: str, length: int = 24) -> str:
    """Return a namespaced, stable SHA-256 identifier for a domain value."""
    if not namespace or not namespace.strip():
        raise ValueError("namespace must not be blank")
    if length < 12 or length > 64:
        raise ValueError("length must be between 12 and 64")
    payload = f"{namespace}\n{_canonical_json(canonicalize(value))}".encode()
    digest = hashlib.sha256(payload).hexdigest()[:length]
    return f"{namespace}_{digest}"


def full_hash(value: Any) -> str:
    """Return a full SHA-256 over the canonical representation of a value."""
    return hashlib.sha256(_canonical_json(canonicalize(value)).encode()).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
