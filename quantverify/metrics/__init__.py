"""Engine-independent, versioned performance metrics."""

from quantverify.metrics.calculator import calculate_metric_set
from quantverify.metrics.models import (
    AnnualizationPolicy,
    EquityObservation,
    MetricInput,
    MetricReason,
    MetricSet,
    MetricStatus,
    MetricValue,
    ReturnBasis,
    ReturnKind,
    ReturnObservation,
    RiskFreePolicy,
    RiskFreeRateKind,
)
from quantverify.metrics.returns import maximum_drawdown, total_return

__all__ = [
    "AnnualizationPolicy",
    "EquityObservation",
    "MetricInput",
    "MetricReason",
    "MetricSet",
    "MetricStatus",
    "MetricValue",
    "ReturnBasis",
    "ReturnKind",
    "ReturnObservation",
    "RiskFreePolicy",
    "RiskFreeRateKind",
    "calculate_metric_set",
    "maximum_drawdown",
    "total_return",
]
