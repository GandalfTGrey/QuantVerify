"""Full SHA-256 identities for scientific quality-evaluation inputs."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from datetime import UTC, date
from decimal import Decimal
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
    """Hash complete evaluated rows in their supplied scientific sequence."""

    canonical_bars = [_quality_bar_payload(bar) for bar in bars]
    return full_content_hash(canonical_bars)


def _quality_bar_payload(bar: NormalizedBar) -> dict[str, Any]:
    return {
        "asset": canonicalize(bar.asset),
        "session": canonicalize(bar.session),
        "session_open_at": canonicalize(bar.session_open_at.astimezone(UTC)),
        "session_close_at": canonicalize(bar.session_close_at.astimezone(UTC)),
        "available_at": canonicalize(bar.available_at.astimezone(UTC)),
        "open": _quality_number(bar.open),
        "high": _quality_number(bar.high),
        "low": _quality_number(bar.low),
        "close": _quality_number(bar.close),
        "volume": _quality_number(bar.volume),
        "source": canonicalize(bar.source),
    }


def _quality_number(value: Any) -> Any:
    if isinstance(value, Decimal) and not value.is_finite():
        return {"non_finite_decimal": str(value)}
    if isinstance(value, Decimal):
        return format(Decimal(0) if value == 0 else value.normalize(), "f")
    if isinstance(value, float) and not math.isfinite(value):
        return {"non_finite_float": str(value)}
    return canonicalize(value)


def expected_sessions_hash(calendar_id: str, sessions: Sequence[date]) -> str:
    """Hash the exact de-duplicated session set supplied to the evaluator."""

    ordered = tuple(sorted(set(sessions)))
    return full_content_hash(
        {
            "calendar_id": calendar_id,
            "sessions": ordered,
        }
    )
