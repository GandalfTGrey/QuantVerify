import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest import TestCase

import yaml

from quantverify.core.enums import AssetClass
from quantverify.core.models import AssetId
from quantverify.data.models import NormalizedBar
from quantverify.features.moving_average import simple_moving_average
from quantverify.strategies.trend import price_above_sma_targets

FIXTURES = Path(__file__).parent / "fixtures"
ASSET = AssetId(symbol="QQQ", venue="XNAS", asset_class=AssetClass.ETF, currency="USD")


def load_bars() -> tuple[NormalizedBar, ...]:
    with (FIXTURES / "sma3_daily_bars.csv").open(encoding="utf-8", newline="") as stream:
        rows = csv.DictReader(stream)
        return tuple(
            NormalizedBar(
                asset=ASSET,
                session=date.fromisoformat(row["session"]),
                session_open_at=datetime.fromisoformat(row["session_open_at"]),
                session_close_at=datetime.fromisoformat(row["session_close_at"]),
                available_at=datetime.fromisoformat(row["available_at"]),
                open=Decimal(row["open"]),
                high=Decimal(row["high"]),
                low=Decimal(row["low"]),
                close=Decimal(row["close"]),
                volume=Decimal(row["volume"]),
                source="golden_fixture",
            )
            for row in rows
        )


class MovingAverageTests(TestCase):
    def test_warmup_and_inclusive_trailing_values(self) -> None:
        result = simple_moving_average(
            (Decimal("100"), Decimal("101"), Decimal("102"), Decimal("104")),
            window=3,
        )
        self.assertEqual(
            result,
            (None, None, Decimal("101"), Decimal("102.3333333333333333333333333")),
        )

    def test_rejects_non_positive_window(self) -> None:
        with self.assertRaisesRegex(ValueError, "window must be positive"):
            simple_moving_average((Decimal("1"),), window=0)


class TrendGoldenTests(TestCase):
    def test_sma_targets_match_hand_verified_fixture(self) -> None:
        expected = yaml.safe_load(
            (FIXTURES / "sma3_expected_targets.yaml").read_text(encoding="utf-8")
        )
        actual = price_above_sma_targets(load_bars(), window=expected["window"])
        self.assertEqual(len(actual), len(expected["targets"]))
        for target, expected_target in zip(actual, expected["targets"], strict=True):
            self.assertEqual(target.decision_at.isoformat(), expected_target["decision_at"])
            self.assertEqual(target.effective_at.isoformat(), expected_target["effective_at"])
            self.assertEqual(target.weight, Decimal(expected_target["weight"]))

    def test_truncating_future_does_not_change_past_targets(self) -> None:
        bars = load_bars()
        full = price_above_sma_targets(bars, window=3)
        truncated = price_above_sma_targets(bars[:-1], window=3)
        self.assertEqual(full[: len(truncated)], truncated)
