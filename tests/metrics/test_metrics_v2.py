from __future__ import annotations

import decimal
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, getcontext, localcontext
from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

from quantverify.core.enums import SessionLabelPolicy
from quantverify.core.models import CalendarArtifactRef, SessionSchedule, TradingSession
from quantverify.metrics import (
    AnnualizationPolicy,
    AnnualizationPolicyV2,
    EquityObservationV2,
    MetricCalculatorRef,
    MetricInputV2,
    MetricReason,
    MetricStatus,
    MetricV2ContractError,
    MetricValueV2,
    RationalReturnObservation,
    ReturnBasis,
    RiskFreePolicy,
    RiskFreePolicyV2,
    RiskFreeRateKind,
    calculate_metric_set_v2,
    canonical_v2_bytes,
    decimal_value_v1,
    load_metric_input_v2,
    load_metric_set_v2,
)
from quantverify.metrics.v2_identity import MAX_V2_JSON_NESTING, canonicalize_v2


def schedule_for(*sessions: date) -> SessionSchedule:
    calendar = CalendarArtifactRef(
        calendar_id="XNAS-TEST",
        calendar_version="2026a",
        timezone="America/New_York",
        session_label_policy=SessionLabelPolicy.CLOSE_LOCAL_DATE,
        source_id="hand-calendar",
        source_version="1",
        content_hash="a" * 64,
    )
    rows = tuple(
        TradingSession(
            session=session,
            session_open_at=datetime.combine(
                session,
                datetime.min.time(),
                tzinfo=UTC,
            )
            + timedelta(hours=14, minutes=30),
            session_close_at=datetime.combine(
                session,
                datetime.min.time(),
                tzinfo=UTC,
            )
            + timedelta(hours=21),
        )
        for session in sessions
    )
    return SessionSchedule.create(
        requested_start=sessions[0],
        requested_end=sessions[-1],
        calendar=calendar,
        sessions=rows,
    )


def annualization(*, periods: str = "2", days: str = "365") -> AnnualizationPolicyV2:
    return AnnualizationPolicyV2(
        policy_id="two-period-v1",
        periods_per_year=Decimal(periods),
        days_per_year=Decimal(days),
    )


def risk_free(
    *,
    rate: str = "0",
    kind: RiskFreeRateKind = RiskFreeRateKind.PER_OBSERVATION_SIMPLE,
) -> RiskFreePolicyV2:
    return RiskFreePolicyV2(
        policy_id="fixed-rate-v1",
        kind=kind,
        rate=Decimal(rate),
        source_id="hand-fixture",
        source_version="1",
    )


def metric_input_v2(
    values: tuple[str, ...],
    sessions: tuple[date, ...],
    *,
    ddof: int = 0,
    annual: AnnualizationPolicyV2 | None = None,
    rf: RiskFreePolicyV2 | None = None,
) -> MetricInputV2:
    return MetricInputV2.from_equity(
        schedule=schedule_for(*sessions),
        return_basis=ReturnBasis.NET_OF_COSTS,
        annualization=annual or annualization(),
        volatility_ddof=ddof,
        risk_free=rf or risk_free(),
        equity=tuple(
            EquityObservationV2(observed_on=session, equity=Decimal(value))
            for session, value in zip(sessions, values, strict=True)
        ),
    )


