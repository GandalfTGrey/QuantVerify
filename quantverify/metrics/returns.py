"""Small, engine-independent return and drawdown primitives."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal


def total_return(equity: Sequence[Decimal]) -> Decimal:
    """Return ``ending / starting - 1`` for a positive equity sequence."""
    _validate_equity(equity)
    return equity[-1] / equity[0] - Decimal("1")


def maximum_drawdown(equity: Sequence[Decimal]) -> Decimal:
    """Return the most negative value of ``equity / running_peak - 1``."""
    _validate_equity(equity)
    running_peak = equity[0]
    worst = Decimal("0")
    for value in equity:
        running_peak = max(running_peak, value)
        worst = min(worst, value / running_peak - Decimal("1"))
    return worst


def _validate_equity(equity: Sequence[Decimal]) -> None:
    if not equity:
        raise ValueError("equity must not be empty")
    if len(equity) == 1 and (equity[0] <= 0 or not equity[0].is_finite()):
        raise ValueError("single equity observation must be positive and finite")
    if any(value <= 0 or not value.is_finite() for value in equity[:-1]):
        raise ValueError("non-terminal equity values must be positive and finite")
    if equity[-1] < 0 or not equity[-1].is_finite():
        raise ValueError("terminal equity must be non-negative and finite")
