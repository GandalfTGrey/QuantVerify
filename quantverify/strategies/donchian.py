"""Causal S2 daily 55/20 Donchian breakout strategy."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from pydantic import ValidationError

from quantverify.core.enums import SessionLabelPolicy
from quantverify.core.exceptions import DataQualityError
from quantverify.core.models import SessionSchedule, TargetPosition
from quantverify.data.models import NormalizedBar
from quantverify.features.donchian import prior_rolling_max, prior_rolling_min

S2_ENTRY_WINDOW = 55
S2_EXIT_WINDOW = 20


def daily_donchian_targets(
    bars: Sequence[NormalizedBar],
    *,
    eligible_schedule: SessionSchedule,
) -> tuple[TargetPosition, ...]:
    """Return stateful S2 long/flat targets at each immediate next session open."""

    schedule = _revalidate_schedule(eligible_schedule)
    daily_bars = _revalidate_bars(bars)
    _validate_inputs(daily_bars, schedule=schedule)
    if len(daily_bars) <= S2_ENTRY_WINDOW:
        return ()

    entry_channels = prior_rolling_max(
        tuple(bar.high for bar in daily_bars),
        window=S2_ENTRY_WINDOW,
    )
    exit_channels = prior_rolling_min(
        tuple(bar.low for bar in daily_bars),
        window=S2_EXIT_WINDOW,
    )

    is_long = False
    state_available_at = None
    targets: list[TargetPosition] = []
    for index in range(S2_ENTRY_WINDOW, len(daily_bars)):
        entry_channel = entry_channels[index]
        exit_channel = exit_channels[index]
        if entry_channel is None or exit_channel is None:
            raise DataQualityError("S2 channel warm-up state is inconsistent")

        decision_bar = daily_bars[index]
        if is_long:
            if decision_bar.close < exit_channel:
                is_long = False
        elif decision_bar.close > entry_channel:
            is_long = True

        dependencies = daily_bars[index - S2_ENTRY_WINDOW : index + 1]
        dependency_available_at = max(bar.available_at for bar in dependencies)
        decision_at = (
            dependency_available_at
            if state_available_at is None
            else max(state_available_at, dependency_available_at)
        )
        state_available_at = decision_at
        next_session = schedule.sessions[index + 1]
        if decision_at >= next_session.session_open_at:
            raise DataQualityError(
                "S2 consumed state is not available before the immediate next session open"
            )
        targets.append(
            TargetPosition(
                asset=decision_bar.asset,
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
        raise DataQualityError("S2 eligible schedule failed integrity validation") from exc


def _revalidate_bars(bars: Sequence[NormalizedBar]) -> tuple[NormalizedBar, ...]:
    try:
        return tuple(
            NormalizedBar.model_validate(bar.model_dump(mode="python")) for bar in bars
        )
    except ValidationError as exc:
        raise DataQualityError("S2 daily bars failed integrity validation") from exc


def _validate_inputs(
    bars: tuple[NormalizedBar, ...],
    *,
    schedule: SessionSchedule,
) -> None:
    if schedule.calendar.session_label_policy is not SessionLabelPolicy.CLOSE_LOCAL_DATE:
        raise DataQualityError("S2 requires close-local-date eligible session labels")
    if len(schedule.sessions) <= len(bars):
        raise DataQualityError("S2 requires an immediate next eligible session after the bars")
    expected_prefix = schedule.sessions[: len(bars)]
    if tuple(bar.session for bar in bars) != tuple(item.session for item in expected_prefix):
        raise DataQualityError("S2 daily bars must exactly cover the eligible schedule prefix")
    for bar, trading_session in zip(bars, expected_prefix, strict=True):
        if (
            bar.session_open_at != trading_session.session_open_at
            or bar.session_close_at != trading_session.session_close_at
        ):
            raise DataQualityError("S2 daily bar timestamps must match the eligible schedule")
    if not bars:
        return
    asset = bars[0].asset
    source = bars[0].source
    if any(bar.asset != asset for bar in bars):
        raise DataQualityError("S2 input must contain one identical asset")
    if any(bar.source != source for bar in bars):
        raise DataQualityError("S2 input must contain one normalized data source")
