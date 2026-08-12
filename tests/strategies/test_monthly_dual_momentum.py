from __future__ import annotations

from calendar import monthrange
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from unittest import TestCase
from zoneinfo import ZoneInfo

from pydantic import ValidationError

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
from quantverify.features import trailing_total_return
from quantverify.strategies import (
    S5_HURDLE_POLICY_ID,
    S5_LOOKBACK_MONTHS,
    S5_SIGNAL_SCHEMA_VERSION,
    S5_STRATEGY_VERSION,
    S5_ZERO_HURDLE,
    DualMomentumReason,
    DualMomentumSignal,
    monthly_dual_momentum_signals,
)

NY = ZoneInfo("America/New_York")
QQQ = AssetId(symbol="QQQ", venue="XNAS", asset_class=AssetClass.ETF, currency="USD")
DIA = AssetId(symbol="DIA", venue="ARCX", asset_class=AssetClass.ETF, currency="USD")
SPY = AssetId(symbol="SPY", venue="ARCX", asset_class=AssetClass.ETF, currency="USD")
CALENDAR = CalendarArtifactRef(
    calendar_id="SYNTHETIC-US-S5",
    calendar_version="golden-2024a",
    timezone="America/New_York",
    session_label_policy=SessionLabelPolicy.CLOSE_LOCAL_DATE,
    source_id="offline-s5-calendar-fixture",
    source_version="1",
    content_hash="a" * 64,
)


def next_month(month_start: date) -> date:
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1)
    return date(month_start.year, month_start.month + 1, 1)


def month_sequence(start: date, count: int) -> tuple[date, ...]:
    result = [start]
    for _ in range(count - 1):
        result.append(next_month(result[-1]))
    return tuple(result)


def month_sessions(month_start: date, *, calendar: CalendarArtifactRef) -> SessionSchedule:
    period_end = date(
        month_start.year,
        month_start.month,
        monthrange(month_start.year, month_start.month)[1],
    )
    days = (
        month_start + timedelta(days=offset)
        for offset in range((period_end - month_start).days + 1)
    )
    sessions = tuple(
        TradingSession(
            session=day,
            session_open_at=datetime.combine(day, time(9, 30), tzinfo=NY),
            session_close_at=datetime.combine(day, time(16), tzinfo=NY),
        )
        for day in days
        if day.weekday() < 5
    )
    return SessionSchedule.create(
        requested_start=month_start,
        requested_end=period_end,
        calendar=calendar,
        sessions=sessions,
    )


def descriptor(
    asset: AssetId,
    *,
    adjustment: AdjustmentMode = AdjustmentMode.TOTAL_RETURN,
    calendar: CalendarArtifactRef = CALENDAR,
    source_kind: SeriesSourceKind = SeriesSourceKind.FIXTURE,
    schema_version: str = "derived-period-bar-v1",
    producer_id: str = "qf01-calendar-ohlcv",
    producer_version: str = "1",
) -> SeriesDescriptor:
    return SeriesDescriptor(
        asset=asset,
        frequency=BarFrequency.MONTH,
        adjustment_mode=adjustment,
        source_kind=source_kind,
        source_id=f"s5-{asset.symbol.lower()}-monthly-golden",
        source_content_hash=("b" if asset.symbol == "QQQ" else "c") * 64,
        source_schema_version=schema_version,
        producer_id=producer_id,
        producer_version=producer_version,
        calendar=calendar,
    )


def period_bar(
    series: SeriesDescriptor,
    *,
    month_start: date,
    close: Decimal,
) -> DerivedPeriodBar:
    schedule = month_sessions(month_start, calendar=series.calendar)
    availability = tuple(
        session.session_close_at + timedelta(minutes=5) for session in schedule.sessions
    )
    return DerivedPeriodBar(
        series=series,
        period_start=schedule.requested_start,
        period_end=schedule.requested_end,
        constituent_schedule=schedule,
        expected_schedule=schedule,
        constituent_available_at=availability,
        cutoff_at=max(availability),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=Decimal("1000000"),
    )


