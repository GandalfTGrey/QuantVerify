from __future__ import annotations

from datetime import date, datetime, timedelta
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
from quantverify.data.models import NormalizedBar
from quantverify.research.frequency import derive_period_bars, require_complete_period_bars

NY = ZoneInfo("America/New_York")
QQQ = AssetId(symbol="QQQ", venue="XNAS", asset_class=AssetClass.ETF, currency="USD")
DIA = AssetId(symbol="DIA", venue="ARCX", asset_class=AssetClass.ETF, currency="USD")
CALENDAR = CalendarArtifactRef(
    calendar_id="XNAS",
    calendar_version="test-2026a",
    timezone="America/New_York",
    session_label_policy=SessionLabelPolicy.CLOSE_LOCAL_DATE,
    source_id="verified-calendar-fixture",
    source_version="1",
    content_hash="c" * 64,
)


def trading_session(day: date, *, half_day: bool = False) -> TradingSession:
    close_hour = 13 if half_day else 16
    return TradingSession(
        session=day,
        session_open_at=datetime(day.year, day.month, day.day, 9, 30, tzinfo=NY),
        session_close_at=datetime(day.year, day.month, day.day, close_hour, 0, tzinfo=NY),
    )


def make_schedule(days: tuple[date, ...], *, start: date, end: date) -> SessionSchedule:
    sessions = tuple(
        trading_session(day, half_day=day == date(2026, 11, 27)) for day in days
    )
    return SessionSchedule.create(
        requested_start=start,
        requested_end=end,
        calendar=CALENDAR,
        sessions=sessions,
    )


def bar(session: TradingSession, *, index: int, asset: AssetId = QQQ) -> NormalizedBar:
    price = Decimal(100 + index)
    return NormalizedBar(
        asset=asset,
        session=session.session,
        session_open_at=session.session_open_at,
        session_close_at=session.session_close_at,
        available_at=session.session_close_at + timedelta(minutes=5),
        open=price,
        high=price + Decimal("2"),
        low=price - Decimal("1"),
        close=price + Decimal("1"),
        volume=Decimal(1000 + index),
        source="offline-fixture",
    )


def descriptor(frequency: BarFrequency) -> SeriesDescriptor:
    return SeriesDescriptor(
        asset=QQQ,
        frequency=frequency,
        adjustment_mode=AdjustmentMode.RAW,
        source_kind=SeriesSourceKind.FIXTURE,
        source_id="daily-bars-fixture",
        source_content_hash="d" * 64,
        source_schema_version="normalized-bar-v1",
        producer_id="qf01-calendar-ohlcv",
        producer_version="1",
        calendar=CALENDAR,
    )


def bars_for(schedule: SessionSchedule) -> tuple[NormalizedBar, ...]:
    return tuple(bar(item, index=index) for index, item in enumerate(schedule.sessions))


