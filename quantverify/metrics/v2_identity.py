"""Canonical byte identities shared by Metrics v2 contracts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any, Final, TypeVar

from pydantic import BaseModel, ValidationError

from quantverify.core.exceptions import QuantVerifyError

if TYPE_CHECKING:
    from quantverify.metrics.v2_models import MetricInputV2, MetricSetV2

MAX_V2_DECIMAL_DIGITS: Final = 64
MAX_V2_DECIMAL_ADJUSTED_EXPONENT: Final = 1000
MAX_V2_CANONICAL_BYTES: Final = 32 * 1024 * 1024
MAX_V2_JSON_NESTING: Final = 32
_CANONICAL_COEFFICIENT = re.compile(r"^-?(?:0|[1-9][0-9]*)$")
_V2Root = TypeVar("_V2Root", bound=BaseModel)


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


def parse_decimal_value_v1(value: Any) -> Decimal:
    """Accept a Decimal object or one exact ``decimal-value-v1`` wire object."""

    if type(value) is Decimal:
        return require_v2_decimal(value)
    if type(value) is not dict or set(value) != {"coefficient", "exponent"}:
        raise ValueError("Metrics v2 Decimal input is not canonical")
    coefficient = value["coefficient"]
    exponent = value["exponent"]
    if type(coefficient) is not str or type(exponent) is not int:
        raise ValueError("Metrics v2 Decimal input is not canonical")
    if not _CANONICAL_COEFFICIENT.fullmatch(coefficient):
        raise ValueError("Metrics v2 Decimal input is not canonical")
    unsigned = coefficient.removeprefix("-")
    if coefficient == "-0" or (coefficient != "0" and unsigned.endswith("0")):
        raise ValueError("Metrics v2 Decimal input is not canonical")
    if coefficient == "0" and exponent != 0:
        raise ValueError("Metrics v2 Decimal input is not canonical")
    if len(unsigned) > MAX_V2_DECIMAL_DIGITS:
        raise ValueError("Metrics v2 Decimal exceeds the coefficient digit limit")
    adjusted = exponent + len(unsigned) - 1
    if abs(adjusted) > MAX_V2_DECIMAL_ADJUSTED_EXPONENT:
        raise ValueError("Metrics v2 Decimal exceeds the adjusted exponent limit")
    parsed = Decimal(
        (
            1 if coefficient.startswith("-") else 0,
            tuple(int(item) for item in unsigned),
            exponent,
        )
    )
    if decimal_value_v1(parsed) != value:
        raise ValueError("Metrics v2 Decimal input is not canonical")
    return parsed


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
        normalized = value.astimezone(UTC)
        return (
            f"{normalized.year:04d}-{normalized.month:02d}-{normalized.day:02d}"
            f"T{normalized.hour:02d}:{normalized.minute:02d}:{normalized.second:02d}"
            f".{normalized.microsecond:06d}Z"
        )
    if isinstance(value, date):
        return f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
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
        encoded = _canonical_payload_bytes(value.model_dump(mode="python"))
        if len(encoded) > MAX_V2_CANONICAL_BYTES:
            raise ValueError("canonical v2 payload exceeds the byte limit")
    except (AttributeError, OverflowError, TypeError, UnicodeEncodeError, ValueError):
        failed = True
    if failed:
        raise MetricV2ContractError(
            "Metrics v2 canonical serialization failed integrity validation"
        ) from None
    return encoded


def load_metric_input_v2(document: bytes) -> MetricInputV2:
    """Load one exact canonical Metrics v2 input document."""

    from quantverify.metrics.v2_models import MetricInputV2

    return _load_canonical_v2(document, MetricInputV2)


def load_metric_set_v2(document: bytes) -> MetricSetV2:
    """Load one exact canonical Metrics v2 output document."""

    from quantverify.metrics.v2_models import MetricSetV2

    return _load_canonical_v2(document, MetricSetV2)


def v2_content_hash(value: Any) -> str:
    """Return full SHA-256 over canonical v2 bytes."""

    return hashlib.sha256(canonical_v2_bytes(value)).hexdigest()


def _canonical_payload_bytes(value: Any) -> bytes:
    payload = canonicalize_v2(value)
    if not isinstance(payload, dict):
        raise TypeError("canonical v2 root must be an object")
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _load_canonical_v2(document: bytes, model_type: type[_V2Root]) -> _V2Root:
    failed = False
    result: _V2Root | None = None
    try:
        if type(document) is not bytes or len(document) > MAX_V2_CANONICAL_BYTES:
            raise ValueError("canonical v2 document has an invalid byte boundary")
        decoded = document.decode("utf-8")
        _require_bounded_json_depth(decoded)
        payload = json.loads(
            decoded,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
        )
        if type(payload) is not dict:
            raise ValueError("canonical v2 document root must be an object")
        result = model_type.model_validate(payload)
        if canonical_v2_bytes(result) != document:
            raise ValueError("canonical v2 document bytes are not canonical")
    except (
        AttributeError,
        json.JSONDecodeError,
        MemoryError,
        OverflowError,
        RecursionError,
        TypeError,
        UnicodeDecodeError,
        ValidationError,
        ValueError,
    ):
        failed = True
    if failed or result is None:
        raise MetricV2ContractError(
            "Metrics v2 canonical document failed integrity validation"
        ) from None
    return result


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate canonical v2 JSON key")
        result[key] = value
    return result


def _reject_json_constant(_: str) -> Any:
    raise ValueError("non-finite canonical v2 JSON number")


def _require_bounded_json_depth(document: str) -> None:
    """Reject excessive JSON nesting without counting brackets inside strings."""

    depth = 0
    in_string = False
    escaped = False
    for character in document:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > MAX_V2_JSON_NESTING:
                raise ValueError("canonical v2 JSON nesting exceeds the limit")
        elif character in "]}":
            depth -= 1
            if depth < 0:
                raise ValueError("canonical v2 JSON nesting is invalid")
