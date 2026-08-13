from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, ROUND_UP, Decimal, localcontext
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from pydantic import ValidationError

from quantverify.core.enums import AdjustmentMode, AssetClass, BarFrequency
from quantverify.core.exceptions import DataQualityError
from quantverify.core.models import AssetId
from quantverify.data.capture import RawCapture
from quantverify.data.models import NormalizedBar
from quantverify.data.quality import (
    CheckResult,
    CheckStatus,
    CrossSourceRequirement,
    DataQualityReportV2,
    EligibilityStatus,
    ExpectedSessionSetRef,
    FindingSeverity,
    NormalizedInputRef,
    QualityFinding,
    QualityPolicy,
    QualitySourceData,
    QualitySuite,
    RangeEligibility,
    RevisionPair,
    evidence_ref_from_verified_capture,
)
from quantverify.data.quality.identity import canonical_decimal, normalized_bars_hash
from quantverify.data.store import CaptureStore, DataLicenseProfile, VerifiedCapture

ASSET = AssetId(
    symbol="QQQ",
    venue="XNAS",
    asset_class=AssetClass.ETF,
    currency="USD",
)
SUITE = QualitySuite()
LICENSE = DataLicenseProfile(
    profile_id="fixture-personal-research-v1",
    permitted_uses=("local_research", "automated_testing"),
    redistribution_allowed=False,
)


def bar(day: str, *, close: str = "100", source_name: str = "fixture") -> NormalizedBar:
    session = date.fromisoformat(day)
    close_value = Decimal(close)
    return NormalizedBar(
        asset=ASSET,
        session=session,
        session_open_at=datetime(session.year, session.month, session.day, 14, 30, tzinfo=UTC),
        session_close_at=datetime(session.year, session.month, session.day, 21, tzinfo=UTC),
        available_at=datetime(session.year, session.month, session.day, 21, tzinfo=UTC),
        open=Decimal("100"),
        high=max(Decimal("110"), close_value + Decimal("10")),
        low=min(Decimal("90"), close_value - Decimal("10")),
        close=close_value,
        volume=Decimal("1000000"),
        source=source_name,
    )


def verified_capture(
    provider: str,
    capture_char: str,
    manifest_char: str,
    *,
    request_char: str = "c",
) -> VerifiedCapture:
    raw = RawCapture.from_records(
        provider=provider,
        endpoint="daily",
        request={"semantic_request": request_char},
        records=[{"capture_marker": capture_char}],
        captured_at=datetime(2026, 1, 2, 22, tzinfo=UTC),
        schema_version="fixture-v1",
    )
    stored_offset = ord(manifest_char[0]) if manifest_char else 0
    with TemporaryDirectory() as directory:
        store = CaptureStore(Path(directory))
        stored = store.write(
            raw,
            adapter_version="fixture-adapter-v1",
            license_profile=LICENSE,
            stored_at=datetime(2026, 1, 2, 22, tzinfo=UTC)
            + timedelta(microseconds=stored_offset),
        )
        return store.load_verified(stored.manifest_path)


def normalized_input(
    bars: list[NormalizedBar],
    *,
    schema_version: str = "normalized-bar-v1",
    normalizer_id: str = "fixture-normalizer",
    normalizer_version: str = "1.0.0",
) -> NormalizedInputRef:
    try:
        return NormalizedInputRef.from_bars(
            bars,
            schema_version=schema_version,
            normalizer_id=normalizer_id,
            normalizer_version=normalizer_version,
        )
    except (TypeError, ValueError):
        # Only adversarial tests with deliberately non-canonical values use this path.
        return NormalizedInputRef.model_construct(
            content_hash="0" * 64,
            schema_version=schema_version,
            normalizer_id=normalizer_id,
            normalizer_version=normalizer_version,
            row_count=len(bars),
        )


def source(
    provider: str,
    capture_char: str,
    manifest_char: str,
    bars: list[NormalizedBar],
    *,
    request_char: str = "c",
    schema_version: str = "normalized-bar-v1",
    normalizer_id: str = "fixture-normalizer",
    normalizer_version: str = "1.0.0",
) -> QualitySourceData:
    # Tests intentionally permit adversarial bars that bypass NormalizedBar's
    # boundary validation so QualitySuite defense-in-depth can be exercised.
    verified = verified_capture(
        provider,
        capture_char,
        manifest_char,
        request_char=request_char,
    )
    return QualitySourceData.model_construct(
        verified_capture=verified,
        evidence=evidence_ref_from_verified_capture(verified),
        normalized_input=normalized_input(
            bars,
            schema_version=schema_version,
            normalizer_id=normalizer_id,
            normalizer_version=normalizer_version,
        ),
        bars=tuple(bars),
    )


def evaluate(
    sources: list[QualitySourceData],
    expected_sessions: list[date],
    *,
    start: date,
    end: date,
    policy: QualityPolicy | None = None,
    revisions: tuple[RevisionPair, ...] = (),
) -> DataQualityReportV2:
    return SUITE.evaluate(
        asset=ASSET,
        frequency=BarFrequency.DAY,
        adjustment_mode=AdjustmentMode.RAW,
        calendar_id="XNYS",
        requested_start=start,
        requested_end=end,
        sources=sources,
        expected_sessions=expected_sessions,
        policy=policy,
        revisions=revisions,
    )