class WeeklyDerivationTests(TestCase):
    def test_holiday_short_week_is_complete_without_weekend_placeholders(self) -> None:
        days = tuple(date(2026, 1, day) for day in (20, 21, 22, 23))
        schedule = make_schedule(days, start=date(2026, 1, 19), end=date(2026, 1, 25))
        daily = bars_for(schedule)

        result = derive_period_bars(
            daily,
            expected_schedule=schedule,
            series=descriptor(BarFrequency.WEEK),
            cutoff_at=daily[-1].available_at,
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].completeness, PeriodCompleteness.COMPLETE)
        self.assertEqual(result[0].constituent_count, 4)
        self.assertEqual(result[0].open, daily[0].open)
        self.assertEqual(result[0].close, daily[-1].close)
        self.assertEqual(result[0].high, max(item.high for item in daily))
        self.assertEqual(result[0].low, min(item.low for item in daily))
        self.assertEqual(result[0].volume, sum(item.volume for item in daily))

    def test_dst_and_half_day_use_schedule_instants_without_fixed_clock_assumptions(self) -> None:
        dst_days = tuple(
            date(2026, 3, day)
            for day in (2, 3, 4, 5, 6, 9, 10, 11, 12, 13)
        )
        dst_schedule = make_schedule(
            dst_days,
            start=date(2026, 3, 2),
            end=date(2026, 3, 15),
        )
        thanksgiving_days = tuple(date(2026, 11, day) for day in (23, 24, 25, 27))
        half_day_schedule = make_schedule(
            thanksgiving_days,
            start=date(2026, 11, 23),
            end=date(2026, 11, 29),
        )

        dst = derive_period_bars(
            bars_for(dst_schedule),
            expected_schedule=dst_schedule,
            series=descriptor(BarFrequency.WEEK),
            cutoff_at=bars_for(dst_schedule)[-1].available_at,
        )
        half_day = derive_period_bars(
            bars_for(half_day_schedule),
            expected_schedule=half_day_schedule,
            series=descriptor(BarFrequency.WEEK),
            cutoff_at=bars_for(half_day_schedule)[-1].available_at,
        )[0]

        self.assertEqual(len(dst), 2)
        self.assertEqual(dst[0].period_open_at.utcoffset(), timedelta(hours=-5))
        self.assertEqual(dst[1].period_open_at.utcoffset(), timedelta(hours=-4))
        self.assertEqual(half_day.period_close_at.hour, 13)
        self.assertTrue(all(item.complete for item in dst))
        self.assertTrue(half_day.complete)

    def test_missing_final_session_distinguishes_cutoff_from_missing_data(self) -> None:
        days = tuple(date(2026, 1, day) for day in (5, 6, 7, 8, 9))
        schedule = make_schedule(days, start=date(2026, 1, 5), end=date(2026, 1, 11))
        daily = bars_for(schedule)[:-1]
        omitted = schedule.sessions[-1]

        partial = derive_period_bars(
            daily,
            expected_schedule=schedule,
            series=descriptor(BarFrequency.WEEK),
            cutoff_at=omitted.session_close_at - timedelta(seconds=1),
        )[0]
        missing = derive_period_bars(
            daily,
            expected_schedule=schedule,
            series=descriptor(BarFrequency.WEEK),
            cutoff_at=omitted.session_close_at + timedelta(minutes=10),
        )[0]

        self.assertEqual(partial.completeness, PeriodCompleteness.PARTIAL_CUTOFF)
        self.assertEqual(missing.completeness, PeriodCompleteness.INCOMPLETE_MISSING_DATA)

    def test_exact_close_with_unknown_publication_is_missing_not_future_complete(self) -> None:
        days = tuple(date(2026, 1, day) for day in (5, 6, 7, 8, 9))
        schedule = make_schedule(days, start=date(2026, 1, 5), end=date(2026, 1, 11))
        daily = bars_for(schedule)[:-1]

        result = derive_period_bars(
            daily,
            expected_schedule=schedule,
            series=descriptor(BarFrequency.WEEK),
            cutoff_at=schedule.sessions[-1].session_close_at,
        )[0]

        self.assertEqual(result.completeness, PeriodCompleteness.INCOMPLETE_MISSING_DATA)
        with self.assertRaisesRegex(DataQualityError, "requires COMPLETE"):
            require_complete_period_bars((result,))

    def test_middle_gap_is_rejected_instead_of_silently_filled(self) -> None:
        days = tuple(date(2026, 1, day) for day in (5, 6, 7, 8, 9))
        schedule = make_schedule(days, start=date(2026, 1, 5), end=date(2026, 1, 11))
        daily = bars_for(schedule)

        with self.assertRaisesRegex(DataQualityError, "exact prefix"):
            derive_period_bars(
                (*daily[:2], *daily[3:]),
                expected_schedule=schedule,
                series=descriptor(BarFrequency.WEEK),
                cutoff_at=daily[-1].available_at,
            )

    def test_truncating_future_only_changes_the_terminal_period(self) -> None:
        days = tuple(date(2026, 1, day) for day in (5, 6, 7, 8, 9, 12, 13, 14, 15, 16))
        schedule = make_schedule(days, start=date(2026, 1, 5), end=date(2026, 1, 18))
        daily = bars_for(schedule)
        full = derive_period_bars(
            daily,
            expected_schedule=schedule,
            series=descriptor(BarFrequency.WEEK),
            cutoff_at=daily[-1].available_at,
        )
        truncated = derive_period_bars(
            daily[:-1],
            expected_schedule=schedule,
            series=descriptor(BarFrequency.WEEK),
            cutoff_at=schedule.sessions[-1].session_close_at - timedelta(seconds=1),
        )

        self.assertEqual(full[0].period_bar_id, truncated[0].period_bar_id)
        self.assertEqual(full[0].cutoff_at, full[0].available_at)
        self.assertEqual(truncated[-1].completeness, PeriodCompleteness.PARTIAL_CUTOFF)

        first_week_only = derive_period_bars(
            daily[:5],
            expected_schedule=schedule,
            series=descriptor(BarFrequency.WEEK),
            cutoff_at=daily[4].available_at,
        )
        self.assertEqual(len(first_week_only), 1)
        self.assertEqual(first_week_only[0].period_bar_id, full[0].period_bar_id)

    def test_elapsed_week_with_no_observations_fails_closed(self) -> None:
        days = tuple(date(2026, 1, day) for day in (5, 6, 7, 8, 9, 12, 13, 14, 15, 16))
        schedule = make_schedule(days, start=date(2026, 1, 5), end=date(2026, 1, 18))
        daily = bars_for(schedule)

        with self.assertRaisesRegex(DataQualityError, "no daily observations"):
            derive_period_bars(
                daily[:5],
                expected_schedule=schedule,
                series=descriptor(BarFrequency.WEEK),
                cutoff_at=daily[-1].available_at,
            )

    def test_unobserved_future_week_is_not_fabricated(self) -> None:
        days = tuple(date(2026, 1, day) for day in (5, 6, 7, 8, 9, 12, 13, 14, 15, 16))
        schedule = make_schedule(days, start=date(2026, 1, 5), end=date(2026, 1, 18))
        daily = bars_for(schedule)

        result = derive_period_bars(
            daily[:5],
            expected_schedule=schedule,
            series=descriptor(BarFrequency.WEEK),
            cutoff_at=schedule.sessions[5].session_close_at - timedelta(seconds=1),
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].completeness, PeriodCompleteness.COMPLETE)

    def test_complete_gate_cannot_accept_range_with_wholly_missing_week(self) -> None:
        days = tuple(date(2026, 1, day) for day in (5, 6, 7, 8, 9, 12, 13, 14, 15, 16))
        schedule = make_schedule(days, start=date(2026, 1, 5), end=date(2026, 1, 18))
        daily = bars_for(schedule)

        with self.assertRaisesRegex(DataQualityError, "Elapsed expected period"):
            period_bars = derive_period_bars(
                daily[:5],
                expected_schedule=schedule,
                series=descriptor(BarFrequency.WEEK),
                cutoff_at=daily[-1].available_at,
            )
            require_complete_period_bars(period_bars)


