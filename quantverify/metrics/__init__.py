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
    load_metric_input_v2,
    load_metric_set_v2,
)
from quantverify.metrics.v2_models import (
    AnnualizationPolicyV2,
    DecimalContextV1,
    EquityObservationV2,
    MetricCalculatorRef,
    MetricInputV2,
    MetricSetV2,
    MetricValueV2,
    RationalReturnObservation,
    RiskFreePolicyV2,
)

__all__ = [
    "AnnualizationPolicy",
    "AnnualizationPolicyV2",
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
    "MetricValueV2",
    "RationalReturnObservation",
    "ReturnBasis",
    "ReturnKind",
    "ReturnObservation",
    "RiskFreePolicy",
    "RiskFreePolicyV2",
    "RiskFreeRateKind",
    "calculate_metric_set",
    "calculate_metric_set_v2",
    "canonical_v2_bytes",
    "decimal_value_v1",
    "load_metric_input_v2",
    "load_metric_set_v2",
    "maximum_drawdown",
    "total_return",
]
