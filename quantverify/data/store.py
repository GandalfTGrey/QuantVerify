"""Provider-agnostic persistence for immutable raw captures and manifests."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import unicodedata
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

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
        "credential",
        "credentials",
        "password",
        "passwd",
        "secret",
        "signature",
        "token",
    }
)
_CREDENTIAL_COMPACT_KEYS = frozenset(
    {
        "accesskey",
        "accesskeyid",
        "accesstoken",
        "appkey",
        "appsecret",
        "apikey",
        "authtoken",
        "clientsecret",
        "consumerkey",
        "encryptionkey",
        "functionskey",
        "privatekey",
        "refreshtoken",
        "secretaccesskey",
        "secretkey",
        "securitytoken",
        "sessiontoken",
        "signingkey",
        "subscriptionkey",
    }
)
_CREDENTIAL_COMPACT_SUFFIXES = _CREDENTIAL_COMPACT_KEYS | frozenset(
    {
        "authorization",
        "credential",
        "passwd",
        "password",
        "secret",
        "signature",
        "token",
    }
)
_CREDENTIAL_KEY_QUALIFIERS = frozenset(
    {
        "access",
        "api",
        "apim",
        "app",
        "aws",
        "azure",
        "consumer",
        "encryption",
        "functions",
        "oauth",
        "oauth2",
        "private",
        "secret",
        "service",
        "signing",
        "subscription",
    }
)


def _decode_request_key(key: str) -> str:
    """Normalize common transport encodings without inspecting request values."""

    decoded = key
    # NFKC may expose a percent escape, while percent decoding may expose new
    # compatibility characters. Iterate the composition to one joint fixed point.
    # Effective percent passes shorten the finite input; NFKC is idempotent after
    # each newly decoded layer, so this input-sized work bound is fail-closed.
    for _ in range(max(4, len(key) * 2 + 1)):
        next_value = unquote(unicodedata.normalize("NFKC", decoded))
        if next_value == decoded:
            return decoded
        decoded = next_value
    # Defensive fail-closed sentinel; this should be unreachable for urllib's
    # non-expanding unquote implementation.
    return "credential"


def _credential_key_tokens(key: str) -> tuple[str, ...]:
    """Split a request key into case-folded semantic tokens."""

    decoded = _decode_request_key(key)
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", decoded)
    acronym_split = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", camel_split)
    return tuple(
        re.sub(r"\d+$", "", token)
        for token in re.split(r"[^A-Za-z0-9]+", acronym_split.casefold())
        if re.sub(r"\d+$", "", token)
    )


def _is_credential_key(key: str) -> bool:
    tokens = _credential_key_tokens(key)
    if not tokens:
        return False
    token_set = set(tokens)
    compact = "".join(tokens)
    if token_set & _CREDENTIAL_TOKENS:
        return True
    if token_set & _CREDENTIAL_COMPACT_KEYS:
        return True
    if any(compact.endswith(candidate) for candidate in _CREDENTIAL_COMPACT_SUFFIXES):
        return True
    if "key" not in token_set:
        return False
    return len(tokens) == 1 or bool(token_set & _CREDENTIAL_KEY_QUALIFIERS)


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        canonicalize(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _reject_credentials(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _is_credential_key(key):
                raise ValueError("prohibited credential field")
            _reject_credentials(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _reject_credentials(item)


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
    """Portable references returned immediately after capture persistence."""

    manifest: CaptureManifest
    manifest_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    content_path: str = Field(min_length=1, max_length=2048)
    manifest_path: str = Field(min_length=1, max_length=2048)


class VerifiedCapture(DomainModel):
    """Replay result retaining verified observation and license provenance."""

    capture: RawCapture
    manifest: CaptureManifest
    manifest_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    content_path: str = Field(min_length=1, max_length=2048)
    manifest_path: str = Field(min_length=1, max_length=2048)

    @model_validator(mode="after")
    def validate_verified_lineage(self) -> VerifiedCapture:
        try:
            capture = RawCapture.model_validate(self.capture.model_dump(mode="python"))
            manifest = CaptureManifest.model_validate(self.manifest.model_dump(mode="python"))
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError("verified capture nested integrity validation failed") from error

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
        if capture.captured_at.astimezone(UTC) != manifest.captured_at:
            mismatches.append("captured_at")
        if mismatches:
            fields = ", ".join(mismatches)
            raise ValueError(f"verified capture lineage mismatch: {fields}")
        try:
            _reject_credentials(capture.request)
            _reject_credentials(manifest.request)
        except ValueError:
            raise ValueError("verified capture contains prohibited credential field") from None

        expected_manifest_hash = hashlib.sha256(
            _canonical_json_bytes(manifest.model_dump(mode="json"))
        ).hexdigest()
        if self.manifest_hash != expected_manifest_hash:
            raise ValueError("verified capture manifest hash does not match its manifest")

        expected_content = (
            Path("captures")
            / manifest.provider
            / manifest.capture_hash[:2]
            / f"{manifest.capture_hash}.json"
        ).as_posix()
        if manifest.content_path != expected_content or self.content_path != expected_content:
            raise ValueError("verified capture content path is not canonical")

        capture_stamp = manifest.captured_at.astimezone(UTC).strftime(
            "%Y%m%dT%H%M%S%fZ"
        )
        expected_manifest = (
            Path("manifests")
            / manifest.provider
            / manifest.capture_hash
            / f"{capture_stamp}-{self.manifest_hash}.json"
        ).as_posix()
        if self.manifest_path != expected_manifest:
            raise ValueError("verified capture manifest path is not canonical")
        return self


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
        if not isinstance(observation_stored_at, datetime) or (
            observation_stored_at.tzinfo is None
        ):
            raise ReproducibilityError("stored_at must be timezone-aware")

        capture = self._revalidate_capture(capture)
        license_profile = self._revalidate_license_profile(license_profile)
        try:
            _reject_credentials(capture.request)
        except ValueError:
            raise ReproducibilityError(
                "Capture request contains prohibited credential field"
            ) from None

        content = capture.content_bytes()
        content_hash = hashlib.sha256(content).hexdigest()
        if content_hash != capture.content_hash:
            raise ReproducibilityError("RawCapture content hash changed before persistence")

        content_relative = self._canonical_content_relative(capture.provider, content_hash)
        content_path = self._resolve_relative(content_relative)

        document = capture.content_document()
        request = document.get("request")
        if not isinstance(request, dict):
            raise ReproducibilityError("RawCapture request did not serialize as a mapping")
        try:
            validated_manifest: CaptureManifest | None = CaptureManifest(
                capture_hash=content_hash,
                provider=capture.provider,
                endpoint=capture.endpoint,
                request=request,
                capture_schema_version=capture.schema_version,
                adapter_version=adapter_version,
                captured_at=capture.captured_at.astimezone(UTC),
                stored_at=observation_stored_at.astimezone(UTC),
                record_count=len(capture.records),
                content_path=content_relative.as_posix(),
                license_profile=license_profile,
            )
        except (TypeError, ValueError):
            validated_manifest = None
        if validated_manifest is None:
            raise ReproducibilityError("Capture manifest failed integrity validation")
        manifest = validated_manifest
        manifest_content = self._serialize(manifest.model_dump(mode="json"))
        manifest_hash = hashlib.sha256(manifest_content).hexdigest()
        manifest_relative = self._canonical_manifest_relative(manifest, manifest_hash)
        manifest_path = self._resolve_relative(manifest_relative)
        stored = StoredCapture(
            manifest=manifest,
            manifest_hash=manifest_hash,
            content_path=content_relative.as_posix(),
            manifest_path=manifest_relative.as_posix(),
        )

        # All validation and canonical serialization succeed before atomic publication.
        self._write_immutable(content_path, content, "capture content")
        self._write_immutable(manifest_path, manifest_content, "capture manifest")
        return stored

    def load(self, manifest_path: str | Path) -> RawCapture:
        """Compatibility replay returning only the capture payload."""

        return self.load_verified(manifest_path).capture

    def load_verified(self, manifest_path: str | Path) -> VerifiedCapture:
        """Verify immutable lineage and replay capture plus observation provenance."""

        manifest_file = self._resolve_relative(Path(manifest_path))
        try:
            manifest_content = self._read_regular_bytes(manifest_file, "capture manifest")
        except ReproducibilityError as error:
            raise ReproducibilityError(f"Invalid capture manifest: {manifest_file}") from error
        manifest_hash = hashlib.sha256(manifest_content).hexdigest()
        path_hash = manifest_file.stem.rsplit("-", maxsplit=1)[-1]
        if manifest_hash != path_hash:
            raise ReproducibilityError(
                "Capture manifest content hash does not match its path"
            )
        parsed_manifest: CaptureManifest | None = None
        with suppress(ValueError, TypeError):
            parsed_manifest = CaptureManifest.model_validate(
                self._loads_strict(manifest_content)
            )
        if parsed_manifest is None:
            raise ReproducibilityError(f"Invalid capture manifest: {manifest_file}")
        manifest = parsed_manifest

        expected_manifest_relative = self._canonical_manifest_relative(manifest, manifest_hash)
        if manifest_file != self._resolve_relative(expected_manifest_relative):
            raise ReproducibilityError("Capture manifest path is not canonical")

        expected_content_relative = self._canonical_content_relative(
            manifest.provider,
            manifest.capture_hash,
        )
        if manifest.content_path != expected_content_relative.as_posix():
            raise ReproducibilityError("Capture manifest content path is not canonical")
        content_file = self._resolve_relative(expected_content_relative)
        try:
            content = self._read_regular_bytes(content_file, "capture content")
        except ReproducibilityError as error:
            raise ReproducibilityError(f"Capture content is unavailable: {content_file}") from error
        if hashlib.sha256(content).hexdigest() != manifest.capture_hash:
            raise ReproducibilityError("Capture content does not match manifest hash")

        reconstructed_capture: RawCapture | None = None
        try:
            document = self._loads_strict(content)
            if isinstance(document, dict):
                reconstructed_capture = RawCapture.from_records(
                provider=document["provider"],
                endpoint=document["endpoint"],
                request=document["request"],
                records=document["records"],
                captured_at=manifest.captured_at,
                schema_version=document["schema_version"],
            )
        except (KeyError, ValueError, TypeError):
            pass
        if reconstructed_capture is None:
            raise ReproducibilityError("Capture content cannot be reconstructed")
        capture = reconstructed_capture

        self._validate_lineage(capture, manifest)
        verified_capture: VerifiedCapture | None = None
        with suppress(TypeError, ValueError):
            verified_capture = VerifiedCapture(
                capture=capture,
                manifest=manifest,
                manifest_hash=manifest_hash,
                content_path=expected_content_relative.as_posix(),
                manifest_path=expected_manifest_relative.as_posix(),
            )
        if verified_capture is None:
            raise ReproducibilityError("Verified capture failed integrity validation")
        return verified_capture

    @staticmethod
    def _canonical_content_relative(provider: str, content_hash: str) -> Path:
        return Path("captures") / provider / content_hash[:2] / f"{content_hash}.json"

    @staticmethod
    def _canonical_manifest_relative(
        manifest: CaptureManifest,
        manifest_hash: str,
    ) -> Path:
        capture_stamp = manifest.captured_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        return (
            Path("manifests")
            / manifest.provider
            / manifest.capture_hash
            / f"{capture_stamp}-{manifest_hash}.json"
        )

    def _resolve_relative(self, relative_path: Path) -> Path:
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ReproducibilityError(f"CaptureStore path must be relative: {relative_path}")
        lexical_path = self._root / relative_path
        resolved = lexical_path.resolve()
        if resolved != self._root and self._root not in resolved.parents:
            raise ReproducibilityError(f"CaptureStore path escapes its root: {relative_path}")
        current = self._root
        for part in relative_path.parts:
            current = current / part
            if current.is_symlink():
                raise ReproducibilityError(
                    f"CaptureStore path contains a symbolic link: {relative_path}"
                )
        return lexical_path

    @staticmethod
    def _revalidate_capture(capture: RawCapture) -> RawCapture:
        try:
            payload = {
                field_name: getattr(capture, field_name)
                for field_name in RawCapture.model_fields
            }
            validated_capture: RawCapture | None = RawCapture.model_validate(payload)
        except (AttributeError, TypeError, ValueError):
            validated_capture = None
        if validated_capture is None:
            raise ReproducibilityError("RawCapture failed integrity validation")
        return validated_capture

    @staticmethod
    def _revalidate_license_profile(
        license_profile: DataLicenseProfile,
    ) -> DataLicenseProfile:
        try:
            payload = {
                field_name: getattr(license_profile, field_name)
                for field_name in DataLicenseProfile.model_fields
            }
            validated_profile: DataLicenseProfile | None = (
                DataLicenseProfile.model_validate(payload)
            )
        except (AttributeError, TypeError, ValueError):
            validated_profile = None
        if validated_profile is None:
            raise ReproducibilityError("DataLicenseProfile failed integrity validation")
        return validated_profile

    def _write_immutable(self, path: Path, content: bytes, label: str) -> None:
        """Publish complete bytes atomically without replacing an existing object."""

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            file_descriptor, temporary_name = tempfile.mkstemp(
                prefix=".quantverify-",
                dir=path.parent,
            )
        except OSError as error:
            raise ReproducibilityError(
                f"Atomic {label} staging failed at {path}"
            ) from error
        temporary_path = Path(temporary_name)
        primary_error: Exception | None = None
        try:
            handle_opened = False
            try:
                handle = os.fdopen(file_descriptor, "wb")
                handle_opened = True
                with handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError as error:
                if not handle_opened:
                    with suppress(OSError):
                        os.close(file_descriptor)
                raise ReproducibilityError(
                    f"Atomic {label} staging failed at {path}"
                ) from error
            try:
                os.link(temporary_path, path)
            except FileExistsError:
                if not self._existing_regular_file_matches(path, content):
                    raise ReproducibilityError(
                        f"Immutable {label} collision at {path}"
                    ) from None
            except OSError as error:
                raise ReproducibilityError(
                    f"Atomic {label} publication failed at {path}"
                ) from error
            try:
                # Repeat this even for an identical pre-existing object. A prior
                # attempt may have linked it successfully but failed its directory
                # sync, so idempotent retry must finish the durability boundary.
                self._fsync_directory_chain(path.parent)
            except OSError as error:
                raise ReproducibilityError(
                    f"Atomic {label} directory sync failed at {path.parent}"
                ) from error
        except Exception as error:
            primary_error = error

        cleanup_error: ReproducibilityError | None = None
        try:
            temporary_path.unlink(missing_ok=True)
            self._fsync_directory_chain(path.parent)
        except OSError as error:
            cleanup_error = ReproducibilityError(
                f"Atomic {label} staging cleanup failed at {temporary_path}"
            )
            cleanup_error.__cause__ = error

        if primary_error is not None:
            if cleanup_error is not None:
                primary_error.add_note(str(cleanup_error))
            raise primary_error
        if cleanup_error is not None:
            raise cleanup_error

    @staticmethod
    def _existing_regular_file_matches(path: Path, content: bytes) -> bool:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError:
            return False
        matches = False
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != len(content):
                matches = False
            else:
                chunks: list[bytes] = []
                remaining = len(content)
                while remaining:
                    chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                matches = (
                    remaining == 0
                    and b"".join(chunks) == content
                    and os.read(descriptor, 1) == b""
                )
        except OSError:
            matches = False
        try:
            os.close(descriptor)
        except OSError:
            matches = False
        return matches

    @staticmethod
    def _read_regular_bytes(path: Path, label: str) -> bytes:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as error:
            raise ReproducibilityError(f"{label} cannot be opened as a regular file") from error
        read_error: OSError | None = None
        content: bytes | None = None
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise OSError(f"{label} is not a regular file")
            chunks: list[bytes] = []
            remaining = metadata.st_size
            while remaining:
                chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                if not chunk:
                    raise OSError(f"{label} ended before its declared size")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1) != b"":
                raise OSError(f"{label} grew during replay")
            content = b"".join(chunks)
        except OSError as error:
            read_error = error
        try:
            os.close(descriptor)
        except OSError as error:
            if read_error is None:
                read_error = error
        if read_error is not None or content is None:
            raise ReproducibilityError(
                f"{label} cannot be verified as a regular file"
            ) from read_error
        return content

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_descriptor = os.open(directory, flags)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)

    def _fsync_directory_chain(self, directory: Path) -> None:
        current = directory
        while True:
            self._fsync_directory(current)
            if current == self._root:
                return
            if self._root not in current.parents:
                raise OSError("directory sync path escapes CaptureStore root")
            current = current.parent

    @staticmethod
    def _serialize(payload: Any) -> bytes:
        return _canonical_json_bytes(payload)

    @staticmethod
    def _loads_strict(content: bytes) -> Any:
        def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate JSON key")
                result[key] = value
            return result

        return json.loads(content, object_pairs_hook=reject_duplicate_keys)

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
