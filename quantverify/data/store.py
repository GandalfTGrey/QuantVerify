"""Provider-agnostic persistence for immutable raw captures and manifests."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field, field_serializer, field_validator, model_validator

from quantverify.core.exceptions import ReproducibilityError
from quantverify.core.identity import canonicalize
from quantverify.core.models import DomainModel
from quantverify.data.capture import FrozenMapping, RawCapture

_CREDENTIAL_TOKENS = frozenset(
    {
        "auth",
        "authentication",
        "authorization",
        "bearer",
        "cookie",
        "cookies",
        "passwd",
        "password",
        "secret",
        "token",
    }
)
_CREDENTIAL_COMPACT_KEYS = frozenset(
    {
        "apikey",
        "privatekey",
    }
)


def _credential_key_tokens(key: str) -> tuple[str, ...]:
    """Split request keys into lower-case semantic tokens without inspecting values."""

    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", key)
    acronym_split = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", camel_split)
    return tuple(
        token
        for token in re.split(r"[^A-Za-z0-9]+", acronym_split.lower())
        if token
    )


def _is_credential_key(key: str) -> bool:
    tokens = _credential_key_tokens(key)
    if not tokens:
        return False
    token_set = set(tokens)
    if token_set & _CREDENTIAL_TOKENS:
        return True
    compact = "".join(tokens)
    if compact in _CREDENTIAL_COMPACT_KEYS:
        return True
    return ("api" in token_set and "key" in token_set) or (
        "private" in token_set and "key" in token_set
    )


class DataLicenseProfile(DomainModel):
    """Versioned usage constraints attached to a captured provider response."""

    profile_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,63}$")
    permitted_uses: tuple[str, ...] = Field(min_length=1)
    redistribution_allowed: bool
    terms_uri: str | None = Field(default=None, max_length=2048)


class CaptureManifest(DomainModel):
    """One immutable observation event for a content-addressed capture."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        arbitrary_types_allowed=True,
    )

    manifest_version: str = Field(default="capture-manifest-v1", min_length=1, max_length=64)
    capture_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    provider: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    endpoint: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    request: FrozenMapping
    capture_schema_version: str = Field(min_length=1, max_length=64)
    adapter_version: str = Field(min_length=1, max_length=128)
    captured_at: datetime
    stored_at: datetime
    record_count: int = Field(ge=0)
    content_path: str = Field(min_length=1, max_length=2048)
    license_profile: DataLicenseProfile

    @field_validator("request", mode="before")
    @classmethod
    def freeze_request(cls, value: Any) -> FrozenMapping:
        try:
            return FrozenMapping.from_value(value)
        except TypeError as error:
            raise TypeError("CaptureManifest request must be a mapping") from error

    @field_serializer("request")
    def serialize_request(self, value: FrozenMapping) -> dict[str, Any]:
        return value.to_dict()

    @model_validator(mode="after")
    def validate_timestamps(self) -> CaptureManifest:
        if self.captured_at.tzinfo is None or self.stored_at.tzinfo is None:
            raise ValueError("capture manifest timestamps must be timezone-aware")
        if self.stored_at < self.captured_at:
            raise ValueError("stored_at cannot be earlier than captured_at")
        return self


class StoredCapture(DomainModel):
    """Portable references to a persisted capture and observation manifest."""

    manifest: CaptureManifest
    manifest_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    content_path: str = Field(min_length=1, max_length=2048)
    manifest_path: str = Field(min_length=1, max_length=2048)


