"""Simple trend strategies used to establish golden timing semantics."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from itertools import pairwise

from quantverify.core.exceptions import DataQualityError
from quantverify.core.models import TargetPosition
from quantverify.data.models import NormalizedBar
from quantverify.features.moving_average import simple_moving_average


def price_above_sma_targets(
    bars: Sequence[NormalizedBar],
    *,
    window: int,
) -> tuple[TargetPosition, ...]:
    """Create long/flat targets at the next session open from close-based signals."""
    if len(bars) < 2:
        return ()
    asset = bars[0].asset
    if any(bar.asset != asset for bar in bars):
        raise DataQualityError("Strategy input must contain one identical asset")
    if any(left.session >= right.session for left, right in pairwise(bars)):
        raise DataQualityError("Strategy bars must be strictly ordered by session")

    averages = simple_moving_average(tuple(bar.close for bar in bars), window=window)
    targets: list[TargetPosition] = []
    for index, average in enumerate(averages[:-1]):
        if average is None:
            continue
        decision_bar = bars[index]
        next_bar = bars[index + 1]
        weight = Decimal("1") if decision_bar.close > average else Decimal("0")
        targets.append(
            TargetPosition(
                asset=asset,
                decision_at=decision_bar.session_close_at,
                effective_at=next_bar.session_open_at,
                weight=weight,
            )
        )
    return tuple(targets)
