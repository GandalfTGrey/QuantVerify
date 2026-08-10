from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest import TestCase

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


def bar(day: str, *, close: str = "100", source: str = "fixture") -> NormalizedBar:
    session = date.fromisoformat(day)
    close_value = Decimal(close)
    high = max(Decimal("110"), close_value + Decimal("10"))
    low = min(Decimal("90"), close_value - Decimal("10"))
    return NormalizedBar(
        asset=ASSET,
        session=session,
        session_open_at=datetime(session.year, session.month, session.day, 14, 30, tzinfo=UTC),
        session_close_at=datetime(session.year, session.month, session.day, 21, tzinfo=UTC),
        available_at=datetime(session.year, session.month, session.day, 21, tzinfo=UTC),
        open=Decimal("100"),
        high=high,
        low=low,
        close=close_value,
        volume=Decimal("1000000"),
        source=source,
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
    return QualitySourceData(
        evidence=evidence(
            provider,
            capture_char,
            manifest_char,
            request_char=request_char,
        ),
        bars=tuple(bars),
    )


class QualitySuiteV2Tests(TestCase):
    def setUp(self) -> None:
        self.suite = QualitySuite()

    def evaluate(
        self,
        sources: list[QualitySourceData],
        expected_sessions: list[date],
        *,
        start: date,
        end: date,
        policy: QualityPolicy | None = None,
        revisions: tuple[RevisionPair, ...] = (),
    ) -> DataQualityReportV2:
        return self.suite.evaluate(
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

    def test_clean_single_source_range_is_eligible_and_deterministic(self) -> None:
        sessions = [date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 6)]
        data = source(
            "source_a",
            "a",
            "b",
            [bar(day.isoformat(), source="source_a") for day in sessions],
        )
        first = self.evaluate([data], sessions, start=sessions[0], end=sessions[-1])
        second = self.evaluate([data], sessions, start=sessions[0], end=sessions[-1])

        self.assertEqual(first.eligibility.status, EligibilityStatus.ELIGIBLE)
        self.assertEqual(first.report_id, second.report_id)
        self.assertEqual(first.model_dump(mode="json"), second.model_dump(mode="json"))

    def test_historical_conflict_outside_requested_range_remains_visible(self) -> None:
        old = date(2002, 11, 1)
        current = date(2015, 1, 2)
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
        report = self.evaluate([left, right], [old, current], start=current, end=current)
        cross = next(r for r in report.check_results if r.check_id == "cross_source_ohlc")

        self.assertEqual(cross.status, CheckStatus.FAIL)
        self.assertTrue(
            any(f.finding_code == "cross_source_field_conflict" and f.affected_start == old for f in cross.findings)
        )
        self.assertEqual(report.eligibility.status, EligibilityStatus.ELIGIBLE)

    def test_cross_source_warning_inside_range_is_visible_but_eligible(self) -> None:
        session = date(2026, 1, 2)
        left = source("source_a", "a", "b", [bar(session.isoformat(), close="100")])
        right = source(
            "source_b",
            "d",
            "e",
            [bar(session.isoformat(), close="100.2")],
            request_char="f",
        )
        report = self.evaluate([left, right], [session], start=session, end=session)

        self.assertEqual(report.eligibility.status, EligibilityStatus.ELIGIBLE)
        self.assertTrue(report.eligibility.warning_finding_ids)

    def test_cross_source_fail_inside_range_is_ineligible(self) -> None:
        session = date(2026, 1, 2)
        left = source("source_a", "a", "b", [bar(session.isoformat(), close="100")])
        right = source(
            "source_b",
            "d",
            "e",
            [bar(session.isoformat(), close="101")],
            request_char="f",
        )
        report = self.evaluate([left, right], [session], start=session, end=session)

        self.assertEqual(report.eligibility.status, EligibilityStatus.INELIGIBLE)
        self.assertTrue(report.eligibility.blocking_finding_ids)

    def test_optional_cross_source_gap_does_not_invalidate_covered_range(self) -> None:
        first, second = date(2026, 1, 2), date(2026, 1, 5)
        left = source("source_a", "a", "b", [bar(first.isoformat()), bar(second.isoformat())])
        right = source("source_b", "d", "e", [bar(first.isoformat())], request_char="f")
        report = self.evaluate([left, right], [first, second], start=first, end=second)

        self.assertEqual(report.eligibility.status, EligibilityStatus.ELIGIBLE)
        self.assertTrue(report.eligibility.warning_finding_ids)

    def test_required_dual_source_gap_is_incomplete_not_blended(self) -> None:
        first, second = date(2026, 1, 2), date(2026, 1, 5)
        left = source("source_a", "a", "b", [bar(first.isoformat()), bar(second.isoformat())])
        right = source("source_b", "d", "e", [bar(first.isoformat())], request_char="f")
        policy = QualityPolicy(cross_source_requirement=CrossSourceRequirement.REQUIRED)
        report = self.evaluate(
            [left, right],
            [first, second],
            start=first,
            end=second,
            policy=policy,
        )

        self.assertEqual(report.eligibility.status, EligibilityStatus.INCOMPLETE)
        self.assertTrue(report.eligibility.incomplete_finding_ids)

    def test_qqq_like_early_coverage_gap_does_not_block_later_range(self) -> None:
        early, current = date(2000, 1, 3), date(2015, 1, 2)
        data = source("source_a", "a", "b", [bar(current.isoformat())])
        report = self.evaluate([data], [early, current], start=current, end=current)

        self.assertEqual(report.eligibility.status, EligibilityStatus.ELIGIBLE)
        self.assertTrue(
            any(f.finding_code == "source_missing_session" and f.affected_start == early for f in report.findings)
        )

    def test_dia_like_isolated_missing_session_inside_range_is_incomplete(self) -> None:
        first, missing = date(2015, 4, 8), date(2015, 4, 9)
        data = source("source_a", "a", "b", [bar(first.isoformat())])
        report = self.evaluate([data], [first, missing], start=first, end=missing)

        self.assertEqual(report.eligibility.status, EligibilityStatus.INCOMPLETE)
        self.assertTrue(
            any(f.finding_code == "insufficient_session_coverage" for f in report.findings)
        )

    def test_duplicate_session_blocks_requested_range(self) -> None:
        session = date(2026, 1, 2)
        duplicate = bar(session.isoformat())
        data = source("source_a", "a", "b", [duplicate, duplicate])
        report = self.evaluate([data], [session], start=session, end=session)

        self.assertEqual(report.eligibility.status, EligibilityStatus.INELIGIBLE)
        check = next(r for r in report.check_results if r.check_id == "session_integrity")
        self.assertEqual(check.status, CheckStatus.FAIL)

    def test_corrupted_ohlc_is_caught_even_if_model_validation_was_bypassed(self) -> None:
        session = date(2026, 1, 2)
        corrupted = bar(session.isoformat()).model_copy(update={"low": Decimal("120")})
        data = source("source_a", "a", "b", [corrupted])
        report = self.evaluate([data], [session], start=session, end=session)

        self.assertEqual(report.eligibility.status, EligibilityStatus.INELIGIBLE)
        self.assertTrue(any(f.finding_code == "invalid_ohlc" for f in report.findings))

    def test_non_finite_price_is_fail_closed_when_validation_is_bypassed(self) -> None:
        session = date(2026, 1, 2)
        corrupted = bar(session.isoformat()).model_copy(update={"close": Decimal("NaN")})
        data = source("source_a", "a", "b", [corrupted])
        report = self.evaluate([data], [session], start=session, end=session)

        self.assertEqual(report.eligibility.status, EligibilityStatus.INELIGIBLE)
        self.assertTrue(any(f.finding_code == "non_finite_field" for f in report.findings))

    def test_revision_is_evidence_and_policy_can_make_it_incomplete(self) -> None:
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
        default = self.evaluate([current], [session], start=session, end=session, revisions=(revision,))
        strict = self.evaluate(
            [current],
            [session],
            start=session,
            end=session,
            revisions=(revision,),
            policy=QualityPolicy(revision_blocks_requested_range=True),
        )

        self.assertEqual(default.eligibility.status, EligibilityStatus.ELIGIBLE)
        self.assertEqual(strict.eligibility.status, EligibilityStatus.INCOMPLETE)
        self.assertTrue(any(f.finding_code == "provider_history_revision" for f in default.findings))

    def test_source_order_does_not_change_report_identity(self) -> None:
        session = date(2026, 1, 2)
        left = source("source_a", "a", "b", [bar(session.isoformat())])
        right = source("source_b", "d", "e", [bar(session.isoformat())], request_char="f")
        first = self.evaluate([left, right], [session], start=session, end=session)
        second = self.evaluate([right, left], [session], start=session, end=session)

        self.assertEqual(first.report_id, second.report_id)
        self.assertEqual(first.model_dump(mode="json"), second.model_dump(mode="json"))
