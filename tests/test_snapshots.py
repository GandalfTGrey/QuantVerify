from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from quantverify.core.enums import AdjustmentMode, AssetClass
from quantverify.core.exceptions import DataQualityError
from quantverify.core.models import AssetId
from quantverify.data.snapshots import RawSnapshotWriter

ASSET = AssetId(symbol="QQQ", venue="XNAS", asset_class=AssetClass.ETF, currency="USD")


class RawSnapshotWriterTests(TestCase):
    def test_writes_content_addressed_canonical_snapshot(self) -> None:
        records = [{"close": Decimal("500.10"), "date": date(2026, 1, 2), "volume": 123.0}]
        with TemporaryDirectory() as directory:
            writer = RawSnapshotWriter(Path(directory))
            result = writer.write_akshare_daily(
                asset=ASSET,
                records=records,
                captured_at=datetime(2026, 1, 2, 22, tzinfo=UTC),
                adjustment_mode=AdjustmentMode.RAW,
            )

            path = Path(result.raw_uri.removeprefix("file://"))
            payload = json.loads(path.read_text(encoding="utf-8"))
            manifest_path = Path(result.manifest_uri.removeprefix("file://"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(result.record_count, 1)
        self.assertEqual(result.snapshot.content_hash, path.stem)
        self.assertEqual(result.snapshot.adjustment_mode, AdjustmentMode.RAW)
        self.assertEqual(manifest["snapshot"]["captured_at"], "2026-01-02T22:00:00Z")
        self.assertEqual(manifest["raw_uri"], result.raw_uri)
        self.assertEqual(
            payload["records"][0],
            {"close": "500.10", "date": "2026-01-02", "volume": "123.0"},
        )

    def test_same_content_reuses_immutable_object_across_capture_times(self) -> None:
        records = [{"date": "2026-01-02", "close": "500"}]
        with TemporaryDirectory() as directory:
            writer = RawSnapshotWriter(Path(directory))
            first = writer.write_akshare_daily(
                asset=ASSET,
                records=records,
                captured_at=datetime(2026, 1, 2, 22, tzinfo=UTC),
                adjustment_mode=AdjustmentMode.RAW,
            )
            second = writer.write_akshare_daily(
                asset=ASSET,
                records=records,
                captured_at=datetime(2026, 1, 3, 22, tzinfo=UTC),
                adjustment_mode=AdjustmentMode.RAW,
            )

        self.assertEqual(first.snapshot.content_hash, second.snapshot.content_hash)
        self.assertNotEqual(first.snapshot.captured_at, second.snapshot.captured_at)
        self.assertEqual(first.raw_uri, second.raw_uri)
        self.assertNotEqual(first.manifest_uri, second.manifest_uri)

    def test_rejects_naive_capture_time(self) -> None:
        with TemporaryDirectory() as directory:
            writer = RawSnapshotWriter(Path(directory))
            with self.assertRaisesRegex(DataQualityError, "captured_at must be timezone-aware"):
                writer.write_akshare_daily(
                    asset=ASSET,
                    records=[],
                    captured_at=datetime(2026, 1, 2, 22),
                    adjustment_mode=AdjustmentMode.RAW,
                )

    def test_rejects_nonfinite_values(self) -> None:
        with TemporaryDirectory() as directory:
            writer = RawSnapshotWriter(Path(directory))
            with self.assertRaisesRegex(DataQualityError, "floats must be finite"):
                writer.write_akshare_daily(
                    asset=ASSET,
                    records=[{"close": float("nan")}],
                    captured_at=datetime(2026, 1, 2, 22, tzinfo=UTC),
                    adjustment_mode=AdjustmentMode.RAW,
                )
