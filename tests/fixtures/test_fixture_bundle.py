from __future__ import annotations

import json
import socket
from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from importlib import resources
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from quantverify.core.enums import BarFrequency
from quantverify.core.models import DataSnapshot, SessionSchedule, TradingSession
from quantverify.data.models import NormalizedBar
from quantverify.data.quality.identity import normalized_bars_hash
from quantverify.data.quality.models import NormalizedInputRef
from quantverify.fixtures import (
    BUILTIN_FIXTURE_ID,
    FixtureBundle,
    FixtureIntegrityError,
    FixtureManifest,
    FixtureNotFoundError,
    FixtureRegistry,
    LoadedFixture,
    load_fixture_manifest,
)

BUNDLE_ID = "fixture-bundle_0b59068d12214827eff4fc78"
BUNDLE_HASH = "eb62eb05de878db9b6b731034bcfb014ad9219bb8a42f3de19cda0c4927d2b59"
MANIFEST_HASH = "394f84ce5a522a208c94d1a18bd8f89be2406368aeb15e58f0a42194b443c7d6"
NORMALIZED_HASH = "63d46b5ce9da5ef67284c07ebf84658217d302e2304d6d24105f612a8ed7a448"


def manifest_document() -> bytes:
    return (
        resources.files("quantverify.fixtures.resources")
        .joinpath("qqq_sma3_daily_v1.json")
        .read_bytes()
    )


def manifest_values() -> dict[str, object]:
    return json.loads(manifest_document())


def update_ordered_bar_hashes(values: dict[str, object]) -> None:
    bundle = values["bundle"]
    assert isinstance(bundle, dict)
    bars_raw = bundle["bars"]
    assert isinstance(bars_raw, list)
    bars = tuple(NormalizedBar.model_validate(item) for item in bars_raw)
    content_hash = normalized_bars_hash(bars)
    normalized = bundle["normalized_input"]
    snapshot = bundle["snapshot"]
    assert isinstance(normalized, dict)
    assert isinstance(snapshot, dict)
    normalized["content_hash"] = content_hash
    normalized["row_count"] = len(bars)
    snapshot["content_hash"] = content_hash


def valid_manifest_for_bundle(bundle: FixtureBundle) -> str:
    return FixtureManifest.create(bundle).model_dump_json()


def test_builtin_registry_loads_one_fixed_complete_fixture_offline() -> None:
    with (
        patch.object(socket, "getaddrinfo", side_effect=AssertionError("network forbidden")),
        patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden")),
    ):
        registry = FixtureRegistry.builtin()
        loaded = registry.resolve(BUILTIN_FIXTURE_ID)

    assert registry.fixture_ids == (BUILTIN_FIXTURE_ID,)
    assert isinstance(loaded, LoadedFixture)
    assert loaded.fixture_id == BUILTIN_FIXTURE_ID
    assert loaded.asset.symbol == "QQQ"
    assert loaded.frequency.value == "1d"
    assert loaded.snapshot.dataset_id == BUILTIN_FIXTURE_ID
    assert loaded.normalized_content_hash == NORMALIZED_HASH
    assert loaded.normalized_schema_version == "normalized-bar-v1"
    assert loaded.expected_schedule_id == "session-schedule_ec8a813682d1ab91fc0b171b"
    assert len(loaded.bars) == len(loaded.schedule.sessions) == 9
    assert loaded.bundle_id == BUNDLE_ID
    assert loaded.bundle_content_hash == BUNDLE_HASH
    assert loaded.manifest.manifest_content_hash == MANIFEST_HASH


def test_manifest_round_trip_and_fresh_registry_values_are_deterministic() -> None:
    first = load_fixture_manifest(manifest_document())
    replayed = load_fixture_manifest(first.manifest.model_dump_json())
    registry = FixtureRegistry({first.fixture_id: first.manifest.model_dump_json()})
    resolved = registry.resolve(first.fixture_id)

    assert replayed == first
    assert resolved == first
    assert resolved is not first
    assert resolved.model_dump(mode="json") == first.model_dump(mode="json")


@pytest.mark.parametrize("fixture_id", ["latest", "../qqq-sma3-daily-v1", "/tmp/x.json", ""])
def test_registry_has_no_latest_path_or_fallback_lookup(fixture_id: str) -> None:
    registry = FixtureRegistry.builtin()
    with pytest.raises(FixtureNotFoundError, match="not registered"):
        registry.resolve(fixture_id)


def test_registry_key_must_equal_the_manifest_identifier() -> None:
    with pytest.raises(FixtureIntegrityError, match="must equal"):
        FixtureRegistry({"different-explicit-id": manifest_document()})


