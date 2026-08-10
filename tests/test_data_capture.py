from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from unittest import TestCase

from pydantic import ValidationError

from quantverify.core.enums import AssetClass
from quantverify.core.models import AssetId
from quantverify.data.capture import RawCapture
from quantverify.data.providers.akshare import AkShareUSDailyProvider
from quantverify.data.providers.yfinance import YFinanceUSDailyProvider

ASSET = AssetId(symbol="QQQ", venue="XNAS", asset_class=AssetClass.ETF, currency="USD")


class FixtureSessionResolver:
    def resolve(self, session: date) -> tuple[datetime, datetime]:
        return (
            datetime(session.year, session.month, session.day, 14, 30, tzinfo=UTC),
            datetime(session.year, session.month, session.day, 21, 0, tzinfo=UTC),
        )


class FakeYFinanceFrame:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records
        self.empty = not records

    def reset_index(self) -> FakeYFinanceFrame:
        return self

    def to_dict(self, *, orient: str) -> list[dict[str, Any]]:
        if orient != "records":
            raise AssertionError("record-oriented conversion required")
        return self._records


class FakeYFinanceClient:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = records
        self.calls = 0

    def download(self, **_: Any) -> FakeYFinanceFrame:
        self.calls += 1
        return FakeYFinanceFrame(self.records)


class FakeAkShareFrame:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records

    def to_dict(self, *, orient: str) -> list[dict[str, Any]]:
        if orient != "records":
            raise AssertionError("record-oriented conversion required")
        return self._records


class FakeAkShareClient:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = records
        self.calls = 0

    def stock_us_daily(self, **_: Any) -> FakeAkShareFrame:
        self.calls += 1
        return FakeAkShareFrame(self.records)


class FixtureEnum(Enum):
    VALUE = "fixture-value"


class ItemScalar:
    def item(self) -> int:
        return 7


class IsoScalar:
    def isoformat(self) -> str:
        return "2026-01-02T00:00:00"


class UnsupportedScalar:
    pass


def yahoo_row(close: str = "500") -> dict[str, str]:
    return {
        "Date": "2026-01-02",
        "Open": "490",
        "High": "505",
        "Low": "485",
        "Close": close,
        "Adj Close": "480",
        "Volume": "123456",
    }


def akshare_row(close: str = "500") -> dict[str, str]:
    return {
        "date": "2026-01-02",
        "open": "490",
        "high": "505",
        "low": "485",
        "close": close,
        "volume": "123456",
    }


