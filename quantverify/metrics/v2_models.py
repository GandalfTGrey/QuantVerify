"""Exact, replayable Metrics v2 domain contracts."""

from __future__ import annotations

import decimal
import math
from datetime import date
from decimal import Decimal
from fractions import Fraction
from itertools import pairwise
from typing import Annotated, Final, Literal

from pydantic import BeforeValidator, Field, StrictInt, model_validator

from quantverify.core.enums import BarFrequency
from quantverify.core.models import SessionSchedule
from quantverify.metrics.models import (
    MetricModel,
    MetricReason,
    MetricStatus,
    ReturnBasis,
    RiskFreeRateKind,
)
from quantverify.metrics.v2_identity import (
    MetricV2ContractError,
    parse_decimal_value_v1,
    require_v2_decimal,
    v2_content_hash,
)

MAX_V2_ROWS: Final = 10_000
MAX_RATIONAL_BITS: Final = 4_096
SUPPORTED_LIBMPDEC_VERSIONS: Final = frozenset({"2.5.1", "4.0.0"})

V2Decimal = Annotated[
    Decimal,
    BeforeValidator(parse_decimal_value_v1),
    Field(strict=True, allow_inf_nan=False),
]


class EquityObservationV2(MetricModel):
    observed_on: date
    equity: V2Decimal

    @model_validator(mode="after")
    def validate_decimal_domain(self) -> EquityObservationV2:
        require_v2_decimal(self.equity)
        if self.equity < 0:
            raise ValueError("equity must be non-negative")
        return self


class RationalReturnObservation(MetricModel):
    observed_on: date
    numerator: StrictInt
    denominator: StrictInt = Field(gt=0)

    @model_validator(mode="after")
    def validate_reduced_fraction(self) -> RationalReturnObservation:
        if abs(self.numerator).bit_length() > MAX_RATIONAL_BITS:
            raise ValueError("rational numerator exceeds the bit limit")
        if self.denominator.bit_length() > MAX_RATIONAL_BITS:
            raise ValueError("rational denominator exceeds the bit limit")
        if math.gcd(self.numerator, self.denominator) != 1:
            raise ValueError("rational return must be in lowest terms")
        if self.numerator < -self.denominator:
            raise ValueError("simple return must be greater than or equal to -1")
        return self

    @property
    def fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)


class DecimalContextV1(MetricModel):
    context_id: Literal["decimal-context-v1"] = "decimal-context-v1"
    precision: Literal[34] = 34
    rounding: Literal["ROUND_HALF_EVEN"] = "ROUND_HALF_EVEN"
    emin: Literal[-999999] = -999999
    emax: Literal[999999] = 999999
    capitals: Literal[1] = 1
    clamp: Literal[0] = 0
    invalid_operation_trap: Literal[True] = True
    float_operation_trap: Literal[True] = True
    division_by_zero_trap: Literal[True] = True
    overflow_trap: Literal[True] = True
    underflow_trap: Literal[False] = False
    subnormal_trap: Literal[False] = False
    inexact_trap: Literal[False] = False
    rounded_trap: Literal[False] = False
    clamped_trap: Literal[False] = False


class AnnualizationPolicyV2(MetricModel):
    policy_id: str = Field(min_length=1, max_length=128)
    periods_per_year: V2Decimal
    days_per_year: V2Decimal

    @model_validator(mode="after")
    def validate_positive_values(self) -> AnnualizationPolicyV2:
        for value in (self.periods_per_year, self.days_per_year):
            require_v2_decimal(value)
            if value <= 0:
                raise ValueError("annualization values must be positive")
        return self


class RiskFreePolicyV2(MetricModel):
    policy_id: str = Field(min_length=1, max_length=128)
    kind: RiskFreeRateKind
    rate: V2Decimal
    source_id: str = Field(min_length=1, max_length=128)
    source_version: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_rate(self) -> RiskFreePolicyV2:
        require_v2_decimal(self.rate)
        if self.rate <= Decimal("-1"):
            raise ValueError("risk-free rate must be greater than -1")
        return self


