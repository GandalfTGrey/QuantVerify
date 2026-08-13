"""Immutable contracts for small, fully offline research fixtures."""

from __future__ import annotations

from datetime import UTC
from typing import Any, Final, Literal

from pydantic import Field, model_validator

from quantverify.core.enums import AdjustmentMode, BarFrequency
from quantverify.core.identity import stable_hash
from quantverify.core.models import (
    AssetId,
    CalendarArtifactRef,
    DataSnapshot,
    DomainModel,
    SessionSchedule,
)
from quantverify.data.models import NormalizedBar
from quantverify.data.quality.identity import full_content_hash, normalized_bars_hash
from quantverify.data.quality.models import NormalizedInputRef

FIXTURE_BUNDLE_SCHEMA: Final = "fixture-bundle-v1"
FIXTURE_MANIFEST_SCHEMA: Final = "fixture-manifest-v1"
NORMALIZED_BAR_SCHEMA: Final = "normalized-bar-v1"


class FixtureBundle(DomainModel):
    """Complete scientific content for one explicitly named daily fixture."""

    schema_version: Literal["fixture-bundle-v1"] = FIXTURE_BUNDLE_SCHEMA
    fixture_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    asset: AssetId
    frequency: BarFrequency
    adjustment_mode: AdjustmentMode
    snapshot: DataSnapshot
    calendar: CalendarArtifactRef
    schedule: SessionSchedule
    normalized_input: NormalizedInputRef
    bars: tuple[NormalizedBar, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bundle(self) -> FixtureBundle:
        if not isinstance(self.bars, tuple):
            raise ValueError("fixture bars must remain an immutable tuple")
        if self.fixture_id == "latest":
            raise ValueError("latest is not a valid explicit fixture identifier")

        asset = AssetId.model_validate(self.asset.model_dump(mode="python"))
        snapshot = DataSnapshot.model_validate(self.snapshot.model_dump(mode="python"))
        calendar = CalendarArtifactRef.model_validate(self.calendar.model_dump(mode="python"))
        schedule = SessionSchedule.model_validate(self.schedule.model_dump(mode="python"))
        normalized_input = NormalizedInputRef.model_validate(
            self.normalized_input.model_dump(mode="python")
        )
        bars = tuple(
            NormalizedBar.model_validate(bar.model_dump(mode="python")) for bar in self.bars
        )

        if self.frequency is not BarFrequency.DAY:
            raise ValueError("fixture bundle v1 requires daily normalized bars")
        if snapshot.dataset_id != self.fixture_id:
            raise ValueError("fixture snapshot dataset_id must equal fixture_id")
        if snapshot.adjustment_mode is not self.adjustment_mode:
            raise ValueError("fixture snapshot adjustment mode does not match the bundle")
        if calendar != schedule.calendar:
            raise ValueError("fixture calendar must equal the schedule calendar")
        if normalized_input.schema_version != NORMALIZED_BAR_SCHEMA:
            raise ValueError("fixture bundle v1 requires normalized-bar-v1 rows")
        if normalized_input.row_count != len(bars):
            raise ValueError("fixture normalized row count does not match bars")

        actual_normalized_hash = normalized_bars_hash(bars)
        if normalized_input.content_hash != actual_normalized_hash:
            raise ValueError("fixture normalized content hash does not match ordered bars")
        if snapshot.content_hash != normalized_input.content_hash:
            raise ValueError("fixture snapshot content hash must bind normalized bars")
        if snapshot.schema_version != normalized_input.schema_version:
            raise ValueError("fixture snapshot schema must match normalized input schema")

        if any(bar.asset != asset for bar in bars):
            raise ValueError("fixture bars must contain one identical declared asset")
        if any(bar.source != snapshot.source for bar in bars):
            raise ValueError("fixture bar source must equal snapshot source")
        if snapshot.captured_at < max(bar.available_at for bar in bars):
            raise ValueError("fixture snapshot cannot precede bar availability")

        if tuple(bar.session for bar in bars) != tuple(
            session.session for session in schedule.sessions
        ):
            raise ValueError("fixture bars must exactly cover the expected schedule")
        for bar, session in zip(bars, schedule.sessions, strict=True):
            if (
                bar.session_open_at != session.session_open_at
                or bar.session_close_at != session.session_close_at
            ):
                raise ValueError("fixture bar timestamps must match the expected schedule")
        return self

    @property
    def bundle_content_hash(self) -> str:
        """Return a full identity over all fixture semantics and upstream identities."""

        self._require_immutable_sequences()
        validated = type(self).model_validate(self.model_dump(mode="python"))
        return full_content_hash(validated._identity_payload())

    @property
    def bundle_id(self) -> str:
        """Return a compact namespaced identity for registry/application references."""

        return stable_hash(self.bundle_content_hash, namespace="fixture-bundle")

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "fixture_id": self.fixture_id,
            "asset": self.asset,
            "frequency": self.frequency,
            "adjustment_mode": self.adjustment_mode,
            "snapshot": {
                **self.snapshot.model_dump(mode="python"),
                "captured_at": self.snapshot.captured_at.astimezone(UTC),
            },
            "calendar": self.calendar,
            "schedule_id": self.schedule.schedule_id,
            "schedule_content_hash": self.schedule.content_hash,
            "normalized_input": self.normalized_input,
        }

    def _require_immutable_sequences(self) -> None:
        if not isinstance(self.bars, tuple):
            raise ValueError("fixture bars must remain an immutable tuple")