def test_clean_single_source_range_is_eligible_and_deterministic() -> None:
    sessions = [date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 6)]
    data = source("source_a", "a", "b", [bar(day.isoformat()) for day in sessions])
    first = evaluate([data], sessions, start=sessions[0], end=sessions[-1])
    second = evaluate([data], sessions, start=sessions[0], end=sessions[-1])

    assert first.eligibility.status is EligibilityStatus.ELIGIBLE
    assert first.report_id == second.report_id
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_clean_report_has_fixed_identity_and_json_round_trip() -> None:
    session = date(2026, 1, 2)
    report = evaluate(
        [source("source_a", "a", "b", [bar(session.isoformat())])],
        [session],
        start=session,
        end=session,
    )

    assert report.context.quality_suite_id == "quantverify-quality-suite"
    assert report.context.quality_suite_version == "2"
    assert report.report_content_hash == (
        "0b644aebd48b2bbfc1d1401db4b7c2ebdbe965bae74569d3b2587534448dfc6f"
    )
    assert report.report_id == "dqr_0a6e33a2b9607a603b5f2da2"
    replayed = DataQualityReportV2.model_validate_json(report.model_dump_json())
    assert replayed == report
    assert replayed.report_id == report.report_id


def test_normalized_bar_change_changes_report_identity_even_when_checks_pass() -> None:
    session = date(2026, 1, 2)
    first_source = source(
        "source_a",
        "a",
        "b",
        [bar(session.isoformat(), close="100")],
    )
    second_source = source(
        "source_a",
        "a",
        "b",
        [bar(session.isoformat(), close="101")],
    )

    first = evaluate([first_source], [session], start=session, end=session)
    second = evaluate([second_source], [session], start=session, end=session)

    assert first.eligibility.status is EligibilityStatus.ELIGIBLE
    assert second.eligibility.status is EligibilityStatus.ELIGIBLE
    assert first.context.evidence_refs == second.context.evidence_refs
    assert first.context.normalized_input_refs != second.context.normalized_input_refs
    assert first.report_id != second.report_id


def test_normalized_input_identity_preserves_supplied_row_sequence() -> None:
    first, second = date(2026, 1, 2), date(2026, 1, 5)
    ordered_bars = [bar(first.isoformat()), bar(second.isoformat())]
    reversed_bars = list(reversed(ordered_bars))

    ordered = normalized_input(ordered_bars)
    reversed_input = normalized_input(reversed_bars)

    assert ordered.content_hash != reversed_input.content_hash
    assert ordered.input_id != reversed_input.input_id


def test_equivalent_timestamp_offsets_have_one_normalized_and_report_identity() -> None:
    session = date(2026, 1, 2)
    original_bar = bar(session.isoformat())
    offset = timezone(timedelta(hours=-5))
    offset_bar = original_bar.model_copy(
        update={
            "session_open_at": original_bar.session_open_at.astimezone(offset),
            "session_close_at": original_bar.session_close_at.astimezone(offset),
            "available_at": original_bar.available_at.astimezone(offset),
        }
    )
    first = evaluate(
        [source("source_a", "a", "b", [original_bar])],
        [session],
        start=session,
        end=session,
    )
    second = evaluate(
        [source("source_a", "a", "b", [offset_bar])],
        [session],
        start=session,
        end=session,
    )

    assert first.context.normalized_input_refs == second.context.normalized_input_refs
    assert first.report_id == second.report_id


def test_equivalent_decimal_scales_have_one_scientific_identity() -> None:
    session = date(2026, 1, 2)
    original_bar = bar(session.isoformat())
    scaled_bar = original_bar.model_copy(
        update={
            "open": Decimal("100.0"),
            "high": Decimal("110.00"),
            "low": Decimal("90.000"),
            "close": Decimal("100.0000"),
            "volume": Decimal("1000000.00"),
        }
    )
    first_policy = QualityPolicy(
        price_pass_tolerance_bps=Decimal("10"),
        price_warning_tolerance_bps=Decimal("50"),
    )
    second_policy = QualityPolicy(
        price_pass_tolerance_bps=Decimal("10.0"),
        price_warning_tolerance_bps=Decimal("50.00"),
    )
    first = evaluate(
        [source("source_a", "a", "b", [original_bar])],
        [session],
        start=session,
        end=session,
        policy=first_policy,
    )
    second = evaluate(
        [source("source_a", "a", "b", [scaled_bar])],
        [session],
        start=session,
        end=session,
        policy=second_policy,
    )

    assert first_policy.content_hash == second_policy.content_hash
    assert first.context.normalized_input_refs == second.context.normalized_input_refs
    assert first.report_id == second.report_id


def test_scientific_decimal_identity_is_exact_and_context_independent() -> None:
    first_value = Decimal("12345678901234567890123456781")
    second_value = Decimal("12345678901234567890123456782")
    first_bar = bar("2026-01-02", close=str(first_value))
    second_bar = bar("2026-01-02", close=str(second_value))

    identities: list[tuple[str, str, str, str]] = []
    for precision in (10, 28, 50):
        with localcontext() as context:
            context.prec = precision
            identities.append(
                (
                    canonical_decimal(first_value),
                    canonical_decimal(second_value),
                    normalized_bars_hash((first_bar,)),
                    normalized_bars_hash((second_bar,)),
                )
            )

    assert len(set(identities)) == 1
    first_identity, second_identity, first_hash, second_hash = identities[0]
    assert first_identity == str(first_value)
    assert second_identity == str(second_value)
    assert first_identity != second_identity
    assert first_hash != second_hash


