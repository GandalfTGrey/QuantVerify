"""Framework-independent strategy implementations."""

from quantverify.strategies.donchian import (
    S2_ENTRY_WINDOW,
    S2_EXIT_WINDOW,
    daily_donchian_targets,
)
from quantverify.strategies.dual_momentum import (
    S5_HURDLE_POLICY_ID,
    S5_LOOKBACK_MONTHS,
    S5_SIGNAL_SCHEMA_VERSION,
    S5_STRATEGY_VERSION,
    S5_ZERO_HURDLE,
    DualMomentumReason,
    DualMomentumSignal,
    monthly_dual_momentum_signals,
)
from quantverify.strategies.monthly_sma import (
    S4_MONTHLY_SMA_WINDOW,
    monthly_ten_month_sma_targets,
)
from quantverify.strategies.rsi_pullback import (
    S1_ENTRY_RSI,
    S1_EXIT_RSI,
    S1_RSI_PERIOD,
    S1_SMA_WINDOW,
    daily_rsi2_pullback_targets,
)
from quantverify.strategies.trend import price_above_sma_targets
from quantverify.strategies.weekly_dual_ma import (
    S3_FAST_WINDOW,
    S3_SLOW_WINDOW,
    weekly_dual_ma_targets,
)

__all__ = [
    "S1_ENTRY_RSI",
    "S1_EXIT_RSI",
    "S1_RSI_PERIOD",
    "S1_SMA_WINDOW",
    "S2_ENTRY_WINDOW",
    "S2_EXIT_WINDOW",
    "S3_FAST_WINDOW",
    "S3_SLOW_WINDOW",
    "S4_MONTHLY_SMA_WINDOW",
    "S5_HURDLE_POLICY_ID",
    "S5_LOOKBACK_MONTHS",
    "S5_SIGNAL_SCHEMA_VERSION",
    "S5_STRATEGY_VERSION",
    "S5_ZERO_HURDLE",
    "DualMomentumReason",
    "DualMomentumSignal",
    "daily_donchian_targets",
    "daily_rsi2_pullback_targets",
    "monthly_dual_momentum_signals",
    "monthly_ten_month_sma_targets",
    "price_above_sma_targets",
    "weekly_dual_ma_targets",
]
