"""Immutable adapter-level raw snapshots with content-addressed identities."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import Field

from quantverify.core.enums import AdjustmentMode
from quantverify.core.exceptions import DataQualityError, ReproducibilityError
from quantverify.core.models import AssetId, DataSnapshot, DomainModel


class SnapshotWriteResult(DomainModel):
    """Immutable snapshot metadata plus its local raw-artifact location."""

    snapshot: DataSnapshot
    record_count: int = Field(ge=0)
    raw_uri: str = Field(min_length=1)
    manifest_uri: str = Field(min_length=1)


class RawSnapshotWriter:
    """Persist a canonical adapter response without silently overwriting history."""

    schema_version = "akshare-raw-v1"
    source = "akshare:stock_us_daily"

    def __init__(self, root: Path) -> None:
        self._root = root

    def write_akshare_daily(
        self,
        *,
        asset: AssetId,
        records: Sequence[Mapping[str, Any]],
        captured_at: datetime,
        adjustment_mode: AdjustmentMode,
    ) -> SnapshotWriteResult:
        """Write a content-addressed raw response and return provenance metadata.

        ``captured_at`` is intentionally not part of the content hash: an
        identical provider response is one immutable content object, while its
        fetch time remains preserved in the returned ``DataSnapshot`` manifest.
        """

        if captured_at.tzinfo is None:
            raise DataQualityError("captured_at must be timezone-aware")
        payload = {
            "asset": asset.model_dump(mode="json"),
            "endpoint": "stock_us_daily",
            "provider": "akshare",
            "records": [self._canonicalize(record) for record in records],
            "schema_version": self.schema_version,
        }
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        content = serialized.encode("utf-8")
        content_hash = hashlib.sha256(content).hexdigest()
        relative_path = Path("raw") / "akshare" / asset.symbol.upper() / f"{content_hash}.json"
        path = self._root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as handle:
                handle.write(content)
        except FileExistsError:
            if path.read_bytes() != content:
                raise ReproducibilityError(
                    f"Content-addressed snapshot collision at {path}"
                ) from None

        snapshot = DataSnapshot(
            dataset_id=f"akshare-us-daily-{asset.symbol.lower()}-{content_hash[:12]}",
            content_hash=content_hash,
            schema_version=self.schema_version,
            source=self.source,
            captured_at=captured_at,
            adjustment_mode=adjustment_mode,
        )
        manifest_content = json.dumps(
            {
                "raw_uri": path.resolve().as_uri(),
                "record_count": len(records),
                "snapshot": snapshot.model_dump(mode="json"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        capture_name = captured_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        manifest_path = (
            self._root
            / "manifests"
            / "akshare"
            / asset.symbol.upper()
            / content_hash
            / f"{capture_name}.json"
        )
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with manifest_path.open("xb") as handle:
                handle.write(manifest_content)
        except FileExistsError:
            if manifest_path.read_bytes() != manifest_content:
                raise ReproducibilityError(
                    f"Immutable snapshot manifest collision at {manifest_path}"
                ) from None

        return SnapshotWriteResult(
            snapshot=snapshot,
            record_count=len(records),
            raw_uri=path.resolve().as_uri(),
            manifest_uri=manifest_path.resolve().as_uri(),
        )

    @classmethod
    def _canonicalize(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            if not all(isinstance(key, str) for key in value):
                raise DataQualityError("Raw snapshot mappings require string keys")
            return {key: cls._canonicalize(item) for key, item in sorted(value.items())}
        if isinstance(value, (list, tuple)):
            return [cls._canonicalize(item) for item in value]
        if isinstance(value, datetime):
            # Provider payloads often encode a session *date* as a timezone-naive
            # pandas Timestamp.  This raw artifact preserves it verbatim; the
            # provider's NormalizedBar conversion separately assigns an exchange
            # calendar and timezone-aware event times.
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise DataQualityError("Raw snapshot decimals must be finite")
            return str(value)
        if isinstance(value, float):
            if not math.isfinite(value):
                raise DataQualityError("Raw snapshot floats must be finite")
            return repr(value)
        if value is None or isinstance(value, (bool, int, str)):
            return value
        return str(value)
