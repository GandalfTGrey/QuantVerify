"""Versioned models for provider-independent, range-scoped data quality evidence."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from quantverify.core.enums import AdjustmentMode, BarFrequency
from quantverify.core.identity import canonicalize, stable_hash
from quantverify.core.models import AssetId, DomainModel
from quantverify.data.models import NormalizedBar
from quantverify.data.quality.identity import expected_sessions_hash, normalized_bars_hash


class FindingSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKER = "blocker"


class CheckStatus(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    INCOMPLETE = "incomplete"
    NOT_APPLICABLE = "not_applicable"


class EligibilityStatus(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    INCOMPLETE = "incomplete"


class QualityEvidenceRef(DomainModel):
    """Verified raw-capture lineage for one persisted provider observation."""

    capture_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    manifest_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    provider: str = Field(min_length=1, max_length=128)
    endpoint: str = Field(min_length=1, max_length=128)
    capture_schema_version: str = Field(min_length=1, max_length=64)
    adapter_version: str = Field(min_length=1, max_length=128)
    request_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")

    @property
    def evidence_id(self) -> str:
        return stable_hash(self, namespace="dqe")


class NormalizedInputRef(DomainModel):
    """Immutable identity of normalized rows evaluated by the quality suite."""

    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    schema_version: str = Field(min_length=1, max_length=64)
    normalizer_id: str = Field(min_length=1, max_length=128)
    normalizer_version: str = Field(min_length=1, max_length=128)
    row_count: int = Field(ge=0)

    @classmethod
    def from_bars(
        cls,
        bars: Sequence[NormalizedBar],
        *,
        schema_version: str,
        normalizer_id: str,
        normalizer_version: str,
    ) -> NormalizedInputRef:
        return cls(
            content_hash=normalized_bars_hash(bars),
            schema_version=schema_version,
            normalizer_id=normalizer_id,
            normalizer_version=normalizer_version,
            row_count=len(bars),
        )

    @property
    def input_id(self) -> str:
        return stable_hash(self, namespace="dqi")


class ExpectedSessionSetRef(DomainModel):
    """Identity of the exact exchange-session set supplied to evaluation."""

    calendar_id: str = Field(min_length=1, max_length=128)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    session_count: int = Field(ge=0)
    first_session: date | None = None
    last_session: date | None = None

    @classmethod
    def from_sessions(
        cls,
        calendar_id: str,
        sessions: Sequence[date],
    ) -> ExpectedSessionSetRef:
        ordered = tuple(sorted(set(sessions)))
        return cls(
            calendar_id=calendar_id,
            content_hash=expected_sessions_hash(calendar_id, ordered),
            session_count=len(ordered),
            first_session=ordered[0] if ordered else None,
            last_session=ordered[-1] if ordered else None,
        )

    @model_validator(mode="after")
    def validate_bounds(self) -> ExpectedSessionSetRef:
        if self.session_count == 0:
            if self.first_session is not None or self.last_session is not None:
                raise ValueError("empty session set cannot have date bounds")
        elif self.first_session is None or self.last_session is None:
            raise ValueError("non-empty session set requires date bounds")
        elif self.first_session > self.last_session:
            raise ValueError("session-set bounds are invalid")
        return self


class QualitySourceData(DomainModel):
    """One offline normalized source plus raw and normalized lineage identities."""

    evidence: QualityEvidenceRef
    normalized_input: NormalizedInputRef
    bars: tuple[NormalizedBar, ...]

    @model_validator(mode="after")
    def validate_source(self) -> QualitySourceData:
        if self.bars:
            asset = self.bars[0].asset
            if any(bar.asset != asset for bar in self.bars):
                raise ValueError("quality source bars must contain one identical asset")
        if self.normalized_input.row_count != len(self.bars):
            raise ValueError("normalized input row_count does not match bars")
        if normalized_bars_hash(self.bars) != self.normalized_input.content_hash:
            raise ValueError("normalized input content hash does not match bars")
        return self


class RevisionPair(DomainModel):
    """Two observations of the same provider request used to detect history revision."""

    previous: QualitySourceData
    current: QualitySourceData

    @model_validator(mode="after")
    def validate_semantic_request(self) -> RevisionPair:
        previous = self.previous.evidence
        current = self.current.evidence
        identity = (
            previous.provider,
            previous.endpoint,
            previous.request_fingerprint,
        )
        current_identity = (
            current.provider,
            current.endpoint,
            current.request_fingerprint,
        )
        if identity != current_identity:
            raise ValueError("revision pair must represent the same provider request")
        return self


class QualityEvaluationContext(DomainModel):
    asset: AssetId
    frequency: BarFrequency
    adjustment_mode: AdjustmentMode
    calendar_id: str = Field(min_length=1, max_length=128)
    expected_sessions: ExpectedSessionSetRef
    requested_start: date
    requested_end: date
    observed_start: date
    observed_end: date
    policy_version: str = Field(min_length=1, max_length=64)
    policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_refs: tuple[QualityEvidenceRef, ...]
    normalized_input_refs: tuple[NormalizedInputRef, ...]

    @model_validator(mode="after")
    def validate_context(self) -> QualityEvaluationContext:
        if self.requested_start > self.requested_end:
            raise ValueError("requested_start must not be later than requested_end")
        if self.observed_start > self.observed_end:
            raise ValueError("observed_start must not be later than observed_end")
        if self.calendar_id != self.expected_sessions.calendar_id:
            raise ValueError("calendar_id must match expected session identity")
        if len(self.evidence_refs) != len(self.normalized_input_refs):
            raise ValueError("raw and normalized lineage reference counts must match")
        return self


class QualityFinding(DomainModel):
    check_id: str = Field(min_length=1, max_length=128)
    check_version: str = Field(min_length=1, max_length=32)
    severity: FindingSeverity
    finding_code: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,127}$")
    affected_start: date
    affected_end: date
    field: str | None = Field(default=None, max_length=64)
    source_evidence_ids: tuple[str, ...] = ()
    observed_values: dict[str, Any] = Field(default_factory=dict)
    message: str = Field(min_length=1, max_length=2048)

    @model_validator(mode="after")
    def validate_finding(self) -> QualityFinding:
        if self.affected_start > self.affected_end:
            raise ValueError("finding affected_start must not exceed affected_end")
        canonicalize(self.observed_values)
        return self

    @property
    def finding_id(self) -> str:
        return stable_hash(self, namespace="dqf")


class CheckResult(DomainModel):
    check_id: str = Field(min_length=1, max_length=128)
    check_version: str = Field(min_length=1, max_length=32)
    status: CheckStatus
    findings: tuple[QualityFinding, ...] = ()
    metrics: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_metrics(self) -> CheckResult:
        canonicalize(self.metrics)
        return self


class RangeEligibility(DomainModel):
    requested_start: date
    requested_end: date
    status: EligibilityStatus
    blocking_finding_ids: tuple[str, ...] = ()
    incomplete_finding_ids: tuple[str, ...] = ()
    warning_finding_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_range(self) -> RangeEligibility:
        if self.requested_start > self.requested_end:
            raise ValueError("eligibility range is invalid")
        return self


class DataQualityReportV2(DomainModel):
    context: QualityEvaluationContext
    policy_id: str = Field(min_length=1, max_length=64)
    policy_version: str = Field(min_length=1, max_length=64)
    check_results: tuple[CheckResult, ...]
    eligibility: RangeEligibility

    @model_validator(mode="after")
    def validate_policy_and_range(self) -> DataQualityReportV2:
        if self.context.policy_version != self.policy_version:
            raise ValueError("context policy version must match report policy version")
        if (
            self.context.requested_start != self.eligibility.requested_start
            or self.context.requested_end != self.eligibility.requested_end
        ):
            raise ValueError("report eligibility range must match evaluation context")
        return self

    @property
    def findings(self) -> tuple[QualityFinding, ...]:
        return tuple(
            finding
            for result in self.check_results
            for finding in result.findings
        )

    @property
    def report_id(self) -> str:
        return stable_hash(self, namespace="dqr")
