from __future__ import annotations

from calendar import monthrange
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
from quantverify.strategies import (
    S4_MONTHLY_SMA_WINDOW,
    monthly_ten_month_sma_targets,
)

NY = ZoneInfo("America/New_York")
QQQ = AssetId(symbol="QQQ", venue="XNAS", asset_class=AssetClass.ETF, currency="USD")
DIA = AssetId(symbol="DIA", venue="ARCX", asset_class=AssetClass.ETF, currency="USD")
CALENDAR = CalendarArtifactRef(
    calendar_id="SYNTHETIC-XNAS-S4",
    calendar_version="golden-2025a",
    timezone="America/New_York",
    session_label_policy=SessionLabelPolicy.CLOSE_LOCAL_DATE,
    source_id="offline-s4-calendar-fixture",
    source_version="1",
    content_hash="a" * 64,
)


def trading_session(day: date) -> TradingSession:
    close_time = time(13) if day == date(2025, 11, 28) else time(16)
    return TradingSession(
        session=day,
        session_open_at=datetime.combine(day, time(9, 30), tzinfo=NY),
        session_close_at=datetime.combine(day, close_time, tzinfo=NY),
    )


def weekday_sessions(start: date, end: date) -> tuple[TradingSession, ...]:
    days = (start + timedelta(days=offset) for offset in range((end - start).days + 1))
    return tuple(trading_session(day) for day in days if day.weekday() < 5)


def eligible_schedule(
    *,
    start: date = date(2025, 1, 1),
    end: date = date(2025, 12, 1),
) -> SessionSchedule:
    return SessionSchedule.create(
        requested_start=start,
        requested_end=end,
        calendar=CALENDAR,
        sessions=weekday_sessions(start, end),
    )


def descriptor(*, asset: AssetId = QQQ, source_hash: str = "b" * 64) -> SeriesDescriptor:
    return SeriesDescriptor(
        asset=asset,
        frequency=BarFrequency.MONTH,
        adjustment_mode=AdjustmentMode.RAW,
        source_kind=SeriesSourceKind.FIXTURE,
        source_id="s4-monthly-golden",
        source_content_hash=source_hash,
        source_schema_version="derived-period-bar-v1",
        producer_id="qf01-calendar-ohlcv",
        producer_version="1",
        calendar=CALENDAR,
    )


def period_bar(
    schedule: SessionSchedule,
    *,
    year: int,
    month: int,
    close: Decimal,
    series: SeriesDescriptor | None = None,
) -> DerivedPeriodBar:
    period_start = date(year, month, 1)
    period_end = date(year, month, monthrange(year, month)[1])
    sessions = tuple(
        item for item in schedule.sessions if period_start <= item.session <= period_end
    )
    period_schedule = SessionSchedule.create(
        requested_start=period_start,
        requested_end=period_end,
        calendar=schedule.calendar,
        sessions=sessions,
    )
    available_at = tuple(
        item.session_close_at + timedelta(minutes=5) for item in period_schedule.sessions
    )
    return DerivedPeriodBar(
        series=series or descriptor(),
        period_start=period_start,
        period_end=period_end,
        constituent_schedule=period_schedule,
        expected_schedule=period_schedule,
        constituent_available_at=available_at,
        cutoff_at=max(available_at),
        open=close,
        high=close + Decimal("1"),
        low=close,
        close=close,
        volume=Decimal("1000000"),
    )


def golden_bars(schedule: SessionSchedule) -> tuple[DerivedPeriodBar, ...]:
    closes = (*tuple(str(value) for value in range(10, 101, 10)), "1")
    bars = tuple(
        period_bar(schedule, year=2025, month=month, close=Decimal(close))
        for month, close in enumerate(closes, start=1)
    )
    january = bars[0]
    delayed_at = datetime(2025, 11, 3, 9, 0, tzinfo=NY)
    delayed_january = rebuild_bar(
        january,
        constituent_available_at=(*january.constituent_available_at[:-1], delayed_at),
        cutoff_at=delayed_at,
    )
    return (delayed_january, *bars[1:])


def rebuild_bar(bar: DerivedPeriodBar, **updates: object) -> DerivedPeriodBar:
    return DerivedPeriodBar.model_validate({**bar.model_dump(mode="python"), **updates})