def series_bars(
    asset: AssetId,
    closes: tuple[Decimal, ...],
    *,
    start: date = date(2024, 1, 1),
    series: SeriesDescriptor | None = None,
) -> tuple[DerivedPeriodBar, ...]:
    resolved = series or descriptor(asset)
    return tuple(
        period_bar(resolved, month_start=month, close=close)
        for month, close in zip(month_sequence(start, len(closes)), closes, strict=True)
    )


def rebuild_bar(bar: DerivedPeriodBar, **updates: object) -> DerivedPeriodBar:
    return DerivedPeriodBar.model_validate({**bar.model_dump(mode="python"), **updates})


def replace_close(bar: DerivedPeriodBar, close: Decimal) -> DerivedPeriodBar:
    return rebuild_bar(bar, open=close, high=close, low=close, close=close)


def weekly_bar(asset: AssetId) -> DerivedPeriodBar:
    period_start = date(2024, 1, 1)
    period_end = date(2024, 1, 7)
    sessions = tuple(
        TradingSession(
            session=day,
            session_open_at=datetime.combine(day, time(9, 30), tzinfo=NY),
            session_close_at=datetime.combine(day, time(16), tzinfo=NY),
        )
        for day in (date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4))
    )
    schedule = SessionSchedule.create(
        requested_start=period_start,
        requested_end=period_end,
        calendar=CALENDAR,
        sessions=sessions,
    )
    monthly = descriptor(asset)
    weekly = SeriesDescriptor.model_validate(
        {**monthly.model_dump(mode="python"), "frequency": BarFrequency.WEEK}
    )
    availability = tuple(item.session_close_at + timedelta(minutes=5) for item in sessions)
    return DerivedPeriodBar(
        series=weekly,
        period_start=period_start,
        period_end=period_end,
        constituent_schedule=schedule,
        expected_schedule=schedule,
        constituent_available_at=availability,
        cutoff_at=max(availability),
        open=Decimal("100"),
        high=Decimal("100"),
        low=Decimal("100"),
        close=Decimal("100"),
        volume=Decimal("1000"),
    )


class TrailingTotalReturnTests(TestCase):
    def test_hand_calculated_alignment_and_warmup(self) -> None:
        closes = (Decimal("100"), Decimal("50"), Decimal("125"))
        self.assertEqual(
            trailing_total_return(closes, lookback=2),
            (None, None, Decimal("0.25")),
        )
        self.assertEqual(trailing_total_return((), lookback=12), ())

    def test_validation_is_explicit(self) -> None:
        with self.assertRaisesRegex(ValueError, "lookback"):
            trailing_total_return((Decimal("1"),), lookback=0)
        for invalid in (Decimal("0"), Decimal("-1"), Decimal("NaN")):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                ValueError, "positive and finite"
            ):
                trailing_total_return((Decimal("1"), invalid), lookback=1)


