from datetime import date
from decimal import Decimal
from unittest import TestCase

from pydantic import ValidationError

from quantverify.metrics import (
    AnnualizationPolicy,
    EquityObservation,
    MetricInput,
    MetricReason,
    MetricStatus,
    MetricValue,
    ReturnBasis,
    ReturnObservation,
    RiskFreePolicy,
    RiskFreeRateKind,
    calculate_metric_set,
    maximum_drawdown,
    total_return,
)


def equity(day: int, value: str) -> EquityObservation:
    return EquityObservation(observed_on=date(2024, 1, day), equity=Decimal(value))


def period_return(day: int, value: str) -> ReturnObservation:
    return ReturnObservation(observed_on=date(2024, 1, day), value=Decimal(value))


def metric_input(
    *,
    equity_observations: tuple[EquityObservation, ...] = (),
    return_observations: tuple[ReturnObservation, ...] = (),
    periods_per_year: str = "4",
    days_per_year: str = "365",
    ddof: int = 0,
    risk_free_kind: RiskFreeRateKind = RiskFreeRateKind.PER_OBSERVATION_SIMPLE,
    risk_free_rate: str = "0",
) -> MetricInput:
    return MetricInput(
        calendar_id="GREGORIAN-TEST",
        calendar_version="2024a",
        return_basis=ReturnBasis.NET_OF_COSTS,
        annualization=AnnualizationPolicy(
            policy_id="four-period-test-v1",
            periods_per_year=Decimal(periods_per_year),
            days_per_year=Decimal(days_per_year),
        ),
        volatility_ddof=ddof,
        risk_free=RiskFreePolicy(
            policy_id="fixed-test-rate-v1",
            kind=risk_free_kind,
            rate=Decimal(risk_free_rate),
            source_id="hand-calculated-fixture",
            source_version="1",
        ),
        equity=equity_observations,
        returns=return_observations,
    )