def weekly_bar(schedule: SessionSchedule) -> DerivedPeriodBar:
    period_start = date(2025, 1, 6)
    period_end = date(2025, 1, 12)
    sessions = tuple(
        item for item in schedule.sessions if period_start <= item.session <= period_end
    )
    period_schedule = SessionSchedule.create(
        requested_start=period_start,
        requested_end=period_end,
        calendar=CALENDAR,
        sessions=sessions,
    )
    weekly_series = SeriesDescriptor.model_validate(
        {
            **descriptor().model_dump(mode="python"),
            "frequency": BarFrequency.WEEK,
        }
    )
    availability = tuple(item.session_close_at + timedelta(minutes=5) for item in sessions)
    return DerivedPeriodBar(
        series=weekly_series,
        period_start=period_start,
        period_end=period_end,
        constituent_schedule=period_schedule,
        expected_schedule=period_schedule,
        constituent_available_at=availability,
        cutoff_at=max(availability),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10"),
        volume=Decimal("1000"),
    )


class MonthlySmaGoldenTests(TestCase):
    def setUp(self) -> None:
        self.schedule = eligible_schedule()
        self.bars = golden_bars(self.schedule)

    def test_hand_calculated_inclusive_ten_month_signals(self) -> None:
        targets = monthly_ten_month_sma_targets(
            self.bars,
            eligible_schedule=self.schedule,
        )

        self.assertEqual(S4_MONTHLY_SMA_WINDOW, 10)
        self.assertEqual(len(targets), 2)
        self.assertEqual(
            sum((bar.close for bar in self.bars[:10]), Decimal("0")) / Decimal("10"),
            Decimal("55"),
        )
        self.assertEqual(
            sum((bar.close for bar in self.bars[1:11]), Decimal("0")) / Decimal("10"),
            Decimal("54.1"),
        )
        self.assertEqual(targets[0].weight, Decimal("1"))
        self.assertEqual(targets[1].weight, Decimal("0"))
        self.assertEqual(targets[0].effective_at, datetime(2025, 11, 3, 9, 30, tzinfo=NY))
        self.assertEqual(targets[1].effective_at, datetime(2025, 12, 1, 9, 30, tzinfo=NY))
        self.assertEqual(targets[0].decision_at, datetime(2025, 11, 3, 9, 0, tzinfo=NY))
        self.assertEqual(targets[1].decision_at, self.bars[10].available_at)
        self.assertEqual(targets[1].decision_at, datetime(2025, 11, 28, 13, 5, tzinfo=NY))

        equal_to_average = rebuild_bar(
            self.bars[9],
            open=Decimal("50"),
            high=Decimal("51"),
            low=Decimal("49"),
            close=Decimal("50"),
        )
        self.assertEqual(
            (sum((bar.close for bar in self.bars[:9]), Decimal("0")) + Decimal("50"))
            / Decimal("10"),
            Decimal("50"),
        )
        equal_target = monthly_ten_month_sma_targets(
            (*self.bars[:9], equal_to_average),
            eligible_schedule=self.schedule,
        )[0]
        self.assertEqual(equal_target.weight, Decimal("0"))

    def test_warmup_and_future_truncation_are_invariant(self) -> None:
        self.assertEqual(
            monthly_ten_month_sma_targets((), eligible_schedule=self.schedule),
            (),
        )
        self.assertEqual(
            monthly_ten_month_sma_targets(
                self.bars[:9],
                eligible_schedule=self.schedule,
            ),
            (),
        )
        full = monthly_ten_month_sma_targets(
            self.bars,
            eligible_schedule=self.schedule,
        )
        truncated = monthly_ten_month_sma_targets(
            self.bars[:10],
            eligible_schedule=self.schedule,
        )
        self.assertEqual(full[:1], truncated)

        extended_schedule = eligible_schedule(end=date(2026, 1, 2))
        extended = monthly_ten_month_sma_targets(
            self.bars,
            eligible_schedule=extended_schedule,
        )
        self.assertEqual(full, extended)

    def test_consecutive_month_validation_crosses_year_boundary(self) -> None:
        schedule = eligible_schedule(start=date(2024, 12, 1), end=date(2025, 2, 3))
        bars = (
            period_bar(schedule, year=2024, month=12, close=Decimal("10")),
            period_bar(schedule, year=2025, month=1, close=Decimal("11")),
        )
        self.assertEqual(
            monthly_ten_month_sma_targets(bars, eligible_schedule=schedule),
            (),
        )

    def test_positive_price_scaling_does_not_change_targets(self) -> None:
        scaled = tuple(
            rebuild_bar(
                bar,
                open=bar.open * 7,
                high=bar.high * 7,
                low=bar.low * 7,
                close=bar.close * 7,
            )
            for bar in self.bars
        )

        original = monthly_ten_month_sma_targets(
            self.bars,
            eligible_schedule=self.schedule,
        )
        transformed = monthly_ten_month_sma_targets(
            scaled,
            eligible_schedule=self.schedule,
        )
        self.assertEqual(
            tuple((item.decision_at, item.effective_at, item.weight) for item in original),
            tuple((item.decision_at, item.effective_at, item.weight) for item in transformed),
        )

    def test_latest_dependency_controls_decision_watermark(self) -> None:
        first_target_next_open = datetime(2025, 11, 3, 9, 30, tzinfo=NY)
        delayed_at = first_target_next_open - timedelta(minutes=1)
        first = self.bars[0]
        delayed = rebuild_bar(
            first,
            constituent_available_at=(*first.constituent_available_at[:-1], delayed_at),
            cutoff_at=delayed_at,
        )

        target = monthly_ten_month_sma_targets(
            (delayed, *self.bars[1:10]),
            eligible_schedule=self.schedule,
        )[0]
        self.assertEqual(target.decision_at, delayed_at)

    def test_only_the_inclusive_ten_month_window_controls_each_target(self) -> None:
        target = monthly_ten_month_sma_targets(
            self.bars[1:11],
            eligible_schedule=self.schedule,
        )[0]

        self.assertEqual(target.decision_at, self.bars[10].available_at)
        self.assertEqual(target.effective_at, datetime(2025, 12, 1, 9, 30, tzinfo=NY))