class CaptureStore:
    """Write and replay RawCapture objects without provider/network access."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def write(
        self,
        capture: RawCapture,
        *,
        adapter_version: str,
        license_profile: DataLicenseProfile,
        stored_at: datetime | None = None,
    ) -> StoredCapture:
        """Persist capture content once and one manifest per observation event."""

        observation_stored_at = stored_at or datetime.now(UTC)
        if observation_stored_at.tzinfo is None:
            raise ReproducibilityError("stored_at must be timezone-aware")
        self._reject_credentials(capture.request)

        content = capture.content_bytes()
        content_hash = hashlib.sha256(content).hexdigest()
        if content_hash != capture.content_hash:
            raise ReproducibilityError("RawCapture content hash changed before persistence")

        content_relative = (
            Path("captures")
            / capture.provider
            / content_hash[:2]
            / f"{content_hash}.json"
        )
        content_path = self._resolve_relative(content_relative)
        self._write_immutable(content_path, content, "capture content")

        document = capture.content_document()
        request = document.get("request")
        if not isinstance(request, dict):
            raise ReproducibilityError("RawCapture request did not serialize as a mapping")
        manifest = CaptureManifest(
            capture_hash=content_hash,
            provider=capture.provider,
            endpoint=capture.endpoint,
            request=request,
            capture_schema_version=capture.schema_version,
            adapter_version=adapter_version,
            captured_at=capture.captured_at,
            stored_at=observation_stored_at,
            record_count=len(capture.records),
            content_path=content_relative.as_posix(),
            license_profile=license_profile,
        )
        manifest_content = self._serialize(manifest.model_dump(mode="json"))
        manifest_hash = hashlib.sha256(manifest_content).hexdigest()
        capture_stamp = capture.captured_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        manifest_relative = (
            Path("manifests")
            / capture.provider
            / content_hash
            / f"{capture_stamp}-{manifest_hash}.json"
        )
        manifest_path = self._resolve_relative(manifest_relative)
        self._write_immutable(manifest_path, manifest_content, "capture manifest")
        return StoredCapture(
            manifest=manifest,
            manifest_hash=manifest_hash,
            content_path=content_relative.as_posix(),
            manifest_path=manifest_relative.as_posix(),
        )

    def load(self, manifest_path: str | Path) -> RawCapture:
        """Verify and reconstruct a capture from a persisted manifest."""

        manifest_file = self._resolve_relative(Path(manifest_path))
        try:
            manifest_content = manifest_file.read_bytes()
            manifest_hash = hashlib.sha256(manifest_content).hexdigest()
            path_hash = manifest_file.stem.rsplit("-", maxsplit=1)[-1]
            if manifest_hash != path_hash:
                raise ReproducibilityError("Capture manifest content hash does not match its path")
            manifest_payload = json.loads(manifest_content)
            manifest = CaptureManifest.model_validate(manifest_payload)
        except ReproducibilityError:
            raise
        except (OSError, ValueError, TypeError) as error:
            raise ReproducibilityError(f"Invalid capture manifest: {manifest_file}") from error

        content_file = self._resolve_relative(Path(manifest.content_path))
        try:
            content = content_file.read_bytes()
        except OSError as error:
            raise ReproducibilityError(f"Capture content is unavailable: {content_file}") from error
        actual_hash = hashlib.sha256(content).hexdigest()
        if actual_hash != manifest.capture_hash:
            raise ReproducibilityError("Capture content does not match manifest hash")

        try:
            document = json.loads(content)
            capture = RawCapture.from_records(
                provider=document["provider"],
                endpoint=document["endpoint"],
                request=document["request"],
                records=document["records"],
                captured_at=manifest.captured_at,
                schema_version=document["schema_version"],
            )
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise ReproducibilityError("Capture content cannot be reconstructed") from error

        self._validate_lineage(capture, manifest)
        return capture

    def _resolve_relative(self, relative_path: Path) -> Path:
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ReproducibilityError(f"CaptureStore path must be relative: {relative_path}")
        resolved = (self._root / relative_path).resolve()
        if resolved != self._root and self._root not in resolved.parents:
            raise ReproducibilityError(f"CaptureStore path escapes its root: {relative_path}")
        return resolved

    @classmethod
    def _reject_credentials(cls, value: Any, path: str = "request") -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                item_path = f"{path}.{key}"
                if _is_credential_key(key):
                    raise ReproducibilityError(
                        f"Capture request contains prohibited credential field: {item_path}"
                    )
                cls._reject_credentials(item, item_path)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for index, item in enumerate(value):
                cls._reject_credentials(item, f"{path}[{index}]")

    @staticmethod
    def _write_immutable(path: Path, content: bytes, label: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as handle:
                handle.write(content)
        except FileExistsError:
            if path.read_bytes() != content:
                raise ReproducibilityError(f"Immutable {label} collision at {path}") from None

    @staticmethod
    def _serialize(payload: Any) -> bytes:
        return json.dumps(
            canonicalize(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _validate_lineage(capture: RawCapture, manifest: CaptureManifest) -> None:
        mismatches = []
        if capture.content_hash != manifest.capture_hash:
            mismatches.append("content_hash")
        if capture.provider != manifest.provider:
            mismatches.append("provider")
        if capture.endpoint != manifest.endpoint:
            mismatches.append("endpoint")
        if capture.schema_version != manifest.capture_schema_version:
            mismatches.append("schema_version")
        if len(capture.records) != manifest.record_count:
            mismatches.append("record_count")
        if canonicalize(capture.request) != canonicalize(manifest.request):
            mismatches.append("request")
        if mismatches:
            fields = ", ".join(mismatches)
            raise ReproducibilityError(f"Capture manifest lineage mismatch: {fields}")