def test_hand_calculated_metrics_and_exact_rational_returns() -> None:
    sessions = (date(2023, 1, 2), date(2023, 7, 3), date(2024, 1, 2))
    source = metric_input_v2(("100", "110", "99"), sessions)

    assert tuple((item.numerator, item.denominator) for item in source.returns) == (
        (1, 10),
        (-1, 10),
    )
    result = calculate_metric_set_v2(source)
    assert result.total_return.value == Decimal("-0.01")
    assert result.cagr.value == Decimal("-0.01")
    assert result.volatility.value == Decimal("0.1414213562373095048801688724209698")
    assert result.sharpe.value == Decimal("0E+33")
    assert result.max_drawdown.value == Decimal("-0.1")
    assert result.metric_input_content_hash == source.content_hash
    assert source.content_hash == "9edd2ff44abac33ef5d7a5d8c93189ead86fa2b84f2d446d559ac1067bbf4cc9"
    expected_set_hash = {
        "2.5.1": "e4a24a9ed7bf396334afa4a8ed4387e58a116dab54b107ce891737b48ea4716a",
        "4.0.0": "776a97a44552a159ae8ba33ed464acb8b2fef2b7269b86c4af3a08c109744d34",
    }
    assert result.content_hash == expected_set_hash[result.calculator.backend_version]
    golden_root = Path(__file__).parent
    assert canonical_v2_bytes(source) == (
        golden_root / "metrics_v2_input_golden.json"
    ).read_bytes()
    assert canonical_v2_bytes(result) == (
        golden_root
        / f"metrics_v2_set_{result.calculator.backend_version.replace('.', '_')}_golden.json"
    ).read_bytes()
    assert load_metric_input_v2(canonical_v2_bytes(source)) == source
    assert load_metric_set_v2(canonical_v2_bytes(result)) == result


def test_ddof_and_risk_free_change_the_declared_calculation() -> None:
    sessions = (date(2023, 1, 2), date(2023, 7, 3), date(2024, 1, 2))
    sample = calculate_metric_set_v2(metric_input_v2(("100", "110", "99"), sessions, ddof=1))
    annual_rf = calculate_metric_set_v2(
        metric_input_v2(
            ("100", "110", "99"),
            sessions,
            rf=risk_free(rate="0.21", kind=RiskFreeRateKind.ANNUAL_EFFECTIVE),
        )
    )

    assert sample.volatility.value == Decimal("0.2")
    assert sample.sharpe.value == Decimal("0")
    assert annual_rf.sharpe.value == Decimal("-1.414213562373095048801688724209698")


def test_recurring_fraction_is_stored_exactly_before_decimal_conversion() -> None:
    sessions = (date(2024, 1, 2), date(2025, 1, 1))
    source = metric_input_v2(("10300", "10400"), sessions)
    assert source.returns[0].fraction == Fraction(1, 103)

    with localcontext() as context:
        context.prec = 34
        assert Decimal(source.returns[0].numerator) / Decimal(
            source.returns[0].denominator
        ) == Decimal("0.009708737864077669902912621359223301")


def test_total_loss_is_terminal_and_has_valid_negative_one_metrics() -> None:
    sessions = (date(2024, 1, 2), date(2025, 1, 1))
    source = metric_input_v2(("100", "0"), sessions)
    result = calculate_metric_set_v2(source)

    assert source.returns[0].fraction == Fraction(-1, 1)
    assert result.total_return.value == Decimal("-1")
    assert result.cagr.value == Decimal("-1")
    assert result.max_drawdown.value == Decimal("-1")
    assert result.volatility.value == Decimal("0")
    assert result.sharpe.status is MetricStatus.UNDEFINED
    assert result.sharpe.reason is MetricReason.ZERO_VOLATILITY


def test_running_peak_drawdown_and_positive_cagr_are_hand_verified() -> None:
    sessions = (date(2023, 1, 2), date(2023, 7, 3), date(2024, 1, 2))
    result = calculate_metric_set_v2(metric_input_v2(("100", "80", "120"), sessions))
    assert result.total_return.value == Decimal("0.2")
    assert result.cagr.value == Decimal("0.2")
    assert result.max_drawdown.value == Decimal("-0.2")


def test_factory_rejects_resurrection_and_incomplete_schedule_coverage() -> None:
    sessions = (date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4))
    with pytest.raises(MetricV2ContractError, match="integrity validation"):
        metric_input_v2(("100", "0", "1"), sessions)

    with pytest.raises(MetricV2ContractError, match="integrity validation"):
        MetricInputV2.from_equity(
            schedule=schedule_for(*sessions),
            return_basis=ReturnBasis.NET_OF_COSTS,
            annualization=annualization(),
            volatility_ddof=0,
            risk_free=risk_free(),
            equity=(
                EquityObservationV2(observed_on=sessions[0], equity=Decimal("100")),
                EquityObservationV2(observed_on=sessions[2], equity=Decimal("101")),
            ),
        )


