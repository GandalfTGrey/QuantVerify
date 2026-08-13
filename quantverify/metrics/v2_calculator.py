"""Fixed-context calculator for Metrics v2."""

from __future__ import annotations

import decimal
from decimal import (
    ROUND_HALF_EVEN,
    Clamped,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    FloatOperation,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    Subnormal,
    Underflow,
    localcontext,
)

from pydantic import ValidationError

from quantverify.metrics.models import (
    MetricReason,
    MetricStatus,
    MetricValue,
    RiskFreeRateKind,
)
from quantverify.metrics.v2_identity import MetricV2ContractError, require_v2_decimal
from quantverify.metrics.v2_models import (
    MetricCalculatorRef,
    MetricInputV2,
    MetricSetV2,
)

_ONE = Decimal("1")
_ZERO = Decimal("0")


def calculate_metric_set_v2(
    metric_input: MetricInputV2,
    *,
    calculator: MetricCalculatorRef | None = None,
) -> MetricSetV2:
    """Calculate the five v2 metrics after rebuilding the complete input."""

    failed = False
    validated: MetricInputV2 | None = None
    ref: MetricCalculatorRef | None = None
    try:
        metric_input._require_immutable_sequences()
        validated = MetricInputV2.model_validate(metric_input.model_dump(mode="python"))
        ref = MetricCalculatorRef.model_validate(
            (calculator or MetricCalculatorRef.baseline()).model_dump(mode="python")
        )
        if ref.backend_version != decimal.__libmpdec_version__:
            raise ValueError("calculator backend does not match the runtime")
    except (AttributeError, TypeError, ValueError, ValidationError):
        failed = True
    if failed or validated is None or ref is None:
        raise MetricV2ContractError("Metrics v2 calculation input is invalid") from None

    context = _decimal_context(ref)
    total = _total_return(validated, context)
    cagr = _cagr(validated, context)
    volatility, mean = _volatility_and_mean(validated, context)
    sharpe = _sharpe(validated, volatility, mean, context)
    drawdown = _maximum_drawdown(validated, context)
    output: MetricSetV2 | None = None
    try:
        output = MetricSetV2(
            metric_input_content_hash=validated.content_hash,
            calculator=ref,
            total_return=total,
            cagr=cagr,
            volatility=volatility,
            sharpe=sharpe,
            max_drawdown=drawdown,
        )
    except (TypeError, ValueError, ValidationError):
        failed = True
    if failed or output is None:
        raise MetricV2ContractError("Metrics v2 calculation output is invalid") from None
    return output


def _decimal_context(ref: MetricCalculatorRef) -> Context:
    definition = ref.decimal_context
    context = Context(
        prec=definition.precision,
        rounding=ROUND_HALF_EVEN,
        Emin=definition.emin,
        Emax=definition.emax,
        capitals=definition.capitals,
        clamp=definition.clamp,
    )
    configured = {
        InvalidOperation: definition.invalid_operation_trap,
        FloatOperation: definition.float_operation_trap,
        DivisionByZero: definition.division_by_zero_trap,
        Overflow: definition.overflow_trap,
        Underflow: definition.underflow_trap,
        Subnormal: definition.subnormal_trap,
        Inexact: definition.inexact_trap,
        Rounded: definition.rounded_trap,
        Clamped: definition.clamped_trap,
    }
    for signal, enabled in configured.items():
        context.traps[signal] = enabled
    context.clear_flags()
    return context


def _total_return(metric_input: MetricInputV2, context: Context) -> MetricValue:
    try:
        with localcontext(context) as active:
            active.clear_flags()
            first = metric_input.equity[0].equity
            last = metric_input.equity[-1].equity
            return _valid(last / first - _ONE)
    except (ArithmeticError, DecimalException, ValueError):
        return _failure()


