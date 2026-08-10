from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from unittest import TestCase

from quantverify.core.enums import AssetClass
from quantverify.core.exceptions import DataQualityError
from quantverify.core.models import AssetId
from quantverify.data.providers.yfinance import YFinanceUSDailyProvider

ASSET = AssetId(symbol="QQQ", venue="XNAS", asset_class=AssetClass.ETF, currency="USD")


class FakeFrame:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records
        self.empty = not records

    def reset_index(self) -> FakeFrame:
        return self

    def to_dict(self, *, orient: str) -> list[dict[str, Any]]:
        if orient != "records":
            raise AssertionError("The adapter must request record-oriented rows")
        return self._records


class FakeYFinanceClient:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = records
        self.calls: list[dict[str, Any]] = []

    def download(self, tickers: str, **kwargs: Any) -> FakeFrame:
        self.calls.append({"tickers": tickers, **kwargs})
        return FakeFrame(self.records)


class FixtureSessionResolver:
    def resolve(self, session: date) -> tuple[datetime, datetime]:
        session_open = datetime(session.year, session.month, session.day, 14, 30, tzinfo=UTC)
        session_close = datetime(session.year, session.month, session.day, 21, tzinfo=UTC)
        return session_open, session_close


def row(day: str, close: str = "500") -> dict[str, str]:
    return {
        "Date": day,
        "Open": "490",
        "High": "505",
        "Low": "485",
        "Close": close,
        "Adj Close": "480",
        "Volume": "123456",
    }


class YFinanceUSDailyProviderTests(TestCase):
    def make_provider(
        self, records: list[dict[str, Any]]
    ) -> tuple[YFinanceUSDailyProvider, FakeYFinanceClient]:
        client = FakeYFinanceClient(records)
        return YFinanceUSDailyProvider(client, FixtureSessionResolver()), client

    def test_loads_raw_bars_with_inclusive_end_conversion(self) -> None:
        provider, client = self.make_provider([row("2026-01-02"), row("2026-01-05", "500")])

        bars = provider.load_daily(ASSET, start=date(2026, 1, 2), end=date(2026, 1, 5))

        self.assertEqual([bar.session for bar in bars], [date(2026, 1, 2), date(2026, 1, 5)])
        self.assertEqual(bars[1].close, 500)
        self.assertEqual(bars[0].source, "yfinance:download:raw")
        self.assertEqual(bars[0].available_at, bars[0].session_close_at)
        self.assertEqual(
            client.calls,
            [
                {
                    "tickers": "QQQ",
                    "start": "2026-01-02",
                    "end": "2026-01-06",
                    "interval": "1d",
                    "auto_adjust": False,
                    "actions": False,
                    "progress": False,
                    "threads": False,
                    "group_by": "column",
                    "multi_level_index": False,
                }
            ],
        )

    def test_rejects_empty_response(self) -> None:
        provider, _ = self.make_provider([])

        with self.assertRaisesRegex(DataQualityError, "returned no bars"):
            provider.load_daily(ASSET, start=date(2026, 1, 2), end=date(2026, 1, 5))

    def test_rejects_invalid_ohlc(self) -> None:
        invalid = row("2026-01-02")
        invalid["Low"] = "-1"
        provider, _ = self.make_provider([invalid])

        with self.assertRaisesRegex(DataQualityError, "row 0 violates the normalized-bar contract"):
            provider.load_daily(ASSET, start=date(2026, 1, 2), end=date(2026, 1, 2))

    def test_rejects_response_outside_requested_range(self) -> None:
        provider, _ = self.make_provider([row("2026-01-06")])

        with self.assertRaisesRegex(DataQualityError, "outside requested inclusive range"):
            provider.load_daily(ASSET, start=date(2026, 1, 2), end=date(2026, 1, 5))