def test_scientific_decimal_identity_normalizes_scale_zero_and_extreme_exponents() -> None:
    assert canonical_decimal(Decimal("1.2300")) == "1.23"
    assert canonical_decimal(Decimal("-0")) == canonical_decimal(Decimal("0.000")) == "0"
    assert canonical_decimal(Decimal("1E+10000")) == "1E+10000"
    assert canonical_decimal(Decimal("1.00E+10000")) == "1E+10000"
    assert canonical_decimal(Decimal("1E-10000")) == "1E-10000"


def test_cross_source_evidence_uses_one_fixed_decimal_context() -> None:
    session = date(2026, 1, 2)
    sources = [
        source("source_a", "a", "b", [bar(session.isoformat())]),
        source(
            "source_b",
            "d",
            "e",
            [bar(session.isoformat(), close="100.105")],
        ),
    ]

    reports = []
    for precision, rounding in ((2, ROUND_DOWN), (10, ROUND_UP), (50, ROUND_DOWN)):
        with localcontext() as context:
            context.prec = precision
            context.rounding = rounding
            reports.append(
                evaluate(
                    sources,
                    [session],
                    start=session,
                    end=session,
                )
            )

    assert all(report == reports[0] for report in reports[1:])
    assert all(report.report_id == reports[0].report_id for report in reports[1:])
    cross_source = next(
        result for result in reports[0].check_results if result.check_id == "cross_source_ohlc"
    )
    assert cross_source.status is CheckStatus.WARNING
    assert cross_source.metrics["max_difference_bps"] == (
        "10.49449039254391444491641888008795"
    )


@pytest.mark.parametrize(
    ("right", "expected_status"),
    [
        ("2000.9999999999999999999999999999999999999999", CheckStatus.PASS),
        ("2001", CheckStatus.PASS),
        ("2001.0000000000000000000000000000000000000001", CheckStatus.WARNING),
        ("2005.01", CheckStatus.WARNING),
        ("2010.04", CheckStatus.FAIL),
    ],
)
def test_cross_source_thresholds_use_exact_rational_comparison(
    right: str,
    expected_status: CheckStatus,
) -> None:
    session = date(2026, 1, 2)
    left = bar(session.isoformat(), close="1999")
    right_bar = bar(session.isoformat(), close=right)
    report = evaluate(
        [source("source_a", "a", "b", [left]), source("source_b", "d", "e", [right_bar])],
        [session],
        start=session,
        end=session,
    )
    cross_source = next(
        result for result in report.check_results if result.check_id == "cross_source_ohlc"
    )
    assert cross_source.status is expected_status


@pytest.mark.parametrize(
    "value",
    [
        Decimal("1E+1001"),
        Decimal("1E-1001"),
        Decimal("1." + "1" * 64),
    ],
)
def test_quality_decimal_domain_rejects_unbounded_values_without_overflow(
    value: Decimal,
) -> None:
    session = date(2026, 1, 2)
    extreme = bar(session.isoformat()).model_copy(
        update={"open": value, "high": value, "low": value, "close": value}
    )
    with pytest.raises(
        DataQualityError,
        match="quality source rows cannot be deterministically identified",
    ):
        evaluate(
            [source("source_a", "a", "b", [extreme])],
            [session],
            start=session,
            end=session,
        )


def test_normalizer_version_changes_report_identity() -> None:
    session = date(2026, 1, 2)
    bars = [bar(session.isoformat())]
    first = evaluate(
        [source("source_a", "a", "b", bars, normalizer_version="1.0.0")],
        [session],
        start=session,
        end=session,
    )
    second = evaluate(
        [source("source_a", "a", "b", bars, normalizer_version="1.0.1")],
        [session],
        start=session,
        end=session,
    )

    assert first.report_id != second.report_id


def test_policy_content_change_changes_report_identity_with_same_label() -> None:
    session = date(2026, 1, 2)
    data = source("source_a", "a", "b", [bar(session.isoformat())])
    first_policy = QualityPolicy(
        price_pass_tolerance_bps=Decimal("10"),
        price_warning_tolerance_bps=Decimal("50"),
    )
    second_policy = QualityPolicy(
        price_pass_tolerance_bps=Decimal("20"),
        price_warning_tolerance_bps=Decimal("60"),
    )

    first = evaluate(
        [data],
        [session],
        start=session,
        end=session,
        policy=first_policy,
    )
    second = evaluate(
        [data],
        [session],
        start=session,
        end=session,
        policy=second_policy,
    )

    assert first.policy_id == second.policy_id
    assert first.policy_version == second.policy_version
    assert first.eligibility.status is EligibilityStatus.ELIGIBLE
    assert second.eligibility.status is EligibilityStatus.ELIGIBLE
    assert first.context.policy_hash != second.context.policy_hash
    assert first.report_id != second.report_id


def test_exact_expected_session_set_has_content_identity() -> None:
    first = ExpectedSessionSetRef.from_sessions(
        "XNYS",
        [date(2026, 1, 2), date(2026, 1, 5)],
    )
    second = ExpectedSessionSetRef.from_sessions(
        "XNYS",
        [date(2026, 1, 2), date(2026, 1, 6)],
    )

    assert first.session_count == second.session_count
    assert first.content_hash != second.content_hash


def test_expected_session_identity_rejects_inconsistent_bounds() -> None:
    with pytest.raises(ValidationError, match="empty session set"):
        ExpectedSessionSetRef(
            calendar_id="XNYS",
            content_hash="a" * 64,
            session_count=0,
            first_session=date(2026, 1, 2),
        )
    with pytest.raises(ValidationError, match="requires date bounds"):
        ExpectedSessionSetRef(
            calendar_id="XNYS",
            content_hash="a" * 64,
            session_count=1,
        )
    with pytest.raises(ValidationError, match="bounds are invalid"):
        ExpectedSessionSetRef(
            calendar_id="XNYS",
            content_hash="a" * 64,
            session_count=2,
            first_session=date(2026, 1, 5),
            last_session=date(2026, 1, 2),
        )


