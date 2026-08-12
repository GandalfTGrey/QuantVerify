"""Momentum features with explicit lookback and warm-up semantics."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal


def trailing_total_return(
    closes: Sequence[Decimal],
    *,
    lookback: int,
) -> tuple[Decimal | None, ...]:
    """Return ``close[t] / close[t-lookback] - 1`` aligned to ``closes``."""

    if lookback <= 0:
        raise ValueError("lookback must be positive")
    if any(not close.is_finite() or close <= 0 for close in closes):
        raise ValueError("closes must be positive and finite")

    result: list[Decimal | None] = []
    for index, close in enumerate(closes):
        if index < lookback:
            result.append(None)
        else:
            result.append(close / closes[index - lookback] - Decimal("1"))
    return tuple(result)
