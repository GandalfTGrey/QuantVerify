from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import TestCase
from zoneinfo import ZoneInfo

from quantverify.core.enums import (
    AdjustmentMode,
    AssetClass,
    BarFrequency,
    PeriodCompleteness,
    SeriesSourceKind,
    SessionLabelPolicy,
)
from quantverify.core.exceptions import DataQualityError
from quantverify.core.models import (
    AssetId,
    CalendarArtifactRef,
    SeriesDescriptor,
    SessionSchedule,
    TradingSession,
)
from quantverify.data.models import DerivedPeriodBar
from quantverify.strategies import S3_FAST_WINDOW, S3_SLOW_WINDOW, weekly_dual_ma_targets

NY = ZoneInfo("America/New_York")
QQQ = AssetId(symbol="QQQ", venue="XNAS", asset_class=AssetClass.ETF, currency="USD")
DIA = AssetId(symbol="DIA", venue="ARCX", asset_class=AssetClass.ETF, currency="USD")
CALENDAR = CalendarArtifactRef(
    calendar_id="SYNTHETIC-XNAS-S3",
    calendar_version="golden-v1",
    timezone="America/New_York",
    session_label_policy=SessionLabelPolicy.CLOSE_LOCAL_DATE,
    source_id="offline-s3-calendar-fixture",
    source_version="1",
    content_hash="a" * 64,
)
HOLIDAYS = {date(2025, 1, 20), date(2025, 7, 4)}
HALF_DAY = date(2025, 7, 3)


def session(day: date) -> TradingSession:
    close_time = time(13) if day == HALF_DAY else time(16)
    return TradingSession(
        session=day,
        session_open_at=datetime.combine(day, time(9, 30), tzinfo=NY),
        session_close_at=datetime.combine(day, close_time, tzinfo=NY),
    )


def schedule(*, weeks: int = 41, include_next: bool = True) -> SessionSchedule:
    first_monday = date(2025, 1, 6)
    end = first_monday + timedelta(days=weeks * 7 if include_next else weeks * 7 - 1)
    sessions = tuple(
        session(first_monday + timedelta(days=offset))
        for offset in range((end - first_monday).days + 1)
        if (first_monday + timedelta(days=offset)).weekday() < 5
        and first_monday + timedelta(days=offset) not in HOLIDAYS
    )
    return SessionSchedule.create(
        requested_start=first_monday,
        requested_end=end,
        calendar=CALENDAR,
        sessions=sessions,
    )


def descriptor(*, asset: AssetId = QQQ, source_hash: str = "b" * 64) -> SeriesDescriptor:
    return SeriesDescriptor(
        asset=asset,
        frequency=BarFrequency.WEEK,
        adjustment_mode=AdjustmentMode.RAW,
        source_kind=SeriesSourceKind.FIXTURE,
        source_id="s3-weekly-golden",
        source_content_hash=source_hash,
        source_schema_version="derived-period-bar-v1",
        producer_id="qf01-calendar-ohlcv",
        producer_version="1",
        calendar=CALENDAR,
    )


def weekly_bar(
    eligible: SessionSchedule,
    *,
    index: int,
    close: Decimal,
    series: SeriesDescriptor | None = None,
) -> DerivedPeriodBar:
    start = date(2025, 1, 6) + timedelta(days=index * 7)
    end = start + timedelta(days=6)
    sessions = tuple(item for item in eligible.sessions if start <= item.session <= end)
    period_schedule = SessionSchedule.create(
        requested_start=start,
        requested_end=end,
        calendar=eligible.calendar,
        sessions=sessions,
    )
    availability = tuple(item.session_close_at + timedelta(minutes=5) for item in sessions)
    return DerivedPeriodBar(
        series=series or descriptor(),
        period_start=start,
        period_end=end,
        constituent_schedule=period_schedule,
        expected_schedule=period_schedule,
        constituent_available_at=availability,
        cutoff_at=max(availability),
        open=close,
        high=close + Decimal("1"),
        low=close,
        close=close,
        volume=Decimal("1000000"),
    )


def golden_bars(eligible: SessionSchedule) -> tuple[DerivedPeriodBar, ...]:
    closes = (*((Decimal("10"),) * 27), *((Decimal("10.5"),) * 13), Decimal("1"))
    return tuple(
        weekly_bar(eligible, index=index, close=close)
        for index, close in enumerate(closes)
    )


def rebuild_bar(bar: DerivedPeriodBar, **updates: object) -> DerivedPeriodBar:
    return DerivedPeriodBar.model_validate({**bar.model_dump(mode="python"), **updates})


def next_open_after(bar: DerivedPeriodBar, eligible: SessionSchedule) -> datetime:
    terminal = bar.expected_schedule.sessions[-1]
    terminal_index = eligible.sessions.index(terminal)
    return eligible.sessions[terminal_index + 1].session_open_at


