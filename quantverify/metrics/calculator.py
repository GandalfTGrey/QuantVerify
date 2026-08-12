"""MetricSet v1 implementation with explicit policies and failure states."""

from __future__ import annotations

from decimal import Decimal, DecimalException, localcontext

from quantverify.metrics.models import (
    MetricInput,
    MetricReason,
    MetricSet,
    MetricStatus,
    MetricValue,
    RiskFreeRateKind,
)
from quantverify.metrics.returns import maximum_drawdown, total_return

_ONE = Decimal("1")
_DECIMAL_PRECISION = 34


def calculate_metric_set(metric_input: MetricInput) -> MetricSet:
    """Calculate MetricSet v1 after rebuilding the complete input contract."""
    validated = MetricInput.model_validate(metric_input.model_dump(mode="python"))
    total = _total_return(validated)
    cagr = _cagr(validated)
    volatility, mean_return = _volatility_and_mean(validated)
    sharpe = _sharpe(validated, volatility, mean_return)
    drawdown = _maximum_drawdown(validated)
    return MetricSet(
        input_schema_version=validated.schema_version,
        calendar_id=validated.calendar_id,
        calendar_version=validated.calendar_version,
        return_kind=validated.return_kind,
        return_basis=validated.return_basis,
        annualization=validated.annualization,
        volatility_ddof=validated.volatility_ddof,
        risk_free=validated.risk_free,
        total_return=total,
        cagr=cagr,
        volatility=volatility,
        sharpe=sharpe,
        max_drawdown=drawdown,
    )


def _total_return(metric_input: MetricInput) -> MetricValue:
    if len(metric_input.equity) < 2:
        return _undefined(MetricReason.INSUFFICIENT_EQUITY_OBSERVATIONS)
    try:
        with localcontext() as context:
            context.prec = _DECIMAL_PRECISION
            value = total_return(tuple(item.equity for item in metric_input.equity))
    except (ArithmeticError, DecimalException, ValueError):
        return _failure()
    return _valid(value)


def _cagr(metric_input: MetricInput) -> MetricValue:
    if len(metric_input.equity) < 2:
        return _undefined(MetricReason.INSUFFICIENT_EQUITY_OBSERVATIONS)
    first = metric_input.equity[0]
    last = metric_input.equity[-1]
    elapsed_days = (last.observed_on - first.observed_on).days
    if elapsed_days <= 0:
        return _undefined(MetricReason.NON_POSITIVE_ELAPSED_TIME)
    try:
        with localcontext() as context:
            context.prec = _DECIMAL_PRECISION
            years = Decimal(elapsed_days) / metric_input.annualization.days_per_year
            value = (last.equity / first.equity) ** (_ONE / years) - _ONE
    except (ArithmeticError, DecimalException, ValueError):
        return _failure()
    return _valid(value)


def _volatility_and_mean(metric_input: MetricInput) -> tuple[MetricValue, Decimal | None]:
    count = len(metric_input.returns)
    if count <= metric_input.volatility_ddof:
        return _undefined(MetricReason.INSUFFICIENT_RETURN_OBSERVATIONS), None
    try:
        with localcontext() as context:
            context.prec = _DECIMAL_PRECISION
            values = tuple(item.value for item in metric_input.returns)
            mean = sum(values, Decimal("0")) / Decimal(count)
            variance = sum(((value - mean) ** 2 for value in values), Decimal("0")) / Decimal(
                count - metric_input.volatility_ddof
            )
            annualized = variance.sqrt() * metric_input.annualization.periods_per_year.sqrt()
    except (ArithmeticError, DecimalException, ValueError):
        return _failure(), None
    return _valid(annualized), mean


def _sharpe(
    metric_input: MetricInput,
    volatility: MetricValue,
    mean_return: Decimal | None,
) -> MetricValue:
    if volatility.status is MetricStatus.FAILURE:
        return _failure()
    if volatility.status is MetricStatus.UNDEFINED or mean_return is None:
        return _undefined(MetricReason.INSUFFICIENT_RETURN_OBSERVATIONS)
    annualized_volatility = volatility.value
    if annualized_volatility is None:
        return _failure()
    if annualized_volatility == 0:
        return _undefined(MetricReason.ZERO_VOLATILITY)
    try:
        with localcontext() as context:
            context.prec = _DECIMAL_PRECISION
            if metric_input.risk_free.kind is RiskFreeRateKind.ANNUAL_EFFECTIVE:
                periodic_risk_free = (
                    (_ONE + metric_input.risk_free.rate)
                    ** (_ONE / metric_input.annualization.periods_per_year)
                    - _ONE
                )
            else:
                periodic_risk_free = metric_input.risk_free.rate
            annualized_excess_return = (
                mean_return - periodic_risk_free
            ) * metric_input.annualization.periods_per_year
            value = annualized_excess_return / annualized_volatility
    except (ArithmeticError, DecimalException, ValueError):
        return _failure()
    return _valid(value)


def _maximum_drawdown(metric_input: MetricInput) -> MetricValue:
    if not metric_input.equity:
        return _undefined(MetricReason.INSUFFICIENT_EQUITY_OBSERVATIONS)
    try:
        with localcontext() as context:
            context.prec = _DECIMAL_PRECISION
            value = maximum_drawdown(tuple(item.equity for item in metric_input.equity))
    except (ArithmeticError, DecimalException, ValueError):
        return _failure()
    return _valid(value)


def _valid(value: Decimal) -> MetricValue:
    if not value.is_finite():
        return _failure()
    return MetricValue(status=MetricStatus.VALID, value=value)


def _undefined(reason: MetricReason) -> MetricValue:
    return MetricValue(status=MetricStatus.UNDEFINED, reason=reason)


def _failure() -> MetricValue:
    return MetricValue(status=MetricStatus.FAILURE, reason=MetricReason.NUMERIC_ERROR)
