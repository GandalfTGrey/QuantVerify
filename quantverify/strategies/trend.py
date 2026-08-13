"""Simple trend strategies used to establish golden timing semantics."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from pydantic import ValidationError

from quantverify.core.enums import SessionLabelPolicy
from quantverify.core.exceptions import DataQualityError
from quantverify.core.models import SessionSchedule, TargetPosition
from quantverify.core.numerics import fixture_execution_decimal
from quantverify.data.models import NormalizedBar
from quantverify.features.moving_average import simple_moving_average


def price_above_sma_targets(
    bars: Sequence[NormalizedBar],
    *,
    window: int,
    schedule: SessionSchedule,
) -> tuple[TargetPosition, ...]:
    """Create long/flat targets at the next session open from close-based signals."""
    try:
        schedule = SessionSchedule.model_validate(schedule.model_dump(mode="python"))
    except ValidationError as exc:
        raise DataQualityError("Strategy session schedule failed integrity validation") from exc
    try:
        bars = tuple(
            NormalizedBar.model_validate(bar.model_dump(mode="python")) for bar in bars
        )
    except ValidationError as exc:
        raise DataQualityError("Strategy bars failed integrity validation") from exc
    if schedule.calendar.session_label_policy is not SessionLabelPolicy.CLOSE_LOCAL_DATE:
        raise DataQualityError("SMA strategy v1 requires close-local-date session labels")
    bar_sessions = tuple(bar.session for bar in bars)
    expected_sessions = tuple(session.session for session in schedule.sessions)
    if bar_sessions != expected_sessions:
        raise DataQualityError("Strategy bars must exactly cover the supplied session schedule")

    for bar, session in zip(bars, schedule.sessions, strict=True):
        if (
            bar.session_open_at != session.session_open_at
            or bar.session_close_at != session.session_close_at
        ):
            raise DataQualityError("Strategy bar timestamps must match the session schedule")

    if len(bars) < 2:
        return ()
    asset = bars[0].asset
    if any(bar.asset != asset for bar in bars):
        raise DataQualityError("Strategy input must contain one identical asset")

    numerical_failure = False
    try:
        with fixture_execution_decimal():
            averages = simple_moving_average(tuple(bar.close for bar in bars), window=window)
    except ArithmeticError:
        numerical_failure = True
        averages = ()
    if numerical_failure:
        raise DataQualityError("SMA strategy numerical execution failed") from None
    targets: list[TargetPosition] = []
    for index, average in enumerate(averages[:-1]):
        if average is None:
            continue
        decision_bar = bars[index]
        next_session = schedule.sessions[index + 1]
        dependency_start = index - window + 1
        decision_at = max(
            bar.available_at for bar in bars[dependency_start : index + 1]
        )
        if decision_at >= next_session.session_open_at:
            raise DataQualityError("Signal is not available before the next session open")
        weight = Decimal("1") if decision_bar.close > average else Decimal("0")
        targets.append(
            TargetPosition(
                asset=asset,
                decision_at=decision_at,
                effective_at=next_session.session_open_at,
                weight=weight,
            )
        )
    return tuple(targets)