class MetricsV1GoldenTests(TestCase):
    def test_hand_calculated_return_risk_and_sign_conventions(self) -> None:
        result = calculate_metric_set(
            metric_input(
                equity_observations=(
                    equity(1, "100"),
                    equity(2, "110"),
                    equity(3, "99"),
                ),
                return_observations=(
                    period_return(2, "0.10"),
                    period_return(3, "-0.10"),
                ),
            )
        )

        self.assertEqual(result.metric_set_version, "metrics-v1")
        self.assertEqual(result.total_return.value, Decimal("-0.01"))
        self.assertEqual(result.max_drawdown.value, Decimal("-0.1"))
        self.assertEqual(result.volatility.value, Decimal("0.2"))
        self.assertEqual(result.sharpe.value, Decimal("0"))
        self.assertEqual(result.total_return.status, MetricStatus.VALID)
        self.assertEqual(
            type(result).model_validate_json(result.model_dump_json()),
            result,
        )

    def test_cagr_uses_elapsed_dates_not_observation_count(self) -> None:
        result = calculate_metric_set(
            MetricInput(
                calendar_id="GREGORIAN-TEST",
                calendar_version="2024a",
                return_basis=ReturnBasis.NET_OF_COSTS,
                annualization=AnnualizationPolicy(
                    policy_id="two-day-year-v1",
                    periods_per_year=Decimal("2"),
                    days_per_year=Decimal("2"),
                ),
                volatility_ddof=0,
                risk_free=RiskFreePolicy(
                    policy_id="zero-v1",
                    kind=RiskFreeRateKind.PER_OBSERVATION_SIMPLE,
                    rate=Decimal("0"),
                    source_id="fixture",
                    source_version="1",
                ),
                equity=(
                    EquityObservation(observed_on=date(2024, 1, 1), equity=Decimal("100")),
                    EquityObservation(observed_on=date(2024, 1, 3), equity=Decimal("121")),
                    EquityObservation(observed_on=date(2024, 1, 11), equity=Decimal("400")),
                ),
            )
        )

        # Ten elapsed days / two days per year = five years; 400/100 = 4.
        self.assertAlmostEqual(float(result.cagr.value or 0), 4 ** (1 / 5) - 1, places=14)

    def test_ddof_and_annualization_are_explicit_and_change_volatility(self) -> None:
        observations = (period_return(2, "0.10"), period_return(3, "-0.10"))
        population = calculate_metric_set(
            metric_input(return_observations=observations, periods_per_year="4", ddof=0)
        )
        sample = calculate_metric_set(
            metric_input(return_observations=observations, periods_per_year="4", ddof=1)
        )
        different_annualization = calculate_metric_set(
            metric_input(return_observations=observations, periods_per_year="1", ddof=0)
        )

        self.assertEqual(population.volatility.value, Decimal("0.2"))
        self.assertAlmostEqual(float(sample.volatility.value or 0), (0.02**0.5) * 2, places=14)
        self.assertEqual(different_annualization.volatility.value, Decimal("0.1"))

    def test_losing_equity_has_negative_return_and_drawdown(self) -> None:
        result = calculate_metric_set(
            metric_input(equity_observations=(equity(1, "100"), equity(2, "80")))
        )

        self.assertEqual(result.total_return.value, Decimal("-0.2"))
        self.assertEqual(result.max_drawdown.value, Decimal("-0.2"))

    def test_total_loss_is_valid_for_returns_and_terminal_equity(self) -> None:
        result = calculate_metric_set(
            metric_input(
                equity_observations=(equity(1, "100"), equity(2, "0")),
                return_observations=(period_return(2, "-1"),),
            )
        )

        self.assertEqual(result.total_return.value, Decimal("-1"))
        self.assertEqual(result.cagr.value, Decimal("-1"))
        self.assertEqual(result.max_drawdown.value, Decimal("-1"))
        self.assertEqual(result.volatility.value, Decimal("0"))
        self.assertEqual(result.sharpe.reason, MetricReason.ZERO_VOLATILITY)
        self.assertEqual(total_return((Decimal("100"), Decimal("0"))), Decimal("-1"))
        self.assertEqual(maximum_drawdown((Decimal("100"), Decimal("0"))), Decimal("-1"))

    def test_sharpe_applies_declared_risk_free_policy(self) -> None:
        observations = (period_return(2, "0.10"), period_return(3, "0.30"))
        zero_rate = calculate_metric_set(
            metric_input(return_observations=observations, risk_free_rate="0")
        )
        periodic_rate = calculate_metric_set(
            metric_input(return_observations=observations, risk_free_rate="0.05")
        )
        annual_rate = calculate_metric_set(
            metric_input(
                return_observations=observations,
                risk_free_kind=RiskFreeRateKind.ANNUAL_EFFECTIVE,
                risk_free_rate="0.4641",
            )
        )

        self.assertEqual(zero_rate.sharpe.value, Decimal("4"))
        self.assertEqual(periodic_rate.sharpe.value, Decimal("3"))
        # 46.41% annual effective at four periods/year equals 10% per period.
        self.assertAlmostEqual(float(annual_rate.sharpe.value or 0), 2.0, places=12)

    def test_insufficient_samples_and_zero_volatility_are_undefined(self) -> None:
        insufficient_equity = calculate_metric_set(
            metric_input(equity_observations=(equity(1, "100"),))
        )
        insufficient_returns = calculate_metric_set(
            metric_input(return_observations=(period_return(2, "0.1"),), ddof=1)
        )
        constant = calculate_metric_set(
            metric_input(
                return_observations=(
                    period_return(2, "0.01"),
                    period_return(3, "0.01"),
                )
            )
        )

        self.assertEqual(
            insufficient_equity.total_return.reason,
            MetricReason.INSUFFICIENT_EQUITY_OBSERVATIONS,
        )
        self.assertEqual(
            insufficient_returns.volatility.reason,
            MetricReason.INSUFFICIENT_RETURN_OBSERVATIONS,
        )
        self.assertEqual(
            insufficient_returns.sharpe.reason,
            MetricReason.INSUFFICIENT_RETURN_OBSERVATIONS,
        )
        self.assertEqual(constant.volatility.value, Decimal("0"))
        self.assertEqual(constant.sharpe.status, MetricStatus.UNDEFINED)
        self.assertEqual(constant.sharpe.reason, MetricReason.ZERO_VOLATILITY)

    def test_empty_sources_return_explicit_undefined_states(self) -> None:
        result = calculate_metric_set(metric_input())

        self.assertEqual(result.total_return.status, MetricStatus.UNDEFINED)
        self.assertEqual(result.cagr.status, MetricStatus.UNDEFINED)
        self.assertEqual(result.volatility.status, MetricStatus.UNDEFINED)
        self.assertEqual(result.sharpe.status, MetricStatus.UNDEFINED)
        self.assertEqual(result.max_drawdown.status, MetricStatus.UNDEFINED)
        self.assertTrue(
            all(
                item.value is None
                for item in (
                    result.total_return,
                    result.cagr,
                    result.volatility,
                    result.sharpe,
                    result.max_drawdown,
                )
            )
        )

    def test_input_rejects_duplicate_dates_non_finite_values_and_invalid_returns(self) -> None:
        with self.assertRaisesRegex(ValidationError, "strictly ordered"):
            metric_input(
                equity_observations=(equity(1, "100"), equity(1, "101")),
            )
        with self.assertRaises(ValidationError):
            ReturnObservation(observed_on=date(2024, 1, 1), value=Decimal("NaN"))
        with self.assertRaisesRegex(ValidationError, "greater than or equal to -1"):
            ReturnObservation(observed_on=date(2024, 1, 1), value=Decimal("-1.0001"))

    def test_zero_initial_and_negative_equity_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValidationError, "initial equity"):
            metric_input(
                equity_observations=(equity(1, "0"), equity(2, "100")),
            )
        with self.assertRaises(ValidationError):
            EquityObservation(observed_on=date(2024, 1, 1), equity=Decimal("-0.01"))
        with self.assertRaisesRegex(ValueError, "non-terminal equity"):
            total_return((Decimal("0"), Decimal("100")))
        with self.assertRaisesRegex(ValueError, "terminal equity"):
            maximum_drawdown((Decimal("100"), Decimal("-1")))

    def test_public_helpers_reject_zero_equity_resurrection(self) -> None:
        resurrected = (Decimal("100"), Decimal("0"), Decimal("100"))
        with self.assertRaisesRegex(ValueError, "non-terminal equity"):
            total_return(resurrected)
        with self.assertRaisesRegex(ValueError, "non-terminal equity"):
            maximum_drawdown(resurrected)

    def test_dual_sources_require_complete_exact_transition_coverage(self) -> None:
        equity_series = (equity(1, "100"), equity(2, "110"), equity(3, "99"))
        invalid_returns = (
            ((period_return(2, "0.10"),), "cover every equity transition"),
            (
                (period_return(2, "0.10"), period_return(4, "-0.10")),
                "later equity observation date",
            ),
            (
                (period_return(2, "0.10"), period_return(3, "-0.09")),
                "exactly match",
            ),
        )
        for returns, message in invalid_returns:
            with self.subTest(message=message), self.assertRaisesRegex(
                ValidationError,
                message,
            ):
                metric_input(
                    equity_observations=equity_series,
                    return_observations=returns,
                )

    def test_zero_equity_and_complete_loss_cannot_resurrect(self) -> None:
        with self.assertRaisesRegex(ValidationError, "zero equity must be the terminal"):
            metric_input(
                equity_observations=(equity(1, "100"), equity(2, "0"), equity(3, "10")),
            )
        with self.assertRaisesRegex(ValidationError, "complete-loss return must be the terminal"):
            metric_input(
                return_observations=(period_return(2, "-1"), period_return(3, "0.1")),
            )

    def test_equity_only_and_returns_only_inputs_remain_supported(self) -> None:
        equity_only = calculate_metric_set(
            metric_input(equity_observations=(equity(1, "100"), equity(2, "110")))
        )
        returns_only = calculate_metric_set(
            metric_input(
                return_observations=(period_return(2, "0.1"), period_return(3, "-0.1"))
            )
        )

        self.assertEqual(equity_only.total_return.value, Decimal("0.1"))
        self.assertEqual(
            equity_only.volatility.reason,
            MetricReason.INSUFFICIENT_RETURN_OBSERVATIONS,
        )
        self.assertEqual(returns_only.volatility.value, Decimal("0.2"))
        self.assertEqual(
            returns_only.total_return.reason,
            MetricReason.INSUFFICIENT_EQUITY_OBSERVATIONS,
        )

    def test_metric_status_reason_matrix_is_closed(self) -> None:
        mathematical_reasons = (
            MetricReason.INSUFFICIENT_EQUITY_OBSERVATIONS,
            MetricReason.INSUFFICIENT_RETURN_OBSERVATIONS,
            MetricReason.NON_POSITIVE_ELAPSED_TIME,
            MetricReason.ZERO_VOLATILITY,
        )
        MetricValue(status=MetricStatus.VALID, value=Decimal("0"))
        MetricValue(status=MetricStatus.FAILURE, reason=MetricReason.NUMERIC_ERROR)
        for reason in mathematical_reasons:
            MetricValue(status=MetricStatus.UNDEFINED, reason=reason)

        invalid_states = [
            {"status": MetricStatus.VALID},
            {
                "status": MetricStatus.VALID,
                "value": Decimal("0"),
                "reason": MetricReason.ZERO_VOLATILITY,
            },
            {"status": MetricStatus.UNDEFINED},
            {
                "status": MetricStatus.UNDEFINED,
                "reason": MetricReason.NUMERIC_ERROR,
            },
            {
                "status": MetricStatus.UNDEFINED,
                "value": Decimal("0"),
                "reason": MetricReason.ZERO_VOLATILITY,
            },
            {"status": MetricStatus.FAILURE},
            {
                "status": MetricStatus.FAILURE,
                "reason": MetricReason.ZERO_VOLATILITY,
            },
            {
                "status": MetricStatus.FAILURE,
                "value": Decimal("0"),
                "reason": MetricReason.NUMERIC_ERROR,
            },
        ]
        for state in invalid_states:
            with self.subTest(state=state), self.assertRaises(ValidationError):
                MetricValue.model_validate(state)

    def test_metric_value_never_presents_nan_or_infinity_as_valid(self) -> None:
        for invalid in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                MetricValue(
                    status=MetricStatus.VALID,
                    value=invalid,
                )

    def test_numeric_overflow_is_an_explicit_failure_not_infinity(self) -> None:
        result = calculate_metric_set(
            metric_input(
                equity_observations=(equity(1, "1"), equity(2, "2")),
                days_per_year="1E+999999",
            )
        )

        self.assertEqual(result.cagr.status, MetricStatus.FAILURE)
        self.assertEqual(result.cagr.reason, MetricReason.NUMERIC_ERROR)
        self.assertIsNone(result.cagr.value)

    def test_calculator_revalidates_unsafe_nested_input(self) -> None:
        trusted = metric_input(return_observations=(period_return(2, "0.1"),))
        unsafe_return = trusted.returns[0].model_copy(update={"value": Decimal("NaN")})
        unsafe = trusted.model_copy(update={"returns": (unsafe_return,)})
        with self.assertRaises(ValidationError):
            calculate_metric_set(unsafe)

        trusted_equity = metric_input(
            equity_observations=(equity(1, "100"), equity(2, "90"))
        )
        resurrected_equity = trusted_equity.model_copy(
            update={
                "equity": (
                    equity(1, "100"),
                    equity(2, "0"),
                    equity(3, "100"),
                )
            }
        )
        with self.assertRaises(ValidationError):
            calculate_metric_set(resurrected_equity)
