from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from unittest import TestCase

from quantverify.core.enums import AdjustmentMode, AssetClass
from quantverify.core.exceptions import DataQualityError
from quantverify.core.models import AssetId
from quantverify.data.providers.akshare import AkShareAdjustment, AkShareUSDailyProvider

ASSET = AssetId(symbol="QQQ", venue="XNAS", asset_class=AssetClass.ETF, currency="USD")


class FakeFrame:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records

    def to_dict(self, *, orient: str) -> list[dict[str, Any]]:
        if orient != "records":
            raise AssertionError("The adapter must request record-oriented rows")
        return self._records


class FakeAkShareClient:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = records
        self.calls: list[tuple[str, str]] = []

    def stock_us_daily(self, symbol: str, adjust: str = "") -> FakeFrame:
        self.calls.append((symbol, adjust))
        return FakeFrame(self.records)


class FixtureSessionResolver:
    def resolve(self, session: date) -> tuple[datetime, datetime]:
        session_open = datetime(session.year, session.month, session.day, 14, 30, tzinfo=UTC)
        session_close = datetime(session.year, session.month, session.day, 21, tzinfo=UTC)
        return session_open, session_close


def row(day: str, close: str = "500") -> dict[str, str]:
    return {
        "date": day,
        "open": "490",
        "high": "505",
        "low": "485",
        "close": close,
        "volume": "123456",
    }


class AkShareUSDailyProviderTests(TestCase):
    def make_provider(
        self, records: list[dict[str, Any]]
    ) -> tuple[AkShareUSDailyProvider, FakeAkShareClient]:
        client = FakeAkShareClient(records)
        return AkShareUSDailyProvider(client, FixtureSessionResolver()), client

    def test_loads_raw_daily_bars_with_explicit_causal_times(self) -> None:
        provider, client = self.make_provider([row("2026-01-05"), row("2026-01-02", "490")])

        bars = provider.load_daily(ASSET)

        self.assertEqual(client.calls, [("QQQ", "")])
        self.assertEqual([bar.session for bar in bars], [date(2026, 1, 2), date(2026, 1, 5)])
        self.assertEqual(bars[0].source, "akshare:stock_us_daily:raw")
        self.assertEqual(bars[0].available_at, bars[0].session_close_at)
        self.assertEqual(bars[0].close, 490)
        self.assertEqual(AkShareAdjustment.RAW.adjustment_mode, AdjustmentMode.RAW)

    def test_requests_qfq_without_claiming_total_return(self) -> None:
        provider, client = self.make_provider([row("2026-01-02")])

        bars = provider.load_daily(ASSET, adjustment=AkShareAdjustment.QFQ)

        self.assertEqual(client.calls, [("QQQ", "qfq")])
        self.assertEqual(bars[0].source, "akshare:stock_us_daily:qfq")
        self.assertEqual(AkShareAdjustment.QFQ.adjustment_mode, AdjustmentMode.SPLIT_ADJUSTED)

    def test_filters_requested_dates_after_validating_the_response(self) -> None:
        provider, _ = self.make_provider(
            [row("2026-01-02"), row("2026-01-05"), row("2026-01-06")]
        )

        bars = provider.load_daily(ASSET, start=date(2026, 1, 5), end=date(2026, 1, 5))

        self.assertEqual([bar.session for bar in bars], [date(2026, 1, 5)])

    def test_rejects_missing_required_columns(self) -> None:
        invalid = row("2026-01-02")
        invalid.pop("volume")
        provider, _ = self.make_provider([invalid])

        with self.assertRaisesRegex(DataQualityError, "missing required columns: volume"):
            provider.load_daily(ASSET)

    def test_rejects_duplicate_sessions(self) -> None:
        provider, _ = self.make_provider([row("2026-01-02"), row("2026-01-02")])

        with self.assertRaisesRegex(DataQualityError, "duplicate session"):
            provider.load_daily(ASSET)

    def test_rejects_non_finite_numeric_values(self) -> None:
        provider, _ = self.make_provider([row("2026-01-02", close="NaN")])

        with self.assertRaisesRegex(DataQualityError, "non-finite close"):
            provider.load_daily(ASSET)
