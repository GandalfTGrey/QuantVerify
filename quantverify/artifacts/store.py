"""Content-addressed persistence for small, canonical research results."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Final, Literal, TypeVar

from pydantic import BaseModel, Field, ValidationError, model_validator

from quantverify.core.exceptions import ReproducibilityError
from quantverify.core.identity import canonicalize
from quantverify.core.models import (
    ArtifactRef,
    DataSnapshot,
    DomainModel,
    EngineVersion,
    RuntimeContext,
)
from quantverify.engines.reference import ReferenceResult

REFERENCE_RESULT_KIND: Final = "reference_result"
REFERENCE_RESULT_SCHEMA: Final = "reference-result-v1"
ModelT = TypeVar("ModelT", bound=BaseModel)


class ReferenceResultEnvelope(DomainModel):
    """Deterministic content whose bytes define one reference-result artifact."""

    schema_version: Literal["reference-result-v1"] = REFERENCE_RESULT_SCHEMA
    kind: Literal["reference_result"] = REFERENCE_RESULT_KIND
    result: ReferenceResult


class RunArtifactManifest(DomainModel):
    """Observation metadata linking immutable content to one research run."""

    manifest_version: Literal["run-artifact-manifest-v1"] = "run-artifact-manifest-v1"
    experiment_id: str = Field(pattern=r"^exp_[a-f0-9]{12,64}$")
    run_id: str = Field(pattern=r"^run_[a-f0-9]{12,64}$")
    artifact: ArtifactRef
    runtime: RuntimeContext
    engine: EngineVersion
    dataset: DataSnapshot
    created_at: datetime
    content_path: str = Field(min_length=1, max_length=2048)

    @model_validator(mode="after")
    def validate_manifest(self) -> RunArtifactManifest:
        if self.created_at.tzinfo is None:
            raise ValueError("run artifact created_at must be timezone-aware")
        if self.artifact.kind != REFERENCE_RESULT_KIND:
            raise ValueError(f"unsupported run artifact kind: {self.artifact.kind!r}")
        if self.artifact.schema_version != REFERENCE_RESULT_SCHEMA:
            raise ValueError(
                f"unsupported run artifact schema: {self.artifact.schema_version!r}"
            )
        if self.artifact.uri != self.content_path:
            raise ValueError("artifact URI must match manifest content_path")
        return self


class StoredRunArtifact(DomainModel):
    """Portable references returned after an immutable artifact write."""

    manifest: RunArtifactManifest
    manifest_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    artifact_path: str = Field(min_length=1, max_length=2048)
    manifest_path: str = Field(min_length=1, max_length=2048)


class VerifiedRunArtifact(DomainModel):
    """Fully verified manifest, result, identity, and portable relative paths."""

    manifest: RunArtifactManifest
    manifest_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    reference_result: ReferenceResult
    artifact_path: str = Field(min_length=1, max_length=2048)
    manifest_path: str = Field(min_length=1, max_length=2048)

    @model_validator(mode="after")
    def validate_verified_artifact(self) -> VerifiedRunArtifact:
        manifest = RunArtifactManifest.model_validate(self.manifest.model_dump(mode="python"))
        result = ReferenceResult.model_validate(self.reference_result.model_dump(mode="python"))
        expected_manifest_hash = _content_hash(
            _serialize_canonical(manifest.model_dump(mode="python"))
        )
        if self.manifest_hash != expected_manifest_hash:
            raise ValueError("verified manifest hash does not match canonical manifest content")
        expected_artifact_path = _artifact_relative_path(manifest.artifact.content_hash)
        if self.artifact_path != expected_artifact_path:
            raise ValueError("verified artifact path is not canonical")
        expected_manifest_path = _manifest_relative_path(manifest, self.manifest_hash)
        if self.manifest_path != expected_manifest_path:
            raise ValueError("verified manifest path is not canonical")
        envelope = ReferenceResultEnvelope(result=result)
        expected_artifact_hash = _content_hash(
            _serialize_canonical(envelope.model_dump(mode="python"))
        )
        if manifest.artifact.content_hash != expected_artifact_hash:
            raise ValueError("verified reference result does not match manifest content hash")
        return self


class RunArtifactStore:
    """Persist and replay deterministic reference results without a database."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def write_reference_result(
        self,
        result: ReferenceResult,
        *,
        experiment_id: str,
        run_id: str,
        runtime: RuntimeContext,
        engine: EngineVersion,
        dataset: DataSnapshot,
        created_at: datetime | None = None,
    ) -> StoredRunArtifact:
        """Persist deterministic result content and one immutable run manifest."""

        observation_created_at = created_at or datetime.now(UTC)
        if observation_created_at.tzinfo is None:
            raise ReproducibilityError("run artifact created_at must be timezone-aware")
        observation_created_at = observation_created_at.astimezone(UTC)
        validated_result = ReferenceResult.model_validate(result.model_dump(mode="python"))
        validated_runtime = RuntimeContext.model_validate(runtime.model_dump(mode="python"))
        validated_engine = EngineVersion.model_validate(engine.model_dump(mode="python"))
        validated_dataset = DataSnapshot.model_validate(dataset.model_dump(mode="python"))
        envelope = ReferenceResultEnvelope(result=validated_result)
        content = self._serialize(envelope.model_dump(mode="python"))
        artifact_hash = _content_hash(content)
        artifact_relative = _artifact_relative_path(artifact_hash)
        artifact_path = self._resolve_relative(Path(artifact_relative))

        artifact_ref = ArtifactRef(
            kind=REFERENCE_RESULT_KIND,
            uri=artifact_relative,
            content_hash=artifact_hash,
            schema_version=REFERENCE_RESULT_SCHEMA,
        )
        manifest = RunArtifactManifest(
            experiment_id=experiment_id,
            run_id=run_id,
            artifact=artifact_ref,
            runtime=validated_runtime,
            engine=validated_engine,
            dataset=validated_dataset,
            created_at=observation_created_at,
            content_path=artifact_relative,
        )
        manifest_content = self._serialize(manifest.model_dump(mode="python"))
        manifest_hash = _content_hash(manifest_content)
        manifest_relative = _manifest_relative_path(manifest, manifest_hash)
        manifest_path = self._resolve_relative(Path(manifest_relative))
        self._write_immutable(artifact_path, content, "run artifact")
        self._write_immutable(manifest_path, manifest_content, "run artifact manifest")
        return StoredRunArtifact(
            manifest=manifest,
            manifest_hash=manifest_hash,
            artifact_path=artifact_relative,
            manifest_path=manifest_relative,
        )

    def load_reference_result(self, manifest_path: str | Path) -> ReferenceResult:
        """Compatibility loader backed by the verified inspection API."""

        return self.inspect_reference_result(manifest_path).reference_result

    def inspect_reference_result(self, manifest_path: str | Path) -> VerifiedRunArtifact:
        """Verify one explicitly named manifest and its reference result offline."""

        manifest_file = self._resolve_relative(Path(manifest_path))
        try:
            manifest_content = manifest_file.read_bytes()
            manifest_hash = _content_hash(manifest_content)
            path_hash = manifest_file.stem.rsplit("-", maxsplit=1)[-1]
            if manifest_hash != path_hash:
                raise ReproducibilityError(
                    "Run artifact manifest content hash does not match its path"
                )
            manifest = self._load_canonical_model(
                manifest_content,
                RunArtifactManifest,
                "Run artifact manifest",
            )
        except ReproducibilityError:
            raise
        except (OSError, ValidationError, ValueError, TypeError) as error:
            raise ReproducibilityError(f"Invalid run artifact manifest: {manifest_file}") from error

        expected_manifest_relative = _manifest_relative_path(manifest, manifest_hash)
        if manifest_file != self._resolve_relative(Path(expected_manifest_relative)):
            raise ReproducibilityError("Run artifact manifest path is not canonical")

        expected_relative = _artifact_relative_path(manifest.artifact.content_hash)
        if manifest.content_path != expected_relative:
            raise ReproducibilityError("Run artifact manifest content path is not canonical")
        artifact_file = self._resolve_relative(Path(manifest.content_path))
        try:
            content = artifact_file.read_bytes()
        except OSError as error:
            raise ReproducibilityError(f"Run artifact is unavailable: {artifact_file}") from error
        actual_hash = _content_hash(content)
        if actual_hash != manifest.artifact.content_hash:
            raise ReproducibilityError("Run artifact content does not match manifest hash")

        try:
            envelope = self._load_canonical_model(
                content,
                ReferenceResultEnvelope,
                "Run artifact content",
            )
            verified = VerifiedRunArtifact(
                manifest=manifest,
                manifest_hash=manifest_hash,
                reference_result=envelope.result,
                artifact_path=expected_relative,
                manifest_path=expected_manifest_relative,
            )
            return VerifiedRunArtifact.model_validate(verified.model_dump(mode="python"))
        except (ValidationError, ValueError, TypeError) as error:
            raise ReproducibilityError("Run artifact content cannot be reconstructed") from error

    def _resolve_relative(self, relative_path: Path) -> Path:
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ReproducibilityError(f"RunArtifactStore path must be relative: {relative_path}")
        resolved = (self._root / relative_path).resolve()
        if resolved != self._root and self._root not in resolved.parents:
            raise ReproducibilityError(f"RunArtifactStore path escapes its root: {relative_path}")
        return resolved

    @staticmethod
    def _write_immutable(path: Path, content: bytes, label: str) -> None:
        """Publish complete bytes atomically without replacing an existing object."""

        path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_name = tempfile.mkstemp(prefix=".quantverify-", dir=path.parent)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(file_descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary_path, path)
            except FileExistsError:
                if path.read_bytes() != content:
                    raise ReproducibilityError(
                        f"Immutable {label} collision at {path}"
                    ) from None
        finally:
            temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _serialize(payload: Any) -> bytes:
        return _serialize_canonical(payload)

    @classmethod
    def _load_canonical_model(
        cls,
        content: bytes,
        model_type: type[ModelT],
        label: str,
    ) -> ModelT:
        model = model_type.model_validate(cls._loads_strict(content))
        canonical_content = cls._serialize(model.model_dump(mode="python"))
        if content != canonical_content:
            raise ReproducibilityError(f"{label} is not canonical JSON")
        return model

    @staticmethod
    def _loads_strict(content: bytes) -> Any:
        def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"Duplicate JSON key: {key}")
                result[key] = value
            return result

        return json.loads(content, object_pairs_hook=reject_duplicate_keys)


def _serialize_canonical(payload: Any) -> bytes:
    return json.dumps(
        canonicalize(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _artifact_relative_path(content_hash: str) -> str:
    return (
        PurePosixPath("artifacts")
        / REFERENCE_RESULT_KIND
        / content_hash[:2]
        / f"{content_hash}.json"
    ).as_posix()


def _manifest_relative_path(manifest: RunArtifactManifest, manifest_hash: str) -> str:
    created_stamp = manifest.created_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return (
        PurePosixPath("run_manifests")
        / manifest.run_id
        / manifest.artifact.content_hash
        / f"{created_stamp}-{manifest_hash}.json"
    ).as_posix()
