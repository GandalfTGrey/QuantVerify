from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
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
from quantverify.features import wilder_rsi
from quantverify.strategies import (
    S1_ENTRY_RSI,
    S1_EXIT_RSI,
    S1_RSI_PERIOD,
    S1_SMA_WINDOW,
    daily_rsi2_pullback_targets,
)

NY = ZoneInfo("America/New_York")
QQQ = AssetId(symbol="QQQ", venue="XNAS", asset_class=AssetClass.ETF, currency="USD")
DIA = AssetId(symbol="DIA", venue="ARCX", asset_class=AssetClass.ETF, currency="USD")
CALENDAR = CalendarArtifactRef(
    calendar_id="SYNTHETIC-XNAS-S1",
    calendar_version="golden-v1",
    timezone="America/New_York",
    session_label_policy=SessionLabelPolicy.CLOSE_LOCAL_DATE,
    source_id="offline-s1-calendar-fixture",
    source_version="1",
    content_hash="a" * 64,
)


def sessions(count: int) -> tuple[TradingSession, ...]:
    result: list[TradingSession] = []
    day = date(2024, 6, 3)
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


def schedule(count: int = 203) -> SessionSchedule:
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
    close: Decimal,
    index: int,
    asset: AssetId = QQQ,
    source: str = "s1-golden",
    available_at: datetime | None = None,
) -> NormalizedBar:
    return NormalizedBar(
        asset=asset,
        session=trading_session.session,
        session_open_at=trading_session.session_open_at,
        session_close_at=trading_session.session_close_at,
        available_at=available_at or trading_session.session_close_at + timedelta(minutes=5),
        open=close,
        high=close + Decimal("1"),
        low=close,
        close=close,
        volume=Decimal(1000 + index),
        source=source,
    )


def golden_bars(eligible: SessionSchedule) -> tuple[NormalizedBar, ...]:
    closes = (
        *tuple(Decimal(100 + index) for index in range(197)),
        Decimal("300"),
        Decimal("290"),
        Decimal("280"),
        Decimal("281"),
        Decimal("320"),
    )
    return tuple(
        bar(item, close=close, index=index)
        for index, (item, close) in enumerate(zip(eligible.sessions, closes, strict=False))
    )


def rebuild_bar(item: NormalizedBar, **updates: object) -> NormalizedBar:
    return NormalizedBar.model_validate({**item.model_dump(mode="python"), **updates})


class WilderRsiTests(TestCase):
    def test_seed_and_recursion_are_hand_calculated(self) -> None:
        result = wilder_rsi(
            tuple(Decimal(value) for value in (100, 102, 101, 105)),
            period=2,
        )
        self.assertEqual(result[:2], (None, None))
        self.assertEqual(result[2], Decimal("66.66666666666666666666666667"))
        self.assertEqual(result[3], Decimal("90.90909090909090909090909091"))

    def test_zero_fifty_and_hundred_edges(self) -> None:
        cases = (
            (("1", "1", "1"), Decimal("50")),
            (("1", "2", "3"), Decimal("100")),
            (("3", "2", "1"), Decimal("0")),
        )
        for values, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(
                    wilder_rsi(tuple(Decimal(value) for value in values), period=2)[2],
                    expected,
                )

    def test_alignment_warmup_threshold_values_and_validation(self) -> None:
        self.assertEqual(wilder_rsi((), period=2), ())
        self.assertEqual(wilder_rsi((Decimal("1"), Decimal("2")), period=2), (None, None))
        self.assertEqual(
            wilder_rsi((Decimal("100"), Decimal("101"), Decimal("92")), period=2)[2],
            Decimal("10"),
        )
        self.assertEqual(
            wilder_rsi((Decimal("100"), Decimal("107"), Decimal("104")), period=2)[2],
            Decimal("70"),
        )
        with self.assertRaisesRegex(ValueError, "positive"):
            wilder_rsi((Decimal("1"),), period=0)
        with self.assertRaisesRegex(ValueError, "positive and finite"):
            wilder_rsi((Decimal("NaN"),), period=2)