def test_duplicate_json_keys_and_invalid_document_types_fail_closed() -> None:
    duplicated = manifest_document().replace(
        b'{"manifest_schema_version":',
        b'{"manifest_schema_version":"fixture-manifest-v1","manifest_schema_version":',
        1,
    )
    with pytest.raises(FixtureIntegrityError, match="duplicate"):
        load_fixture_manifest(duplicated)
    with pytest.raises(FixtureIntegrityError, match="UTF-8"):
        load_fixture_manifest(123)  # type: ignore[arg-type]
    with pytest.raises(FixtureIntegrityError, match="size"):
        load_fixture_manifest(b"")


@pytest.mark.parametrize("field", ["bundle_content_hash", "manifest_content_hash"])
def test_manifest_and_bundle_hash_mismatches_fail_closed(field: str) -> None:
    values = manifest_values()
    values[field] = "f" * 64
    with pytest.raises(FixtureIntegrityError, match="integrity validation"):
        load_fixture_manifest(json.dumps(values))


def test_order_change_cannot_preserve_the_normalized_or_bundle_identity() -> None:
    values = manifest_values()
    bundle = values["bundle"]
    assert isinstance(bundle, dict)
    bars = bundle["bars"]
    assert isinstance(bars, list)
    bars.reverse()

    with pytest.raises(FixtureIntegrityError, match="integrity validation"):
        load_fixture_manifest(json.dumps(values))

    update_ordered_bar_hashes(values)
    assert bundle["normalized_input"] != manifest_values()["bundle"]["normalized_input"]  # type: ignore[index]
    with pytest.raises(FixtureIntegrityError, match="integrity validation"):
        load_fixture_manifest(json.dumps(values))


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate"])
def test_gap_extra_and_duplicate_bars_cannot_match_the_schedule(mutation: str) -> None:
    values = manifest_values()
    bundle = values["bundle"]
    assert isinstance(bundle, dict)
    bars = bundle["bars"]
    assert isinstance(bars, list)
    if mutation == "missing":
        bars.pop(3)
    elif mutation == "extra":
        extra = deepcopy(bars[-1])
        assert isinstance(extra, dict)
        extra["session"] = "2026-01-15"
        extra["session_open_at"] = "2026-01-15T14:30:00Z"
        extra["session_close_at"] = "2026-01-15T21:00:00Z"
        extra["available_at"] = "2026-01-15T21:05:00Z"
        bars.append(extra)
        snapshot = bundle["snapshot"]
        assert isinstance(snapshot, dict)
        snapshot["captured_at"] = "2026-01-15T22:00:00Z"
    else:
        bars.insert(3, deepcopy(bars[2]))
    update_ordered_bar_hashes(values)

    with pytest.raises(FixtureIntegrityError, match="integrity validation"):
        load_fixture_manifest(json.dumps(values))


@pytest.mark.parametrize("mutation", ["asset", "source", "calendar", "timestamp"])
def test_mixed_asset_source_calendar_and_schedule_timestamp_fail_closed(
    mutation: str,
) -> None:
    values = manifest_values()
    bundle = values["bundle"]
    assert isinstance(bundle, dict)
    bars = bundle["bars"]
    assert isinstance(bars, list)
    first = bars[0]
    assert isinstance(first, dict)
    if mutation == "asset":
        asset = first["asset"]
        assert isinstance(asset, dict)
        asset["symbol"] = "DIA"
        update_ordered_bar_hashes(values)
    elif mutation == "source":
        first["source"] = "different_fixture"
        update_ordered_bar_hashes(values)
    elif mutation == "calendar":
        calendar = bundle["calendar"]
        assert isinstance(calendar, dict)
        calendar["content_hash"] = "e" * 64
    else:
        first["session_open_at"] = "2026-01-02T14:31:00Z"
        update_ordered_bar_hashes(values)

    with pytest.raises(FixtureIntegrityError, match="integrity validation"):
        load_fixture_manifest(json.dumps(values))


def test_snapshot_lineage_must_match_adjustment_schema_source_and_availability() -> None:
    updates = (
        {"adjustment_mode": "total_return"},
        {"schema_version": "other-v1"},
        {"source": "other-source"},
        {"captured_at": "2026-01-01T00:00:00Z"},
    )
    for update in updates:
        values = manifest_values()
        bundle = values["bundle"]
        assert isinstance(bundle, dict)
        snapshot = bundle["snapshot"]
        assert isinstance(snapshot, dict)
        snapshot.update(update)
        with pytest.raises(FixtureIntegrityError, match="integrity validation"):
            load_fixture_manifest(json.dumps(values))