def test_detached_or_non_reduced_rational_returns_are_rejected() -> None:
    with pytest.raises(ValidationError, match="lowest terms"):
        RationalReturnObservation(
            observed_on=date(2024, 1, 3),
            numerator=2,
            denominator=20,
        )
    with pytest.raises(ValidationError):
        RationalReturnObservation(
            observed_on=date(2024, 1, 3),
            numerator=True,
            denominator=1,
        )

    sessions = (date(2024, 1, 2), date(2025, 1, 1))
    source = metric_input_v2(("100", "110"), sessions)
    forged = source.model_copy(
        update={
            "returns": (
                RationalReturnObservation(
                    observed_on=sessions[1],
                    numerator=1,
                    denominator=11,
                ),
            )
        }
    )
    with pytest.raises(MetricV2ContractError, match="integrity validation"):
        _ = forged.content_hash
    with pytest.raises(MetricV2ContractError, match="calculation input"):
        calculate_metric_set_v2(forged)


def test_decimal_canonical_payload_converges_scale_and_signed_zero() -> None:
    assert decimal_value_v1(Decimal("1.2300")) == {
        "coefficient": "123",
        "exponent": -2,
    }
    assert decimal_value_v1(Decimal("-0E-9")) == {
        "coefficient": "0",
        "exponent": 0,
    }
    assert decimal_value_v1(Decimal("1E+3")) == {
        "coefficient": "1",
        "exponent": 3,
    }

    sessions = (date(2024, 1, 2), date(2025, 1, 1))
    plain = metric_input_v2(("100", "110"), sessions)
    scaled = metric_input_v2(("100.0", "110.00"), sessions)
    assert canonical_v2_bytes(plain) == canonical_v2_bytes(scaled)
    assert plain.content_hash == scaled.content_hash


def test_year_one_date_and_datetime_wire_values_are_fixed_width() -> None:
    assert canonicalize_v2(date(1, 1, 1)) == "0001-01-01"
    assert canonicalize_v2(datetime(1, 1, 1, 2, 3, 4, 5, tzinfo=UTC)) == (
        "0001-01-01T02:03:04.000005Z"
    )

    source = MetricInputV2.from_equity(
        schedule=schedule_for(date(1, 1, 1), date(1, 1, 2)),
        return_basis=ReturnBasis.NET_OF_COSTS,
        annualization=annualization(),
        volatility_ddof=0,
        risk_free=risk_free(),
        equity=(
            EquityObservationV2(observed_on=date(1, 1, 1), equity=Decimal("100")),
            EquityObservationV2(observed_on=date(1, 1, 2), equity=Decimal("101")),
        ),
    )
    encoded = canonical_v2_bytes(source)
    assert b'"requested_start":"0001-01-01"' in encoded
    assert b'"session_open_at":"0001-01-01T14:30:00.000000Z"' in encoded
    assert load_metric_input_v2(encoded) == source


def test_schedule_offset_equivalence_preserves_input_identity() -> None:
    sessions = (date(2024, 1, 2), date(2025, 1, 1))
    original = metric_input_v2(("100", "110"), sessions)
    offset = timezone(timedelta(hours=-5))
    shifted_schedule = SessionSchedule.create(
        requested_start=original.schedule.requested_start,
        requested_end=original.schedule.requested_end,
        calendar=original.schedule.calendar,
        sessions=tuple(
            TradingSession(
                session=item.session,
                session_open_at=item.session_open_at.astimezone(offset),
                session_close_at=item.session_close_at.astimezone(offset),
            )
            for item in original.schedule.sessions
        ),
    )
    shifted = MetricInputV2.from_equity(
        schedule=shifted_schedule,
        return_basis=original.return_basis,
        annualization=original.annualization,
        volatility_ddof=original.volatility_ddof,
        risk_free=original.risk_free,
        equity=original.equity,
    )
    assert original.content_hash == shifted.content_hash