class DailyRsiPullbackGoldenTests(TestCase):
    def setUp(self) -> None:
        self.schedule = schedule()
        self.bars = golden_bars(self.schedule)

    def test_hand_calculated_entry_hold_exit_path(self) -> None:
        strengths = wilder_rsi(tuple(item.close for item in self.bars), period=2)
        targets = daily_rsi2_pullback_targets(self.bars, eligible_schedule=self.schedule)

        self.assertEqual((S1_RSI_PERIOD, S1_SMA_WINDOW), (2, 200))
        self.assertEqual((S1_ENTRY_RSI, S1_EXIT_RSI), (Decimal("10"), Decimal("70")))
        self.assertLess(strengths[199] or Decimal("100"), Decimal("10"))
        self.assertGreater(self.bars[199].close, sum(item.close for item in self.bars[:200]) / 200)
        self.assertGreater(strengths[201] or Decimal("0"), Decimal("70"))
        self.assertEqual(tuple(target.weight for target in targets), (
            Decimal("1"), Decimal("1"), Decimal("0")
        ))
        self.assertEqual(targets[0].effective_at, self.schedule.sessions[200].session_open_at)

    def test_199_warmup_and_200_first_target_boundary(self) -> None:
        self.assertEqual(
            daily_rsi2_pullback_targets((), eligible_schedule=self.schedule),
            (),
        )
        exact_warmup = schedule(199)
        self.assertEqual(
            daily_rsi2_pullback_targets(self.bars[:199], eligible_schedule=exact_warmup),
            (),
        )
        with self.assertRaisesRegex(DataQualityError, "immediate next"):
            daily_rsi2_pullback_targets(self.bars[:200], eligible_schedule=schedule(200))
        self.assertEqual(
            len(daily_rsi2_pullback_targets(self.bars[:200], eligible_schedule=schedule(201))),
            1,
        )
        with self.assertRaisesRegex(DataQualityError, "cannot be shorter"):
            daily_rsi2_pullback_targets(self.bars[:199], eligible_schedule=schedule(198))

    def test_trend_filter_blocks_oversold_entry(self) -> None:
        weak = rebuild_bar(
            self.bars[199],
            open=Decimal("1"),
            high=Decimal("2"),
            low=Decimal("1"),
            close=Decimal("1"),
        )
        target = daily_rsi2_pullback_targets(
            (*self.bars[:199], weak),
            eligible_schedule=self.schedule,
        )[0]
        self.assertEqual(target.weight, Decimal("0"))

    def test_strict_rsi_threshold_equality_preserves_state(self) -> None:
        entry_tie_closes = (*tuple(Decimal(100 + index) for index in range(199)), Decimal("289"))
        self.assertEqual(wilder_rsi(entry_tie_closes, period=2)[-1], Decimal("10"))
        entry_tie_bars = tuple(
            bar(item, close=close, index=index)
            for index, (item, close) in enumerate(
                zip(self.schedule.sessions, entry_tie_closes, strict=False)
            )
        )
        self.assertEqual(
            daily_rsi2_pullback_targets(
                entry_tie_bars,
                eligible_schedule=self.schedule,
            )[0].weight,
            Decimal("0"),
        )

        exit_tie = rebuild_bar(
            self.bars[200],
            open=Decimal("296.875"),
            high=Decimal("297.875"),
            low=Decimal("296.875"),
            close=Decimal("296.875"),
        )
        exit_tie_bars = (*self.bars[:200], exit_tie)
        self.assertEqual(
            wilder_rsi(tuple(item.close for item in exit_tie_bars), period=2)[-1],
            Decimal("70"),
        )
        self.assertEqual(
            tuple(
                target.weight
                for target in daily_rsi2_pullback_targets(
                    exit_tie_bars,
                    eligible_schedule=self.schedule,
                )
            ),
            (Decimal("1"), Decimal("1")),
        )

    def test_truncation_extension_and_positive_scaling_are_invariant(self) -> None:
        full = daily_rsi2_pullback_targets(self.bars, eligible_schedule=self.schedule)
        truncated = daily_rsi2_pullback_targets(self.bars[:200], eligible_schedule=self.schedule)
        self.assertEqual(full[:1], truncated)
        self.assertEqual(
            full,
            daily_rsi2_pullback_targets(self.bars, eligible_schedule=schedule(205)),
        )
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
        transformed = daily_rsi2_pullback_targets(scaled, eligible_schedule=self.schedule)
        self.assertEqual(
            tuple((item.decision_at, item.effective_at, item.weight) for item in full),
            tuple((item.decision_at, item.effective_at, item.weight) for item in transformed),
        )

    def test_ancient_recursive_dependency_controls_watermark(self) -> None:
        next_open = self.schedule.sessions[200].session_open_at
        delayed_at = next_open - timedelta(minutes=1)
        delayed = rebuild_bar(self.bars[0], available_at=delayed_at)
        targets = daily_rsi2_pullback_targets(
            (delayed, *self.bars[1:]),
            eligible_schedule=self.schedule,
        )
        self.assertEqual(targets[0].decision_at, delayed_at)

        late = rebuild_bar(self.bars[0], available_at=next_open)
        with self.assertRaisesRegex(DataQualityError, "not available"):
            daily_rsi2_pullback_targets(
                (late, *self.bars[1:200]),
                eligible_schedule=self.schedule,
            )