def test_unsupported_normalized_schema_is_incomplete_for_requested_range() -> None:
    session = date(2026, 1, 2)
    data = source(
        "source_a",
        "a",
        "b",
        [bar(session.isoformat())],
        schema_version="unknown-normalized-v9",
    )
    report = evaluate([data], [session], start=session, end=session)
    schema_check = next(
        result for result in report.check_results if result.check_id == "schema_contract"
    )

    assert schema_check.status is CheckStatus.INCOMPLETE
    assert report.eligibility.status is EligibilityStatus.INCOMPLETE
    assert any(
        finding.finding_code == "unsupported_normalized_schema"
        for finding in schema_check.findings
    )


def test_normalized_input_ref_rejects_hash_mismatch() -> None:
    session = date(2026, 1, 2)
    bars = [bar(session.isoformat())]
    wrong_ref = NormalizedInputRef(
        content_hash="0" * 64,
        schema_version="normalized-bar-v1",
        normalizer_id="fixture-normalizer",
        normalizer_version="1.0.0",
        row_count=1,
    )

    verified = verified_capture("source_a", "a", "b")
    with pytest.raises(ValidationError, match="content hash does not match"):
        QualitySourceData(
            verified_capture=verified,
            evidence=evidence_ref_from_verified_capture(verified),
            normalized_input=wrong_ref,
            bars=tuple(bars),
        )


def test_historical_conflict_outside_requested_range_remains_visible() -> None:
    old, current = date(2002, 11, 1), date(2015, 1, 2)
    left = source(
        "source_a",
        "a",
        "b",
        [bar(old.isoformat(), close="100"), bar(current.isoformat(), close="200")],
    )
    right = source(
        "source_b",
        "d",
        "e",
        [bar(old.isoformat(), close="103"), bar(current.isoformat(), close="200")],
        request_char="f",
    )
    report = evaluate([left, right], [old, current], start=current, end=current)
    cross = next(
        result
        for result in report.check_results
        if result.check_id == "cross_source_ohlc"
    )

    assert cross.status is CheckStatus.FAIL
    assert any(
        finding.finding_code == "cross_source_field_conflict"
        and finding.affected_start == old
        for finding in cross.findings
    )
    assert report.eligibility.status is EligibilityStatus.ELIGIBLE


def test_historical_local_inversion_does_not_contaminate_later_range() -> None:
    inverted_previous = date(2002, 11, 4)
    inverted_current = date(2002, 11, 1)
    requested_start = date(2015, 1, 2)
    requested_end = date(2026, 1, 2)
    sessions = (
        inverted_previous,
        inverted_current,
        requested_start,
        requested_end,
    )
    data = source(
        "akshare",
        "a",
        "b",
        [bar(session.isoformat()) for session in sessions],
    )

    later = evaluate(
        [data],
        list(sessions),
        start=requested_start,
        end=requested_end,
    )
    finding = next(
        item
        for item in later.findings
        if item.finding_code == "non_monotonic_sessions"
    )

    assert finding.affected_start == inverted_current
    assert finding.affected_end == inverted_previous
    assert later.eligibility.status is EligibilityStatus.ELIGIBLE

    historical = evaluate(
        [data],
        list(sessions),
        start=inverted_current,
        end=inverted_previous,
    )
    assert historical.eligibility.status is EligibilityStatus.INELIGIBLE


def test_cross_source_warning_inside_range_is_visible_but_eligible() -> None:
    session = date(2026, 1, 2)
    left = source("source_a", "a", "b", [bar(session.isoformat(), close="100")])
    right = source(
        "source_b",
        "d",
        "e",
        [bar(session.isoformat(), close="100.2")],
        request_char="f",
    )
    report = evaluate([left, right], [session], start=session, end=session)

    assert report.eligibility.status is EligibilityStatus.ELIGIBLE
    assert report.eligibility.warning_finding_ids


def test_cross_source_fail_inside_range_is_ineligible() -> None:
    session = date(2026, 1, 2)
    left = source("source_a", "a", "b", [bar(session.isoformat(), close="100")])
    right = source(
        "source_b",
        "d",
        "e",
        [bar(session.isoformat(), close="101")],
        request_char="f",
    )
    report = evaluate([left, right], [session], start=session, end=session)

    assert report.eligibility.status is EligibilityStatus.INELIGIBLE
    assert report.eligibility.blocking_finding_ids


def test_optional_cross_source_gap_does_not_invalidate_covered_range() -> None:
    first, second = date(2026, 1, 2), date(2026, 1, 5)
    left = source("source_a", "a", "b", [bar(first.isoformat()), bar(second.isoformat())])
    right = source("source_b", "d", "e", [bar(first.isoformat())], request_char="f")
    report = evaluate([left, right], [first, second], start=first, end=second)

    assert report.eligibility.status is EligibilityStatus.ELIGIBLE
    assert report.eligibility.warning_finding_ids


