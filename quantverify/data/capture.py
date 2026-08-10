"""Provider-independent immutable boundary for captured market-data responses."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

from quantverify.core.identity import canonicalize
from quantverify.core.models import DomainModel


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
        # Fail early when request/records contain values that cannot participate
        # in deterministic identity. Credentials must never be included here.
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
        """Build a capture while freezing the outer record sequence as a tuple."""

        return cls(
            provider=provider,
            endpoint=endpoint,
            request=dict(request),
            records=tuple(dict(record) for record in records),
            captured_at=captured_at,
            schema_version=schema_version,
        )
