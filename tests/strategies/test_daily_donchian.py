from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from unittest import TestCase
from zoneinfo import ZoneInfo

from quantverify.core.enums import AssetClass, SessionLabelPolicy
from quantverify.core.exceptions import DataQualityError
from quantverify.core.models import (
    AssetId,
    CalendarArtifactRef,
    SessionSchedule,
    TradingSession,
)
from quantverify.data.models import NormalizedBar
from quantverify.features import prior_rolling_max, prior_rolling_min
from quantverify.strategies import (
    S2_ENTRY_WINDOW,
    S2_EXIT_WINDOW,
    daily_donchian_targets,
)

NY = ZoneInfo("America/New_York")
QQQ = AssetId(symbol="QQQ", venue="XNAS", asset_class=AssetClass.ETF, currency="USD")
DIA = AssetId(symbol="DIA", venue="ARCX", asset_class=AssetClass.ETF, currency="USD")
CALENDAR = CalendarArtifactRef(
    calendar_id="SYNTHETIC-XNAS-S2",
    calendar_version="golden-v1",
    timezone="America/New_York",
    session_label_policy=SessionLabelPolicy.CLOSE_LOCAL_DATE,
    source_id="offline-s2-calendar-fixture",
    source_version="1",
    content_hash="a" * 64,
)


def sessions(count: int) -> tuple[TradingSession, ...]:
    result: list[TradingSession] = []
    day = date(2025, 1, 2)
    while len(result) < count:
        if day.weekday() < 5:
            result.append(
                TradingSession(
                    session=day,
                    session_open_at=datetime(day.year, day.month, day.day, 9, 30, tzinfo=NY),
                    session_close_at=datetime(day.year, day.month, day.day, 16, 0, tzinfo=NY),
                )
            )
        day += timedelta(days=1)
    return tuple(result)


def schedule(count: int = 61) -> SessionSchedule:
    items = sessions(count)
    return SessionSchedule.create(
        requested_start=items[0].session,
        requested_end=items[-1].session,
        calendar=CALENDAR,
        sessions=items,
    )


def bar(
    trading_session: TradingSession,
    *,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    index: int,
    asset: AssetId = QQQ,
    source: str = "s2-golden",
    available_at: datetime | None = None,
) -> NormalizedBar:
    return NormalizedBar(
        asset=asset,
        session=trading_session.session,
        session_open_at=trading_session.session_open_at,
        session_close_at=trading_session.session_close_at,
        available_at=available_at or trading_session.session_close_at + timedelta(minutes=5),
        open=close,
        high=high,
        low=low,
        close=close,
        volume=Decimal(1000 + index),
        source=source,
    )


def golden_bars(eligible: SessionSchedule) -> tuple[NormalizedBar, ...]:
    result = [
        bar(
            item,
            high=Decimal("100"),
            low=Decimal("90"),
            close=Decimal("95"),
            index=index,
        )
        for index, item in enumerate(eligible.sessions[:60])
    ]
    result[55] = bar(
        eligible.sessions[55],
        high=Decimal("110"),
        low=Decimal("100"),
        close=Decimal("101"),
        index=55,
    )
    result[56] = bar(
        eligible.sessions[56],
        high=Decimal("108"),
        low=Decimal("91"),
        close=Decimal("105"),
        index=56,
    )
    result[57] = bar(
        eligible.sessions[57],
        high=Decimal("109"),
        low=Decimal("80"),
        close=Decimal("89"),
        index=57,
    )
    result[58] = bar(
        eligible.sessions[58],
        high=Decimal("120"),
        low=Decimal("110"),
        close=Decimal("111"),
        index=58,
    )
    result[59] = bar(
        eligible.sessions[59],
        high=Decimal("119"),
        low=Decimal("100"),
        close=Decimal("115"),
        index=59,
    )
    return tuple(result)


def rebuild_bar(item: NormalizedBar, **updates: object) -> NormalizedBar:
    return NormalizedBar.model_validate({**item.model_dump(mode="python"), **updates})


