from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from quantverify.core.enums import AdjustmentMode, AssetClass, BarFrequency
from quantverify.core.models import AssetId
from quantverify.data.models import NormalizedBar
from quantverify.data.quality import (
    CheckStatus,
    CrossSourceRequirement,
    DataQualityReportV2,
    EligibilityStatus,
    QualityEvidenceRef,
    QualityPolicy,
    QualitySourceData,
    QualitySuite,
    RevisionPair,
)

ASSET = AssetId(
    symbol="QQQ",
    venue="XNAS",
    asset_class=AssetClass.ETF,
    currency="USD",
)
SUITE = QualitySuite()


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


def evidence(
    provider: str,
    capture_char: str,
    manifest_char: str,
    *,
    request_char: str = "c",
) -> QualityEvidenceRef:
    return QualityEvidenceRef(
        capture_hash=capture_char * 64,
        manifest_hash=manifest_char * 64,
        provider=provider,
        endpoint="daily",
        capture_schema_version="fixture-v1",
        adapter_version="fixture-adapter-v1",
        request_fingerprint=request_char * 64,
    )


def source(
    provider: str,
    capture_char: str,
    manifest_char: str,
    bars: list[NormalizedBar],
    *,
    request_char: str = "c",
) -> QualitySourceData:
    # Tests intentionally permit adversarial bars that bypass NormalizedBar's
    # boundary validation so QualitySuite defense-in-depth can be exercised.
    return QualitySourceData.model_construct(
        evidence=evidence(
            provider,
            capture_char,
            manifest_char,
            request_char=request_char,
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