class MonthlySmaFailureTests(TestCase):
    def setUp(self) -> None:
        self.schedule = eligible_schedule()
        self.bars = golden_bars(self.schedule)

    def test_partial_and_missing_periods_fail_closed(self) -> None:
        complete = self.bars[9]
        omitted = complete.expected_schedule.sessions[-1]
        prefix = complete.expected_schedule.sessions[:-1]
        prefix_schedule = SessionSchedule.create(
            requested_start=complete.period_start,
            requested_end=complete.period_end,
            calendar=CALENDAR,
            sessions=prefix,
        )
        base_updates = {
            "constituent_schedule": prefix_schedule,
            "constituent_available_at": complete.constituent_available_at[:-1],
        }
        partial = rebuild_bar(
            complete,
            **base_updates,
            cutoff_at=omitted.session_close_at - timedelta(seconds=1),
        )
        missing = rebuild_bar(
            complete,
            **base_updates,
            cutoff_at=omitted.session_close_at,
        )

        self.assertEqual(partial.completeness, PeriodCompleteness.PARTIAL_CUTOFF)
        self.assertEqual(missing.completeness, PeriodCompleteness.INCOMPLETE_MISSING_DATA)
        for invalid in (partial, missing):
            with self.subTest(invalid=invalid.completeness), self.assertRaisesRegex(
                DataQualityError, "requires COMPLETE"
            ):
                monthly_ten_month_sma_targets(
                    (*self.bars[:9], invalid),
                    eligible_schedule=self.schedule,
                )

    def test_missing_month_and_mixed_series_fail_closed(self) -> None:
        with self.assertRaisesRegex(DataQualityError, "consecutive natural months"):
            monthly_ten_month_sma_targets(
                (*self.bars[:4], *self.bars[5:]),
                eligible_schedule=self.schedule,
            )

        with self.assertRaisesRegex(DataQualityError, "requires monthly"):
            monthly_ten_month_sma_targets(
                (weekly_bar(self.schedule),),
                eligible_schedule=self.schedule,
            )

        different_series = descriptor(asset=DIA, source_hash="c" * 64)
        mixed = rebuild_bar(self.bars[5], series=different_series)
        with self.assertRaisesRegex(DataQualityError, "one immutable monthly series"):
            monthly_ten_month_sma_targets(
                (*self.bars[:5], mixed, *self.bars[6:]),
                eligible_schedule=self.schedule,
            )

        different_source = descriptor(source_hash="c" * 64)
        source_mixed = rebuild_bar(self.bars[5], series=different_source)
        with self.assertRaisesRegex(DataQualityError, "one immutable monthly series"):
            monthly_ten_month_sma_targets(
                (*self.bars[:5], source_mixed, *self.bars[6:]),
                eligible_schedule=self.schedule,
            )

    def test_independent_schedule_must_exactly_cover_period_sessions(self) -> None:
        omitted = self.bars[5].expected_schedule.sessions[3]
        sessions = tuple(item for item in self.schedule.sessions if item != omitted)
        incomplete = SessionSchedule.create(
            requested_start=self.schedule.requested_start,
            requested_end=self.schedule.requested_end,
            calendar=CALENDAR,
            sessions=sessions,
        )

        with self.assertRaisesRegex(DataQualityError, "exactly match"):
            monthly_ten_month_sma_targets(
                self.bars,
                eligible_schedule=incomplete,
            )

    def test_schedule_calendar_mismatch_fails_closed(self) -> None:
        other_calendar = CALENDAR.model_copy(update={"content_hash": "d" * 64})
        other_schedule = SessionSchedule.create(
            requested_start=self.schedule.requested_start,
            requested_end=self.schedule.requested_end,
            calendar=other_calendar,
            sessions=self.schedule.sessions,
        )
        with self.assertRaisesRegex(DataQualityError, "one calendar artifact"):
            monthly_ten_month_sma_targets(
                self.bars,
                eligible_schedule=other_schedule,
            )

        calendar_values = CALENDAR.model_dump(mode="python")
        calendar_values["session_label_policy"] = SessionLabelPolicy.CALENDAR_DEFINED
        unsupported_calendar = CalendarArtifactRef.model_validate(calendar_values)
        unsupported_schedule = SessionSchedule.create(
            requested_start=self.schedule.requested_start,
            requested_end=self.schedule.requested_end,
            calendar=unsupported_calendar,
            sessions=self.schedule.sessions,
        )
        unsupported_series = SeriesDescriptor.model_validate(
            {
                **descriptor().model_dump(mode="python"),
                "calendar": unsupported_calendar,
            }
        )
        unsupported_bars = tuple(
            rebuild_bar(
                bar,
                series=unsupported_series,
                constituent_schedule=SessionSchedule.create(
                    requested_start=bar.period_start,
                    requested_end=bar.period_end,
                    calendar=unsupported_calendar,
                    sessions=bar.constituent_schedule.sessions,
                ),
                expected_schedule=SessionSchedule.create(
                    requested_start=bar.period_start,
                    requested_end=bar.period_end,
                    calendar=unsupported_calendar,
                    sessions=bar.expected_schedule.sessions,
                ),
            )
            for bar in self.bars
        )
        with self.assertRaisesRegex(DataQualityError, "close-local-date"):
            monthly_ten_month_sma_targets(
                unsupported_bars,
                eligible_schedule=unsupported_schedule,
            )

    def test_missing_next_eligible_session_fails_closed(self) -> None:
        terminal = self.bars[9].expected_schedule.sessions[-1]
        truncated_sessions = tuple(
            item for item in self.schedule.sessions if item.session <= terminal.session
        )
        truncated_schedule = SessionSchedule.create(
            requested_start=self.schedule.requested_start,
            requested_end=terminal.session,
            calendar=CALENDAR,
            sessions=truncated_sessions,
        )

        with self.assertRaisesRegex(DataQualityError, "next eligible session"):
            monthly_ten_month_sma_targets(
                self.bars[:10],
                eligible_schedule=truncated_schedule,
            )

    def test_dependency_available_at_or_after_next_open_fails_closed(self) -> None:
        first_target_next_open = datetime(2025, 11, 3, 9, 30, tzinfo=NY)
        first = self.bars[0]
        for delayed_at in (first_target_next_open, first_target_next_open + timedelta(seconds=1)):
            delayed = rebuild_bar(
                first,
                constituent_available_at=(*first.constituent_available_at[:-1], delayed_at),
                cutoff_at=delayed_at,
            )
            with self.subTest(delayed_at=delayed_at), self.assertRaisesRegex(
                DataQualityError, "not available"
            ):
                monthly_ten_month_sma_targets(
                    (delayed, *self.bars[1:10]),
                    eligible_schedule=self.schedule,
                )

    def test_unsafe_nested_bar_and_schedule_state_fail_at_public_boundary(self) -> None:
        invalid_asset = self.bars[0].series.asset.model_copy(update={"currency": "INVALID"})
        invalid_series = self.bars[0].series.model_copy(update={"asset": invalid_asset})
        unsafe_bar = self.bars[0].model_copy(
            update={"series": invalid_series, "close": Decimal("-1")}
        )
        with self.assertRaisesRegex(DataQualityError, "integrity validation"):
            monthly_ten_month_sma_targets(
                (unsafe_bar, *self.bars[1:]),
                eligible_schedule=self.schedule,
            )

        invalid_calendar = self.schedule.calendar.model_copy(update={"content_hash": "bad"})
        unsafe_schedule = self.schedule.model_copy(update={"calendar": invalid_calendar})
        with self.assertRaisesRegex(DataQualityError, "integrity validation"):
            monthly_ten_month_sma_targets(
                self.bars,
                eligible_schedule=unsafe_schedule,
            )
