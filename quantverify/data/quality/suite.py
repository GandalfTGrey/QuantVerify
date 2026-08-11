"""Deterministic offline quality suite with range-scoped eligibility."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from itertools import combinations
from typing import Any

from quantverify.core.enums import AdjustmentMode, BarFrequency
from quantverify.core.exceptions import DataQualityError
from quantverify.core.models import AssetId
from quantverify.data.models import NormalizedBar
from quantverify.data.quality.models import (
    CheckResult,
    CheckStatus,
    DataQualityReportV2,
    EligibilityStatus,
    ExpectedSessionSetRef,
    FindingSeverity,
    QualityEvaluationContext,
    QualityFinding,
    QualitySourceData,
    RangeEligibility,
    RevisionPair,
)
from quantverify.data.quality.policy import QualityPolicy

_CHECK_VERSION = "2"
_PRICE_FIELDS = ("open", "high", "low", "close")
_INELIGIBLE_CODES = frozenset(
    {
        "cross_source_field_conflict",
        "duplicate_session",
        "invalid_ohlc",
        "negative_volume",
        "non_finite_field",
        "non_monotonic_sessions",
        "non_positive_price",
        "unexpected_session",
    }
)
_INCOMPLETE_CODES = frozenset(
    {
        "insufficient_session_coverage",
        "insufficient_source_verification",
        "unsupported_normalized_schema",
    }
)


class QualitySuite:
    """Evaluate captured and normalized market data without provider access."""

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
        if requested_start > requested_end:
            raise DataQualityError("requested_start must not be later than requested_end")
        if not sources:
            raise DataQualityError("quality evaluation requires at least one source")

        active_policy = policy or QualityPolicy()
        ordered_sources = tuple(
            sorted(
                sources,
                key=lambda source: (
                    source.evidence.evidence_id,
                    source.normalized_input.input_id,
                ),
            )
        )
        self._validate_assets(asset, ordered_sources)
        expected = tuple(sorted(set(expected_sessions)))
        expected_ref = ExpectedSessionSetRef.from_sessions(calendar_id, expected)
        ordered_revisions = tuple(
            sorted(
                revisions,
                key=lambda pair: (
                    pair.previous.evidence.evidence_id,
                    pair.previous.normalized_input.input_id,
                    pair.current.evidence.evidence_id,
                    pair.current.normalized_input.input_id,
                ),
            )
        )
        all_sessions = [bar.session for source in ordered_sources for bar in source.bars]
        observed_start = min(all_sessions) if all_sessions else requested_start
        observed_end = max(all_sessions) if all_sessions else requested_end
        context = QualityEvaluationContext(
            asset=asset,
            frequency=frequency,
            adjustment_mode=adjustment_mode,
            calendar_id=calendar_id,
            expected_sessions=expected_ref,
            requested_start=requested_start,
            requested_end=requested_end,
            observed_start=observed_start,
            observed_end=observed_end,
            policy_version=active_policy.version,
            policy_hash=active_policy.content_hash,
            evidence_refs=tuple(source.evidence for source in ordered_sources),
            normalized_input_refs=tuple(
                source.normalized_input for source in ordered_sources
            ),
        )

        results = (
            self._schema_contract(
                ordered_sources,
                active_policy,
                requested_start,
                requested_end,
            ),
            self._session_integrity(ordered_sources),
            self._ohlc_integrity(ordered_sources),
            self._volume_integrity(ordered_sources),
            self._calendar_membership(ordered_sources, expected),
            self._source_coverage(ordered_sources, expected),
            self._requested_range_coverage(
                ordered_sources,
                expected,
                requested_start,
                requested_end,
                active_policy,
            ),
            self._cross_source_overlap(ordered_sources),
            self._cross_source_ohlc(ordered_sources, active_policy),
            self._provider_revision(ordered_revisions),
            self._adjustment_semantics(adjustment_mode),
        )
        findings = tuple(
            finding for result in results for finding in result.findings
        )
        eligibility = self._evaluate_range(
            findings,
            requested_start=requested_start,
            requested_end=requested_end,
            policy=active_policy,
        )
        return DataQualityReportV2(
            context=context,
            policy_id=active_policy.policy_id,
            policy_version=active_policy.version,
            check_results=results,
            eligibility=eligibility,
        )

    @staticmethod
    def _validate_assets(asset: AssetId, sources: Sequence[QualitySourceData]) -> None:
        for source in sources:
            if any(bar.asset != asset for bar in source.bars):
                raise DataQualityError(
                    "quality evaluation requires every source to match the requested asset"
                )

    def _schema_contract(
        self,
        sources: Sequence[QualitySourceData],
        policy: QualityPolicy,
        requested_start: date,
        requested_end: date,
    ) -> CheckResult:
        findings: list[QualityFinding] = []
        accepted = set(policy.accepted_normalized_schema_versions)
        for source in sources:
            normalized = source.normalized_input
            if normalized.schema_version in accepted:
                continue
            sessions = [bar.session for bar in source.bars]
            affected_start = min(sessions) if sessions else requested_start
            affected_end = max(sessions) if sessions else requested_end
            findings.append(
                self._finding(
                    "schema_contract",
                    FindingSeverity.ERROR,
                    "unsupported_normalized_schema",
                    affected_start,
                    affected_end,
                    "normalized input schema is not accepted by quality policy",
                    source_ids=(source.evidence.evidence_id,),
                    values={
                        "normalizer_id": normalized.normalizer_id,
                        "normalizer_version": normalized.normalizer_version,
                        "schema_version": normalized.schema_version,
                    },
                )
            )
        status = CheckStatus.INCOMPLETE if findings else CheckStatus.PASS
        return self._result(
            "schema_contract",
            findings,
            {
                "accepted_normalized_schema_versions": sorted(accepted),
                "capture_schema_versions": [
                    source.evidence.capture_schema_version for source in sources
                ],
                "normalized_schema_versions": [
                    source.normalized_input.schema_version for source in sources
                ],
                "normalizers": [
                    {
                        "id": source.normalized_input.normalizer_id,
                        "version": source.normalized_input.normalizer_version,
                    }
                    for source in sources
                ],
                "source_count": len(sources),
            },
            status=status,
        )

    def _session_integrity(self, sources: Sequence[QualitySourceData]) -> CheckResult:
        findings: list[QualityFinding] = []
        for source in sources:
            sessions = [bar.session for bar in source.bars]
            counts = Counter(sessions)
            for session in sorted(day for day, count in counts.items() if count > 1):
                findings.append(
                    self._finding(
                        "session_integrity",
                        FindingSeverity.ERROR,
                        "duplicate_session",
                        session,
                        session,
                        "duplicate market session",
                        source_ids=(source.evidence.evidence_id,),
                        values={"count": counts[session]},
                    )
                )
            if sessions and sessions != sorted(sessions):
                findings.append(
                    self._finding(
                        "session_integrity",
                        FindingSeverity.ERROR,
                        "non_monotonic_sessions",
                        min(sessions),
                        max(sessions),
                        "source sessions are not monotonically increasing",
                        source_ids=(source.evidence.evidence_id,),
                        values={"record_count": len(sessions)},
                    )
                )
        return self._result(
            "session_integrity",
            findings,
            {"source_count": len(sources)},
        )

    def _ohlc_integrity(self, sources: Sequence[QualitySourceData]) -> CheckResult:
        findings: list[QualityFinding] = []
        for source in sources:
            evidence_id = source.evidence.evidence_id
            for bar in source.bars:
                parsed = {
                    field: self._decimal(getattr(bar, field)) for field in _PRICE_FIELDS
                }
                for field, value in parsed.items():
                    if value is None:
                        findings.append(
                            self._finding(
                                "ohlc_integrity",
                                FindingSeverity.BLOCKER,
                                "non_finite_field",
                                bar.session,
                                bar.session,
                                f"{field} is not a finite decimal",
                                field=field,
                                source_ids=(evidence_id,),
                                values={"value": str(getattr(bar, field))},
                            )
                        )
                    elif value <= 0:
                        findings.append(
                            self._finding(
                                "ohlc_integrity",
                                FindingSeverity.BLOCKER,
                                "non_positive_price",
                                bar.session,
                                bar.session,
                                f"{field} must be positive",
                                field=field,
                                source_ids=(evidence_id,),
                                values={"value": format(value, "f")},
                            )
                        )
                values = tuple(parsed[field] for field in _PRICE_FIELDS)
                if any(value is None for value in values):
                    continue
                open_price, high, low, close = values
                if (
                    open_price is None
                    or high is None
                    or low is None
                    or close is None
                ):
                    continue
                valid = high >= low and low <= open_price <= high and low <= close <= high
                if not valid:
                    findings.append(
                        self._finding(
                            "ohlc_integrity",
                            FindingSeverity.BLOCKER,
                            "invalid_ohlc",
                            bar.session,
                            bar.session,
                            "OHLC ordering is internally inconsistent",
                            source_ids=(evidence_id,),
                            values={
                                "close": format(close, "f"),
                                "high": format(high, "f"),
                                "low": format(low, "f"),
                                "open": format(open_price, "f"),
                            },
                        )
                    )
        return self._result(
            "ohlc_integrity",
            findings,
            {"checked_bars": sum(len(source.bars) for source in sources)},
        )

    def _volume_integrity(self, sources: Sequence[QualitySourceData]) -> CheckResult:
        findings: list[QualityFinding] = []
        for source in sources:
            evidence_id = source.evidence.evidence_id
            for bar in source.bars:
                volume = self._decimal(bar.volume)
                if volume is None:
                    findings.append(
                        self._finding(
                            "volume_integrity",
                            FindingSeverity.BLOCKER,
                            "non_finite_field",
                            bar.session,
                            bar.session,
                            "volume is not a finite decimal",
                            field="volume",
                            source_ids=(evidence_id,),
                            values={"value": str(bar.volume)},
                        )
                    )
                elif volume < 0:
                    findings.append(
                        self._finding(
                            "volume_integrity",
                            FindingSeverity.BLOCKER,
                            "negative_volume",
                            bar.session,
                            bar.session,
                            "volume must be non-negative",
                            field="volume",
                            source_ids=(evidence_id,),
                            values={"value": format(volume, "f")},
                        )
                    )
        return self._result(
            "volume_integrity",
            findings,
            {"checked_bars": sum(len(source.bars) for source in sources)},
        )

    def _calendar_membership(
        self,
        sources: Sequence[QualitySourceData],
        expected_sessions: Sequence[date],
    ) -> CheckResult:
        expected = set(expected_sessions)
        findings: list[QualityFinding] = []
        for source in sources:
            for bar in source.bars:
                if bar.session in expected:
                    continue
                findings.append(
                    self._finding(
                        "calendar_membership",
                        FindingSeverity.ERROR,
                        "unexpected_session",
                        bar.session,
                        bar.session,
                        "bar session is not in the supplied exchange calendar",
                        source_ids=(source.evidence.evidence_id,),
                        values={"calendar_member": False},
                    )
                )
        return self._result(
            "calendar_membership",
            findings,
            {"expected_session_count": len(expected_sessions)},
        )

    def _source_coverage(
        self,
        sources: Sequence[QualitySourceData],
        expected_sessions: Sequence[date],
    ) -> CheckResult:
        findings: list[QualityFinding] = []
        for source in sources:
            present = {bar.session for bar in source.bars}
            missing = {session for session in expected_sessions if session not in present}
            for start, end, count in self._missing_intervals(expected_sessions, missing):
                findings.append(
                    self._finding(
                        "source_coverage",
                        FindingSeverity.WARNING,
                        "source_missing_session",
                        start,
                        end,
                        "source is missing one or more expected sessions",
                        source_ids=(source.evidence.evidence_id,),
                        values={"missing_count": count},
                    )
                )
        return self._result(
            "source_coverage",
            findings,
            {"expected_session_count": len(expected_sessions)},
        )

    def _requested_range_coverage(
        self,
        sources: Sequence[QualitySourceData],
        expected_sessions: Sequence[date],
        requested_start: date,
        requested_end: date,
        policy: QualityPolicy,
    ) -> CheckResult:
        expected = tuple(
            session
            for session in expected_sessions
            if requested_start <= session <= requested_end
        )
        source_sessions = [{bar.session for bar in source.bars} for source in sources]
        counts = {
            session: sum(session in observed for observed in source_sessions)
            for session in expected
        }
        missing_all = {session for session, count in counts.items() if count == 0}
        insufficient_verify = {
            session
            for session, count in counts.items()
            if 0 < count < policy.minimum_sources_per_session
        }
        findings: list[QualityFinding] = []
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
            },
            status=status,
        )

    def _coverage_findings(
        self,
        expected: Sequence[date],
        affected: set[date],
        *,
        code: str,
        source_ids: tuple[str, ...],
        minimum_sources: int,
        counts: dict[date, int],
    ) -> tuple[QualityFinding, ...]:
        result: list[QualityFinding] = []
        for start, end, count in self._missing_intervals(expected, affected):
            observed = [
                counts[session]
                for session in expected
                if start <= session <= end and session in affected
            ]
            result.append(
                self._finding(
                    "requested_range_coverage",
                    FindingSeverity.ERROR,
                    code,
                    start,
                    end,
                    "requested range lacks the required source coverage",
                    source_ids=source_ids,
                    values={
                        "minimum_sources": minimum_sources,
                        "missing_count": count,
                        "observed_min_sources": min(observed),
                    },
                )
            )
        return tuple(result)

    def _cross_source_overlap(
        self,
        sources: Sequence[QualitySourceData],
    ) -> CheckResult:
        if len(sources) < 2:
            return self._result(
                "cross_source_overlap",
                (),
                {"missing_session_count": 0, "pair_count": 0},
                status=CheckStatus.NOT_APPLICABLE,
            )
        findings: list[QualityFinding] = []
        missing_count = 0
        pair_count = 0
        for left, right in combinations(sources, 2):
            pair_count += 1
            left_sessions = {bar.session for bar in left.bars}
            right_sessions = {bar.session for bar in right.bars}
            for missing_from, sessions in (
                (right.evidence.evidence_id, left_sessions - right_sessions),
                (left.evidence.evidence_id, right_sessions - left_sessions),
            ):
                missing_count += len(sessions)
                for session in sorted(sessions):
                    findings.append(
                        self._finding(
                            "cross_source_overlap",
                            FindingSeverity.WARNING,
                            "cross_source_session_missing",
                            session,
                            session,
                            "session exists in one source but not the other",
                            source_ids=(
                                left.evidence.evidence_id,
                                right.evidence.evidence_id,
                            ),
                            values={"missing_from": missing_from},
                        )
                    )
        return self._result(
            "cross_source_overlap",
            findings,
            {"missing_session_count": missing_count, "pair_count": pair_count},
        )

    def _cross_source_ohlc(
        self,
        sources: Sequence[QualitySourceData],
        policy: QualityPolicy,
    ) -> CheckResult:
        if len(sources) < 2:
            return self._result(
                "cross_source_ohlc",
                (),
                {"compared_values": 0, "pair_count": 0},
                status=CheckStatus.NOT_APPLICABLE,
            )
        findings: list[QualityFinding] = []
        compared = 0
        pair_count = 0
        maximum = Decimal("0")
        for left, right in combinations(sources, 2):
            pair_count += 1
            left_map = self._stable_bar_map(left.bars)
            right_map = self._stable_bar_map(right.bars)
            for session in sorted(left_map.keys() & right_map.keys()):
                for field in _PRICE_FIELDS:
                    left_value = self._decimal(getattr(left_map[session], field))
                    right_value = self._decimal(getattr(right_map[session], field))
                    if left_value is None or right_value is None:
                        continue
                    difference = self._symmetric_difference_bps(left_value, right_value)
                    if difference is None:
                        continue
                    compared += 1
                    maximum = max(maximum, difference)
                    if difference <= policy.price_pass_tolerance_bps:
                        continue
                    if difference <= policy.price_warning_tolerance_bps:
                        severity = FindingSeverity.WARNING
                        code = "cross_source_field_warning"
                    else:
                        severity = FindingSeverity.ERROR
                        code = "cross_source_field_conflict"
                    findings.append(
                        self._finding(
                            "cross_source_ohlc",
                            severity,
                            code,
                            session,
                            session,
                            "cross-source field difference exceeds policy tolerance",
                            field=field,
                            source_ids=(
                                left.evidence.evidence_id,
                                right.evidence.evidence_id,
                            ),
                            values={
                                "difference_bps": format(difference, "f"),
                                "left": format(left_value, "f"),
                                "right": format(right_value, "f"),
                            },
                        )
                    )
        return self._result(
            "cross_source_ohlc",
            findings,
            {
                "compared_values": compared,
                "max_difference_bps": format(maximum, "f"),
                "pair_count": pair_count,
            },
        )

    def _provider_revision(self, revisions: Sequence[RevisionPair]) -> CheckResult:
        if not revisions:
            return self._result(
                "provider_revision",
                (),
                {"changed_sessions": 0, "revision_pairs": 0},
                status=CheckStatus.NOT_APPLICABLE,
            )
        findings: list[QualityFinding] = []
        for pair in revisions:
            previous = self._stable_bar_map(pair.previous.bars)
            current = self._stable_bar_map(pair.current.bars)
            for session in sorted(previous.keys() | current.keys()):
                changed = self._changed_fields(previous.get(session), current.get(session))
                if not changed:
                    continue
                findings.append(
                    self._finding(
                        "provider_revision",
                        FindingSeverity.WARNING,
                        "provider_history_revision",
                        session,
                        session,
                        "provider history differs between two captures",
                        source_ids=(
                            pair.previous.evidence.evidence_id,
                            pair.current.evidence.evidence_id,
                        ),
                        values={
                            "changed_fields": changed,
                            "current_capture": pair.current.evidence.capture_hash,
                            "previous_capture": pair.previous.evidence.capture_hash,
                        },
                    )
                )
        return self._result(
            "provider_revision",
            findings,
            {"changed_sessions": len(findings), "revision_pairs": len(revisions)},
        )

    def _adjustment_semantics(self, adjustment_mode: AdjustmentMode) -> CheckResult:
        return self._result(
            "adjustment_semantics",
            (),
            {"adjustment_mode": adjustment_mode.value},
        )

    def _evaluate_range(
        self,
        findings: Sequence[QualityFinding],
        *,
        requested_start: date,
        requested_end: date,
        policy: QualityPolicy,
    ) -> RangeEligibility:
        blocking: list[str] = []
        incomplete: list[str] = []
        warnings: list[str] = []
        for finding in findings:
            if not self._intersects(
                finding.affected_start,
                finding.affected_end,
                requested_start,
                requested_end,
            ):
                continue
            finding_id = finding.finding_id
            if finding.finding_code in _INELIGIBLE_CODES:
                blocking.append(finding_id)
            elif finding.finding_code in _INCOMPLETE_CODES or (
                finding.finding_code == "provider_history_revision"
                and policy.revision_blocks_requested_range
            ):
                incomplete.append(finding_id)
            elif finding.severity is not FindingSeverity.INFO:
                warnings.append(finding_id)
        blocking_ids = tuple(sorted(set(blocking)))
        incomplete_ids = tuple(sorted(set(incomplete)))
        warning_ids = tuple(sorted(set(warnings)))
        if blocking_ids:
            status = EligibilityStatus.INELIGIBLE
        elif incomplete_ids:
            status = EligibilityStatus.INCOMPLETE
        else:
            status = EligibilityStatus.ELIGIBLE
        return RangeEligibility(
            requested_start=requested_start,
            requested_end=requested_end,
            status=status,
            blocking_finding_ids=blocking_ids,
            incomplete_finding_ids=incomplete_ids,
            warning_finding_ids=warning_ids,
        )

    def _result(
        self,
        check_id: str,
        findings: Sequence[QualityFinding],
        metrics: dict[str, Any],
        *,
        status: CheckStatus | None = None,
    ) -> CheckResult:
        ordered = tuple(
            sorted(
                findings,
                key=lambda finding: (
                    finding.affected_start,
                    finding.affected_end,
                    finding.finding_code,
                    finding.field or "",
                    finding.source_evidence_ids,
                    finding.finding_id,
                ),
            )
        )
        resolved_status = status
        if resolved_status is None:
            severities = {finding.severity for finding in ordered}
            if FindingSeverity.BLOCKER in severities or FindingSeverity.ERROR in severities:
                resolved_status = CheckStatus.FAIL
            elif FindingSeverity.WARNING in severities:
                resolved_status = CheckStatus.WARNING
            else:
                resolved_status = CheckStatus.PASS
        return CheckResult(
            check_id=check_id,
            check_version=_CHECK_VERSION,
            status=resolved_status,
            findings=ordered,
            metrics=metrics,
        )

    @staticmethod
    def _finding(
        check_id: str,
        severity: FindingSeverity,
        code: str,
        start: date,
        end: date,
        message: str,
        *,
        source_ids: tuple[str, ...] = (),
        values: dict[str, Any] | None = None,
        field: str | None = None,
    ) -> QualityFinding:
        return QualityFinding(
            check_id=check_id,
            check_version=_CHECK_VERSION,
            severity=severity,
            finding_code=code,
            affected_start=start,
            affected_end=end,
            field=field,
            source_evidence_ids=tuple(sorted(source_ids)),
            observed_values=values or {},
            message=message,
        )

    @staticmethod
    def _decimal(value: Any) -> Decimal | None:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        return parsed if parsed.is_finite() else None

    @staticmethod
    def _symmetric_difference_bps(left: Decimal, right: Decimal) -> Decimal | None:
        denominator = (abs(left) + abs(right)) / Decimal("2")
        if denominator == 0:
            return None
        return abs(left - right) / denominator * Decimal("10000")

    @staticmethod
    def _stable_bar_map(bars: Sequence[NormalizedBar]) -> dict[date, NormalizedBar]:
        ordered = sorted(
            bars,
            key=lambda bar: (
                bar.session,
                str(bar.open),
                str(bar.high),
                str(bar.low),
                str(bar.close),
                str(bar.volume),
                bar.source,
            ),
        )
        result: dict[date, NormalizedBar] = {}
        for bar in ordered:
            result.setdefault(bar.session, bar)
        return result

    @staticmethod
    def _changed_fields(
        previous: NormalizedBar | None,
        current: NormalizedBar | None,
    ) -> list[str]:
        if previous is None or current is None:
            return ["session_presence"]
        return [
            field
            for field in (*_PRICE_FIELDS, "volume")
            if str(getattr(previous, field)) != str(getattr(current, field))
        ]

    @staticmethod
    def _intersects(
        affected_start: date,
        affected_end: date,
        requested_start: date,
        requested_end: date,
    ) -> bool:
        return affected_start <= requested_end and requested_start <= affected_end

    @staticmethod
    def _missing_intervals(
        ordered_sessions: Sequence[date],
        missing: set[date],
    ) -> tuple[tuple[date, date, int], ...]:
        if not missing:
            return ()
        intervals: list[tuple[date, date, int]] = []
        start: date | None = None
        end: date | None = None
        count = 0
        for session in ordered_sessions:
            if session in missing:
                if start is None:
                    start = session
                end = session
                count += 1
            elif start is not None and end is not None:
                intervals.append((start, end, count))
                start = None
                end = None
                count = 0
        if start is not None and end is not None:
            intervals.append((start, end, count))
        return tuple(intervals)