class MonthlyDerivationTests(TestCase):
    def test_non_trading_month_end_uses_last_real_session(self) -> None:
        days = tuple(date(2026, 1, day) for day in (27, 28, 29, 30))
        schedule = make_schedule(days, start=date(2026, 1, 1), end=date(2026, 1, 31))
        daily = bars_for(schedule)

        result = derive_period_bars(
            daily,
            expected_schedule=schedule,
            series=descriptor(BarFrequency.MONTH),
            cutoff_at=daily[-1].available_at,
        )[0]

        self.assertTrue(result.complete)
        self.assertEqual(result.constituent_end, date(2026, 1, 30))
        self.assertEqual(result.period_end, date(2026, 1, 31))

    def test_elapsed_month_with_no_observations_fails_closed(self) -> None:
        days = tuple(
            date(2026, month, day)
            for month, month_days in ((1, (29, 30)), (2, (2, 3, 4, 5, 6)))
            for day in month_days
        )
        schedule = make_schedule(days, start=date(2026, 1, 1), end=date(2026, 2, 28))
        daily = bars_for(schedule)

        with self.assertRaisesRegex(DataQualityError, "no daily observations"):
            derive_period_bars(
                daily[:2],
                expected_schedule=schedule,
                series=descriptor(BarFrequency.MONTH),
                cutoff_at=daily[-1].available_at,
            )