class MonthlyDualMomentumGoldenTests(TestCase):
    def setUp(self) -> None:
        self.qqq = series_bars(QQQ, (Decimal("100"),) * 12 + (Decimal("120"),))
        self.dia = series_bars(DIA, (Decimal("100"),) * 12 + (Decimal("110"),))

    def test_12_month_warmup_and_hand_calculated_qqq_win(self) -> None:
        self.assertEqual(S5_LOOKBACK_MONTHS, 12)
        self.assertEqual(monthly_dual_momentum_signals((self.qqq[:12], self.dia[:12])), ())

        signals = monthly_dual_momentum_signals((self.qqq, self.dia))

        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal.qqq_return, Decimal("0.2"))
        self.assertEqual(signal.dia_return, Decimal("0.1"))
        self.assertEqual(signal.qqq_asset, QQQ)
        self.assertEqual(signal.dia_asset, DIA)
        self.assertEqual(signal.selected_asset, QQQ)
        self.assertEqual(signal.reason, DualMomentumReason.RISK_ON)
        self.assertEqual(signal.observed_period_start, date(2025, 1, 1))
        self.assertEqual(signal.observed_period_end, date(2025, 1, 31))
        self.assertEqual(
            signal.decision_at,
            max(self.qqq[-1].available_at, self.dia[-1].available_at),
        )

    def test_dia_win_cash_tie_and_hurdle_equality(self) -> None:
        dia_win = monthly_dual_momentum_signals(
            (
                self.qqq,
                (*self.dia[:-1], replace_close(self.dia[-1], Decimal("130"))),
            )
        )[0]
        self.assertEqual(dia_win.selected_asset, DIA)
        self.assertEqual(dia_win.reason, DualMomentumReason.RISK_ON)

        hurdle_equal = monthly_dual_momentum_signals(
            (
                (*self.qqq[:-1], replace_close(self.qqq[-1], Decimal("100"))),
                (*self.dia[:-1], replace_close(self.dia[-1], Decimal("90"))),
            )
        )[0]
        self.assertEqual(hurdle_equal.qqq_return, Decimal("0"))
        self.assertIsNone(hurdle_equal.selected_asset)
        self.assertEqual(hurdle_equal.reason, DualMomentumReason.CASH)

        both_negative = monthly_dual_momentum_signals(
            (
                (*self.qqq[:-1], replace_close(self.qqq[-1], Decimal("80"))),
                (*self.dia[:-1], replace_close(self.dia[-1], Decimal("90"))),
            )
        )[0]
        self.assertIsNone(both_negative.selected_asset)
        self.assertEqual(both_negative.reason, DualMomentumReason.CASH)

        tie = monthly_dual_momentum_signals(
            (
                (*self.qqq[:-1], replace_close(self.qqq[-1], Decimal("110"))),
                self.dia,
            )
        )[0]
        self.assertEqual(tie.qqq_return, tie.dia_return)
        self.assertIsNone(tie.selected_asset)
        self.assertEqual(tie.reason, DualMomentumReason.TIE)

    def test_exact_tie_is_input_order_invariant(self) -> None:
        tied_qqq = (*self.qqq[:-1], replace_close(self.qqq[-1], Decimal("110")))
        forward = monthly_dual_momentum_signals((tied_qqq, self.dia))[0]
        reverse = monthly_dual_momentum_signals((self.dia, tied_qqq))[0]

        self.assertEqual(forward, reverse)
        self.assertEqual(forward.signal_id, reverse.signal_id)
        self.assertEqual(forward.reason, DualMomentumReason.TIE)

    def test_signal_contract_is_versioned_and_has_no_execution_claim(self) -> None:
        signal = monthly_dual_momentum_signals((self.qqq, self.dia))[0]
        values = signal.model_dump(mode="python")

        self.assertIsInstance(signal, DualMomentumSignal)
        self.assertEqual(signal.schema_version, S5_SIGNAL_SCHEMA_VERSION)
        self.assertEqual(signal.strategy_version, S5_STRATEGY_VERSION)
        self.assertEqual(signal.hurdle, S5_ZERO_HURDLE)
        self.assertEqual(signal.hurdle_policy_id, S5_HURDLE_POLICY_ID)
        self.assertTrue(signal.signal_id.startswith("dual-momentum-signal_"))
        self.assertNotIn("effective_at", values)
        self.assertNotIn("weight", values)
        self.assertNotIn("execution_session", values)

        utc_equivalent = DualMomentumSignal.model_validate(
            {**values, "decision_at": signal.decision_at.astimezone(UTC)}
        )
        self.assertEqual(signal.signal_id, utc_equivalent.signal_id)

        unsafe = signal.model_copy(update={"hurdle": Decimal("1")})
        with self.assertRaisesRegex(ValidationError, "zero hurdle"):
            _ = unsafe.signal_id

        bogus_qqq = QQQ.model_copy(update={"venue": "BOGUS"})
        unsafe_universe = signal.model_copy(update={"qqq_asset": bogus_qqq})
        with self.assertRaisesRegex(ValidationError, "canonical QQQ"):
            _ = unsafe_universe.signal_id

        wrong_full_selected = signal.model_copy(
            update={"selected_asset": QQQ.model_copy(update={"venue": "ARCX"})}
        )
        with self.assertRaisesRegex(ValidationError, "winning asset"):
            _ = wrong_full_selected.signal_id

    def test_signal_model_rejects_inconsistent_standalone_state(self) -> None:
        signal = monthly_dual_momentum_signals((self.qqq, self.dia))[0]
        values = signal.model_dump(mode="python")
        invalid_cases = (
            ({"observed_period_end": date(2025, 1, 30)}, "natural month"),
            ({"decision_at": datetime(2025, 2, 1, 12)}, "timezone-aware"),
            ({"qqq_return": Decimal("NaN")}, "finite"),
            ({"dia_return": Decimal("NaN")}, "finite"),
            ({"qqq_return": Decimal("-1")}, "greater than -1"),
            ({"dia_return": Decimal("-1.01")}, "greater than -1"),
            (
                {
                    "qqq_return": Decimal("0.1"),
                    "dia_return": Decimal("0.1"),
                    "reason": DualMomentumReason.RISK_ON,
                    "selected_asset": QQQ,
                },
                "tie/no selection",
            ),
            (
                {
                    "qqq_return": Decimal("0"),
                    "dia_return": Decimal("-0.1"),
                    "reason": DualMomentumReason.CASH,
                    "selected_asset": QQQ,
                },
                "cash/no selection",
            ),
        )
        for updates, message in invalid_cases:
            with self.subTest(updates=updates), self.assertRaisesRegex(
                ValidationError, message
            ):
                DualMomentumSignal.model_validate({**values, **updates})

    def test_weekend_natural_month_end_uses_last_real_session_availability(self) -> None:
        qqq = series_bars(
            QQQ,
            (Decimal("100"),) * 12 + (Decimal("120"),),
            start=date(2024, 8, 1),
        )
        dia = series_bars(
            DIA,
            (Decimal("100"),) * 12 + (Decimal("110"),),
            start=date(2024, 8, 1),
        )

        signal = monthly_dual_momentum_signals((qqq, dia))[0]

        self.assertEqual(signal.observed_period_end, date(2025, 8, 31))
        self.assertEqual(signal.decision_at.astimezone(NY).date(), date(2025, 8, 29))
        self.assertEqual(
            signal.decision_at,
            max(qqq[-1].available_at, dia[-1].available_at),
        )

    def test_full_26_bar_window_controls_decision_watermark(self) -> None:
        qqq = series_bars(QQQ, (Decimal("100"),) * 13 + (Decimal("121"),))
        dia = series_bars(DIA, (Decimal("100"),) * 13 + (Decimal("111"),))
        delayed_at = datetime(2025, 3, 1, 12, tzinfo=NY)
        ancient = qqq[0]
        delayed = rebuild_bar(
            ancient,
            constituent_available_at=(*ancient.constituent_available_at[:-1], delayed_at),
            cutoff_at=delayed_at,
        )

        signals = monthly_dual_momentum_signals(((delayed, *qqq[1:]), dia))

        self.assertEqual(signals[0].decision_at, delayed_at)
        self.assertEqual(
            signals[1].decision_at,
            max(qqq[13].available_at, dia[13].available_at),
        )
        self.assertLess(signals[1].decision_at, signals[0].decision_at)

    def test_truncation_future_changes_and_independent_scaling_are_invariant(self) -> None:
        qqq = series_bars(
            QQQ,
            (Decimal("100"),) * 12 + (Decimal("120"), Decimal("125"), Decimal("130")),
        )
        dia = series_bars(
            DIA,
            (Decimal("100"),) * 12 + (Decimal("110"), Decimal("112"), Decimal("115")),
        )
        full = monthly_dual_momentum_signals((qqq, dia))
        truncated = monthly_dual_momentum_signals((qqq[:13], dia[:13]))
        self.assertEqual(full[:1], truncated)

        changed_future = (
            *qqq[:-1],
            replace_close(qqq[-1], Decimal("1")),
        )
        changed = monthly_dual_momentum_signals((changed_future, dia))
        self.assertEqual(full[:2], changed[:2])

        scaled_qqq = tuple(
            replace_close(bar, bar.close * Decimal("3")) for bar in qqq
        )
        scaled_dia = tuple(
            replace_close(bar, bar.close * Decimal("7")) for bar in dia
        )
        scaled = monthly_dual_momentum_signals((scaled_qqq, scaled_dia))
        self.assertEqual(full, scaled)

    def test_signal_identity_is_semantic_and_lineage_is_external(self) -> None:
        original = monthly_dual_momentum_signals((self.qqq, self.dia))[0]
        alternate_qqq_descriptor = SeriesDescriptor.model_validate(
            {
                **self.qqq[0].series.model_dump(mode="python"),
                "source_content_hash": "e" * 64,
            }
        )
        alternate_qqq = tuple(
            rebuild_bar(bar, series=alternate_qqq_descriptor) for bar in self.qqq
        )
        alternate = monthly_dual_momentum_signals((alternate_qqq, self.dia))[0]

        self.assertNotEqual(
            self.qqq[0].series.descriptor_id,
            alternate_qqq[0].series.descriptor_id,
        )
        self.assertEqual(original, alternate)
        self.assertEqual(original.signal_id, alternate.signal_id)