def test_host_decimal_context_does_not_change_input_or_results() -> None:
    sessions = (date(2023, 1, 2), date(2023, 7, 3), date(2024, 1, 2))
    source = metric_input_v2(("100", "110", "99"), sessions)
    expected = calculate_metric_set_v2(source)
    expected_bytes = canonical_v2_bytes(expected)

    original = getcontext().copy()
    try:
        variants = (
            (1, decimal.ROUND_UP),
            (2, decimal.ROUND_DOWN),
            (50, decimal.ROUND_UP),
        )
        for precision, rounding in variants:
            host = getcontext()
            host.prec = precision
            host.rounding = rounding
            host.flags[decimal.Inexact] = True
            actual = calculate_metric_set_v2(source)
            assert actual == expected
            assert canonical_v2_bytes(actual) == expected_bytes
    finally:
        decimal.setcontext(original)


def test_backend_and_unsafe_calculator_ref_fail_closed() -> None:
    with pytest.raises(ValidationError, match="unsupported"):
        MetricCalculatorRef(backend_version="unknown")

    sessions = (date(2024, 1, 2), date(2025, 1, 1))
    source = metric_input_v2(("100", "110"), sessions)
    unsafe = MetricCalculatorRef.baseline().model_copy(update={"backend_version": "unknown"})
    with pytest.raises(MetricV2ContractError, match="calculation input"):
        calculate_metric_set_v2(source, calculator=unsafe)

    other_supported = next(
        version
        for version in ("2.5.1", "4.0.0")
        if version != decimal.__libmpdec_version__
    )
    mismatched = MetricCalculatorRef(backend_version=other_supported)
    with pytest.raises(MetricV2ContractError, match="calculation input"):
        calculate_metric_set_v2(source, calculator=mismatched)


def test_unsafe_schedule_and_output_cannot_cross_identity_boundaries() -> None:
    sessions = (date(2024, 1, 2), date(2025, 1, 1))
    source = metric_input_v2(("100", "110"), sessions)
    unsafe_schedule = source.schedule.model_copy(update={"content_hash": "f" * 64})
    unsafe_source = source.model_copy(update={"schedule": unsafe_schedule})
    with pytest.raises(MetricV2ContractError, match="integrity validation"):
        _ = unsafe_source.content_hash
    with pytest.raises(MetricV2ContractError, match="calculation input"):
        calculate_metric_set_v2(unsafe_source)

    result = calculate_metric_set_v2(source)
    unsafe_result = result.model_copy(update={"metric_input_content_hash": "g" * 64})
    with pytest.raises(MetricV2ContractError, match="output failed"):
        _ = unsafe_result.content_hash
    with pytest.raises(MetricV2ContractError, match="canonical serialization"):
        canonical_v2_bytes(unsafe_result)

    changed_value = result.model_copy(
        update={
            "total_return": result.total_return.model_copy(
                update={"value": Decimal("999")}
            )
        }
    )
    assert changed_value.content_hash != result.content_hash
    assert canonical_v2_bytes(changed_value) != canonical_v2_bytes(result)


def test_canonical_boundary_rejects_invalid_unicode_without_exposing_input() -> None:
    sessions = (date(2024, 1, 2), date(2025, 1, 1))
    source = metric_input_v2(("100", "110"), sessions)
    unsafe_policy = source.annualization.model_copy(update={"policy_id": "\ud800SECRET"})
    unsafe_source = source.model_copy(update={"annualization": unsafe_policy})

    with pytest.raises(
        MetricV2ContractError,
        match="canonical serialization failed integrity validation",
    ) as captured:
        canonical_v2_bytes(unsafe_source)
    error = captured.value
    assert "SECRET" not in str(error)
    assert error.__cause__ is None
    assert error.__context__ is None


