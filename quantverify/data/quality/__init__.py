"""Range-scoped data-quality evidence and eligibility evaluation."""

from quantverify.data.quality.gated_suite import QualitySuite
from quantverify.data.quality.models import (
    CheckResult,
    CheckStatus,
    DataQualityReportV2,
    EligibilityStatus,
    ExpectedSessionSetRef,
    FindingSeverity,
    NormalizedInputRef,
    QualityEvaluationContext,
    QualityEvidenceRef,
    QualityFinding,
    QualitySourceData,
    RangeEligibility,
    RevisionPair,
)
from quantverify.data.quality.policy import CrossSourceRequirement, QualityPolicy
from quantverify.data.quality.provenance import (
    evidence_ref_from_verified_capture,
    quality_source_from_verified_capture,
)

__all__ = [
    "CheckResult",
    "CheckStatus",
    "CrossSourceRequirement",
    "DataQualityReportV2",
    "EligibilityStatus",
    "ExpectedSessionSetRef",
    "FindingSeverity",
    "NormalizedInputRef",
    "QualityEvaluationContext",
    "QualityEvidenceRef",
    "QualityFinding",
    "QualityPolicy",
    "QualitySourceData",
    "QualitySuite",
    "RangeEligibility",
    "RevisionPair",
    "evidence_ref_from_verified_capture",
    "quality_source_from_verified_capture",
]
