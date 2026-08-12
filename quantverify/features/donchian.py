"""Shifted Donchian channels with explicit warm-up semantics."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal


def prior_rolling_max(
    values: Sequence[Decimal],
    *,
    window: int,
) -> tuple[Decimal | None, ...]:
    """Return the maximum of the strictly prior ``window`` observations."""

    return _prior_rolling_extreme(values, window=window, use_max=True)


def prior_rolling_min(
    values: Sequence[Decimal],
    *,
    window: int,
) -> tuple[Decimal | None, ...]:
    """Return the minimum of the strictly prior ``window`` observations."""

    return _prior_rolling_extreme(values, window=window, use_max=False)


def _prior_rolling_extreme(
    values: Sequence[Decimal],
    *,
    window: int,
    use_max: bool,
) -> tuple[Decimal | None, ...]:
    if window <= 0:
        raise ValueError("window must be positive")
    if any(not value.is_finite() for value in values):
        raise ValueError("values must be finite")

    result: list[Decimal | None] = []
    extreme = max if use_max else min
    for index in range(len(values)):
        if index < window:
            result.append(None)
        else:
            result.append(extreme(values[index - window : index]))
    return tuple(result)
