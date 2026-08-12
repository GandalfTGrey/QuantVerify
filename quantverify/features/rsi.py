"""Wilder relative-strength index with explicit seed and edge semantics."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from itertools import pairwise

_HUNDRED = Decimal("100")
_FIFTY = Decimal("50")


def wilder_rsi(
    closes: Sequence[Decimal],
    *,
    period: int,
) -> tuple[Decimal | None, ...]:
    """Return RSI aligned to closes using Wilder arithmetic seed and recursion."""

    if period <= 0:
        raise ValueError("period must be positive")
    if any(not close.is_finite() or close <= 0 for close in closes):
        raise ValueError("closes must be positive and finite")
    if not closes:
        return ()

    result: list[Decimal | None] = [None] * min(period, len(closes))
    if len(closes) <= period:
        return tuple(result)

    gains: list[Decimal] = []
    losses: list[Decimal] = []
    for previous, current in pairwise(closes[: period + 1]):
        change = current - previous
        gains.append(max(change, Decimal("0")))
        losses.append(max(-change, Decimal("0")))
    divisor = Decimal(period)
    average_gain = sum(gains, Decimal("0")) / divisor
    average_loss = sum(losses, Decimal("0")) / divisor
    result.append(_rsi_value(average_gain, average_loss))

    for previous, current in pairwise(closes[period:]):
        change = current - previous
        gain = max(change, Decimal("0"))
        loss = max(-change, Decimal("0"))
        average_gain = (average_gain * Decimal(period - 1) + gain) / divisor
        average_loss = (average_loss * Decimal(period - 1) + loss) / divisor
        result.append(_rsi_value(average_gain, average_loss))
    return tuple(result)


def _rsi_value(average_gain: Decimal, average_loss: Decimal) -> Decimal:
    if average_loss == 0:
        return _FIFTY if average_gain == 0 else _HUNDRED
    if average_gain == 0:
        return Decimal("0")
    return _HUNDRED * average_gain / (average_gain + average_loss)
