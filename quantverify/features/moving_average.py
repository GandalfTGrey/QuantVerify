"""Moving averages with explicit warm-up semantics."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal


def simple_moving_average(
    values: Sequence[Decimal],
    *,
    window: int,
) -> tuple[Decimal | None, ...]:
    """Return an inclusive trailing SMA; warm-up values are ``None``."""
    if window <= 0:
        raise ValueError("window must be positive")
    if any(not value.is_finite() for value in values):
        raise ValueError("values must be finite")

    result: list[Decimal | None] = []
    rolling_sum = Decimal("0")
    for index, value in enumerate(values):
        rolling_sum += value
        if index >= window:
            rolling_sum -= values[index - window]
        if index + 1 < window:
            result.append(None)
        else:
            result.append(rolling_sum / Decimal(window))
    return tuple(result)