class MetricValueV2(MetricModel):
    status: MetricStatus
    value: V2Decimal | None = None
    reason: MetricReason | None = None

    @model_validator(mode="after")
    def validate_state(self) -> MetricValueV2:
        undefined_reasons = {
            MetricReason.INSUFFICIENT_EQUITY_OBSERVATIONS,
            MetricReason.INSUFFICIENT_RETURN_OBSERVATIONS,
            MetricReason.NON_POSITIVE_ELAPSED_TIME,
            MetricReason.ZERO_VOLATILITY,
        }
        if self.status is MetricStatus.VALID:
            if self.value is None or self.reason is not None:
                raise ValueError("valid metric requires a value and no reason")
            require_v2_decimal(self.value)
        elif self.status is MetricStatus.UNDEFINED:
            if self.value is not None or self.reason not in undefined_reasons:
                raise ValueError("undefined metric state is invalid")
        elif self.value is not None or self.reason is not MetricReason.NUMERIC_ERROR:
            raise ValueError("failure metric state is invalid")
        return self


class MetricCalculatorRef(MetricModel):
    calculator_id: Literal["quantverify-metrics-v2"] = "quantverify-metrics-v2"
    calculator_version: Literal["1"] = "1"
    metric_set_schema_version: Literal["metrics-v2"] = "metrics-v2"
    decimal_context: DecimalContextV1 = DecimalContextV1()
    backend_id: Literal["python-decimal/libmpdec"] = "python-decimal/libmpdec"
    backend_version: str = Field(min_length=1, max_length=32)

    @classmethod
    def baseline(cls) -> MetricCalculatorRef:
        return cls(backend_version=decimal.__libmpdec_version__)

    @model_validator(mode="after")
    def validate_backend(self) -> MetricCalculatorRef:
        DecimalContextV1.model_validate(self.decimal_context.model_dump(mode="python"))
        if self.backend_version not in SUPPORTED_LIBMPDEC_VERSIONS:
            raise ValueError("unsupported libmpdec backend version")
        return self


