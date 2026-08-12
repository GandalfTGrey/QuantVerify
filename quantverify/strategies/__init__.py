"""Framework-independent strategy implementations."""

from quantverify.strategies.donchian import (
    S2_ENTRY_WINDOW,
    S2_EXIT_WINDOW,
    daily_donchian_targets,
)
from quantverify.strategies.monthly_sma import (
    S4_MONTHLY_SMA_WINDOW,
    monthly_ten_month_sma_targets,
)
from quantverify.strategies.trend import price_above_sma_targets
from quantverify.strategies.weekly_dual_ma import (
    S3_FAST_WINDOW,
    S3_SLOW_WINDOW,
    weekly_dual_ma_targets,
)

__all__ = [
    "S2_ENTRY_WINDOW",
    "S2_EXIT_WINDOW",
    "S3_FAST_WINDOW",
    "S3_SLOW_WINDOW",
    "S4_MONTHLY_SMA_WINDOW",
    "daily_donchian_targets",
    "monthly_ten_month_sma_targets",
    "price_above_sma_targets",
    "weekly_dual_ma_targets",
]