def test_decimal_scale_and_equivalent_offsets_have_one_fixture_identity() -> None:
    original = FixtureRegistry.builtin().resolve(BUILTIN_FIXTURE_ID).manifest.bundle
    offset = timezone(timedelta(hours=-5))
    scaled_bars = tuple(
        NormalizedBar.model_validate(
            {
                **bar.model_dump(mode="python"),
                "session_open_at": bar.session_open_at.astimezone(offset),
                "session_close_at": bar.session_close_at.astimezone(offset),
                "available_at": bar.available_at.astimezone(offset),
                "open": Decimal(f"{bar.open}.0"),
                "high": Decimal(f"{bar.high}.00"),
                "low": Decimal(f"{bar.low}.000"),
                "close": Decimal(f"{bar.close}.0000"),
                "volume": Decimal(f"{bar.volume}.00"),
            }
        )
        for bar in original.bars
    )
    offset_sessions = tuple(
        TradingSession(
            session=item.session,
            session_open_at=item.session_open_at.astimezone(offset),
            session_close_at=item.session_close_at.astimezone(offset),
        )
        for item in original.schedule.sessions
    )
    offset_schedule = SessionSchedule.create(
        requested_start=original.schedule.requested_start,
        requested_end=original.schedule.requested_end,
        calendar=original.calendar,
        sessions=offset_sessions,
    )
    normalized = NormalizedInputRef.from_bars(
        scaled_bars,
        schema_version=original.normalized_input.schema_version,
        normalizer_id=original.normalized_input.normalizer_id,
        normalizer_version=original.normalized_input.normalizer_version,
    )
    snapshot = DataSnapshot.model_validate(
        {
            **original.snapshot.model_dump(mode="python"),
            "captured_at": original.snapshot.captured_at.astimezone(offset),
            "content_hash": normalized.content_hash,
        }
    )
    equivalent = FixtureBundle(
        fixture_id=original.fixture_id,
        asset=original.asset,
        frequency=original.frequency,
        adjustment_mode=original.adjustment_mode,
        snapshot=snapshot,
        calendar=original.calendar,
        schedule=offset_schedule,
        normalized_input=normalized,
        bars=scaled_bars,
    )

    assert normalized.content_hash == original.normalized_input.content_hash
    assert offset_schedule.content_hash == original.schedule.content_hash
    assert equivalent.bundle_content_hash == original.bundle_content_hash
    assert equivalent.bundle_id == original.bundle_id
    assert FixtureManifest.create(equivalent).manifest_content_hash == MANIFEST_HASH


def test_unsafe_model_copy_state_is_revalidated_at_loaded_identity_boundary() -> None:
    loaded = FixtureRegistry.builtin().resolve(BUILTIN_FIXTURE_ID)
    original = loaded.manifest.bundle
    unsafe_asset = original.bars[0].asset.model_copy(update={"currency": "INVALID"})
    unsafe_bar = original.bars[0].model_copy(update={"asset": unsafe_asset})
    unsafe_bundle = original.model_copy(update={"bars": (unsafe_bar, *original.bars[1:])})
    unsafe_manifest = loaded.manifest.model_copy(update={"bundle": unsafe_bundle})
    unsafe_loaded = loaded.model_copy(update={"manifest": unsafe_manifest})

    with pytest.raises(ValidationError):
        _ = unsafe_loaded.bundle_content_hash


def test_frozen_sequences_cannot_be_reintroduced_as_mutable_state() -> None:
    loaded = FixtureRegistry.builtin().resolve(BUILTIN_FIXTURE_ID)
    unsafe = loaded.manifest.bundle.model_copy(update={"bars": list(loaded.bars)})
    with pytest.raises(ValueError, match="immutable tuple"):
        _ = unsafe.bundle_content_hash


def test_manifest_factory_revalidates_unsafe_bundle_before_hashing() -> None:
    loaded = FixtureRegistry.builtin().resolve(BUILTIN_FIXTURE_ID)
    unsafe = loaded.manifest.bundle.model_copy(
        update={"frequency": BarFrequency.MONTH, "bars": loaded.bars}
    )
    with pytest.raises(ValidationError, match="daily normalized"):
        FixtureManifest.create(unsafe)


def test_snapshot_timestamp_equivalent_to_utc_is_accepted() -> None:
    loaded = FixtureRegistry.builtin().resolve(BUILTIN_FIXTURE_ID)
    assert loaded.snapshot.captured_at == datetime(2026, 1, 14, 22, tzinfo=UTC)