class ContractValidationTests(TestCase):
    def setUp(self) -> None:
        days = tuple(date(2026, 1, day) for day in (5, 6, 7, 8, 9))
        self.schedule = make_schedule(days, start=date(2026, 1, 5), end=date(2026, 1, 11))
        self.bars = bars_for(self.schedule)

    def test_rejects_time_asset_descriptor_and_cutoff_mismatches(self) -> None:
        wrong_time = self.bars[0].model_copy(
            update={"session_open_at": self.bars[0].session_open_at + timedelta(minutes=1)}
        )
        wrong_asset = bar(self.schedule.sessions[0], index=0, asset=DIA)
        cases = (
            ((*self.bars[:0], wrong_time, *self.bars[1:]), descriptor(BarFrequency.WEEK)),
            ((wrong_asset, *self.bars[1:]), descriptor(BarFrequency.WEEK)),
            (self.bars, descriptor(BarFrequency.DAY)),
        )
        for daily, series in cases:
            with self.subTest(series=series.frequency), self.assertRaises(DataQualityError):
                derive_period_bars(
                    daily,
                    expected_schedule=self.schedule,
                    series=series,
                    cutoff_at=self.bars[-1].available_at,
                )

        with self.assertRaisesRegex(DataQualityError, "not available"):
            derive_period_bars(
                self.bars,
                expected_schedule=self.schedule,
                series=descriptor(BarFrequency.WEEK),
                cutoff_at=self.bars[-1].session_close_at,
            )

        mixed_source = self.bars[2].model_copy(update={"source": "other-fixture"})
        with self.assertRaisesRegex(DataQualityError, "must not mix"):
            derive_period_bars(
                (*self.bars[:2], mixed_source, *self.bars[3:]),
                expected_schedule=self.schedule,
                series=descriptor(BarFrequency.WEEK),
                cutoff_at=self.bars[-1].available_at,
            )

    def test_rejects_partial_expected_period_boundaries(self) -> None:
        partial_range = SessionSchedule.create(
            requested_start=date(2026, 1, 5),
            requested_end=date(2026, 1, 9),
            calendar=CALENDAR,
            sessions=self.schedule.sessions,
        )
        with self.assertRaisesRegex(DataQualityError, "complete period boundaries"):
            derive_period_bars(
                self.bars,
                expected_schedule=partial_range,
                series=descriptor(BarFrequency.WEEK),
                cutoff_at=self.bars[-1].available_at,
            )

    def test_default_research_gate_accepts_only_complete_periods(self) -> None:
        complete = derive_period_bars(
            self.bars,
            expected_schedule=self.schedule,
            series=descriptor(BarFrequency.WEEK),
            cutoff_at=self.bars[-1].available_at,
        )
        accepted = require_complete_period_bars(complete)
        self.assertEqual(accepted[0].period_bar_id, complete[0].period_bar_id)

        partial = derive_period_bars(
            self.bars[:-1],
            expected_schedule=self.schedule,
            series=descriptor(BarFrequency.WEEK),
            cutoff_at=self.schedule.sessions[-1].session_close_at - timedelta(seconds=1),
        )
        with self.assertRaisesRegex(DataQualityError, "partial_cutoff"):
            require_complete_period_bars(partial)

        unsafe = complete[0].model_copy(update={"close": Decimal("-1")})
        with self.assertRaisesRegex(DataQualityError, "integrity validation"):
            require_complete_period_bars((unsafe,))

    def test_public_boundary_revalidates_every_domain_input(self) -> None:
        weekly = descriptor(BarFrequency.WEEK)
        invalid_inputs = (
            (
                self.bars,
                self.schedule.model_copy(update={"content_hash": "bad"}),
                weekly,
                "schedule",
            ),
            (
                self.bars,
                self.schedule,
                weekly.model_copy(update={"source_content_hash": "bad"}),
                "descriptor",
            ),
            (
                (
                    self.bars[0].model_copy(update={"close": Decimal("-1")}),
                    *self.bars[1:],
                ),
                self.schedule,
                weekly,
                "bars",
            ),
        )
        for daily, schedule, series, message in invalid_inputs:
            with self.subTest(message=message), self.assertRaisesRegex(
                DataQualityError, message
            ):
                derive_period_bars(
                    daily,
                    expected_schedule=schedule,
                    series=series,
                    cutoff_at=self.bars[-1].available_at,
                )

    def test_empty_input_and_calendar_mismatch_fail_closed(self) -> None:
        with self.assertRaisesRegex(DataQualityError, "at least one"):
            derive_period_bars(
                (),
                expected_schedule=self.schedule,
                series=descriptor(BarFrequency.WEEK),
                cutoff_at=self.bars[-1].available_at,
            )

        other_calendar = CALENDAR.model_copy(update={"content_hash": "e" * 64})
        other_series = SeriesDescriptor.model_validate(
            {
                **descriptor(BarFrequency.WEEK).model_dump(mode="python"),
                "calendar": other_calendar,
            }
        )
        with self.assertRaisesRegex(DataQualityError, "one calendar artifact"):
            derive_period_bars(
                self.bars,
                expected_schedule=self.schedule,
                series=other_series,
                cutoff_at=self.bars[-1].available_at,
            )
