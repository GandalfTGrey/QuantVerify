"""Closed vocabularies used by core domain contracts."""

from enum import StrEnum


class AssetClass(StrEnum):
    EQUITY = "equity"
    ETF = "etf"
    INDEX = "index"
    FUTURE = "future"
    FX = "fx"
    CRYPTO = "crypto"
    CASH = "cash"


class BarFrequency(StrEnum):
    DAY = "1d"
    HOUR = "1h"
    MINUTE = "1m"


class DecisionTime(StrEnum):
    BAR_OPEN = "bar_open"
    BAR_CLOSE = "bar_close"


class ExecutionPrice(StrEnum):
    NEXT_OPEN = "next_open"
    NEXT_CLOSE = "next_close"
    NEXT_BAR_VWAP = "next_bar_vwap"


class AdjustmentMode(StrEnum):
    RAW = "raw"
    SPLIT_ADJUSTED = "split_adjusted"
    TOTAL_RETURN = "total_return"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
