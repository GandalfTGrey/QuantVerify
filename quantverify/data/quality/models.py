"""Versioned models for provider-independent, range-scoped data quality evidence."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import Field, field_serializer, field_validator, model_validator

from quantverify.core.enums import AdjustmentMode, BarFrequency
from quantverify.core.exceptions import DataQualityError
from quantverify.core.identity import canonicalize, stable_hash
from quantverify.core.models import AssetId, DomainModel
from quantverify.data.capture import FrozenMapping
from quantverify.data.models import NormalizedBar
from quantverify.data.quality.identity import (
    expected_sessions_hash,
    full_content_hash,
    normalized_bars_hash,
)
from quantverify.data.store import VerifiedCapture

INELIGIBLE_FINDING_CODES = frozenset(
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
INCOMPLETE_FINDING_CODES = frozenset(
    {
        "insufficient_session_coverage",
        "insufficient_source_verification",
        "no_expected_sessions_in_requested_range",
        "unsupported_adjustment_semantics",
        "unsupported_normalized_schema",
    }
)
REQUIRED_CHECK_IDS = (
    "schema_contract",
    "session_integrity",
    "ohlc_integrity",
    "volume_integrity",
    "calendar_membership",
    "source_coverage",
    "requested_range_coverage",
    "cross_source_overlap",
    "cross_source_ohlc",
    "provider_revision",
    "adjustment_semantics",
)
QUALITY_SUITE_ID = "quantverify-quality-suite"
QUALITY_SUITE_VERSION = "2"


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
    provider: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    endpoint: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    capture_schema_version: str = Field(min_length=1, max_length=64)
    adapter_version: str = Field(min_length=1, max_length=128)
    request_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")

    @property
    def evidence_id(self) -> str:
        validated = type(self).model_validate(self.model_dump(mode="python"))
        return stable_hash(validated, namespace="dqe")


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
        validated = type(self).model_validate(self.model_dump(mode="python"))
        return stable_hash(validated, namespace="dqi")


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

    verified_capture: VerifiedCapture
    evidence: QualityEvidenceRef
    normalized_input: NormalizedInputRef
    bars: tuple[NormalizedBar, ...]

    @model_validator(mode="after")
    def validate_source(self) -> QualitySourceData:
        from quantverify.data.quality.provenance import (  # avoid module import cycle
            evidence_ref_from_verified_capture,
        )

        expected_evidence = evidence_ref_from_verified_capture(self.verified_capture)
        if self.evidence != expected_evidence:
            raise ValueError("quality evidence must derive from its VerifiedCapture")
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
            previous.provider.casefold(),
            previous.endpoint,
            previous.request_fingerprint,
        )
        current_identity = (
            current.provider.casefold(),
            current.endpoint,
            current.request_fingerprint,
        )
        if identity != current_identity:
            raise ValueError("revision pair must represent the same provider request")
        return self


class RevisionInputRef(DomainModel):
    """Identity-bound raw and normalized inputs for one revision comparison."""

    previous_evidence: QualityEvidenceRef
    previous_normalized_input: NormalizedInputRef
    current_evidence: QualityEvidenceRef
    current_normalized_input: NormalizedInputRef

    @model_validator(mode="after")
    def validate_revision_semantics(self) -> RevisionInputRef:
        if (
            self.previous_evidence.provider.casefold(),
            self.previous_evidence.endpoint,
            self.previous_evidence.request_fingerprint,
        ) != (
            self.current_evidence.provider.casefold(),
            self.current_evidence.endpoint,
            self.current_evidence.request_fingerprint,
        ):
            raise ValueError("revision input must represent one provider request")
        if (
            self.previous_evidence.evidence_id == self.current_evidence.evidence_id
            and self.previous_normalized_input.input_id
            == self.current_normalized_input.input_id
        ):
            raise ValueError("revision input must contain distinct observations")
        return self

    @classmethod
    def from_pair(cls, pair: RevisionPair) -> RevisionInputRef:
        return cls(
            previous_evidence=pair.previous.evidence,
            previous_normalized_input=pair.previous.normalized_input,
            current_evidence=pair.current.evidence,
            current_normalized_input=pair.current.normalized_input,
        )

    @property
    def revision_id(self) -> str:
        validated = type(self).model_validate(self.model_dump(mode="python"))
        return stable_hash(validated, namespace="dqrev")


class QualityEvaluationContext(DomainModel):
    quality_suite_id: str = Field(default=QUALITY_SUITE_ID, min_length=1, max_length=64)
    quality_suite_version: str = Field(
        default=QUALITY_SUITE_VERSION, min_length=1, max_length=32
    )
    asset: AssetId
    frequency: BarFrequency
    adjustment_mode: AdjustmentMode
    calendar_id: str = Field(min_length=1, max_length=128)
    expected_sessions: ExpectedSessionSetRef
    requested_start: date
    requested_end: date
    observed_start: date
    observed_end: date
    policy_id: str = Field(min_length=1, max_length=64)
    policy_version: str = Field(min_length=1, max_length=64)
    policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    revision_blocks_requested_range: bool
    evidence_refs: tuple[QualityEvidenceRef, ...]
    normalized_input_refs: tuple[NormalizedInputRef, ...]
    revision_input_refs: tuple[RevisionInputRef, ...] = ()

    @model_validator(mode="after")
    def validate_context(self) -> QualityEvaluationContext:
        if (
            self.quality_suite_id != QUALITY_SUITE_ID
            or self.quality_suite_version != QUALITY_SUITE_VERSION
        ):
            raise ValueError("quality suite producer identity is unsupported")
        if self.requested_start > self.requested_end:
            raise ValueError("requested_start must not be later than requested_end")
        if self.observed_start > self.observed_end:
            raise ValueError("observed_start must not be later than observed_end")
        if self.calendar_id != self.expected_sessions.calendar_id:
            raise ValueError("calendar_id must match expected session identity")
        if len(self.evidence_refs) != len(self.normalized_input_refs):
            raise ValueError("raw and normalized lineage reference counts must match")

        evidence_ids = tuple(evidence.evidence_id for evidence in self.evidence_refs)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise DataQualityError(
                "active quality sources must have unique evidence identities"
            )

        providers = tuple(evidence.provider.casefold() for evidence in self.evidence_refs)
        if len(providers) != len(set(providers)):
            raise DataQualityError(
                "active quality sources must represent independent providers; "
                "same-provider historical observations belong in RevisionPair"
            )
        revision_ids = tuple(
            revision.revision_id for revision in self.revision_input_refs
        )
        if len(revision_ids) != len(set(revision_ids)):
            raise DataQualityError("quality revision inputs must be unique")
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
    observed_values: FrozenMapping = Field(default_factory=lambda: FrozenMapping(()))
    message: str = Field(min_length=1, max_length=2048)

    @field_validator("observed_values", mode="before")
    @classmethod
    def freeze_observed_values(cls, value: Any) -> FrozenMapping:
        return FrozenMapping.from_value(value)

    @field_serializer("observed_values")
    def serialize_observed_values(self, value: FrozenMapping) -> dict[str, Any]:
        return value.to_dict()

    @model_validator(mode="after")
    def validate_finding(self) -> QualityFinding:
        if self.affected_start > self.affected_end:
            raise ValueError("finding affected_start must not exceed affected_end")
        canonicalize(self.observed_values)
        return self

    @property
    def finding_id(self) -> str:
        validated = type(self).model_validate(self.model_dump(mode="python"))
        return stable_hash(validated, namespace="dqf")


class CheckResult(DomainModel):
    check_id: str = Field(min_length=1, max_length=128)
    check_version: str = Field(min_length=1, max_length=32)
    status: CheckStatus
    findings: tuple[QualityFinding, ...] = ()
    metrics: FrozenMapping = Field(default_factory=lambda: FrozenMapping(()))

    @field_validator("metrics", mode="before")
    @classmethod
    def freeze_metrics(cls, value: Any) -> FrozenMapping:
        return FrozenMapping.from_value(value)

    @field_serializer("metrics")
    def serialize_metrics(self, value: FrozenMapping) -> dict[str, Any]:
        return value.to_dict()

    @model_validator(mode="after")
    def validate_metrics(self) -> CheckResult:
        canonicalize(self.metrics)
        if not self.findings:
            if self.status not in (CheckStatus.PASS, CheckStatus.NOT_APPLICABLE):
                raise ValueError("empty quality check must pass or be not applicable")
            return self
        hard_codes = {
            finding.finding_code
            for finding in self.findings
            if finding.severity in (FindingSeverity.ERROR, FindingSeverity.BLOCKER)
        }
        if hard_codes - INCOMPLETE_FINDING_CODES:
            expected_status = CheckStatus.FAIL
        elif hard_codes:
            expected_status = CheckStatus.INCOMPLETE
        elif any(
            finding.severity is FindingSeverity.WARNING for finding in self.findings
        ):
            expected_status = CheckStatus.WARNING
        else:
            expected_status = CheckStatus.PASS
        if self.status is not expected_status:
            raise ValueError("quality check status is inconsistent with its findings")
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
    report_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @classmethod
    def from_evaluation(
        cls,
        *,
        context: QualityEvaluationContext,
        policy_id: str,
        policy_version: str,
        check_results: tuple[CheckResult, ...],
        eligibility: RangeEligibility,
    ) -> DataQualityReportV2:
        payload = {
            "context": context,
            "policy_id": policy_id,
            "policy_version": policy_version,
            "check_results": check_results,
            "eligibility": eligibility,
        }
        return cls(
            **payload,
            report_content_hash=full_content_hash(payload),
        )

    @model_validator(mode="after")
    def validate_policy_and_range(self) -> DataQualityReportV2:
        if self.context.policy_id != self.policy_id:
            raise ValueError("context policy id must match report policy id")
        if self.context.policy_version != self.policy_version:
            raise ValueError("context policy version must match report policy version")
        if (
            self.context.requested_start != self.eligibility.requested_start
            or self.context.requested_end != self.eligibility.requested_end
        ):
            raise ValueError("report eligibility range must match evaluation context")
        check_keys = tuple(
            (result.check_id, result.check_version) for result in self.check_results
        )
        expected_check_keys = tuple(
            (check_id, "2") for check_id in REQUIRED_CHECK_IDS
        )
        if check_keys != expected_check_keys:
            raise ValueError("quality report must contain the exact A3 v1 check registry")
        findings = self.findings
        for result in self.check_results:
            if any(
                finding.check_id != result.check_id
                or finding.check_version != result.check_version
                for finding in result.findings
            ):
                raise ValueError("quality finding identity must match its check result")
        finding_ids = tuple(finding.finding_id for finding in findings)
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("quality report finding identities must be unique")
        expected_blocking, expected_incomplete, expected_warnings = (
            self._expected_eligibility_ids(findings)
        )
        if self.eligibility.blocking_finding_ids != expected_blocking:
            raise ValueError("blocking eligibility evidence is inconsistent with findings")
        if self.eligibility.incomplete_finding_ids != expected_incomplete:
            raise ValueError("incomplete eligibility evidence is inconsistent with findings")
        if self.eligibility.warning_finding_ids != expected_warnings:
            raise ValueError("warning eligibility evidence is inconsistent with findings")
        expected_status = (
            EligibilityStatus.INELIGIBLE
            if expected_blocking
            else EligibilityStatus.INCOMPLETE
            if expected_incomplete
            else EligibilityStatus.ELIGIBLE
        )
        if self.eligibility.status is not expected_status:
            raise ValueError("eligibility status is inconsistent with findings")
        expected_content_hash = full_content_hash(
            {
                "context": self.context,
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "check_results": self.check_results,
                "eligibility": self.eligibility,
            }
        )
        if self.report_content_hash != expected_content_hash:
            raise ValueError("quality report content hash does not match its evidence")
        return self

    def _expected_eligibility_ids(
        self,
        findings: Sequence[QualityFinding],
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        blocking: list[str] = []
        incomplete: list[str] = []
        warnings: list[str] = []
        for finding in findings:
            if not (
                finding.affected_start <= self.context.requested_end
                and self.context.requested_start <= finding.affected_end
            ):
                continue
            finding_id = finding.finding_id
            if finding.finding_code in INELIGIBLE_FINDING_CODES:
                blocking.append(finding_id)
            elif finding.finding_code in INCOMPLETE_FINDING_CODES or (
                finding.finding_code == "provider_history_revision"
                and self.context.revision_blocks_requested_range
            ):
                incomplete.append(finding_id)
            elif finding.severity is not FindingSeverity.INFO:
                warnings.append(finding_id)
        return (
            tuple(sorted(set(blocking))),
            tuple(sorted(set(incomplete))),
            tuple(sorted(set(warnings))),
        )

    @property
    def findings(self) -> tuple[QualityFinding, ...]:
        return tuple(
            finding
            for result in self.check_results
            for finding in result.findings
        )

    @property
    def report_id(self) -> str:
        validated = type(self).model_validate(self.model_dump(mode="python"))
        return stable_hash(validated, namespace="dqr")
