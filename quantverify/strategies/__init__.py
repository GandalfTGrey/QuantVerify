"""Framework-independent strategy implementations."""

from quantverify.strategies.monthly_sma import (
    S4_MONTHLY_SMA_WINDOW,
    monthly_ten_month_sma_targets,
)
from quantverify.strategies.trend import price_above_sma_targets

__all__ = [
    "S4_MONTHLY_SMA_WINDOW",
    "monthly_ten_month_sma_targets",
    "price_above_sma_targets",
]