def test_required_dual_source_gap_is_incomplete_not_blended() -> None:
    first, second = date(2026, 1, 2), date(2026, 1, 5)
    left = source("source_a", "a", "b", [bar(first.isoformat()), bar(second.isoformat())])
    right = source("source_b", "d", "e", [bar(first.isoformat())], request_char="f")
    policy = QualityPolicy(cross_source_requirement=CrossSourceRequirement.REQUIRED)
    report = evaluate(
        [left, right],
        [first, second],
        start=first,
        end=second,
        policy=policy,
    )

    assert report.eligibility.status is EligibilityStatus.INCOMPLETE
    assert report.eligibility.incomplete_finding_ids


def test_qqq_like_early_coverage_gap_does_not_block_later_range() -> None:
    early, current = date(2000, 1, 3), date(2015, 1, 2)
    data = source("source_a", "a", "b", [bar(current.isoformat())])
    report = evaluate([data], [early, current], start=current, end=current)

    assert report.eligibility.status is EligibilityStatus.ELIGIBLE
    assert any(
        finding.finding_code == "source_missing_session"
        and finding.affected_start == early
        for finding in report.findings
    )


def test_dia_like_isolated_missing_session_inside_range_is_incomplete() -> None:
    first, missing = date(2015, 4, 8), date(2015, 4, 9)
    data = source("source_a", "a", "b", [bar(first.isoformat())])
    report = evaluate([data], [first, missing], start=first, end=missing)

    assert report.eligibility.status is EligibilityStatus.INCOMPLETE
    assert any(
        finding.finding_code == "insufficient_session_coverage"
        for finding in report.findings
    )


def test_duplicate_session_blocks_requested_range() -> None:
    session = date(2026, 1, 2)
    duplicate = bar(session.isoformat())
    data = source("source_a", "a", "b", [duplicate, duplicate])
    report = evaluate([data], [session], start=session, end=session)

    assert report.eligibility.status is EligibilityStatus.INELIGIBLE
    check = next(
        result
        for result in report.check_results
        if result.check_id == "session_integrity"
    )
    assert check.status is CheckStatus.FAIL


def test_corrupted_ohlc_is_caught_when_upstream_validation_is_bypassed() -> None:
    session = date(2026, 1, 2)
    corrupted = bar(session.isoformat()).model_copy(update={"low": Decimal("120")})
    report = evaluate(
        [source("source_a", "a", "b", [corrupted])],
        [session],
        start=session,
        end=session,
    )

    assert report.eligibility.status is EligibilityStatus.INELIGIBLE
    assert any(finding.finding_code == "invalid_ohlc" for finding in report.findings)


def test_non_finite_price_fails_closed_when_upstream_validation_is_bypassed() -> None:
    session = date(2026, 1, 2)
    corrupted = bar(session.isoformat()).model_copy(update={"close": Decimal("NaN")})
    report = evaluate(
        [source("source_a", "a", "b", [corrupted])],
        [session],
        start=session,
        end=session,
    )

    assert report.eligibility.status is EligibilityStatus.INELIGIBLE
    assert any(finding.finding_code == "non_finite_field" for finding in report.findings)


def test_adversarial_non_decimal_numbers_keep_deterministic_input_identity() -> None:
    session = date(2026, 1, 2)
    valid = bar(session.isoformat())
    infinite = valid.model_copy(update={"close": float("inf")})
    integer = valid.model_copy(update={"close": 100})

    first = NormalizedInputRef.from_bars(
        (infinite,),
        schema_version="normalized-bar-v1",
        normalizer_id="fixture-normalizer",
        normalizer_version="1.0.0",
    )
    second = NormalizedInputRef.from_bars(
        (infinite,),
        schema_version="normalized-bar-v1",
        normalizer_id="fixture-normalizer",
        normalizer_version="1.0.0",
    )
    integer_ref = NormalizedInputRef.from_bars(
        (integer,),
        schema_version="normalized-bar-v1",
        normalizer_id="fixture-normalizer",
        normalizer_version="1.0.0",
    )

    assert first == second
    assert first.content_hash != integer_ref.content_hash


def test_revision_is_evidence_and_policy_can_make_it_incomplete() -> None:
    session = date(2026, 1, 2)
    previous = source(
        "source_a",
        "a",
        "b",
        [bar(session.isoformat(), close="100")],
        request_char="c",
    )
    current = source(
        "source_a",
        "d",
        "e",
        [bar(session.isoformat(), close="101")],
        request_char="c",
    )
    revision = RevisionPair(previous=previous, current=current)
    default = evaluate(
        [current],
        [session],
        start=session,
        end=session,
        revisions=(revision,),
    )
    strict = evaluate(
        [current],
        [session],
        start=session,
        end=session,
        revisions=(revision,),
        policy=QualityPolicy(revision_blocks_requested_range=True),
    )

    assert default.eligibility.status is EligibilityStatus.ELIGIBLE
    assert strict.eligibility.status is EligibilityStatus.INCOMPLETE
    assert any(
        finding.finding_code == "provider_history_revision"
        for finding in default.findings
    )


def test_revision_decimal_scale_is_one_scientific_value() -> None:
    session = date(2026, 1, 2)
    previous_bar = bar(session.isoformat())
    current_bar = previous_bar.model_copy(
        update={
            "open": Decimal("100.0"),
            "high": Decimal("110.00"),
            "low": Decimal("90.000"),
            "close": Decimal("100.0000"),
            "volume": Decimal("1000000.00"),
        }
    )
    previous = source("akshare", "a", "b", [previous_bar])
    current = source("AKSHARE", "c", "d", [current_bar])
    revision = RevisionPair(previous=previous, current=current)

    report = evaluate(
        [current],
        [session],
        start=session,
        end=session,
        revisions=(revision,),
        policy=QualityPolicy(revision_blocks_requested_range=True),
    )

    assert report.eligibility.status is EligibilityStatus.ELIGIBLE
    assert not any(
        finding.finding_code == "provider_history_revision"
        for finding in report.findings
    )


