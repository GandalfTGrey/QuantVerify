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
    FindingSeverity,
    QualityEvaluationContext,
    QualityFinding,
    QualitySourceData,
    RangeEligibility,
    RevisionPair,
)
from quantverify.data.quality.policy import QualityPolicy

_CHECK_VERSION = "1"
_PRICE_FIELDS = ("open", "high", "low", "close")

_INELIGIBLE_CODES = frozenset(
    {
        "duplicate_session",
        "invalid_ohlc",
        "negative_volume",
        "non_finite_field",
        "non_monotonic_sessions",
        "non_positive_price",
        "unexpected_session",
        "cross_source_field_conflict",
    }
)
_INCOMPLETE_CODES = frozenset(
    {
        "insufficient_session_coverage",
        "insufficient_source_verification",
    }
)


class QualitySuite:
    """Evaluate already captured/normalized market data without provider access."""

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
        ordered_sources = tuple(sorted(sources, key=lambda source: source.evidence.evidence_id))
        self._validate_assets(asset, ordered_sources)
        expected = tuple(sorted(set(expected_sessions)))
        ordered_revisions = tuple(
            sorted(
                revisions,
                key=lambda pair: (
                    pair.previous.evidence.evidence_id,
                    pair.current.evidence.evidence_id,
                ),
            )
        )

        all_sessions = [
            bar.session
            for source in ordered_sources
            for bar in source.bars
        ]
        observed_start = min(all_sessions) if all_sessions else requested_start
        observed_end = max(all_sessions) if all_sessions else requested_end
        context = QualityEvaluationContext(
            asset=asset,
            frequency=frequency,
            adjustment_mode=adjustment_mode,
            calendar_id=calendar_id,
            requested_start=requested_start,
            requested_end=requested_end,
            observed_start=observed_start,
            observed_end=observed_end,
            policy_version=active_policy.version,
            evidence_refs=tuple(source.evidence for source in ordered_sources),
        )

        results = (
            self._schema_contract(ordered_sources),
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
            finding
            for result in results
            for finding in result.findings
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

    def _schema_contract(self, sources: Sequence[QualitySourceData]) -> CheckResult:
        return self._result(
            "schema_contract",
            (),
            {
                "source_count": len(sources),
                "capture_schema_versions": [
                    source.evidence.capture_schema_version
                    for source in sources
                ],
            },
        )

    def _session_integrity(self, sources: Sequence[QualitySourceData]) -> CheckResult:
        findings: list[QualityFinding] = []
        for source in sources:
            sessions = [bar.session for bar in source.bars]
            counts = Counter(sessions)
            for session in sorted(day for day, count in counts.items() if count > 1):
                findings.append(
                    self._finding(
                        check_id="session_integrity",
                        severity=FindingSeverity.ERROR,
                        code="duplicate_session",
                        start=session,
                        end=session,
                        source_ids=(source.evidence.evidence_id,),
                        values={"count": counts[session]},
                        message=f"duplicate market session: {session.isoformat()}",
                    )
                )
            if sessions and sessions != sorted(sessions):
                findings.append(
                    self._finding(
                        check_id="session_integrity",
                        severity=FindingSeverity.ERROR,
                        code="non_monotonic_sessions",
                        start=min(sessions),
                        end=max(sessions),
                        source_ids=(source.evidence.evidence_id,),
                        values={"record_count": len(sessions)},
                        message="source sessions are not monotonically increasing",
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
            for bar in source.bars:
                values = {
                    field: self._decimal(getattr(bar, field))
                    for field in _PRICE_FIELDS
                }
                for field, value in values.items():
                    if value is None:
                        findings.append(
                            self._finding(
                                check_id="ohlc_integrity",
                                severity=FindingSeverity.BLOCKER,
                                code="non_finite_field",
                                start=bar.session,
                                end=bar.session,
                                field=field,
                                source_ids=(source.evidence.evidence_id,),
                                values={"value": str(getattr(bar, field))},
                                message=f"{field} is not a finite decimal",
                            )
                        )
                    elif value <= 0:
                        findings.append(
                            self._finding(
                                check_id="ohlc_integrity",
                                severity=FindingSeverity.BLOCKER,
                                code="non_positive_price",
                                start=bar.session,
                                end=bar.session,
                                field=field,
                                source_ids=(source.evidence.evidence_id,),
                                values={"value": format(value, "f")},
                                message=f"{field} must be positive",
                            )
                        )

                if any(value is None for value in values.values()):
                    continue
                open_price = values["open"]
                high = values["high"]
                low = values["low"]
                close = values["close"]
                if (
                    open_price is None
                    or high is None
                    or low is None
                    or close is None
                ):
                    continue
                if high < low or not low <= open_price <= high or not low <= close <= high:
                    findings.append(
                        self._finding(
                            check_id="ohlc_integrity",
                            severity=FindingSeverity.BLOCKER,
                            code="invalid_ohlc",
                            start=bar.session,
                            end=bar.session,
                            source_ids=(source.evidence.evidence_id,),
                            values={
                                "open": format(open_price, "f"),
                                "high": format(high, "f"),
                                "low": format(low, "f"),
                                "close": format(close, "f"),
                            },
                            message="OHLC ordering is internally inconsistent",
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
            for bar in source.bars:
                volume = self._decimal(bar.volume)
                if volume is None:
                    findings.append(
                        self._finding(
                            check_id="volume_integrity",
                            severity=FindingSeverity.BLOCKER,
                            code="non_finite_field",
                            start=bar.session,
                            end=bar.session,
                            field="volume",
                            source_ids=(source.evidence.evidence_id,),
                            values={"value": str(bar.volume)},
                            message="volume is not a finite decimal",
                        )
                    )
                elif volume < 0:
                    findings.append(
                        self._finding(
                            check_id="volume_integrity",
                            severity=FindingSeverity.BLOCKER,
                            code="negative_volume",
                            start=bar.session,
                            end=bar.session,
                            field="volume",
                            source_ids=(source.evidence.evidence_id,),
                            values={"value": format(volume, "f")},
                            message="volume must be non-negative",
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
                if bar.session not in expected:
                    findings.append(
                        self._finding(
                            check_id="calendar_membership",
                            severity=FindingSeverity.ERROR,
                            code="unexpected_session",
                            start=bar.session,
                            end=bar.session,
                            source_ids=(source.evidence.evidence_id,),
                            values={"calendar_member": False},
                            message=(
                                f"bar session {bar.session.isoformat()} is not in "
                                "the supplied exchange calendar"
                            ),
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
                        check_id="source_coverage",
                        severity=FindingSeverity.WARNING,
                        code="source_missing_session",
                        start=start,
                        end=end,
                        source_ids=(source.evidence.evidence_id,),
                        values={"missing_count": count},
                        message="source is missing one or more expected sessions",
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
        source_sessions = [
            {bar.session for bar in source.bars}
            for source in sources
        ]
        insufficient: dict[str, set[date]] = {
            "insufficient_session_coverage": set(),
            "insufficient_source_verification": set(),
        }
        counts: dict[date, int] = {}
        for session in expected:
            observed_count = sum(session in sessions for sessions in source_sessions)
            counts[session] = observed_count
            if observed_count < policy.minimum_sources_per_session:
                if observed_count == 0:
                    insufficient["insufficient_session_coverage"].add(session)
                else:
                    insufficient["insufficient_source_verification"].add(session)

        findings: list[QualityFinding] = []
        source_ids = tuple(source.evidence.evidence_id for source in sources)
        for code, missing in insufficient.items():
            for start, end, count in self._missing_intervals(expected, missing):
                observed_counts = [
                    counts[session]
                    for session in expected
                    if start <= session <= end and session in missing
                ]
                findings.append(
                    self._finding(
                        check_id="requested_range_coverage",
                        severity=FindingSeverity.ERROR,
                        code=code,
                        start=start,
                        end=end,
                        source_ids=source_ids,
                        values={
                            "missing_count": count,
                            "minimum_sources": policy.minimum_sources_per_session,
                            "observed_min_sources": min(observed_counts),
                        },
                        message="requested range lacks the required source coverage",
                    )
                )

        status = CheckStatus.INCOMPLETE if findings else CheckStatus.PASS
        return self._result(
            "requested_range_coverage",
            findings,
            {
                "requested_expected_sessions": len(expected),
                "minimum_sources_per_session": policy.minimum_sources_per_session,
            },
            status=status,
        )

    def _cross_source_overlap(
        self,
        sources: Sequence[QualitySourceData],
    ) -> CheckResult:
        findings: list[QualityFinding] = []
        pair_count = 0
        missing_count = 0
        for left, right in combinations(sources, 2):
            pair_count += 1
            left_sessions = {bar.session for bar in left.bars}
            right_sessions = {bar.session for bar in right.bars}
            only_left = left_sessions - right_sessions
            only_right = right_sessions - left_sessions
            missing_count += len(only_left) + len(only_right)
            for start, end, count in self._calendar_intervals(only_left):
                findings.append(
                    self._finding(
                        check_id="cross_source_overlap",
                        severity=FindingSeverity.WARNING,
                        code="cross_source_session_missing",
                        start=start,
                        end=end,
                        source_ids=(
                            left.evidence.evidence_id,
                            right.evidence.evidence_id,
                        ),
                        values={
                            "missing_from": right.evidence.evidence_id,
                            "session_count": count,
                        },
                        message="session exists in one source but not the other",
                    )
                )
            for start, end, count in self._calendar_intervals(only_right):
                findings.append(
                    self._finding(
                        check_id="cross_source_overlap",
                        severity=FindingSeverity.WARNING,
                        code="cross_source_session_missing",
                        start=start,
                        end=end,
                        source_ids=(
                            left.evidence.evidence_id,
                            right.evidence.evidence_id,
                        ),
                        values={
                            "missing_from": left.evidence.evidence_id,
                            "session_count": count,
                        },
                        message="session exists in one source but not the other",
                    )
                )
        if len(sources) < 2:
            return self._result(
                "cross_source_overlap",
                (),
                {"pair_count": 0, "missing_session_count": 0},
                status=CheckStatus.NOT_APPLICABLE,
            )
        return self._result(
            "cross_source_overlap",
            findings,
            {"pair_count": pair_count, "missing_session_count": missing_count},
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
                {"pair_count": 0, "compared_values": 0},
                status=CheckStatus.NOT_APPLICABLE,
            )

        findings: list[QualityFinding] = []
        compared_values = 0
        warning_count = 0
        fail_count = 0
        max_difference = Decimal("0")
        for left, right in combinations(sources, 2):
            left_map = self._stable_bar_map(left.bars)
            right_map = self._stable_bar_map(right.bars)
            for session in sorted(left_map.keys() & right_map.keys()):
                left_bar = left_map[session]
                right_bar = right_map[session]
                for field in _PRICE_FIELDS:
                    left_value = self._decimal(getattr(left_bar, field))
                    right_value = self._decimal(getattr(right_bar, field))
                    if left_value is None or right_value is None:
                        continue
                    denominator = (abs(left_value) + abs(right_value)) / Decimal("2")
                    if denominator == 0:
                        continue
                    difference_bps = (
                        abs(left_value - right_value)
                        / denominator
                        * Decimal("10000")
                    )
                    compared_values += 1
                    max_difference = max(max_difference, difference_bps)
                    if difference_bps > policy.price_warning_tolerance_bps:
                        fail_count += 1
                        severity = FindingSeverity.ERROR
                        code = "cross_source_field_conflict"
                    elif difference_bps > policy.price_pass_tolerance_bps:
                        warning_count += 1
                        severity = FindingSeverity.WARNING
                        code = "cross_source_field_warning"
                    else:
                        continue
                    findings.append(
                        self._finding(
                            check_id="cross_source_ohlc",
                            severity=severity,
                            code=code,
                            start=session,
                            end=session,
                            field=field,
                            source_ids=(
                                left.evidence.evidence_id,
                                right.evidence.evidence_id,
                            ),
                            values={
                                "left": format(left_value, "f"),
                                "right": format(right_value, "f"),
                                "difference_bps": format(difference_bps, "f"),
                            },
                            message="cross-source field difference exceeds policy tolerance",
                        )
                    )
        return self._result(
            "cross_source_ohlc",
            findings,
            {
                "pair_count": len(tuple(combinations(sources, 2))),
                "compared_values": compared_values,
                "warning_count": warning_count,
                "fail_count": fail_count,
                "max_difference_bps": format(max_difference, "f"),
            },
        )

    def _provider_revision(
        self,
        revisions: Sequence[RevisionPair],
    ) -> CheckResult:
        if not revisions:
            return self._result(
                "provider_revision",
                (),
                {"revision_pairs": 0, "changed_sessions": 0},
                status=CheckStatus.NOT_APPLICABLE,
            )
        findings: list[QualityFinding] = []
        changed_sessions = 0
        for pair in revisions:
            previous = self._stable_bar_map(pair.previous.bars)
            current = self._stable_bar_map(pair.current.bars)
            for session in sorted(previous.keys() | current.keys()):
                changed_fields = self._changed_fields(
                    previous.get(session),
                    current.get(session),
                )
                if not changed_fields:
                    continue
                changed_sessions += 1
                findings.append(
                    self._finding(
                        check_id="provider_revision",
                        severity=FindingSeverity.WARNING,
                        code="provider_history_revision",
                        start=session,
                        end=session,
                        source_ids=(
                            pair.previous.evidence.evidence_id,
                            pair.current.evidence.evidence_id,
                        ),
                        values={
                            "changed_fields": changed_fields,
                            "previous_capture": pair.previous.evidence.capture_hash,
                            "current_capture": pair.current.evidence.capture_hash,
                        },
                        message="provider history differs between two captures",
                    )
                )
        return self._result(
            "provider_revision",
            findings,
            {
                "revision_pairs": len(revisions),
                "changed_sessions": changed_sessions,
            },
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
            elif finding.finding_code in _INCOMPLETE_CODES:
                incomplete.append(finding_id)
            elif (
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
        if status is None:
            severities = {finding.severity for finding in ordered}
            if FindingSeverity.BLOCKER in severities or FindingSeverity.ERROR in severities:
                status = CheckStatus.FAIL
            elif FindingSeverity.WARNING in severities:
                status = CheckStatus.WARNING
            else:
                status = CheckStatus.PASS
        return CheckResult(
            check_id=check_id,
            check_version=_CHECK_VERSION,
            status=status,
            findings=ordered,
            metrics=metrics,
        )

    @staticmethod
    def _finding(
        *,
        check_id: str,
        severity: FindingSeverity,
        code: str,
        start: date,
        end: date,
        message: str,
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
        if not parsed.is_finite():
            return None
        return parsed

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
        fields = [*_PRICE_FIELDS, "volume"]
        return [
            field
            for field in fields
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

    @staticmethod
    def _calendar_intervals(
        sessions: set[date],
    ) -> tuple[tuple[date, date, int], ...]:
        if not sessions:
            return ()
        ordered = sorted(sessions)
        return tuple((session, session, 1) for session in ordered)