def _cagr(metric_input: MetricInputV2, context: Context) -> MetricValue:
    first = metric_input.equity[0]
    last = metric_input.equity[-1]
    elapsed_days = (last.observed_on - first.observed_on).days
    if elapsed_days <= 0:
        return _undefined(MetricReason.NON_POSITIVE_ELAPSED_TIME)
    if last.equity == 0:
        return _valid(Decimal("-1"))
    try:
        with localcontext(context) as active:
            active.clear_flags()
            years = Decimal(elapsed_days) / metric_input.annualization.days_per_year
            value = (last.equity / first.equity) ** (_ONE / years) - _ONE
            return _valid(value)
    except (ArithmeticError, DecimalException, ValueError):
        return _failure()


def _decimal_returns(metric_input: MetricInputV2, context: Context) -> tuple[Decimal, ...]:
    with localcontext(context) as active:
        active.clear_flags()
        return tuple(
            Decimal(item.numerator) / Decimal(item.denominator)
            for item in metric_input.returns
        )


def _volatility_and_mean(
    metric_input: MetricInputV2,
    context: Context,
) -> tuple[MetricValue, Decimal | None]:
    count = len(metric_input.returns)
    if count <= metric_input.volatility_ddof:
        return _undefined(MetricReason.INSUFFICIENT_RETURN_OBSERVATIONS), None
    try:
        with localcontext(context) as active:
            active.clear_flags()
            values = _decimal_returns(metric_input, active)
            total = _ZERO
            for value in values:
                total += value
            mean = total / Decimal(count)
            squared_total = _ZERO
            for value in values:
                squared_total += (value - mean) ** 2
            variance = squared_total / Decimal(count - metric_input.volatility_ddof)
            annualized = variance.sqrt() * metric_input.annualization.periods_per_year.sqrt()
            return _valid(annualized), mean
    except (ArithmeticError, DecimalException, ValueError):
        return _failure(), None


def _sharpe(
    metric_input: MetricInputV2,
    volatility: MetricValue,
    mean: Decimal | None,
    context: Context,
) -> MetricValue:
    if volatility.status is MetricStatus.FAILURE:
        return _failure()
    if volatility.status is MetricStatus.UNDEFINED or mean is None:
        return _undefined(MetricReason.INSUFFICIENT_RETURN_OBSERVATIONS)
    if volatility.value is None:
        return _failure()
    if volatility.value == 0:
        return _undefined(MetricReason.ZERO_VOLATILITY)
    try:
        with localcontext(context) as active:
            active.clear_flags()
            if metric_input.risk_free.kind is RiskFreeRateKind.ANNUAL_EFFECTIVE:
                periodic = (
                    (_ONE + metric_input.risk_free.rate)
                    ** (_ONE / metric_input.annualization.periods_per_year)
                    - _ONE
                )
            else:
                periodic = metric_input.risk_free.rate
            annualized_excess = (
                mean - periodic
            ) * metric_input.annualization.periods_per_year
            return _valid(annualized_excess / volatility.value)
    except (ArithmeticError, DecimalException, ValueError):
        return _failure()


def _maximum_drawdown(metric_input: MetricInputV2, context: Context) -> MetricValue:
    try:
        with localcontext(context) as active:
            active.clear_flags()
            peak = metric_input.equity[0].equity
            worst = _ZERO
            for item in metric_input.equity:
                if item.equity > peak:
                    peak = item.equity
                drawdown = item.equity / peak - _ONE
                if drawdown < worst:
                    worst = drawdown
            return _valid(worst)
    except (ArithmeticError, DecimalException, ValueError):
        return _failure()


def _valid(value: Decimal) -> MetricValue:
    require_v2_decimal(value)
    return MetricValue(status=MetricStatus.VALID, value=value)


def _undefined(reason: MetricReason) -> MetricValue:
    return MetricValue(status=MetricStatus.UNDEFINED, reason=reason)


def _failure() -> MetricValue:
    return MetricValue(status=MetricStatus.FAILURE, reason=MetricReason.NUMERIC_ERROR)