class MonthlyDualMomentumFailureTests(TestCase):
    def setUp(self) -> None:
        self.qqq = series_bars(QQQ, (Decimal("100"),) * 12 + (Decimal("120"),))
        self.dia = series_bars(DIA, (Decimal("100"),) * 12 + (Decimal("110"),))

    def test_requires_exactly_two_non_empty_series(self) -> None:
        for invalid in ((self.qqq,), (self.qqq, self.dia, self.qqq)):
            with self.subTest(count=len(invalid)), self.assertRaisesRegex(
                DataQualityError, "exactly two"
            ):
                monthly_dual_momentum_signals(invalid)
        with self.assertRaisesRegex(DataQualityError, "non-empty"):
            monthly_dual_momentum_signals(((), ()))

        with self.assertRaisesRegex(DataQualityError, "monthly"):
            monthly_dual_momentum_signals(((weekly_bar(QQQ),), (weekly_bar(DIA),)))

    def test_requires_explicit_distinct_qqq_and_dia_usd_etfs(self) -> None:
        spy = series_bars(SPY, (Decimal("100"),) * 13)
        with self.assertRaisesRegex(DataQualityError, "distinct QQQ and DIA"):
            monthly_dual_momentum_signals((self.qqq, spy))

        crypto_qqq = AssetId(
            symbol="QQQ",
            venue="TEST",
            asset_class=AssetClass.CRYPTO,
            currency="USD",
        )
        fake = series_bars(crypto_qqq, (Decimal("100"),) * 13)
        with self.assertRaisesRegex(DataQualityError, "canonical QQQ and DIA"):
            monthly_dual_momentum_signals((fake, self.dia))

        wrong_venue_qqq = AssetId(
            symbol="QQQ",
            venue="ARCX",
            asset_class=AssetClass.ETF,
            currency="USD",
        )
        wrong_venue = series_bars(wrong_venue_qqq, (Decimal("100"),) * 13)
        with self.assertRaisesRegex(DataQualityError, "canonical QQQ and DIA"):
            monthly_dual_momentum_signals((wrong_venue, self.dia))

    def test_missing_month_length_and_period_misalignment_fail_closed(self) -> None:
        with self.assertRaisesRegex(DataQualityError, "equal aligned length"):
            monthly_dual_momentum_signals((self.qqq, self.dia[:-1]))

        with self.assertRaisesRegex(DataQualityError, "consecutive natural months"):
            monthly_dual_momentum_signals(
                ((*self.qqq[:5], *self.qqq[6:]), (*self.dia[:5], *self.dia[6:]))
            )

        shifted_dia = series_bars(
            DIA,
            (Decimal("100"),) * 12 + (Decimal("110"),),
            start=date(2024, 2, 1),
        )
        with self.assertRaisesRegex(DataQualityError, "exactly aligned"):
            monthly_dual_momentum_signals((self.qqq, shifted_dia))

    def test_incomplete_and_exact_schedule_mismatch_fail_closed(self) -> None:
        complete = self.dia[-1]
        omitted = complete.expected_schedule.sessions[-1]
        prefix = complete.expected_schedule.sessions[:-1]
        prefix_schedule = SessionSchedule.create(
            requested_start=complete.period_start,
            requested_end=complete.period_end,
            calendar=CALENDAR,
            sessions=prefix,
        )
        partial = rebuild_bar(
            complete,
            constituent_schedule=prefix_schedule,
            constituent_available_at=complete.constituent_available_at[:-1],
            cutoff_at=omitted.session_close_at - timedelta(seconds=1),
        )
        self.assertEqual(partial.completeness, PeriodCompleteness.PARTIAL_CUTOFF)
        with self.assertRaisesRegex(DataQualityError, "requires COMPLETE"):
            monthly_dual_momentum_signals((self.qqq, (*self.dia[:-1], partial)))

        internally_complete_but_different = rebuild_bar(
            complete,
            constituent_schedule=prefix_schedule,
            expected_schedule=prefix_schedule,
            constituent_available_at=complete.constituent_available_at[:-1],
            cutoff_at=max(complete.constituent_available_at[:-1]),
        )
        self.assertEqual(
            internally_complete_but_different.completeness,
            PeriodCompleteness.COMPLETE,
        )
        with self.assertRaisesRegex(DataQualityError, "exact expected schedule"):
            monthly_dual_momentum_signals(
                (self.qqq, (*self.dia[:-1], internally_complete_but_different))
            )

    def test_adjustment_calendar_producer_and_schema_mismatches_fail_closed(self) -> None:
        raw_dia = series_bars(
            DIA,
            (Decimal("100"),) * 13,
            series=descriptor(DIA, adjustment=AdjustmentMode.RAW),
        )
        with self.assertRaisesRegex(DataQualityError, "TOTAL_RETURN"):
            monthly_dual_momentum_signals((self.qqq, raw_dia))

        other_calendar = CalendarArtifactRef.model_validate(
            {**CALENDAR.model_dump(mode="python"), "content_hash": "d" * 64}
        )
        semantic_variants = (
            descriptor(DIA, calendar=other_calendar),
            descriptor(DIA, producer_version="2"),
            descriptor(DIA, schema_version="derived-period-bar-v2"),
            descriptor(DIA, source_kind=SeriesSourceKind.DATASET_RELEASE),
        )
        for variant in semantic_variants:
            invalid_dia = series_bars(DIA, (Decimal("100"),) * 13, series=variant)
            with self.subTest(variant=variant), self.assertRaisesRegex(
                DataQualityError, "share source kind, schema, producer"
            ):
                monthly_dual_momentum_signals((self.qqq, invalid_dia))

    def test_mixed_descriptor_and_unsafe_nested_state_fail_closed(self) -> None:
        changed = descriptor(QQQ, producer_version="2")
        mixed = rebuild_bar(self.qqq[5], series=changed)
        with self.assertRaisesRegex(DataQualityError, "one immutable series descriptor"):
            monthly_dual_momentum_signals(
                ((*self.qqq[:5], mixed, *self.qqq[6:]), self.dia)
            )

        invalid_asset = self.qqq[0].series.asset.model_copy(update={"currency": "INVALID"})
        invalid_series = self.qqq[0].series.model_copy(update={"asset": invalid_asset})
        unsafe_nested = self.qqq[0].model_copy(update={"series": invalid_series})
        unsafe_close = self.qqq[0].model_copy(update={"close": Decimal("-1")})
        for invalid in (unsafe_nested, unsafe_close):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                DataQualityError, "integrity validation"
            ):
                monthly_dual_momentum_signals(
                    ((invalid, *self.qqq[1:]), self.dia)
                )
