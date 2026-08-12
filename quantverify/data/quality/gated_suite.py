"""Public A3 QualitySuite gate enforcing independent active source authorities."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from quantverify.core.enums import AdjustmentMode, BarFrequency
from quantverify.core.exceptions import DataQualityError
from quantverify.core.models import AssetId
from quantverify.data.quality.models import (
    CheckResult,
    CheckStatus,
    DataQualityReportV2,
    QualitySourceData,
    RevisionPair,
)
from quantverify.data.quality.policy import QualityPolicy
from quantverify.data.quality.suite import QualitySuite as _BaseQualitySuite


class QualitySuite(_BaseQualitySuite):
    """Quality suite whose active verification sources are independent providers.

    A3 v1 defines the source-authority key as ``QualityEvidenceRef.provider``.
    One provider may contribute at most one current active observation. Historical
    observations from the same provider belong in ``RevisionPair`` instead.
    """

    def evaluate(
        self,
        *,
        asset: AssetId,
        frequency: BarFrequency,
        adjustment_mode: AdjustmentMode,
        calendar_id: str,
        requested_start: date,
        requested_end: date,
        sources: Sequence[QualitySourceData],
        expected_sessions: Sequence[date],
        policy: QualityPolicy | None = None,
        revisions: Sequence[RevisionPair] = (),
    ) -> DataQualityReportV2:
        self._validate_independent_sources(sources)
        return super().evaluate(
            asset=asset,
            frequency=frequency,
            adjustment_mode=adjustment_mode,
            calendar_id=calendar_id,
            requested_start=requested_start,
            requested_end=requested_end,
            sources=sources,
            expected_sessions=expected_sessions,
            policy=policy,
            revisions=revisions,
        )

    @staticmethod
    def _validate_independent_sources(sources: Sequence[QualitySourceData]) -> None:
        evidence_ids = [source.evidence.evidence_id for source in sources]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise DataQualityError(
                "active quality sources must have unique evidence identities"
            )

        providers = [source.evidence.provider for source in sources]
        if len(providers) != len(set(providers)):
            raise DataQualityError(
                "active quality sources must represent independent providers; "
                "same-provider historical observations belong in RevisionPair"
            )

    def _requested_range_coverage(
        self,
        sources: Sequence[QualitySourceData],
        expected_sessions: Sequence[date],
        requested_start: date,
        requested_end: date,
        policy: QualityPolicy,
    ) -> CheckResult:
        self._validate_independent_sources(sources)
        expected = tuple(
            session
            for session in expected_sessions
            if requested_start <= session <= requested_end
        )
        provider_sessions = {
            source.evidence.provider: {bar.session for bar in source.bars}
            for source in sources
        }
        counts = {
            session: sum(
                session in observed_sessions
                for observed_sessions in provider_sessions.values()
            )
            for session in expected
        }
        missing_all = {session for session, count in counts.items() if count == 0}
        insufficient_verify = {
            session
            for session, count in counts.items()
            if 0 < count < policy.minimum_sources_per_session
        }
        findings = []
        evidence_ids = tuple(source.evidence.evidence_id for source in sources)
        findings.extend(
            self._coverage_findings(
                expected,
                missing_all,
                code="insufficient_session_coverage",
                source_ids=evidence_ids,
                minimum_sources=policy.minimum_sources_per_session,
                counts=counts,
            )
        )
        findings.extend(
            self._coverage_findings(
                expected,
                insufficient_verify,
                code="insufficient_source_verification",
                source_ids=evidence_ids,
                minimum_sources=policy.minimum_sources_per_session,
                counts=counts,
            )
        )
        status = CheckStatus.INCOMPLETE if findings else CheckStatus.PASS
        return self._result(
            "requested_range_coverage",
            findings,
            {
                "minimum_sources_per_session": policy.minimum_sources_per_session,
                "requested_expected_sessions": len(expected),
                "source_authority_key": "provider",
                "independent_provider_count": len(provider_sessions),
            },
            status=status,
        )

    def _cross_source_overlap(
        self,
        sources: Sequence[QualitySourceData],
    ) -> CheckResult:
        self._validate_independent_sources(sources)
        return super()._cross_source_overlap(sources)

    def _cross_source_ohlc(
        self,
        sources: Sequence[QualitySourceData],
        policy: QualityPolicy,
    ) -> CheckResult:
        self._validate_independent_sources(sources)
        return super()._cross_source_ohlc(sources, policy)