def test_canonical_loader_rejects_noncanonical_and_duplicate_bytes() -> None:
    sessions = (date(2024, 1, 2), date(2025, 1, 1))
    source = metric_input_v2(("100", "110"), sessions)
    encoded = canonical_v2_bytes(source)
    invalid_documents = (
        b" " + encoded,
        encoded + b"\n",
        encoded.replace(
            b'"schema_version":',
            b'"schema_version":"duplicate","schema_version":',
            1,
        ),
        encoded.replace(
            b'"coefficient":"1","exponent":2',
            b'"coefficient":"10","exponent":1',
            1,
        ),
    )
    for document in invalid_documents:
        with pytest.raises(
            MetricV2ContractError,
            match="canonical document failed integrity validation",
        ) as captured:
            load_metric_input_v2(document)
        assert captured.value.__cause__ is None
        assert captured.value.__context__ is None


def test_canonical_loader_bounds_nesting_without_counting_string_brackets() -> None:
    sessions = (date(2024, 1, 2), date(2025, 1, 1))
    deep = (
        b"{"
        + b'"x":{' * MAX_V2_JSON_NESTING
        + b'"x":0'
        + b"}" * (MAX_V2_JSON_NESTING + 1)
    )
    with pytest.raises(MetricV2ContractError, match="canonical document"):
        load_metric_input_v2(deep)

    bracketed = metric_input_v2(
        ("100", "110"),
        sessions,
        annual=AnnualizationPolicyV2(
            policy_id='[{"escaped":"\\\"}"}]',
            periods_per_year=Decimal("2"),
            days_per_year=Decimal("365"),
        ),
    )
    assert load_metric_input_v2(canonical_v2_bytes(bracketed)) == bracketed

    result = calculate_metric_set_v2(metric_input_v2(("100", "110"), sessions))
    huge_exponent = canonical_v2_bytes(result).replace(
        b'"exponent":-1',
        b'"exponent":1000000000000000000000000000000',
        1,
    )
    with pytest.raises(MetricV2ContractError, match="canonical document") as captured:
        load_metric_set_v2(huge_exponent)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_v1_policy_objects_cannot_cross_the_strict_v2_factory() -> None:
    sessions = (date(2024, 1, 2), date(2025, 1, 1))
    with pytest.raises(MetricV2ContractError, match="integrity validation"):
        MetricInputV2.from_equity(
            schedule=schedule_for(*sessions),
            return_basis=ReturnBasis.NET_OF_COSTS,
            annualization=AnnualizationPolicy(
                policy_id="legacy",
                periods_per_year=1.1,
                days_per_year=365.0,
            ),  # type: ignore[arg-type]
            volatility_ddof=0,
            risk_free=RiskFreePolicy(
                policy_id="legacy",
                kind=RiskFreeRateKind.PER_OBSERVATION_SIMPLE,
                rate=0.1,
                source_id="legacy",
                source_version="1",
            ),  # type: ignore[arg-type]
            equity=(
                EquityObservationV2(observed_on=sessions[0], equity=Decimal("100")),
                EquityObservationV2(observed_on=sessions[1], equity=Decimal("101")),
            ),
        )


def test_factory_rejects_bool_ddof_at_the_public_boundary() -> None:
    sessions = (date(2024, 1, 2), date(2025, 1, 1))
    with pytest.raises(MetricV2ContractError, match="integrity validation"):
        metric_input_v2(("100", "110"), sessions, ddof=True)  # type: ignore[arg-type]