def test_source_order_does_not_change_report_identity() -> None:
    session = date(2026, 1, 2)
    left = source("source_a", "a", "b", [bar(session.isoformat())])
    right = source(
        "source_b",
        "d",
        "e",
        [bar(session.isoformat())],
        request_char="f",
    )
    first = evaluate([left, right], [session], start=session, end=session)
    second = evaluate([right, left], [session], start=session, end=session)

    assert first.report_id == second.report_id
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_case_variants_cannot_masquerade_as_independent_providers() -> None:
    session = date(2026, 1, 2)
    first = source("akshare", "a", "b", [bar(session.isoformat())])
    second = source("AKSHARE", "c", "d", [bar(session.isoformat())])

    with pytest.raises(DataQualityError, match="independent providers"):
        evaluate(
            [first, second],
            [session],
            start=session,
            end=session,
            policy=QualityPolicy(
                cross_source_requirement=CrossSourceRequirement.REQUIRED
            ),
        )


def test_empty_requested_session_set_is_incomplete_not_vacuously_eligible() -> None:
    requested = date(2026, 1, 3)
    empty_source = source("source_a", "a", "b", [])

    report = evaluate(
        [empty_source],
        [],
        start=requested,
        end=requested,
    )

    assert report.eligibility.status is EligibilityStatus.INCOMPLETE
    assert any(
        finding.finding_code == "no_expected_sessions_in_requested_range"
        for finding in report.findings
    )


def test_revision_inputs_change_report_identity_even_without_bar_differences() -> None:
    session = date(2026, 1, 2)
    active = source("source_a", "1", "2", [bar(session.isoformat())])
    previous = source("akshare", "a", "b", [bar(session.isoformat())])
    first_current = source("akshare", "c", "d", [bar(session.isoformat())])
    second_current = source("akshare", "e", "f", [bar(session.isoformat())])

    first = evaluate(
        [active],
        [session],
        start=session,
        end=session,
        revisions=(RevisionPair(previous=previous, current=first_current),),
    )
    second = evaluate(
        [active],
        [session],
        start=session,
        end=session,
        revisions=(RevisionPair(previous=previous, current=second_current),),
    )

    assert not first.findings
    assert not second.findings
    assert first.context.revision_input_refs != second.context.revision_input_refs
    assert first.report_id != second.report_id


def test_revision_sequence_change_is_a_distinct_normalized_observation() -> None:
    first, second = date(2026, 1, 2), date(2026, 1, 5)
    ordered_bars = [bar(first.isoformat()), bar(second.isoformat())]
    previous = source("akshare", "a", "b", ordered_bars)
    reversed_bars = list(reversed(ordered_bars))
    current = QualitySourceData(
        verified_capture=previous.verified_capture,
        evidence=previous.evidence,
        normalized_input=normalized_input(reversed_bars),
        bars=tuple(reversed_bars),
    )
    revision = RevisionPair(previous=previous, current=current)

    report = evaluate(
        [previous],
        [first, second],
        start=first,
        end=second,
        revisions=(revision,),
    )

    assert revision.previous.normalized_input != revision.current.normalized_input
    assert report.context.revision_input_refs[0].previous_normalized_input != (
        report.context.revision_input_refs[0].current_normalized_input
    )


def test_quality_input_identity_rejects_unsafe_model_copies() -> None:
    session = date(2026, 1, 2)
    valid_source = source("source_a", "a", "b", [bar(session.isoformat())])
    unsafe_evidence = valid_source.evidence.model_copy(update={"provider": ""})
    unsafe_input = valid_source.normalized_input.model_copy(
        update={"content_hash": "bad"}
    )
    unsafe_policy = QualityPolicy().model_copy(
        update={
            "price_pass_tolerance_bps": Decimal("100"),
            "price_warning_tolerance_bps": Decimal("10"),
        }
    )

    with pytest.raises(ValidationError):
        _ = unsafe_evidence.evidence_id
    with pytest.raises(ValidationError):
        _ = unsafe_input.input_id
    with pytest.raises(ValidationError):
        _ = unsafe_policy.content_hash
    with pytest.raises(DataQualityError, match="quality source failed integrity validation"):
        evaluate(
            [valid_source.model_copy(update={"normalized_input": unsafe_input})],
            [session],
            start=session,
            end=session,
        )
    mismatched_input = valid_source.normalized_input.model_copy(
        update={"content_hash": "0" * 64}
    )
    with pytest.raises(DataQualityError, match="normalized input content hash"):
        evaluate(
            [valid_source.model_copy(update={"normalized_input": mismatched_input})],
            [session],
            start=session,
            end=session,
        )


def test_verified_capture_adapter_revalidates_top_level_and_nested_models() -> None:
    verified = verified_capture("akshare", "a", "b")
    invalid_license = verified.manifest.license_profile.model_copy(
        update={"profile_id": ""}
    )
    invalid_manifest = verified.manifest.model_copy(
        update={"license_profile": invalid_license}
    )
    invalid_capture = verified.capture.model_copy(update={"provider": ""})
    unsafe_values = (
        verified.model_copy(update={"manifest_hash": "f" * 64}),
        verified.model_copy(update={"manifest": invalid_manifest}),
        verified.model_copy(update={"capture": invalid_capture}),
    )

    for unsafe in unsafe_values:
        with pytest.raises(
            DataQualityError, match="verified capture failed provenance validation"
        ):
            evidence_ref_from_verified_capture(unsafe)


