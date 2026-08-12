"""Adapters from verified CaptureStore replay into A3 quality evidence."""

from __future__ import annotations

from collections.abc import Sequence

from quantverify.data.models import NormalizedBar
from quantverify.data.quality.identity import full_content_hash
from quantverify.data.quality.models import (
    NormalizedInputRef,
    QualityEvidenceRef,
    QualitySourceData,
)
from quantverify.data.store import VerifiedCapture


def evidence_ref_from_verified_capture(verified: VerifiedCapture) -> QualityEvidenceRef:
    """Project cryptographically verified raw lineage into quality evidence identity.

    ``CaptureStore.load_verified()`` owns byte/hash/path verification. This adapter
    does not reopen persisted JSON and does not contact a provider; it only maps the
    already-verified public contract into the provider-independent A3 evidence model.
    """

    manifest = verified.manifest
    return QualityEvidenceRef(
        capture_hash=manifest.capture_hash,
        manifest_hash=verified.manifest_hash,
        provider=manifest.provider,
        endpoint=manifest.endpoint,
        capture_schema_version=manifest.capture_schema_version,
        adapter_version=manifest.adapter_version,
        request_fingerprint=full_content_hash(manifest.request.to_dict()),
    )


def quality_source_from_verified_capture(
    verified: VerifiedCapture,
    bars: Sequence[NormalizedBar],
    *,
    schema_version: str,
    normalizer_id: str,
    normalizer_version: str,
) -> QualitySourceData:
    """Bind verified raw lineage and deterministic normalized-row identity together."""

    immutable_bars = tuple(bars)
    normalized_input = NormalizedInputRef.from_bars(
        immutable_bars,
        schema_version=schema_version,
        normalizer_id=normalizer_id,
        normalizer_version=normalizer_version,
    )
    return QualitySourceData(
        evidence=evidence_ref_from_verified_capture(verified),
        normalized_input=normalized_input,
        bars=immutable_bars,
    )