def test_insufficient_returns_and_zero_volatility_have_explicit_reasons() -> None:
    sessions = (date(2024, 1, 2), date(2025, 1, 1))
    insufficient = calculate_metric_set_v2(
        metric_input_v2(("100", "110"), sessions, ddof=1)
    )
    constant = calculate_metric_set_v2(metric_input_v2(("100", "121"), sessions))
    assert insufficient.volatility.reason is MetricReason.INSUFFICIENT_RETURN_OBSERVATIONS
    assert insufficient.sharpe.reason is MetricReason.INSUFFICIENT_RETURN_OBSERVATIONS
    assert constant.volatility.value == Decimal("0")
    assert constant.sharpe.reason is MetricReason.ZERO_VOLATILITY


def test_direct_input_rejects_wrong_fraction_date_and_schedule_order() -> None:
    sessions = (date(2024, 1, 2), date(2025, 1, 1))
    source = metric_input_v2(("100", "110"), sessions)
    wrong_date = RationalReturnObservation(
        observed_on=sessions[0],
        numerator=1,
        denominator=10,
    )
    with pytest.raises(ValidationError, match="exactly match"):
        MetricInputV2.model_validate(
            {**source.model_dump(mode="python"), "returns": (wrong_date,)}
        )

    reversed_equity = tuple(reversed(source.equity))
    unsafe = source.model_copy(update={"equity": reversed_equity})
    with pytest.raises(MetricV2ContractError, match="integrity validation"):
        _ = unsafe.content_hash


def test_mutable_observations_and_unrelated_models_cannot_be_canonicalized() -> None:
    sessions = (date(2024, 1, 2), date(2025, 1, 1))
    source = metric_input_v2(("100", "110"), sessions)
    unsafe = source.model_copy(update={"equity": list(source.equity)})
    with pytest.raises(MetricV2ContractError, match="integrity validation"):
        _ = unsafe.content_hash
    with pytest.raises(MetricV2ContractError, match="canonical serialization"):
        canonical_v2_bytes(unsafe)
    with pytest.raises(MetricV2ContractError, match="calculation input"):
        calculate_metric_set_v2(unsafe)
    with pytest.raises(MetricV2ContractError, match="canonical serialization"):
        canonical_v2_bytes(annualization())


def test_decimal_and_rational_resource_limits_fail_before_identity() -> None:
    for invalid in (1.1, "1.1", True):
        with pytest.raises(ValidationError):
            EquityObservationV2(
                observed_on=date(2024, 1, 2),
                equity=invalid,  # type: ignore[arg-type]
            )
    for policy_type, field_name in (
        (AnnualizationPolicyV2, "periods_per_year"),
        (RiskFreePolicyV2, "rate"),
    ):
        payload: dict[str, object]
        if policy_type is AnnualizationPolicyV2:
            payload = {
                "policy_id": "strict",
                "periods_per_year": Decimal("2"),
                "days_per_year": Decimal("365"),
            }
        else:
            payload = {
                "policy_id": "strict",
                "kind": RiskFreeRateKind.PER_OBSERVATION_SIMPLE,
                "rate": Decimal("0"),
                "source_id": "test",
                "source_version": "1",
            }
        payload[field_name] = 1.1
        with pytest.raises(ValidationError):
            policy_type.model_validate(payload)
    with pytest.raises(ValidationError, match="coefficient digit"):
        MetricValueV2(
            status=MetricStatus.VALID,
            value=Decimal("1" * 65),
        )
    with pytest.raises(ValidationError, match="adjusted exponent"):
        MetricValueV2(
            status=MetricStatus.VALID,
            value={"coefficient": "1", "exponent": 10**100},  # type: ignore[arg-type]
        )
    with pytest.raises(ValidationError, match="coefficient digit"):
        EquityObservationV2(
            observed_on=date(2024, 1, 2),
            equity=Decimal("1" * 65),
        )
    with pytest.raises(ValidationError, match="exponent"):
        EquityObservationV2(
            observed_on=date(2024, 1, 2),
            equity=Decimal("1E+1001"),
        )
    with pytest.raises(ValidationError, match="bit limit"):
        RationalReturnObservation(
            observed_on=date(2024, 1, 3),
            numerator=2**4096,
            denominator=1,
        )
