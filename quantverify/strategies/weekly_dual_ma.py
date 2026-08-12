"""Causal S3 weekly 13/40 dual-moving-average trend strategy."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal
from itertools import pairwise

from pydantic import ValidationError

from quantverify.core.enums import BarFrequency, SessionLabelPolicy
from quantverify.core.exceptions import DataQualityError
from quantverify.core.models import SessionSchedule, TargetPosition, TradingSession
from quantverify.data.models import DerivedPeriodBar
from quantverify.features.moving_average import simple_moving_average
from quantverify.research.frequency import require_complete_period_bars

S3_FAST_WINDOW = 13
S3_SLOW_WINDOW = 40


def weekly_dual_ma_targets(
    period_bars: Sequence[DerivedPeriodBar],
    *,
    eligible_schedule: SessionSchedule,
) -> tuple[TargetPosition, ...]:
    """Return fixed 13/40 weekly dual-MA targets at the next session open."""

    schedule = _revalidate_schedule(eligible_schedule)
    bars = require_complete_period_bars(period_bars)
    if not bars:
        return ()
    _validate_weekly_series(bars, schedule=schedule)
    execution_sessions = _execution_sessions(bars, schedule=schedule)
    if len(bars) < S3_SLOW_WINDOW:
        return ()

    closes = tuple(bar.close for bar in bars)
    fast_averages = simple_moving_average(closes, window=S3_FAST_WINDOW)
    slow_averages = simple_moving_average(closes, window=S3_SLOW_WINDOW)
    targets: list[TargetPosition] = []
    for index in range(S3_SLOW_WINDOW - 1, len(bars)):
        fast = fast_averages[index]
        slow = slow_averages[index]
        if fast is None or slow is None:
            raise DataQualityError("S3 moving-average warm-up state is inconsistent")
        next_session = execution_sessions[index]
        if next_session is None:
            raise DataQualityError("S3 requires the immediate next eligible session")
        dependencies = bars[index - S3_SLOW_WINDOW + 1 : index + 1]
        decision_at = max(bar.available_at for bar in dependencies)
        if decision_at >= next_session.session_open_at:
            raise DataQualityError(
                "S3 weekly dependencies are not available before the immediate next open"
            )
        targets.append(
            TargetPosition(
                asset=bars[index].series.asset,
                decision_at=decision_at,
                effective_at=next_session.session_open_at,
                weight=Decimal("1") if fast > slow else Decimal("0"),
            )
        )
    return tuple(targets)


def _revalidate_schedule(schedule: SessionSchedule) -> SessionSchedule:
    try:
        return SessionSchedule.model_validate(schedule.model_dump(mode="python"))
    except ValidationError as exc:
        raise DataQualityError("S3 eligible schedule failed integrity validation") from exc


def _validate_weekly_series(
    bars: tuple[DerivedPeriodBar, ...],
    *,
    schedule: SessionSchedule,
) -> None:
    descriptor = bars[0].series
    if descriptor.frequency is not BarFrequency.WEEK:
        raise DataQualityError("S3 requires weekly derived period bars")
    if schedule.calendar.session_label_policy is not SessionLabelPolicy.CLOSE_LOCAL_DATE:
        raise DataQualityError("S3 requires close-local-date eligible session labels")
    if descriptor.calendar != schedule.calendar:
        raise DataQualityError("S3 bars and eligible schedule must use one calendar artifact")
    if any(bar.series != descriptor for bar in bars):
        raise DataQualityError("S3 input must contain one immutable weekly series")
    for previous, current in pairwise(bars):
        if current.period_start != previous.period_start + timedelta(days=7):
            raise DataQualityError("S3 bars must cover consecutive Monday-Sunday weeks")


def _execution_sessions(
    bars: tuple[DerivedPeriodBar, ...],
    *,
    schedule: SessionSchedule,
) -> tuple[TradingSession | None, ...]:
    schedule_index = {item.session: index for index, item in enumerate(schedule.sessions)}
    results: list[TradingSession | None] = []
    for bar in bars:
        period_sessions = tuple(
            item
            for item in schedule.sessions
            if bar.period_start <= item.session <= bar.period_end
        )
        if period_sessions != bar.expected_schedule.sessions:
            raise DataQualityError(
                "S3 period sessions must exactly match the independent eligible schedule"
            )
        terminal_index = schedule_index[bar.expected_schedule.sessions[-1].session]
        next_index = terminal_index + 1
        results.append(
            schedule.sessions[next_index] if next_index < len(schedule.sessions) else None
        )
    return tuple(results)
