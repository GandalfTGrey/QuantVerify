from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from quantverify.core.enums import AdjustmentMode, AssetClass, BarFrequency
from quantverify.core.exceptions import DataQualityError
from quantverify.core.models import AssetId
from quantverify.data.models import NormalizedBar
from quantverify.data.quality import (
    CrossSourceRequirement,
    EligibilityStatus,
    NormalizedInputRef,
    QualityEvidenceRef,
    QualityPolicy,
    QualitySourceData,
    QualitySuite,
)

ASSET = AssetId(
    symbol="QQQ",
    venue="XNAS",
    asset_class=AssetClass.ETF,
    currency="USD",
)
SESSION = date(2026, 1, 2)


def bar(provider: str) -> NormalizedBar:
    return NormalizedBar(
        asset=ASSET,
        session=SESSION,
        session_open_at=datetime(2026, 1, 2, 14, 30, tzinfo=UTC),
        session_close_at=datetime(2026, 1, 2, 21, tzinfo=UTC),
        available_at=datetime(2026, 1, 2, 21, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("101"),
        volume=Decimal("1000000"),
        source=f"{provider}:daily:raw",
    )


def source(provider: str, marker: str) -> QualitySourceData:
    bars = (bar(provider),)
    evidence = QualityEvidenceRef(
        capture_hash=marker * 64,
        manifest_hash=("f" if marker != "f" else "e") * 64,
        provider=provider,
        endpoint="daily",
        capture_schema_version="fixture-daily-v1",
        adapter_version="fixture-adapter-v1",
        request_fingerprint=("d" if marker != "d" else "c") * 64,
    )
    normalized = NormalizedInputRef.from_bars(
        bars,
        schema_version="normalized-bar-v1",
        normalizer_id="fixture-normalizer",
        normalizer_version="1.0.0",
    )
    return QualitySourceData(
        evidence=evidence,
        normalized_input=normalized,
        bars=bars,
    )


def evaluate(sources: list[QualitySourceData]):
    return QualitySuite().evaluate(
        asset=ASSET,
        frequency=BarFrequency.DAY,
        adjustment_mode=AdjustmentMode.RAW,
        calendar_id="XNYS",
        requested_start=SESSION,
        requested_end=SESSION,
        sources=sources,
        expected_sessions=[SESSION],
        policy=QualityPolicy(cross_source_requirement=CrossSourceRequirement.REQUIRED),
    )


def test_exact_duplicate_active_source_cannot_satisfy_dual_source_gate() -> None:
    first = source("provider_a", "a")

    with pytest.raises(DataQualityError, match="unique evidence identities"):
        evaluate([first, first])


def test_two_current_captures_from_same_provider_are_not_independent_sources() -> None:
    first = source("provider_a", "a")
    second = source("provider_a", "b")

    assert first.evidence.evidence_id != second.evidence.evidence_id
    with pytest.raises(DataQualityError, match="independent providers"):
        evaluate([first, second])


def test_two_distinct_providers_can_satisfy_required_verification() -> None:
    report = evaluate(
        [
            source("provider_a", "a"),
            source("provider_b", "b"),
        ]
    )

    assert report.eligibility.status is EligibilityStatus.ELIGIBLE
    coverage = next(
        result
        for result in report.check_results
        if result.check_id == "requested_range_coverage"
    )
    assert coverage.metrics["source_authority_key"] == "provider"
    assert coverage.metrics["independent_provider_count"] == 2
    assert coverage.metrics["minimum_sources_per_session"] == 2
