"""Full SHA-256 identities for scientific quality-evaluation inputs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date
from typing import Any

from quantverify.core.identity import canonicalize
from quantverify.data.models import NormalizedBar


def full_content_hash(value: Any) -> str:
    """Return the full SHA-256 digest of deterministic canonical JSON."""

    payload = json.dumps(
        canonicalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def normalized_bars_hash(bars: Sequence[NormalizedBar]) -> str:
    """Hash complete normalized bars independent of caller-provided ordering."""

    canonical_bars = [canonicalize(bar) for bar in bars]
    canonical_bars.sort(
        key=lambda value: json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return full_content_hash(canonical_bars)


def expected_sessions_hash(calendar_id: str, sessions: Sequence[date]) -> str:
    """Hash the exact de-duplicated session set supplied to the evaluator."""

    ordered = tuple(sorted(set(sessions)))
    return full_content_hash(
        {
            "calendar_id": calendar_id,
            "sessions": ordered,
        }
    )
