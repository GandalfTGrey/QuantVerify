from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from quantverify.core.enums import (
    AdjustmentMode,
    AssetClass,
    BarFrequency,
)
from quantverify.core.models import AssetId
from quantverify.data.capture import RawCapture
from quantverify.data.models import NormalizedBar
from quantverify.data.quality import (
    EligibilityStatus,
    QualitySuite,
    evidence_ref_from_verified_capture,
    quality_source_from_verified_capture,
)
from quantverify.data.quality.identity import full_content_hash
from quantverify.data.store import CaptureStore, DataLicenseProfile, VerifiedCapture

ASSET = AssetId(
    symbol="QQQ",
    venue="XNAS",
    asset_class=AssetClass.ETF,
    currency="USD",
)
LICENSE = DataLicenseProfile(
    profile_id="fixture-personal-research-v1",
    permitted_uses=("local_research", "automated_testing"),
    redistribution_allowed=False,
)
SESSION = date(2026, 1, 2)
CAPTURED_AT = datetime(2026, 1, 2, 22, tzinfo=UTC)
STORED_AT = datetime(2026, 1, 2, 22, 1, tzinfo=UTC)


def replay_verified(root: Path, *, symbol: str = "QQQ") -> VerifiedCapture:
    capture = RawCapture.from_records(
        provider="fixture",
        endpoint="daily",
        request={"symbol": symbol, "adjust": "raw"},
        records=[
            {
                "date": SESSION.isoformat(),
                "open": "100",
                "high": "110",
                "low": "90",
                "close": "101",
                "volume": "1000000",
            }
        ],
        captured_at=CAPTURED_AT,
        schema_version="fixture-daily-v1",
    )
    store = CaptureStore(root)
    stored = store.write(
        capture,
        adapter_version="fixture-adapter-1.0.0",
        license_profile=LICENSE,
        stored_at=STORED_AT,
    )
    return store.load_verified(stored.manifest_path)


def normalized_bar() -> NormalizedBar:
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
        source="fixture:daily:raw",
    )


def test_verified_capture_projects_to_quality_evidence_without_private_replay() -> None:
    with TemporaryDirectory() as directory:
        verified = replay_verified(Path(directory))
        evidence = evidence_ref_from_verified_capture(verified)

    manifest = verified.manifest
    assert evidence.capture_hash == verified.capture.content_hash
    assert evidence.capture_hash == manifest.capture_hash
    assert evidence.manifest_hash == verified.manifest_hash
    assert evidence.provider == manifest.provider
    assert evidence.endpoint == manifest.endpoint
    assert evidence.capture_schema_version == manifest.capture_schema_version
    assert evidence.adapter_version == manifest.adapter_version
    assert evidence.request_fingerprint == full_content_hash(manifest.request.to_dict())
    assert manifest.license_profile == LICENSE


def test_verified_replay_to_quality_suite_binds_raw_and_normalized_identity() -> None:
    with TemporaryDirectory() as directory:
        verified = replay_verified(Path(directory))
        source = quality_source_from_verified_capture(
            verified,
            [normalized_bar()],
            schema_version="normalized-bar-v1",
            normalizer_id="fixture-normalizer",
            normalizer_version="1.0.0",
        )

    report = QualitySuite().evaluate(
        asset=ASSET,
        frequency=BarFrequency.DAY,
        adjustment_mode=AdjustmentMode.RAW,
        calendar_id="XNYS",
        requested_start=SESSION,
        requested_end=SESSION,
        sources=[source],
        expected_sessions=[SESSION],
    )

    assert report.eligibility.status is EligibilityStatus.ELIGIBLE
    assert report.context.evidence_refs == (source.evidence,)
    assert report.context.normalized_input_refs == (source.normalized_input,)
    assert source.evidence.capture_hash == verified.manifest.capture_hash
    assert source.evidence.manifest_hash == verified.manifest_hash
    assert source.normalized_input.row_count == 1


def test_verified_requests_have_distinct_request_fingerprints() -> None:
    with TemporaryDirectory() as first_directory, TemporaryDirectory() as second_directory:
        first = evidence_ref_from_verified_capture(
            replay_verified(Path(first_directory), symbol="QQQ")
        )
        second = evidence_ref_from_verified_capture(
            replay_verified(Path(second_directory), symbol="DIA")
        )

    assert first.request_fingerprint != second.request_fingerprint
    assert first.evidence_id != second.evidence_id
