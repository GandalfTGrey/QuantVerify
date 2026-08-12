from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TypeAlias

import pytest

from quantverify.core.enums import AdjustmentMode, AssetClass, BarFrequency
from quantverify.core.exceptions import DataQualityError
from quantverify.core.models import AssetId
from quantverify.data.capture import RawCapture
from quantverify.data.models import NormalizedBar
from quantverify.data.quality import (
    CheckStatus,
    CrossSourceRequirement,
    EligibilityStatus,
    QualityPolicy,
    QualitySourceData,
    quality_source_from_verified_capture,
)
from quantverify.data.quality import QualitySuite as PublicQualitySuite
from quantverify.data.quality.suite import QualitySuite as DirectQualitySuite
from quantverify.data.store import CaptureStore, DataLicenseProfile

QualitySuiteType: TypeAlias = type[PublicQualitySuite]

ASSET = AssetId(
    symbol="QQQ",
    venue="XNAS",
    asset_class=AssetClass.ETF,
    currency="USD",
)
SESSION = date(2026, 1, 2)
LICENSE = DataLicenseProfile(
    profile_id="fixture-personal-research-v1",
    permitted_uses=("automated_testing",),
    redistribution_allowed=False,
)


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
    capture = RawCapture.from_records(
        provider=provider,
        endpoint="daily",
        request={"symbol": "QQQ", "adjust": "raw"},
        records=[{"marker": marker}],
        captured_at=datetime(2026, 1, 2, 22, tzinfo=UTC),
        schema_version="fixture-daily-v1",
    )
    with TemporaryDirectory() as directory:
        store = CaptureStore(Path(directory))
        stored = store.write(
            capture,
            adapter_version="fixture-adapter-v1",
            license_profile=LICENSE,
            stored_at=datetime(2026, 1, 2, 22, 1, tzinfo=UTC),
        )
        verified = store.load_verified(stored.manifest_path)
    return quality_source_from_verified_capture(
        verified,
        bars,
        schema_version="normalized-bar-v1",
        normalizer_id="fixture-normalizer",
        normalizer_version="1.0.0",
    )


def evaluate(
    sources: list[QualitySourceData],
    *,
    suite_type: QualitySuiteType = PublicQualitySuite,
):
    return suite_type().evaluate(
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


def test_direct_module_import_cannot_bypass_independent_provider_invariant() -> None:
    first = source("provider_a", "a")
    second = source("provider_a", "b")

    with pytest.raises(DataQualityError, match="independent providers"):
        evaluate([first, second], suite_type=DirectQualitySuite)


def test_two_distinct_providers_can_satisfy_required_verification() -> None:
    report = evaluate(
        [
            source("provider_a", "a"),
            source("provider_b", "b"),
        ]
    )

    assert report.eligibility.status is EligibilityStatus.ELIGIBLE
    assert {evidence.provider for evidence in report.context.evidence_refs} == {
        "provider_a",
        "provider_b",
    }
    coverage = next(
        result
        for result in report.check_results
        if result.check_id == "requested_range_coverage"
    )
    assert coverage.status is CheckStatus.PASS
    assert coverage.metrics["minimum_sources_per_session"] == 2