class DailyRsiPullbackFailureTests(TestCase):
    def setUp(self) -> None:
        self.schedule = schedule()
        self.bars = golden_bars(self.schedule)

    def test_missing_or_shifted_session_fails_closed(self) -> None:
        with self.assertRaisesRegex(DataQualityError, "exactly cover"):
            daily_rsi2_pullback_targets(
                (*self.bars[:20], *self.bars[21:]),
                eligible_schedule=self.schedule,
            )
        shifted = rebuild_bar(
            self.bars[20],
            session_open_at=self.bars[20].session_open_at + timedelta(minutes=1),
        )
        with self.assertRaisesRegex(DataQualityError, "timestamps"):
            daily_rsi2_pullback_targets(
                (*self.bars[:20], shifted, *self.bars[21:]),
                eligible_schedule=self.schedule,
            )

    def test_mixed_asset_source_and_unsafe_state_fail_closed(self) -> None:
        mixed_asset = rebuild_bar(self.bars[10], asset=DIA)
        with self.assertRaisesRegex(DataQualityError, "identical asset"):
            daily_rsi2_pullback_targets(
                (*self.bars[:10], mixed_asset, *self.bars[11:]),
                eligible_schedule=self.schedule,
            )
        mixed_source = rebuild_bar(self.bars[10], source="other")
        with self.assertRaisesRegex(DataQualityError, "one normalized data source"):
            daily_rsi2_pullback_targets(
                (*self.bars[:10], mixed_source, *self.bars[11:]),
                eligible_schedule=self.schedule,
            )

        invalid_asset = self.bars[0].asset.model_copy(update={"currency": "INVALID"})
        unsafe = self.bars[0].model_copy(update={"asset": invalid_asset, "close": Decimal("-1")})
        with self.assertRaisesRegex(DataQualityError, "integrity validation"):
            daily_rsi2_pullback_targets(
                (unsafe, *self.bars[1:]),
                eligible_schedule=self.schedule,
            )

        invalid_calendar = self.schedule.calendar.model_copy(update={"content_hash": "bad"})
        unsafe_schedule = self.schedule.model_copy(update={"calendar": invalid_calendar})
        with self.assertRaisesRegex(DataQualityError, "integrity validation"):
            daily_rsi2_pullback_targets(self.bars, eligible_schedule=unsafe_schedule)

    def test_unapproved_label_policy_fails_closed(self) -> None:
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
            daily_rsi2_pullback_targets(self.bars, eligible_schedule=unsupported)