class FixtureManifest(DomainModel):
    """Self-checking canonical semantic manifest for a fixture bundle."""

    manifest_schema_version: Literal["fixture-manifest-v1"] = FIXTURE_MANIFEST_SCHEMA
    bundle: FixtureBundle
    bundle_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    manifest_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @classmethod
    def create(cls, bundle: FixtureBundle) -> FixtureManifest:
        bundle._require_immutable_sequences()
        validated = FixtureBundle.model_validate(bundle.model_dump(mode="python"))
        bundle_hash = validated.bundle_content_hash
        return cls(
            bundle=validated,
            bundle_content_hash=bundle_hash,
            manifest_content_hash=cls._manifest_hash(
                fixture_id=validated.fixture_id,
                bundle_content_hash=bundle_hash,
            ),
        )

    @model_validator(mode="after")
    def validate_manifest(self) -> FixtureManifest:
        bundle = FixtureBundle.model_validate(self.bundle.model_dump(mode="python"))
        if self.bundle_content_hash != bundle.bundle_content_hash:
            raise ValueError("fixture manifest bundle hash does not match bundle content")
        expected_manifest_hash = self._manifest_hash(
            fixture_id=bundle.fixture_id,
            bundle_content_hash=self.bundle_content_hash,
        )
        if self.manifest_content_hash != expected_manifest_hash:
            raise ValueError("fixture manifest content hash does not match manifest")
        return self

    @staticmethod
    def _manifest_hash(*, fixture_id: str, bundle_content_hash: str) -> str:
        return full_content_hash(
            {
                "manifest_schema_version": FIXTURE_MANIFEST_SCHEMA,
                "fixture_id": fixture_id,
                "bundle_content_hash": bundle_content_hash,
            }
        )


class LoadedFixture(DomainModel):
    """Fully validated fixture returned only from an explicit manifest or registry entry."""

    manifest: FixtureManifest

    @model_validator(mode="after")
    def validate_loaded_fixture(self) -> LoadedFixture:
        FixtureManifest.model_validate(self.manifest.model_dump(mode="python"))
        return self

    def _bundle(self) -> FixtureBundle:
        self.manifest.bundle._require_immutable_sequences()
        manifest = FixtureManifest.model_validate(self.manifest.model_dump(mode="python"))
        return manifest.bundle

    @property
    def fixture_id(self) -> str:
        return self._bundle().fixture_id

    @property
    def asset(self) -> AssetId:
        return self._bundle().asset

    @property
    def frequency(self) -> BarFrequency:
        return self._bundle().frequency

    @property
    def adjustment_mode(self) -> AdjustmentMode:
        return self._bundle().adjustment_mode

    @property
    def snapshot(self) -> DataSnapshot:
        return self._bundle().snapshot

    @property
    def calendar(self) -> CalendarArtifactRef:
        return self._bundle().calendar

    @property
    def schedule(self) -> SessionSchedule:
        return self._bundle().schedule

    @property
    def bars(self) -> tuple[NormalizedBar, ...]:
        return self._bundle().bars

    @property
    def normalized_content_hash(self) -> str:
        return self._bundle().normalized_input.content_hash

    @property
    def normalized_schema_version(self) -> str:
        return self._bundle().normalized_input.schema_version

    @property
    def expected_schedule_id(self) -> str:
        return self._bundle().schedule.schedule_id

    @property
    def expected_schedule_content_hash(self) -> str:
        return self._bundle().schedule.content_hash

    @property
    def bundle_content_hash(self) -> str:
        return self._bundle().bundle_content_hash

    @property
    def bundle_id(self) -> str:
        return self._bundle().bundle_id
