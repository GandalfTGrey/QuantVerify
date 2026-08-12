"""Causal S4 monthly ten-month SMA tactical-allocation strategy."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from itertools import pairwise

from pydantic import ValidationError

from quantverify.core.enums import BarFrequency, SessionLabelPolicy
from quantverify.core.exceptions import DataQualityError
from quantverify.core.models import SessionSchedule, TargetPosition, TradingSession
from quantverify.data.models import DerivedPeriodBar
from quantverify.features.moving_average import simple_moving_average
from quantverify.research.frequency import require_complete_period_bars

S4_MONTHLY_SMA_WINDOW = 10


def monthly_ten_month_sma_targets(
    period_bars: Sequence[DerivedPeriodBar],
    *,
    eligible_schedule: SessionSchedule,
) -> tuple[TargetPosition, ...]:
    """Return S4 long/flat targets at the next actual eligible-session open.

    The signal is risk-on only when the current monthly close is strictly above
    the inclusive trailing ten-month SMA. Every monthly dependency must be
    complete and independently covered by ``eligible_schedule``.
    """

    schedule = _revalidate_schedule(eligible_schedule)
    bars = require_complete_period_bars(period_bars)
    if not bars:
        return ()

    _validate_monthly_series(bars, schedule=schedule)
    execution_sessions = _execution_sessions(bars, schedule=schedule)
    averages = simple_moving_average(
        tuple(bar.close for bar in bars),
        window=S4_MONTHLY_SMA_WINDOW,
    )

    targets: list[TargetPosition] = []
    for index, average in enumerate(averages):
        if average is None:
            continue
        next_session = execution_sessions[index]
        if next_session is None:
            raise DataQualityError(
                "S4 requires the next eligible session after every signal month"
            )
        dependencies = bars[index - S4_MONTHLY_SMA_WINDOW + 1 : index + 1]
        decision_at = max(bar.available_at for bar in dependencies)
        if decision_at >= next_session.session_open_at:
            raise DataQualityError(
                "S4 monthly dependencies are not available before the next eligible open"
            )
        targets.append(
            TargetPosition(
                asset=bars[index].series.asset,
                decision_at=decision_at,
                effective_at=next_session.session_open_at,
                weight=Decimal("1") if bars[index].close > average else Decimal("0"),
            )
        )
    return tuple(targets)


def _revalidate_schedule(schedule: SessionSchedule) -> SessionSchedule:
    try:
        return SessionSchedule.model_validate(schedule.model_dump(mode="python"))
    except ValidationError as exc:
        raise DataQualityError("S4 eligible schedule failed integrity validation") from exc


def _validate_monthly_series(
    bars: tuple[DerivedPeriodBar, ...],
    *,
    schedule: SessionSchedule,
) -> None:
    descriptor = bars[0].series
    if descriptor.frequency is not BarFrequency.MONTH:
        raise DataQualityError("S4 requires monthly derived period bars")
    if schedule.calendar.session_label_policy is not SessionLabelPolicy.CLOSE_LOCAL_DATE:
        raise DataQualityError("S4 requires close-local-date eligible session labels")
    if descriptor.calendar != schedule.calendar:
        raise DataQualityError("S4 bars and eligible schedule must use one calendar artifact")
    if any(bar.series != descriptor for bar in bars):
        raise DataQualityError("S4 input must contain one immutable monthly series")

    for previous, current in pairwise(bars):
        if current.period_start != _next_month(previous.period_start):
            raise DataQualityError("S4 monthly bars must cover consecutive natural months")


def _execution_sessions(
    bars: tuple[DerivedPeriodBar, ...],
    *,
    schedule: SessionSchedule,
) -> tuple[TradingSession | None, ...]:
    schedule_index = {
        trading_session.session: index
        for index, trading_session in enumerate(schedule.sessions)
    }
    result: list[TradingSession | None] = []
    for bar in bars:
        eligible_period_sessions = tuple(
            trading_session
            for trading_session in schedule.sessions
            if bar.period_start <= trading_session.session <= bar.period_end
        )
        if eligible_period_sessions != bar.expected_schedule.sessions:
            raise DataQualityError(
                "S4 period sessions must exactly match the independent eligible schedule"
            )

        terminal_session = bar.expected_schedule.sessions[-1]
        terminal_index = schedule_index[terminal_session.session]
        next_index = terminal_index + 1
        result.append(
            schedule.sessions[next_index] if next_index < len(schedule.sessions) else None
        )
    return tuple(result)


def _next_month(month_start: date) -> date:
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1)
    return date(month_start.year, month_start.month + 1, 1)
