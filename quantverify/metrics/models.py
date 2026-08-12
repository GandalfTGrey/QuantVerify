"""Versioned contracts for deterministic performance metrics."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MetricModel(BaseModel):
    """Immutable metric DTO that revalidates nested model instances."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
        str_strip_whitespace=True,
    )


FiniteDecimal = Annotated[Decimal, Field(allow_inf_nan=False)]
PositiveDecimal = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


class ReturnKind(StrEnum):
    """Meaning of a dated return observation."""

    SIMPLE = "simple"


class ReturnBasis(StrEnum):
    """Whether observations include trading costs."""

    GROSS_OF_COSTS = "gross_of_costs"
    NET_OF_COSTS = "net_of_costs"


class RiskFreeRateKind(StrEnum):
    """Unit in which the declared risk-free rate is supplied."""

    ANNUAL_EFFECTIVE = "annual_effective"
    PER_OBSERVATION_SIMPLE = "per_observation_simple"


class MetricStatus(StrEnum):
    VALID = "valid"
    UNDEFINED = "undefined"
    FAILURE = "failure"


class MetricReason(StrEnum):
    INSUFFICIENT_EQUITY_OBSERVATIONS = "insufficient_equity_observations"
    INSUFFICIENT_RETURN_OBSERVATIONS = "insufficient_return_observations"
    NON_POSITIVE_ELAPSED_TIME = "non_positive_elapsed_time"
    ZERO_VOLATILITY = "zero_volatility"
    NUMERIC_ERROR = "numeric_error"


class EquityObservation(MetricModel):
    observed_on: date
    equity: NonNegativeDecimal


class ReturnObservation(MetricModel):
    observed_on: date
    value: FiniteDecimal

    @model_validator(mode="after")
    def validate_simple_return(self) -> ReturnObservation:
        if self.value < Decimal("-1"):
            raise ValueError("simple return must be greater than or equal to -1")
        return self


class AnnualizationPolicy(MetricModel):
    """Explicit observation-frequency and elapsed-time annualization policy."""

    policy_id: str = Field(min_length=1, max_length=128)
    periods_per_year: PositiveDecimal
    days_per_year: PositiveDecimal


class RiskFreePolicy(MetricModel):
    """Explicit scalar risk-free assumption and its provenance."""

    policy_id: str = Field(min_length=1, max_length=128)
    kind: RiskFreeRateKind
    rate: FiniteDecimal
    source_id: str = Field(min_length=1, max_length=128)
    source_version: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_rate(self) -> RiskFreePolicy:
        if self.rate <= Decimal("-1"):
            raise ValueError("risk-free rate must be greater than -1")
        return self


class MetricInput(MetricModel):
    """All observations and policies required by MetricSet v1."""

    schema_version: str = Field(default="metric-input-v1", pattern=r"^metric-input-v1$")
    calendar_id: str = Field(min_length=1, max_length=128)
    calendar_version: str = Field(min_length=1, max_length=64)
    return_kind: ReturnKind = ReturnKind.SIMPLE
    return_basis: ReturnBasis
    annualization: AnnualizationPolicy
    volatility_ddof: int = Field(ge=0)
    risk_free: RiskFreePolicy
    equity: tuple[EquityObservation, ...] = ()
    returns: tuple[ReturnObservation, ...] = ()

    @model_validator(mode="after")
    def validate_observation_order(self) -> MetricInput:
        if self.equity and self.equity[0].equity <= 0:
            raise ValueError("initial equity must be strictly positive")
        for name, observations in (("equity", self.equity), ("returns", self.returns)):
            dates = tuple(item.observed_on for item in observations)
            if any(left >= right for left, right in pairwise(dates)):
                raise ValueError(f"{name} observations must be strictly ordered by date")
        return self


class MetricValue(MetricModel):
    status: MetricStatus
    value: FiniteDecimal | None = None
    reason: MetricReason | None = None

    @model_validator(mode="after")
    def validate_state(self) -> MetricValue:
        if self.status is MetricStatus.VALID:
            if self.value is None or self.reason is not None:
                raise ValueError("valid metric requires a value and no reason")
        elif self.value is not None or self.reason is None:
            raise ValueError("non-valid metric requires a reason and no value")
        return self


class MetricSet(MetricModel):
    """Versioned output for the five foundational performance metrics."""

    metric_set_version: str = Field(default="metrics-v1", pattern=r"^metrics-v1$")
    input_schema_version: str = Field(pattern=r"^metric-input-v1$")
    calendar_id: str = Field(min_length=1, max_length=128)
    calendar_version: str = Field(min_length=1, max_length=64)
    return_kind: ReturnKind
    return_basis: ReturnBasis
    annualization: AnnualizationPolicy
    volatility_ddof: int = Field(ge=0)
    risk_free: RiskFreePolicy
    total_return: MetricValue
    cagr: MetricValue
    volatility: MetricValue
    sharpe: MetricValue
    max_drawdown: MetricValue

    @model_validator(mode="after")
    def validate_nested_results(self) -> MetricSet:
        # Explicitly reconstruct all nested models so unsafe model_copy state cannot
        # cross a persisted metric boundary even on older Pydantic minor versions.
        for result in (
            self.total_return,
            self.cagr,
            self.volatility,
            self.sharpe,
            self.max_drawdown,
        ):
            MetricValue.model_validate(result.model_dump(mode="python"))
        return self
