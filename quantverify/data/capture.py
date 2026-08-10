"""Provider-independent immutable boundary for captured market-data responses."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from quantverify.core.identity import canonicalize
from quantverify.core.models import DomainModel


def _capture_value(value: Any) -> Any:
    """Convert common provider/NumPy/pandas scalars into stable JSON-like values.

    The capture boundary preserves provider fields and values, while removing
    process-specific scalar classes that would make identity or persistence
    depend on a particular SDK/DataFrame implementation.
    """

    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("Raw capture mappings require string keys")
        return {key: _capture_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_capture_value(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Raw capture decimals must be finite")
        return format(value, "f")
    if isinstance(value, Enum):
        return _capture_value(value.value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Raw capture floats must be finite")
        return value
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    # NumPy scalar types expose ``item``. Converting them here keeps the raw
    # field/value semantics without requiring NumPy in the domain layer.
    item = getattr(value, "item", None)
    if callable(item):
        return _capture_value(item())
    # pandas Timestamp and similar provider scalars commonly expose isoformat.
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    raise TypeError(f"Unsupported raw capture value: {type(value).__name__}")


class RawCapture(DomainModel):
    """One provider response captured by exactly one logical network request.

    ``captured_at`` records when QuantVerify received the response but is not part
    of ``content_hash``. Re-fetching identical provider content therefore keeps
    the same content identity while preserving a distinct observation time in
    the capture metadata.

    The object intentionally stores provider-facing records, not
    ``NormalizedBar`` instances. Normalization is a separate, offline step.
    """

    provider: str = Field(min_length=1, max_length=128)
    endpoint: str = Field(min_length=1, max_length=128)
    request: Mapping[str, Any]
    records: tuple[Mapping[str, Any], ...]
    captured_at: datetime
    schema_version: str = Field(default="raw-capture-v1", min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_capture(self) -> RawCapture:
        if self.captured_at.tzinfo is None:
            raise ValueError("captured_at must be timezone-aware")
        canonicalize(self.request)
        canonicalize(self.records)
        return self

    @property
    def content_hash(self) -> str:
        """Return full SHA-256 identity for request semantics plus response content."""

        payload = canonicalize(
            {
                "provider": self.provider,
                "endpoint": self.endpoint,
                "request": self.request,
                "records": self.records,
                "schema_version": self.schema_version,
            }
        )
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(serialized).hexdigest()

    @classmethod
    def from_records(
        cls,
        *,
        provider: str,
        endpoint: str,
        request: Mapping[str, Any],
        records: Sequence[Mapping[str, Any]],
        captured_at: datetime,
        schema_version: str = "raw-capture-v1",
    ) -> RawCapture:
        """Build a capture with provider values converted to stable primitives."""

        frozen_request = _capture_value(request)
        frozen_records = _capture_value(records)
        if not isinstance(frozen_request, Mapping) or not isinstance(frozen_records, list):
            raise TypeError("RawCapture request/records canonicalization failed")
        return cls(
            provider=provider,
            endpoint=endpoint,
            request=dict(frozen_request),
            records=tuple(dict(record) for record in frozen_records),
            captured_at=captured_at,
            schema_version=schema_version,
        )
