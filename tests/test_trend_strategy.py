import csv
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from unittest import TestCase

import yaml

from quantverify.core.enums import AssetClass, SessionLabelPolicy
from quantverify.core.exceptions import DataQualityError
from quantverify.core.models import AssetId, SessionSchedule
from quantverify.data.models import NormalizedBar
from quantverify.features.moving_average import simple_moving_average
from quantverify.strategies.trend import price_above_sma_targets

FIXTURES = Path(__file__).parent / "fixtures"
ASSET = AssetId(symbol="QQQ", venue="XNAS", asset_class=AssetClass.ETF, currency="USD")
DIA = AssetId(symbol="DIA", venue="ARCX", asset_class=AssetClass.ETF, currency="USD")


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


def load_schedule(*, session_count: int | None = None) -> SessionSchedule:
    raw = yaml.safe_load(
        (FIXTURES / "xnas_sessions_2026-01-02_2026-01-14.yaml").read_text(
            encoding="utf-8"
        )
    )
    stored = SessionSchedule.model_validate(raw)
    if session_count is None:
        return stored
    selected = stored.sessions[:session_count]
    return SessionSchedule.create(
        requested_start=stored.requested_start,
        requested_end=selected[-1].session,
        calendar=stored.calendar,
        sessions=selected,
    )


def replace_bar(bar: NormalizedBar, **updates: object) -> NormalizedBar:
    return NormalizedBar.model_validate({**bar.model_dump(mode="python"), **updates})


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
    def test_calendar_fixture_has_pinned_schedule_identity(self) -> None:
        self.assertEqual(
            load_schedule().schedule_id,
            "session-schedule_ec8a813682d1ab91fc0b171b",
        )

    def test_sma_targets_match_hand_verified_fixture(self) -> None:
        expected = yaml.safe_load(
            (FIXTURES / "sma3_expected_targets.yaml").read_text(encoding="utf-8")
        )
        bars = load_bars()
        actual = price_above_sma_targets(
            bars,
            window=expected["window"],
            schedule=load_schedule(),
        )
        self.assertEqual(len(actual), len(expected["targets"]))
        for target, expected_target in zip(actual, expected["targets"], strict=True):
            self.assertEqual(target.decision_at.isoformat(), expected_target["decision_at"])
            self.assertEqual(target.effective_at.isoformat(), expected_target["effective_at"])
            self.assertEqual(target.weight, Decimal(expected_target["weight"]))

    def test_truncating_future_does_not_change_past_targets(self) -> None:
        bars = load_bars()
        full = price_above_sma_targets(bars, window=3, schedule=load_schedule())
        truncated_bars = bars[:-1]
        truncated = price_above_sma_targets(
            truncated_bars,
            window=3,
            schedule=load_schedule(session_count=len(truncated_bars)),
        )
        self.assertEqual(full[: len(truncated)], truncated)

    def test_missing_bar_cannot_be_mistaken_for_the_next_session(self) -> None:
        bars = load_bars()
        with self.assertRaisesRegex(DataQualityError, "exactly cover"):
            price_above_sma_targets(
                bars[:3] + bars[4:],
                window=3,
                schedule=load_schedule(),
            )

    def test_single_complete_session_has_no_executable_target(self) -> None:
        bars = load_bars()[:1]
        self.assertEqual(
            price_above_sma_targets(bars, window=3, schedule=load_schedule(session_count=1)),
            (),
        )

    def test_mixed_assets_fail_closed(self) -> None:
        bars = load_bars()
        mixed = (*bars[:2], replace_bar(bars[2], asset=DIA), *bars[3:])
        with self.assertRaisesRegex(DataQualityError, "identical asset"):
            price_above_sma_targets(mixed, window=3, schedule=load_schedule())

    def test_bar_times_must_match_independent_schedule(self) -> None:
        bars = load_bars()
        shifted = replace_bar(
            bars[2], session_open_at=datetime(2026, 1, 6, 14, 31, tzinfo=UTC)
        )
        mismatched = (*bars[:2], shifted, *bars[3:])
        with self.assertRaisesRegex(DataQualityError, "timestamps must match"):
            price_above_sma_targets(mismatched, window=3, schedule=load_schedule())

    def test_strategy_rejects_unapproved_session_label_policy(self) -> None:
        bars = load_bars()
        trusted = load_schedule()
        calendar_values = trusted.calendar.model_dump(mode="python")
        calendar_values["session_label_policy"] = SessionLabelPolicy.CALENDAR_DEFINED
        unsupported = SessionSchedule.create(
            requested_start=trusted.requested_start,
            requested_end=trusted.requested_end,
            calendar=trusted.calendar.model_validate(calendar_values),
            sessions=trusted.sessions,
        )
        with self.assertRaisesRegex(DataQualityError, "close-local-date"):
            price_above_sma_targets(bars, window=3, schedule=unsupported)

    def test_decision_waits_for_bar_availability(self) -> None:
        bars = load_bars()
        targets = price_above_sma_targets(bars, window=3, schedule=load_schedule())
        self.assertEqual(targets[0].decision_at, bars[2].available_at)
        self.assertGreater(targets[0].decision_at, bars[2].session_close_at)

    def test_late_bar_cannot_execute_at_an_already_open_session(self) -> None:
        bars = load_bars()
        late = replace_bar(bars[2], available_at=datetime(2026, 1, 7, 15, 0, tzinfo=UTC))
        late_bars = (*bars[:2], late, *bars[3:])
        with self.assertRaisesRegex(DataQualityError, "not available"):
            price_above_sma_targets(
                late_bars,
                window=3,
                schedule=load_schedule(),
            )

    def test_late_historical_dependency_sets_the_decision_watermark(self) -> None:
        bars = load_bars()
        delayed = replace_bar(
            bars[0], available_at=datetime(2026, 1, 7, 13, 0, tzinfo=UTC)
        )
        delayed_bars = (delayed, *bars[1:])
        targets = price_above_sma_targets(
            delayed_bars,
            window=3,
            schedule=load_schedule(),
        )
        self.assertEqual(targets[0].decision_at, delayed.available_at)
        self.assertLess(targets[0].decision_at, targets[0].effective_at)

    def test_historical_dependency_available_after_next_open_fails_closed(self) -> None:
        bars = load_bars()
        delayed = replace_bar(
            bars[0], available_at=datetime(2026, 1, 7, 16, 30, tzinfo=UTC)
        )
        delayed_bars = (delayed, *bars[1:])
        with self.assertRaisesRegex(DataQualityError, "not available"):
            price_above_sma_targets(
                delayed_bars,
                window=3,
                schedule=load_schedule(),
            )
