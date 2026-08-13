"""Canonical byte identities shared by Metrics v2 contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Final

from pydantic import BaseModel

from quantverify.core.exceptions import QuantVerifyError

MAX_V2_DECIMAL_DIGITS: Final = 64
MAX_V2_DECIMAL_ADJUSTED_EXPONENT: Final = 1000
MAX_V2_CANONICAL_BYTES: Final = 32 * 1024 * 1024


class MetricV2ContractError(QuantVerifyError):
    """A Metrics v2 factory, identity, or calculation boundary rejected its input."""


def require_v2_decimal(value: Decimal) -> Decimal:
    """Validate the bounded, finite Decimal domain accepted by v2 evidence."""

    if not value.is_finite():
        raise ValueError("Metrics v2 Decimal must be finite")
    parts = value.as_tuple()
    if len(parts.digits) > MAX_V2_DECIMAL_DIGITS:
        raise ValueError("Metrics v2 Decimal exceeds the coefficient digit limit")
    if value and abs(value.adjusted()) > MAX_V2_DECIMAL_ADJUSTED_EXPONENT:
        raise ValueError("Metrics v2 Decimal exceeds the adjusted exponent limit")
    return value


def decimal_value_v1(value: Decimal) -> dict[str, str | int]:
    """Return the context-independent ``decimal-value-v1`` payload."""

    require_v2_decimal(value)
    if not value:
        return {"coefficient": "0", "exponent": 0}
    parts = value.as_tuple()
    digits = list(parts.digits)
    exponent = int(parts.exponent)
    while digits[-1] == 0:
        digits.pop()
        exponent += 1
    coefficient = "".join(str(item) for item in digits)
    if parts.sign:
        coefficient = f"-{coefficient}"
    return {"coefficient": coefficient, "exponent": exponent}


def canonicalize_v2(value: Any) -> Any:
    """Convert supported v2 values into the accepted JSON wire profile."""

    if isinstance(value, BaseModel):
        return canonicalize_v2(value.model_dump(mode="python", exclude_none=False))
    if isinstance(value, Mapping):
        if not all(type(key) is str for key in value):
            raise TypeError("canonical v2 mappings require string keys")
        return {key: canonicalize_v2(value[key]) for key in sorted(value)}
    if isinstance(value, (set, frozenset)):
        raise TypeError("canonical v2 payloads do not accept unordered collections")
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [canonicalize_v2(item) for item in value]
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("canonical v2 datetimes must be timezone-aware")
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, Decimal):
        return decimal_value_v1(value)
    if isinstance(value, Enum):
        return canonicalize_v2(value.value)
    if isinstance(value, float):
        raise TypeError("canonical v2 payloads do not accept floats")
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    raise TypeError(f"unsupported canonical v2 value: {type(value).__name__}")


def canonical_v2_bytes(value: Any) -> bytes:
    """Serialize one v2 root object using the accepted canonical JSON profile."""

    failed = False
    encoded = b""
    try:
        from quantverify.metrics.v2_models import MetricInputV2, MetricSetV2

        if not isinstance(value, (MetricInputV2, MetricSetV2)):
            raise TypeError("canonical v2 root type is not supported")
        if isinstance(value, MetricInputV2):
            value._require_immutable_sequences()
        value = type(value).model_validate(value.model_dump(mode="python"))
        payload = canonicalize_v2(value)
        if not isinstance(payload, dict):
            raise TypeError("canonical v2 root must be an object")
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > MAX_V2_CANONICAL_BYTES:
            raise ValueError("canonical v2 payload exceeds the byte limit")
    except (AttributeError, TypeError, UnicodeEncodeError, ValueError):
        failed = True
    if failed:
        raise MetricV2ContractError(
            "Metrics v2 canonical serialization failed integrity validation"
        ) from None
    return encoded


def v2_content_hash(value: Any) -> str:
    """Return full SHA-256 over canonical v2 bytes."""

    return hashlib.sha256(canonical_v2_bytes(value)).hexdigest()