def test_evaluation_rejects_declared_evidence_not_derived_from_capture() -> None:
    session = date(2026, 1, 2)
    valid_source = source("akshare", "a", "b", [bar(session.isoformat())])
    false_evidence = valid_source.evidence.model_copy(
        update={"manifest_hash": "f" * 64}
    )

    with pytest.raises(DataQualityError, match="must derive from its VerifiedCapture"):
        evaluate(
            [valid_source.model_copy(update={"evidence": false_evidence})],
            [session],
            start=session,
            end=session,
        )


def test_report_identity_rejects_semantically_inconsistent_eligibility_copy() -> None:
    session = date(2026, 1, 2)
    corrupted = bar(session.isoformat()).model_copy(update={"low": Decimal("120")})
    report = evaluate(
        [source("source_a", "a", "b", [corrupted])],
        [session],
        start=session,
        end=session,
    )
    assert report.eligibility.status is EligibilityStatus.INELIGIBLE
    unsafe_eligibility = report.eligibility.model_copy(
        update={
            "status": EligibilityStatus.ELIGIBLE,
            "blocking_finding_ids": (),
        }
    )
    unsafe_report = report.model_copy(update={"eligibility": unsafe_eligibility})

    with pytest.raises(ValidationError, match="blocking eligibility evidence"):
        _ = unsafe_report.report_id
    incomplete_registry = report.model_copy(
        update={"check_results": report.check_results[:-1]}
    )
    with pytest.raises(ValidationError, match="exact A3 v1 check registry"):
        _ = incomplete_registry.report_id


def test_check_status_cannot_contradict_findings() -> None:
    session = date(2026, 1, 2)
    corrupted = bar(session.isoformat()).model_copy(update={"low": Decimal("120")})
    report = evaluate(
        [source("akshare", "a", "b", [corrupted])],
        [session],
        start=session,
        end=session,
    )
    failed = next(result for result in report.check_results if result.findings)

    with pytest.raises(ValidationError, match="status is inconsistent"):
        CheckResult.model_validate(
            failed.model_copy(update={"status": CheckStatus.PASS}).model_dump(
                mode="python"
            )
        )
    clean = next(result for result in report.check_results if not result.findings)
    with pytest.raises(ValidationError, match="empty quality check"):
        CheckResult.model_validate(
            clean.model_copy(update={"status": CheckStatus.FAIL}).model_dump(
                mode="python"
            )
        )
    informational = QualityFinding(
        check_id="fixture",
        check_version="2",
        severity=FindingSeverity.INFO,
        finding_code="fixture_information",
        affected_start=session,
        affected_end=session,
        message="fixture informational evidence",
    )
    info_result = CheckResult(
        check_id="fixture",
        check_version="2",
        status=CheckStatus.PASS,
        findings=(informational,),
    )
    assert info_result.status is CheckStatus.PASS


def test_report_and_context_identity_boundaries_fail_closed() -> None:
    session = date(2026, 1, 2)
    report = evaluate(
        [source("akshare", "a", "b", [bar(session.isoformat())])],
        [session],
        start=session,
        end=session,
    )
    invalid_contexts = (
        report.context.model_copy(update={"quality_suite_version": "999"}),
        report.context.model_copy(
            update={"requested_start": date(2026, 1, 3)}
        ),
        report.context.model_copy(update={"observed_start": date(2026, 1, 3)}),
        report.context.model_copy(update={"calendar_id": "ARCX"}),
        report.context.model_copy(update={"normalized_input_refs": ()}),
    )
    for context in invalid_contexts:
        with pytest.raises(ValidationError):
            _ = report.model_copy(update={"context": context}).report_id

    invalid_reports = (
        report.model_copy(update={"policy_id": "different-policy"}),
        report.model_copy(update={"policy_version": "999"}),
        report.model_copy(
            update={
                "eligibility": report.eligibility.model_copy(
                    update={"requested_end": date(2026, 1, 3)}
                )
            }
        ),
        report.model_copy(update={"report_content_hash": "f" * 64}),
    )
    for candidate in invalid_reports:
        with pytest.raises(ValidationError):
            _ = candidate.report_id

    invalid_range = report.eligibility.model_copy(
        update={
            "requested_start": date(2026, 1, 3),
            "requested_end": date(2026, 1, 2),
        }
    )
    with pytest.raises(ValidationError, match="eligibility range"):
        type(report.eligibility).model_validate(invalid_range.model_dump(mode="python"))