class RawCaptureTests(TestCase):
    def test_content_hash_excludes_observation_time_but_includes_request(self) -> None:
        first = RawCapture.from_records(
            provider="fixture",
            endpoint="daily",
            request={"symbol": "QQQ"},
            records=[{"close": "500"}],
            captured_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        second = RawCapture.from_records(
            provider="fixture",
            endpoint="daily",
            request={"symbol": "QQQ"},
            records=[{"close": "500"}],
            captured_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        different_request = RawCapture.from_records(
            provider="fixture",
            endpoint="daily",
            request={"symbol": "DIA"},
            records=[{"close": "500"}],
            captured_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

        self.assertEqual(first.content_hash, second.content_hash)
        self.assertNotEqual(first.content_hash, different_request.content_hash)
        self.assertEqual(len(first.content_hash), 64)

    def test_capture_canonicalizes_common_provider_scalar_types(self) -> None:
        capture = RawCapture.from_records(
            provider="fixture",
            endpoint="daily",
            request={"symbol": "QQQ"},
            records=[
                {
                    "timestamp": datetime(2026, 1, 2, 12, tzinfo=UTC),
                    "session": date(2026, 1, 2),
                    "decimal": Decimal("1.25"),
                    "enum": FixtureEnum.VALUE,
                    "nested": [Decimal("2.5")],
                    "item_scalar": ItemScalar(),
                    "iso_scalar": IsoScalar(),
                }
            ],
            captured_at=datetime(2026, 1, 2, 13, tzinfo=UTC),
        )

        record = capture.records[0]
        self.assertEqual(record["timestamp"], "2026-01-02T12:00:00+00:00")
        self.assertEqual(record["session"], "2026-01-02")
        self.assertEqual(record["decimal"], "1.25")
        self.assertEqual(record["enum"], "fixture-value")
        self.assertEqual(record["nested"], ["2.5"])
        self.assertEqual(record["item_scalar"], 7)
        self.assertEqual(record["iso_scalar"], "2026-01-02T00:00:00")

    def test_capture_rejects_non_finite_and_unsupported_values(self) -> None:
        common = {
            "provider": "fixture",
            "endpoint": "daily",
            "request": {"symbol": "QQQ"},
            "captured_at": datetime(2026, 1, 2, tzinfo=UTC),
        }
        with self.assertRaisesRegex(ValueError, "decimals must be finite"):
            RawCapture.from_records(records=[{"x": Decimal("NaN")}], **common)
        with self.assertRaisesRegex(ValueError, "floats must be finite"):
            RawCapture.from_records(records=[{"x": float("inf")}], **common)
        with self.assertRaisesRegex(TypeError, "Unsupported raw capture value"):
            RawCapture.from_records(records=[{"x": UnsupportedScalar()}], **common)

    def test_capture_rejects_non_string_mapping_keys_and_naive_capture_time(self) -> None:
        with self.assertRaisesRegex(TypeError, "mappings require string keys"):
            RawCapture.from_records(
                provider="fixture",
                endpoint="daily",
                request={"symbol": "QQQ"},
                records=[{1: "bad-key"}],
                captured_at=datetime(2026, 1, 2, tzinfo=UTC),
            )
        with self.assertRaises(ValidationError):
            RawCapture.from_records(
                provider="fixture",
                endpoint="daily",
                request={"symbol": "QQQ"},
                records=[{"close": "500"}],
                captured_at=datetime(2026, 1, 2),
            )

    def test_yfinance_capture_is_replayable_without_second_network_call(self) -> None:
        client = FakeYFinanceClient([yahoo_row("500")])
        provider = YFinanceUSDailyProvider(client, FixtureSessionResolver())

        capture = provider.capture_daily(
            ASSET, start=date(2026, 1, 2), end=date(2026, 1, 2)
        )
        self.assertEqual(client.calls, 1)
        self.assertEqual(capture.records[0]["Adj Close"], "480")

        # Simulate an upstream revision after capture. Offline normalization must
        # continue to use the captured 500 close rather than fetch the new 999.
        client.records = [yahoo_row("999")]
        first = provider.normalize_daily(
            ASSET, capture, start=date(2026, 1, 2), end=date(2026, 1, 2)
        )
        second = provider.normalize_daily(
            ASSET, capture, start=date(2026, 1, 2), end=date(2026, 1, 2)
        )

        self.assertEqual(client.calls, 1)
        self.assertEqual(first[0].close, 500)
        self.assertEqual(second, first)

    def test_akshare_capture_is_replayable_without_second_network_call(self) -> None:
        client = FakeAkShareClient([akshare_row("500")])
        provider = AkShareUSDailyProvider(client, FixtureSessionResolver())

        capture = provider.capture_daily(ASSET)
        self.assertEqual(client.calls, 1)
        client.records = [akshare_row("999")]

        bars = provider.normalize_daily(ASSET, capture)

        self.assertEqual(client.calls, 1)
        self.assertEqual(bars[0].close, 500)

    def test_load_daily_still_performs_exactly_one_provider_call(self) -> None:
        client = FakeYFinanceClient([yahoo_row()])
        provider = YFinanceUSDailyProvider(client, FixtureSessionResolver())

        provider.load_daily(ASSET, start=date(2026, 1, 2), end=date(2026, 1, 2))

        self.assertEqual(client.calls, 1)
