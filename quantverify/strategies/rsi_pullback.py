"""Causal S1 daily RSI(2) pullback with SMA(200) trend filter."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from pydantic import ValidationError

from quantverify.core.enums import SessionLabelPolicy
from quantverify.core.exceptions import DataQualityError
from quantverify.core.models import SessionSchedule, TargetPosition
from quantverify.data.models import NormalizedBar
from quantverify.features.moving_average import simple_moving_average
from quantverify.features.rsi import wilder_rsi

S1_RSI_PERIOD = 2
S1_SMA_WINDOW = 200
S1_ENTRY_RSI = Decimal("10")
S1_EXIT_RSI = Decimal("70")


def daily_rsi2_pullback_targets(
    bars: Sequence[NormalizedBar],
    *,
    eligible_schedule: SessionSchedule,
) -> tuple[TargetPosition, ...]:
    """Return stateful S1 long/flat targets at immediate next session opens."""

    schedule = _revalidate_schedule(eligible_schedule)
    daily_bars = _revalidate_bars(bars)
    _validate_inputs(daily_bars, schedule=schedule)
    if len(daily_bars) < S1_SMA_WINDOW:
        return ()
    if len(schedule.sessions) <= len(daily_bars):
        raise DataQualityError("S1 requires an immediate next eligible session after the bars")

    closes = tuple(bar.close for bar in daily_bars)
    averages = simple_moving_average(closes, window=S1_SMA_WINDOW)
    strengths = wilder_rsi(closes, period=S1_RSI_PERIOD)
    is_long = False
    state_available_at = None
    targets: list[TargetPosition] = []
    for index in range(S1_SMA_WINDOW - 1, len(daily_bars)):
        average = averages[index]
        strength = strengths[index]
        if average is None or strength is None:
            raise DataQualityError("S1 feature warm-up state is inconsistent")
        current = daily_bars[index]
        if is_long:
            if strength > S1_EXIT_RSI:
                is_long = False
        elif strength < S1_ENTRY_RSI and current.close > average:
            is_long = True

        dependency_available_at = max(bar.available_at for bar in daily_bars[: index + 1])
        decision_at = (
            dependency_available_at
            if state_available_at is None
            else max(state_available_at, dependency_available_at)
        )
        state_available_at = decision_at
        next_session = schedule.sessions[index + 1]
        if decision_at >= next_session.session_open_at:
            raise DataQualityError(
                "S1 consumed state is not available before the immediate next session open"
            )
        targets.append(
            TargetPosition(
                asset=current.asset,
                decision_at=decision_at,
                effective_at=next_session.session_open_at,
                weight=Decimal("1") if is_long else Decimal("0"),
            )
        )
    return tuple(targets)


def _revalidate_schedule(schedule: SessionSchedule) -> SessionSchedule:
    try:
        return SessionSchedule.model_validate(schedule.model_dump(mode="python"))
    except ValidationError as exc:
        raise DataQualityError("S1 eligible schedule failed integrity validation") from exc


def _revalidate_bars(bars: Sequence[NormalizedBar]) -> tuple[NormalizedBar, ...]:
    try:
        return tuple(
            NormalizedBar.model_validate(bar.model_dump(mode="python")) for bar in bars
        )
    except ValidationError as exc:
        raise DataQualityError("S1 daily bars failed integrity validation") from exc


def _validate_inputs(
    bars: tuple[NormalizedBar, ...],
    *,
    schedule: SessionSchedule,
) -> None:
    if schedule.calendar.session_label_policy is not SessionLabelPolicy.CLOSE_LOCAL_DATE:
        raise DataQualityError("S1 requires close-local-date eligible session labels")
    if len(schedule.sessions) < len(bars):
        raise DataQualityError("S1 eligible schedule cannot be shorter than the daily bars")
    expected_prefix = schedule.sessions[: len(bars)]
    if tuple(bar.session for bar in bars) != tuple(item.session for item in expected_prefix):
        raise DataQualityError("S1 daily bars must exactly cover the eligible schedule prefix")
    for bar, trading_session in zip(bars, expected_prefix, strict=True):
        if (
            bar.session_open_at != trading_session.session_open_at
            or bar.session_close_at != trading_session.session_close_at
        ):
            raise DataQualityError("S1 daily bar timestamps must match the eligible schedule")
    if not bars:
        return
    asset = bars[0].asset
    source = bars[0].source
    if any(bar.asset != asset for bar in bars):
        raise DataQualityError("S1 input must contain one identical asset")
    if any(bar.source != source for bar in bars):
        raise DataQualityError("S1 input must contain one normalized data source")