def test_fully_rehashed_forged_report_fails_input_closure_replay() -> None:
    session = date(2026, 1, 2)
    corrupted = bar(session.isoformat()).model_copy(update={"low": Decimal("120")})
    data = source("akshare", "a", "b", [corrupted])
    actual = evaluate([data], [session], start=session, end=session)
    forged_results = tuple(
        CheckResult(
            check_id=result.check_id,
            check_version=result.check_version,
            status=(
                CheckStatus.NOT_APPLICABLE
                if result.status is CheckStatus.NOT_APPLICABLE
                else CheckStatus.PASS
            ),
            findings=(),
            metrics=result.metrics,
        )
        for result in actual.check_results
    )
    forged = DataQualityReportV2.from_evaluation(
        context=actual.context,
        policy_id=actual.policy_id,
        policy_version=actual.policy_version,
        check_results=forged_results,
        eligibility=RangeEligibility(
            requested_start=session,
            requested_end=session,
            status=EligibilityStatus.ELIGIBLE,
        ),
    )
    assert forged.eligibility.status is EligibilityStatus.ELIGIBLE

    unsafe = actual.model_copy(update={"report_content_hash": "f" * 64})
    with pytest.raises(DataQualityError, match="report failed integrity validation"):
        SUITE.verify_report(
            unsafe,
            asset=ASSET,
            frequency=BarFrequency.DAY,
            adjustment_mode=AdjustmentMode.RAW,
            calendar_id="XNYS",
            requested_start=session,
            requested_end=session,
            sources=(data,),
            expected_sessions=(session,),
        )

    with pytest.raises(DataQualityError, match="does not match deterministic"):
        SUITE.verify_report(
            forged,
            asset=ASSET,
            frequency=BarFrequency.DAY,
            adjustment_mode=AdjustmentMode.RAW,
            calendar_id="XNYS",
            requested_start=session,
            requested_end=session,
            sources=(data,),
            expected_sessions=(session,),
        )

    verified = SUITE.verify_report(
        actual,
        asset=ASSET,
        frequency=BarFrequency.DAY,
        adjustment_mode=AdjustmentMode.RAW,
        calendar_id="XNYS",
        requested_start=session,
        requested_end=session,
        sources=(data,),
        expected_sessions=(session,),
    )
    assert verified == actual


def test_structurally_invalid_bar_fails_before_quality_conclusions() -> None:
    session = date(2026, 1, 2)
    valid_bar = bar(session.isoformat())
    unsafe_bar = valid_bar.model_copy(
        update={"available_at": valid_bar.session_open_at}
    )
    unsafe_source = source("source_a", "a", "b", [unsafe_bar])

    with pytest.raises(DataQualityError, match="availability precedes"):
        evaluate(
            [unsafe_source],
            [session],
            start=session,
            end=session,
        )


def test_report_findings_and_metrics_are_deeply_immutable() -> None:
    session = date(2026, 1, 2)
    corrupted = bar(session.isoformat()).model_copy(update={"low": Decimal("120")})
    report = evaluate(
        [source("source_a", "a", "b", [corrupted])],
        [session],
        start=session,
        end=session,
    )
    original_id = report.report_id
    finding = next(
        item for item in report.findings if item.finding_code == "invalid_ohlc"
    )

    with pytest.raises(TypeError):
        finding.observed_values["low"] = "1"  # type: ignore[index]
    with pytest.raises(TypeError):
        report.check_results[0].metrics["source_count"] = 999  # type: ignore[index]
    assert report.report_id == original_id


def test_adjusted_series_remain_incomplete_without_point_in_time_action_policy() -> None:
    session = date(2026, 1, 2)
    left = source("akshare", "a", "b", [bar(session.isoformat())])
    right = source("yfinance", "c", "d", [bar(session.isoformat())])

    report = SUITE.evaluate(
        asset=ASSET,
        frequency=BarFrequency.DAY,
        adjustment_mode=AdjustmentMode.TOTAL_RETURN,
        calendar_id="XNYS",
        requested_start=session,
        requested_end=session,
        sources=(left, right),
        expected_sessions=(session,),
        policy=QualityPolicy(
            cross_source_requirement=CrossSourceRequirement.REQUIRED
        ),
    )

    assert report.eligibility.status is EligibilityStatus.INCOMPLETE
    assert any(
        finding.finding_code == "unsupported_adjustment_semantics"
        for finding in report.findings
    )
    cross_source = next(
        result for result in report.check_results if result.check_id == "cross_source_ohlc"
    )
    assert cross_source.status is CheckStatus.NOT_APPLICABLE
    assert cross_source.metrics["compared_values"] == 0


def test_a3_v1_rejects_non_daily_frequency_claims() -> None:
    session = date(2026, 1, 2)
    with pytest.raises(DataQualityError, match="daily normalized bars"):
        SUITE.evaluate(
            asset=ASSET,
            frequency=BarFrequency.WEEK,
            adjustment_mode=AdjustmentMode.RAW,
            calendar_id="XNYS",
            requested_start=session,
            requested_end=session,
            sources=(source("source_a", "a", "b", [bar(session.isoformat())]),),
            expected_sessions=(session,),
        )


def test_public_evaluation_rejects_untyped_range_calendar_and_adjustment() -> None:
    session = date(2026, 1, 2)
    valid_source = source("source_a", "a", "b", [bar(session.isoformat())])
    base = {
        "asset": ASSET,
        "frequency": BarFrequency.DAY,
        "adjustment_mode": AdjustmentMode.RAW,
        "calendar_id": "XNYS",
        "requested_start": session,
        "requested_end": session,
        "sources": (valid_source,),
        "expected_sessions": (session,),
    }
    invalid_inputs = (
        {"requested_start": "2026-01-02"},
        {"requested_start": date(2026, 1, 3)},
        {"sources": ()},
        {"frequency": "1d"},
        {"calendar_id": ""},
        {"adjustment_mode": "raw"},
        {"expected_sessions": ("2026-01-02",)},
        {"asset": ASSET.model_copy(update={"venue": ""})},
        {
            "policy": QualityPolicy().model_copy(
                update={
                    "price_pass_tolerance_bps": Decimal("100"),
                    "price_warning_tolerance_bps": Decimal("10"),
                }
            )
        },
    )
    for override in invalid_inputs:
        with pytest.raises(DataQualityError):
            SUITE.evaluate(**(base | override))  # type: ignore[arg-type]
