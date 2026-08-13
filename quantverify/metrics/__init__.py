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
from quantverify.metrics.v2_calculator import calculate_metric_set_v2
from quantverify.metrics.v2_identity import (
    MetricV2ContractError,
    canonical_v2_bytes,
    decimal_value_v1,
)
from quantverify.metrics.v2_models import (
    DecimalContextV1,
    EquityObservationV2,
    MetricCalculatorRef,
    MetricInputV2,
    MetricSetV2,
    RationalReturnObservation,
)

__all__ = [
    "AnnualizationPolicy",
    "DecimalContextV1",
    "EquityObservation",
    "EquityObservationV2",
    "MetricCalculatorRef",
    "MetricInput",
    "MetricInputV2",
    "MetricReason",
    "MetricSet",
    "MetricSetV2",
    "MetricStatus",
    "MetricV2ContractError",
    "MetricValue",
    "RationalReturnObservation",
    "ReturnBasis",
    "ReturnKind",
    "ReturnObservation",
    "RiskFreePolicy",
    "RiskFreeRateKind",
    "calculate_metric_set",
    "calculate_metric_set_v2",
    "canonical_v2_bytes",
    "decimal_value_v1",
    "maximum_drawdown",
    "total_return",
]