class DonchianFeatureTests(TestCase):
    def test_channels_use_strictly_prior_observations(self) -> None:
        values = tuple(Decimal(value) for value in (1, 3, 2, 100))
        self.assertEqual(prior_rolling_max(values, window=3), (None, None, None, Decimal("3")))
        self.assertEqual(prior_rolling_min(values, window=3), (None, None, None, Decimal("1")))

    def test_feature_validation_is_explicit(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            prior_rolling_max((Decimal("1"),), window=0)
        with self.assertRaisesRegex(ValueError, "finite"):
            prior_rolling_min((Decimal("NaN"),), window=1)


class DailyDonchianGoldenTests(TestCase):
    def setUp(self) -> None:
        self.schedule = schedule()
        self.bars = golden_bars(self.schedule)

    def test_hand_calculated_state_transitions(self) -> None:
        targets = daily_donchian_targets(self.bars, eligible_schedule=self.schedule)

        self.assertEqual((S2_ENTRY_WINDOW, S2_EXIT_WINDOW), (55, 20))
        self.assertEqual(tuple(target.weight for target in targets), (
            Decimal("1"), Decimal("1"), Decimal("0"), Decimal("1"), Decimal("1")
        ))
        self.assertEqual(targets[0].effective_at, self.schedule.sessions[56].session_open_at)
        self.assertEqual(targets[-1].effective_at, self.schedule.sessions[60].session_open_at)

    def test_current_bar_extremes_do_not_change_same_bar_signal(self) -> None:
        original = daily_donchian_targets(self.bars[:56], eligible_schedule=self.schedule)[0]
        changed = rebuild_bar(self.bars[55], high=Decimal("1000"), low=Decimal("1"))
        transformed = daily_donchian_targets(
            (*self.bars[:55], changed),
            eligible_schedule=self.schedule,
        )[0]
        self.assertEqual(original, transformed)

    def test_warmup_and_future_truncation_are_invariant(self) -> None:
        self.assertEqual(daily_donchian_targets((), eligible_schedule=self.schedule), ())
        self.assertEqual(
            daily_donchian_targets(self.bars[:55], eligible_schedule=self.schedule),
            (),
        )
        full = daily_donchian_targets(self.bars, eligible_schedule=self.schedule)
        truncated = daily_donchian_targets(self.bars[:58], eligible_schedule=self.schedule)
        self.assertEqual(full[: len(truncated)], truncated)

        extended_schedule = schedule(63)
        extended = daily_donchian_targets(self.bars, eligible_schedule=extended_schedule)
        self.assertEqual(full, extended)

    def test_prior_state_availability_watermark_persists(self) -> None:
        delayed_at = self.schedule.sessions[56].session_open_at - timedelta(minutes=1)
        delayed = rebuild_bar(self.bars[0], available_at=delayed_at)
        targets = daily_donchian_targets(
            (delayed, *self.bars[1:]),
            eligible_schedule=self.schedule,
        )
        self.assertEqual(targets[0].decision_at, delayed_at)
        self.assertEqual(targets[1].decision_at, self.bars[56].available_at)
        self.assertTrue(
            all(left.decision_at < right.decision_at for left, right in pairwise(targets))
        )

    def test_strict_entry_and_exit_boundaries_preserve_prior_state(self) -> None:
        entry_tie = rebuild_bar(self.bars[55], close=Decimal("100"))
        flat_target = daily_donchian_targets(
            (*self.bars[:55], entry_tie),
            eligible_schedule=self.schedule,
        )[0]
        self.assertEqual(flat_target.weight, Decimal("0"))

        exit_tie = rebuild_bar(self.bars[57], close=Decimal("90"))
        long_targets = daily_donchian_targets(
            (*self.bars[:57], exit_tie),
            eligible_schedule=self.schedule,
        )
        self.assertEqual(long_targets[-1].weight, Decimal("1"))

    def test_positive_price_scaling_preserves_state_path(self) -> None:
        scaled = tuple(
            rebuild_bar(
                item,
                open=item.open * 7,
                high=item.high * 7,
                low=item.low * 7,
                close=item.close * 7,
            )
            for item in self.bars
        )
        original = daily_donchian_targets(self.bars, eligible_schedule=self.schedule)
        transformed = daily_donchian_targets(scaled, eligible_schedule=self.schedule)
        self.assertEqual(
            tuple((target.decision_at, target.effective_at, target.weight) for target in original),
            tuple(
                (target.decision_at, target.effective_at, target.weight)
                for target in transformed
            ),
        )


class DailyDonchianFailureTests(TestCase):
    def setUp(self) -> None:
        self.schedule = schedule()
        self.bars = golden_bars(self.schedule)

    def test_missing_or_shifted_session_fails_closed(self) -> None:
        with self.assertRaisesRegex(DataQualityError, "exactly cover"):
            daily_donchian_targets(
                (*self.bars[:20], *self.bars[21:]),
                eligible_schedule=self.schedule,
            )
        shifted = rebuild_bar(
            self.bars[20],
            session_open_at=self.bars[20].session_open_at + timedelta(minutes=1),
        )
        with self.assertRaisesRegex(DataQualityError, "timestamps"):
            daily_donchian_targets(
                (*self.bars[:20], shifted, *self.bars[21:]),
                eligible_schedule=self.schedule,
            )

    def test_missing_immediate_next_session_fails_closed(self) -> None:
        no_next = SessionSchedule.create(
            requested_start=self.schedule.requested_start,
            requested_end=self.bars[-1].session,
            calendar=CALENDAR,
            sessions=self.schedule.sessions[: len(self.bars)],
        )
        with self.assertRaisesRegex(DataQualityError, "immediate next"):
            daily_donchian_targets(self.bars, eligible_schedule=no_next)

    def test_mixed_asset_and_source_fail_closed(self) -> None:
        mixed_asset = rebuild_bar(self.bars[10], asset=DIA)
        with self.assertRaisesRegex(DataQualityError, "identical asset"):
            daily_donchian_targets(
                (*self.bars[:10], mixed_asset, *self.bars[11:]),
                eligible_schedule=self.schedule,
            )
        mixed_source = rebuild_bar(self.bars[10], source="different")
        with self.assertRaisesRegex(DataQualityError, "one normalized data source"):
            daily_donchian_targets(
                (*self.bars[:10], mixed_source, *self.bars[11:]),
                eligible_schedule=self.schedule,
            )

    def test_late_dependency_cannot_roll_execution(self) -> None:
        late = rebuild_bar(
            self.bars[0],
            available_at=self.schedule.sessions[56].session_open_at,
        )
        with self.assertRaisesRegex(DataQualityError, "not available"):
            daily_donchian_targets(
                (late, *self.bars[1:]),
                eligible_schedule=self.schedule,
            )

    def test_unsafe_nested_inputs_fail_at_public_boundary(self) -> None:
        invalid_asset = self.bars[0].asset.model_copy(update={"currency": "INVALID"})
        unsafe_bar = self.bars[0].model_copy(
            update={"asset": invalid_asset, "close": Decimal("-1")}
        )
        with self.assertRaisesRegex(DataQualityError, "integrity validation"):
            daily_donchian_targets(
                (unsafe_bar, *self.bars[1:]),
                eligible_schedule=self.schedule,
            )

        invalid_calendar = self.schedule.calendar.model_copy(update={"content_hash": "bad"})
        unsafe_schedule = self.schedule.model_copy(update={"calendar": invalid_calendar})
        with self.assertRaisesRegex(DataQualityError, "integrity validation"):
            daily_donchian_targets(self.bars, eligible_schedule=unsafe_schedule)

    def test_unapproved_session_label_policy_fails_closed(self) -> None:
        values = CALENDAR.model_dump(mode="python")
        values["session_label_policy"] = SessionLabelPolicy.CALENDAR_DEFINED
        unsupported_calendar = CalendarArtifactRef.model_validate(values)
        unsupported = SessionSchedule.create(
            requested_start=self.schedule.requested_start,
            requested_end=self.schedule.requested_end,
            calendar=unsupported_calendar,
            sessions=self.schedule.sessions,
        )
        with self.assertRaisesRegex(DataQualityError, "close-local-date"):
            daily_donchian_targets(self.bars, eligible_schedule=unsupported)