def monthly_bar(eligible: SessionSchedule) -> DerivedPeriodBar:
    start = date(2025, 1, 1)
    end = date(2025, 1, 31)
    sessions = tuple(item for item in eligible.sessions if start <= item.session <= end)
    period_schedule = SessionSchedule.create(
        requested_start=start,
        requested_end=end,
        calendar=CALENDAR,
        sessions=sessions,
    )
    monthly_series = SeriesDescriptor.model_validate(
        {**descriptor().model_dump(mode="python"), "frequency": BarFrequency.MONTH}
    )
    availability = tuple(item.session_close_at + timedelta(minutes=5) for item in sessions)
    return DerivedPeriodBar(
        series=monthly_series,
        period_start=start,
        period_end=end,
        constituent_schedule=period_schedule,
        expected_schedule=period_schedule,
        constituent_available_at=availability,
        cutoff_at=max(availability),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("10"),
        close=Decimal("10"),
        volume=Decimal("1000"),
    )


class WeeklyDualMaGoldenTests(TestCase):
    def setUp(self) -> None:
        self.schedule = schedule()
        self.bars = golden_bars(self.schedule)

    def test_hand_calculated_inclusive_13_40_signals(self) -> None:
        targets = weekly_dual_ma_targets(self.bars, eligible_schedule=self.schedule)

        self.assertEqual((S3_FAST_WINDOW, S3_SLOW_WINDOW), (13, 40))
        self.assertEqual(len(targets), 2)
        self.assertEqual(targets[0].weight, Decimal("1"))
        self.assertEqual(targets[1].weight, Decimal("0"))
        self.assertEqual(sum(bar.close for bar in self.bars[27:40]) / 13, Decimal("10.5"))
        self.assertEqual(sum(bar.close for bar in self.bars[:40]) / 40, Decimal("10.1625"))
        self.assertEqual(targets[0].effective_at, next_open_after(self.bars[39], self.schedule))

    def test_39_week_warmup_and_40_week_first_target(self) -> None:
        self.assertEqual(weekly_dual_ma_targets((), eligible_schedule=self.schedule), ())
        warmup_schedule = schedule(weeks=39, include_next=False)
        self.assertEqual(
            weekly_dual_ma_targets(self.bars[:39], eligible_schedule=warmup_schedule),
            (),
        )
        first_schedule = schedule(weeks=40, include_next=True)
        self.assertEqual(
            len(weekly_dual_ma_targets(self.bars[:40], eligible_schedule=first_schedule)),
            1,
        )

    def test_tie_is_flat(self) -> None:
        equal = tuple(
            weekly_bar(self.schedule, index=index, close=Decimal("10")) for index in range(40)
        )
        self.assertEqual(
            weekly_dual_ma_targets(equal, eligible_schedule=self.schedule)[0].weight,
            Decimal("0"),
        )

    def test_holiday_dst_and_half_day_follow_schedule_instants(self) -> None:
        holiday_week = self.bars[2]
        half_day_week = self.bars[25]
        self.assertEqual(holiday_week.constituent_count, 4)
        self.assertEqual(half_day_week.period_close_at.hour, 13)
        march_before = self.bars[8].period_open_at
        march_after = self.bars[9].period_open_at
        self.assertEqual(march_before.utcoffset(), timedelta(hours=-5))
        self.assertEqual(march_after.utcoffset(), timedelta(hours=-4))

    def test_full_40_week_availability_watermark_and_lateness(self) -> None:
        next_open = next_open_after(self.bars[39], self.schedule)
        delayed_at = next_open - timedelta(minutes=1)
        first = self.bars[0]
        delayed = rebuild_bar(
            first,
            constituent_available_at=(*first.constituent_available_at[:-1], delayed_at),
            cutoff_at=delayed_at,
        )
        target = weekly_dual_ma_targets(
            (delayed, *self.bars[1:40]),
            eligible_schedule=self.schedule,
        )[0]
        self.assertEqual(target.decision_at, delayed_at)

        late = rebuild_bar(
            first,
            constituent_available_at=(*first.constituent_available_at[:-1], next_open),
            cutoff_at=next_open,
        )
        with self.assertRaisesRegex(DataQualityError, "not available"):
            weekly_dual_ma_targets((late, *self.bars[1:40]), eligible_schedule=self.schedule)

    def test_truncation_schedule_extension_and_scaling_are_invariant(self) -> None:
        full = weekly_dual_ma_targets(self.bars, eligible_schedule=self.schedule)
        truncated = weekly_dual_ma_targets(self.bars[:40], eligible_schedule=self.schedule)
        self.assertEqual(full[:1], truncated)

        extended = schedule(weeks=43)
        self.assertEqual(full, weekly_dual_ma_targets(self.bars, eligible_schedule=extended))

        scaled = tuple(
            rebuild_bar(
                bar,
                open=bar.open * 3,
                high=bar.high * 3,
                low=bar.low * 3,
                close=bar.close * 3,
            )
            for bar in self.bars
        )
        transformed = weekly_dual_ma_targets(scaled, eligible_schedule=self.schedule)
        self.assertEqual(
            tuple((item.decision_at, item.effective_at, item.weight) for item in full),
            tuple((item.decision_at, item.effective_at, item.weight) for item in transformed),
        )