class MetricInputV2(MetricModel):
    schema_version: Literal["metric-input-v2"] = "metric-input-v2"
    frequency: Literal[BarFrequency.DAY] = BarFrequency.DAY
    schedule: SessionSchedule
    return_basis: ReturnBasis
    annualization: AnnualizationPolicyV2
    volatility_ddof: StrictInt = Field(ge=0)
    risk_free: RiskFreePolicyV2
    opening_equity_convention: Literal["first-close-flat-v1"] = "first-close-flat-v1"
    return_derivation_id: Literal["equity-ratio-rational"] = "equity-ratio-rational"
    return_derivation_version: Literal["1"] = "1"
    equity: tuple[EquityObservationV2, ...] = Field(min_length=2, max_length=MAX_V2_ROWS)
    returns: tuple[RationalReturnObservation, ...] = Field(
        min_length=1,
        max_length=MAX_V2_ROWS - 1,
    )

    @classmethod
    def from_equity(
        cls,
        *,
        schedule: SessionSchedule,
        return_basis: ReturnBasis,
        annualization: AnnualizationPolicyV2,
        volatility_ddof: int,
        risk_free: RiskFreePolicyV2,
        equity: tuple[EquityObservationV2, ...],
    ) -> MetricInputV2:
        failed = False
        result: MetricInputV2 | None = None
        try:
            if not isinstance(equity, tuple) or not 2 <= len(equity) <= MAX_V2_ROWS:
                raise ValueError("Metrics v2 equity row count is invalid")
            if type(annualization) is not AnnualizationPolicyV2:
                raise TypeError("Metrics v2 requires its strict annualization policy")
            if type(risk_free) is not RiskFreePolicyV2:
                raise TypeError("Metrics v2 requires its strict risk-free policy")
            if not isinstance(schedule.sessions, tuple):
                raise ValueError("Metrics v2 schedule sessions must remain immutable")
            validated_equity = tuple(
                EquityObservationV2.model_validate(item.model_dump(mode="python"))
                for item in equity
            )
            returns = tuple(
                _rational_return(previous, current)
                for previous, current in pairwise(validated_equity)
            )
            result = cls(
                schedule=SessionSchedule.model_validate(schedule.model_dump(mode="python")),
                return_basis=return_basis,
                annualization=AnnualizationPolicyV2.model_validate(
                    annualization.model_dump(mode="python")
                ),
                volatility_ddof=volatility_ddof,
                risk_free=RiskFreePolicyV2.model_validate(risk_free.model_dump(mode="python")),
                equity=validated_equity,
                returns=returns,
            )
        except (AttributeError, TypeError, ValueError):
            failed = True
        if failed or result is None:
            raise MetricV2ContractError(
                "Metrics v2 input failed integrity validation"
            ) from None
        return result

    @model_validator(mode="after")
    def validate_complete_trajectory(self) -> MetricInputV2:
        self._require_immutable_sequences()
        schedule = SessionSchedule.model_validate(self.schedule.model_dump(mode="python"))
        annualization = AnnualizationPolicyV2.model_validate(
            self.annualization.model_dump(mode="python")
        )
        risk_free = RiskFreePolicyV2.model_validate(self.risk_free.model_dump(mode="python"))
        equity = tuple(
            EquityObservationV2.model_validate(item.model_dump(mode="python"))
            for item in self.equity
        )
        returns = tuple(
            RationalReturnObservation.model_validate(item.model_dump(mode="python"))
            for item in self.returns
        )
        if tuple(item.observed_on for item in equity) != tuple(
            item.session for item in schedule.sessions
        ):
            raise ValueError("equity must exactly cover the complete schedule")
        if any(left.observed_on >= right.observed_on for left, right in pairwise(equity)):
            raise ValueError("equity observations must be strictly ordered")
        if equity[0].equity <= 0 or any(item.equity <= 0 for item in equity[:-1]):
            raise ValueError("all non-terminal equity observations must be positive")
        if len(returns) != len(equity) - 1:
            raise ValueError("rational returns must cover every equity transition")
        expected = tuple(_rational_return(left, right) for left, right in pairwise(equity))
        if returns != expected:
            raise ValueError("rational returns must exactly match the equity trajectory")
        if annualization != self.annualization or risk_free != self.risk_free:
            raise ValueError("metric policy failed integrity validation")
        for policy_value in (
            annualization.periods_per_year,
            annualization.days_per_year,
            risk_free.rate,
        ):
            require_v2_decimal(policy_value)
        return self

    def _require_immutable_sequences(self) -> None:
        if not isinstance(self.equity, tuple) or not isinstance(self.returns, tuple):
            raise ValueError("Metrics v2 observations must remain immutable tuples")
        if not isinstance(self.schedule.sessions, tuple):
            raise ValueError("Metrics v2 schedule sessions must remain an immutable tuple")

    @property
    def content_hash(self) -> str:
        failed = False
        result = ""
        try:
            self._require_immutable_sequences()
            validated = type(self).model_validate(self.model_dump(mode="python"))
            result = v2_content_hash(validated)
        except (AttributeError, TypeError, ValueError):
            failed = True
        if failed:
            raise MetricV2ContractError(
                "Metrics v2 input failed integrity validation"
            ) from None
        return result


class MetricSetV2(MetricModel):
    metric_set_version: Literal["metrics-v2"] = "metrics-v2"
    metric_input_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    calculator: MetricCalculatorRef
    total_return: MetricValueV2
    cagr: MetricValueV2
    volatility: MetricValueV2
    sharpe: MetricValueV2
    max_drawdown: MetricValueV2

    @model_validator(mode="after")
    def validate_nested_models(self) -> MetricSetV2:
        MetricCalculatorRef.model_validate(self.calculator.model_dump(mode="python"))
        for result in (
            self.total_return,
            self.cagr,
            self.volatility,
            self.sharpe,
            self.max_drawdown,
        ):
            MetricValueV2.model_validate(result.model_dump(mode="python"))
        return self

    @property
    def content_hash(self) -> str:
        failed = False
        result = ""
        try:
            validated = type(self).model_validate(self.model_dump(mode="python"))
            result = v2_content_hash(validated)
        except (AttributeError, TypeError, ValueError):
            failed = True
        if failed:
            raise MetricV2ContractError(
                "Metrics v2 output failed integrity validation"
            ) from None
        return result

def _rational_return(
    previous: EquityObservationV2,
    current: EquityObservationV2,
) -> RationalReturnObservation:
    if previous.equity <= 0:
        raise ValueError("previous equity must be positive")
    value = Fraction(current.equity) / Fraction(previous.equity) - 1
    return RationalReturnObservation(
        observed_on=current.observed_on,
        numerator=value.numerator,
        denominator=value.denominator,
    )
