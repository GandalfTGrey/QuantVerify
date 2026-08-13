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

_MAX_FIXED_DECIMAL_CHARACTERS = 4096
MAX_QUALITY_DECIMAL_DIGITS = 64
MAX_QUALITY_DECIMAL_ADJUSTED_EXPONENT = 1000


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
        return canonical_decimal(require_quality_decimal_domain(value))
    if isinstance(value, float) and not math.isfinite(value):
        return {"non_finite_float": str(value)}
    return canonicalize(value)


def canonical_decimal(value: Decimal) -> str:
    """Return an exact, context-independent scientific identity for a Decimal."""

    if not value.is_finite():
        raise ValueError("scientific identity requires a finite Decimal")
    if value == 0:
        return "0"

    parts = value.as_tuple()
    digits = list(parts.digits)
    exponent = int(parts.exponent)
    while digits[-1] == 0:
        digits.pop()
        exponent += 1

    coefficient = "".join(str(digit) for digit in digits)
    sign = "-" if parts.sign else ""
    if exponent >= 0:
        fixed_length = len(sign) + len(coefficient) + exponent
    else:
        fixed_length = len(sign) + max(len(coefficient), 1 - exponent) + 1

    if fixed_length <= _MAX_FIXED_DECIMAL_CHARACTERS:
        if exponent >= 0:
            return f"{sign}{coefficient}{'0' * exponent}"
        split = len(coefficient) + exponent
        if split > 0:
            return f"{sign}{coefficient[:split]}.{coefficient[split:]}"
        return f"{sign}0.{'0' * -split}{coefficient}"

    adjusted_exponent = exponent + len(coefficient) - 1
    mantissa = coefficient[0]
    if len(coefficient) > 1:
        mantissa = f"{mantissa}.{coefficient[1:]}"
    return f"{sign}{mantissa}E{adjusted_exponent:+d}"


def require_quality_decimal_domain(value: Decimal) -> Decimal:
    """Reject finite values outside the bounded A3 normalized-number domain."""

    if not value.is_finite():
        raise ValueError("quality Decimal must be finite")
    parts = value.as_tuple()
    if len(parts.digits) > MAX_QUALITY_DECIMAL_DIGITS:
        raise ValueError("quality Decimal exceeds the coefficient digit limit")
    if value and abs(value.adjusted()) > MAX_QUALITY_DECIMAL_ADJUSTED_EXPONENT:
        raise ValueError("quality Decimal exceeds the adjusted exponent limit")
    return value


def expected_sessions_hash(calendar_id: str, sessions: Sequence[date]) -> str:
    """Hash the exact de-duplicated session set supplied to the evaluator."""

    ordered = tuple(sorted(set(sessions)))
    return full_content_hash(
        {
            "calendar_id": calendar_id,
            "sessions": ordered,
        }
    )