class WeeklyDualMaFailureTests(TestCase):
    def setUp(self) -> None:
        self.schedule = schedule()
        self.bars = golden_bars(self.schedule)

    def test_non_complete_period_fails_closed(self) -> None:
        complete = self.bars[39]
        omitted = complete.expected_schedule.sessions[-1]
        prefix_schedule = SessionSchedule.create(
            requested_start=complete.period_start,
            requested_end=complete.period_end,
            calendar=CALENDAR,
            sessions=complete.expected_schedule.sessions[:-1],
        )
        incomplete = rebuild_bar(
            complete,
            constituent_schedule=prefix_schedule,
            constituent_available_at=complete.constituent_available_at[:-1],
            cutoff_at=omitted.session_close_at,
        )
        self.assertEqual(incomplete.completeness, PeriodCompleteness.INCOMPLETE_MISSING_DATA)
        with self.assertRaisesRegex(DataQualityError, "requires COMPLETE"):
            weekly_dual_ma_targets(
                (*self.bars[:39], incomplete),
                eligible_schedule=self.schedule,
            )

    def test_missing_week_and_mixed_series_fail_closed(self) -> None:
        with self.assertRaisesRegex(DataQualityError, "consecutive"):
            weekly_dual_ma_targets(
                (*self.bars[:10], *self.bars[11:]),
                eligible_schedule=self.schedule,
            )
        for changed in (
            descriptor(asset=DIA, source_hash="c" * 64),
            descriptor(source_hash="c" * 64),
        ):
            mixed = rebuild_bar(self.bars[10], series=changed)
            with self.assertRaisesRegex(DataQualityError, "one immutable weekly series"):
                weekly_dual_ma_targets(
                    (*self.bars[:10], mixed, *self.bars[11:]),
                    eligible_schedule=self.schedule,
                )

    def test_schedule_slice_and_next_session_fail_closed(self) -> None:
        removed = self.bars[5].expected_schedule.sessions[2]
        incomplete_schedule = SessionSchedule.create(
            requested_start=self.schedule.requested_start,
            requested_end=self.schedule.requested_end,
            calendar=CALENDAR,
            sessions=tuple(item for item in self.schedule.sessions if item != removed),
        )
        with self.assertRaisesRegex(DataQualityError, "exactly match"):
            weekly_dual_ma_targets(self.bars, eligible_schedule=incomplete_schedule)

        no_next = schedule(weeks=40, include_next=False)
        with self.assertRaisesRegex(DataQualityError, "immediate next"):
            weekly_dual_ma_targets(self.bars[:40], eligible_schedule=no_next)

    def test_monthly_and_unsafe_nested_inputs_fail_closed(self) -> None:
        with self.assertRaisesRegex(DataQualityError, "requires weekly"):
            weekly_dual_ma_targets((monthly_bar(self.schedule),), eligible_schedule=self.schedule)

        invalid_asset = self.bars[0].series.asset.model_copy(update={"currency": "INVALID"})
        invalid_series = self.bars[0].series.model_copy(update={"asset": invalid_asset})
        unsafe = self.bars[0].model_copy(update={"series": invalid_series, "close": Decimal("-1")})
        with self.assertRaisesRegex(DataQualityError, "integrity validation"):
            weekly_dual_ma_targets((unsafe, *self.bars[1:]), eligible_schedule=self.schedule)

        invalid_calendar = self.schedule.calendar.model_copy(update={"content_hash": "bad"})
        unsafe_schedule = self.schedule.model_copy(update={"calendar": invalid_calendar})
        with self.assertRaisesRegex(DataQualityError, "integrity validation"):
            weekly_dual_ma_targets(self.bars, eligible_schedule=unsafe_schedule)

    def test_calendar_and_label_policy_mismatches_fail_closed(self) -> None:
        other_calendar = CALENDAR.model_copy(update={"content_hash": "c" * 64})
        other_schedule = SessionSchedule.create(
            requested_start=self.schedule.requested_start,
            requested_end=self.schedule.requested_end,
            calendar=other_calendar,
            sessions=self.schedule.sessions,
        )
        with self.assertRaisesRegex(DataQualityError, "one calendar artifact"):
            weekly_dual_ma_targets(self.bars, eligible_schedule=other_schedule)

        values = CALENDAR.model_dump(mode="python")
        values["session_label_policy"] = SessionLabelPolicy.CALENDAR_DEFINED
        unsupported_calendar = CalendarArtifactRef.model_validate(values)
        unsupported_schedule = SessionSchedule.create(
            requested_start=self.schedule.requested_start,
            requested_end=self.schedule.requested_end,
            calendar=unsupported_calendar,
            sessions=self.schedule.sessions,
        )
        with self.assertRaisesRegex(DataQualityError, "close-local-date"):
            weekly_dual_ma_targets(self.bars, eligible_schedule=unsupported_schedule)
