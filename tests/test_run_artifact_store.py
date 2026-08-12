import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest import TestCase

from pydantic import ValidationError

from quantverify.artifacts import VerifiedRunArtifact
from quantverify.artifacts.store import (
    ReferenceResultEnvelope,
    RunArtifactManifest,
    RunArtifactStore,
)
from quantverify.core.enums import AdjustmentMode
from quantverify.core.exceptions import ReproducibilityError
from quantverify.core.models import DataSnapshot, EngineVersion, RuntimeContext
from quantverify.engines.reference import LongFlatReferenceEngine
from quantverify.strategies import price_above_sma_targets
from tests.test_trend_strategy import load_bars, load_schedule

CREATED_AT = datetime(2026, 8, 11, 1, 2, 3, tzinfo=UTC)
RUNTIME = RuntimeContext(
    source_commit="a" * 40,
    environment_lock_hash="b" * 64,
    worker_id="mac-m1-local",
)
ENGINE = EngineVersion(engine_id="reference", version="1.0.0")
DATASET = DataSnapshot(
    dataset_id="fixture-sma3-v1",
    content_hash="c" * 64,
    schema_version="bars-v1",
    source="golden_fixture",
    captured_at=datetime(2026, 8, 10, tzinfo=UTC),
    adjustment_mode=AdjustmentMode.RAW,
)
EXPERIMENT_ID = f"exp_{'d' * 24}"
RUN_ID = f"run_{'e' * 24}"


def build_result(*, commission_bps: Decimal = Decimal("0")):
    bars = load_bars()[:7]
    targets = price_above_sma_targets(
        bars,
        window=3,
        schedule=load_schedule(session_count=len(bars)),
    )
    return LongFlatReferenceEngine().run(
        bars,
        targets,
        initial_cash=Decimal("10300"),
        commission_bps=commission_bps,
    )


class RunArtifactStoreTests(TestCase):
    def test_inspects_complete_verified_artifact_and_preserves_loader_compatibility(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            stored = self._write(RunArtifactStore(root))
            reopened = RunArtifactStore(root)

            verified = reopened.inspect_reference_result(stored.manifest_path)
            replayed = reopened.load_reference_result(stored.manifest_path)

        self.assertIsInstance(verified, VerifiedRunArtifact)
        self.assertEqual(verified.manifest, stored.manifest)
        self.assertEqual(verified.manifest_hash, stored.manifest_hash)
        self.assertEqual(verified.reference_result, replayed)
        self.assertEqual(verified.artifact_path, stored.artifact_path)
        self.assertEqual(verified.manifest_path, stored.manifest_path)
        self.assertEqual(
            VerifiedRunArtifact.model_validate_json(verified.model_dump_json()),
            verified,
        )

    def test_persists_and_replays_reference_result_offline(self) -> None:
        with TemporaryDirectory() as directory:
            store = RunArtifactStore(Path(directory))
            result = build_result()
            stored = store.write_reference_result(
                result,
                experiment_id=EXPERIMENT_ID,
                run_id=RUN_ID,
                runtime=RUNTIME,
                engine=ENGINE,
                dataset=DATASET,
                created_at=CREATED_AT,
            )

            replayed = store.load_reference_result(stored.manifest_path)
            persisted_hash = hashlib.sha256(
                (Path(directory) / stored.artifact_path).read_bytes()
            ).hexdigest()

        self.assertEqual(replayed, result)
        self.assertEqual(stored.manifest.artifact.content_hash, persisted_hash)
        self.assertFalse(Path(stored.artifact_path).is_absolute())
        self.assertEqual(stored.manifest.runtime, RUNTIME)
        self.assertEqual(stored.manifest.dataset, DATASET)

    def test_identical_result_reuses_content_but_keeps_run_observations(self) -> None:
        with TemporaryDirectory() as directory:
            store = RunArtifactStore(Path(directory))
            first = self._write(store, created_at=CREATED_AT)
            second = self._write(store, created_at=CREATED_AT + timedelta(seconds=1))

        self.assertEqual(first.artifact_path, second.artifact_path)
        self.assertNotEqual(first.manifest_path, second.manifest_path)
        self.assertNotEqual(first.manifest_hash, second.manifest_hash)

    def test_equivalent_created_at_instants_have_one_manifest_identity(self) -> None:
        offset = timezone(timedelta(hours=-4))
        equivalent = CREATED_AT.astimezone(offset)
        self.assertEqual(CREATED_AT, equivalent)

        with TemporaryDirectory() as directory:
            store = RunArtifactStore(Path(directory))
            utc_stored = self._write(store, created_at=CREATED_AT)
            offset_stored = self._write(store, created_at=equivalent)
            utc_verified = store.inspect_reference_result(utc_stored.manifest_path)
            offset_verified = store.inspect_reference_result(offset_stored.manifest_path)

        self.assertEqual(utc_stored, offset_stored)
        self.assertEqual(utc_stored.manifest_hash, offset_stored.manifest_hash)
        self.assertEqual(utc_stored.manifest_path, offset_stored.manifest_path)
        self.assertEqual(utc_stored.manifest.created_at.tzinfo, UTC)
        self.assertEqual(utc_verified, offset_verified)

    def test_loader_accepts_legacy_canonical_non_utc_manifest(self) -> None:
        offset = timezone(timedelta(hours=-4))
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = RunArtifactStore(root)
            stored = self._write(store)
            legacy_manifest = RunArtifactManifest.model_validate(
                {
                    **stored.manifest.model_dump(mode="python"),
                    "created_at": CREATED_AT.astimezone(offset),
                }
            )
            legacy_relative = self._write_canonical_manifest(root, legacy_manifest)

            verified = store.inspect_reference_result(legacy_relative)

        self.assertEqual(verified.reference_result, build_result())
        self.assertEqual(verified.manifest.created_at.utcoffset(), timedelta(hours=-4))
        self.assertEqual(verified.manifest_path, legacy_relative.as_posix())

    def test_repeated_exact_write_is_idempotent(self) -> None:
        with TemporaryDirectory() as directory:
            store = RunArtifactStore(Path(directory))
            first = self._write(store, created_at=CREATED_AT)
            second = self._write(store, created_at=CREATED_AT)

        self.assertEqual(first, second)

    def test_rejects_invalid_metadata_before_writing_content(self) -> None:
        with TemporaryDirectory() as directory:
            store = RunArtifactStore(Path(directory))
            with self.assertRaisesRegex(ReproducibilityError, "timezone-aware"):
                self._write(store, created_at=datetime(2026, 8, 11))
            self.assertFalse((Path(directory) / "artifacts").exists())

    def test_result_change_produces_new_content_identity(self) -> None:
        with TemporaryDirectory() as directory:
            store = RunArtifactStore(Path(directory))
            free = self._write(store, result=build_result())
            costly = self._write(store, result=build_result(commission_bps=Decimal("10")))

        self.assertNotEqual(free.artifact_path, costly.artifact_path)
        self.assertNotEqual(
            free.manifest.artifact.content_hash,
            costly.manifest.artifact.content_hash,
        )

    def test_rejects_tampered_artifact_and_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            store = RunArtifactStore(Path(directory))
            stored = self._write(store)
            artifact_path = Path(directory) / stored.artifact_path
            artifact_path.write_bytes(artifact_path.read_bytes() + b" ")
            with self.assertRaisesRegex(ReproducibilityError, "content does not match"):
                store.load_reference_result(stored.manifest_path)

        with TemporaryDirectory() as directory:
            store = RunArtifactStore(Path(directory))
            stored = self._write(store)
            manifest_path = Path(directory) / stored.manifest_path
            manifest_path.write_bytes(manifest_path.read_bytes() + b" ")
            with self.assertRaisesRegex(ReproducibilityError, "manifest content hash"):
                store.load_reference_result(stored.manifest_path)

    def test_rejects_noncanonical_and_escaping_paths(self) -> None:
        with TemporaryDirectory() as directory:
            store = RunArtifactStore(Path(directory))
            with self.assertRaisesRegex(ReproducibilityError, "must be relative"):
                store.load_reference_result("../outside.json")

            stored = self._write(store)
            manifest_path = Path(directory) / stored.manifest_path
            payload = json.loads(manifest_path.read_bytes())
            payload["content_path"] = "artifacts/reference_result/not-canonical.json"
            payload["artifact"]["uri"] = payload["content_path"]
            content = RunArtifactStore._serialize(payload)
            digest = hashlib.sha256(content).hexdigest()
            forged_path = manifest_path.with_name(f"20260811T010203000000Z-{digest}.json")
            forged_path.write_bytes(content)
            with self.assertRaisesRegex(ReproducibilityError, "path is not canonical"):
                store.load_reference_result(forged_path.relative_to(directory))

            moved_path = Path(directory) / "run_manifests" / "wrong" / manifest_path.name
            moved_path.parent.mkdir(parents=True)
            moved_path.write_bytes(manifest_path.read_bytes())
            with self.assertRaisesRegex(ReproducibilityError, "manifest path is not canonical"):
                store.load_reference_result(moved_path.relative_to(directory))

    def test_rejects_immutable_content_collision(self) -> None:
        with TemporaryDirectory() as directory:
            store = RunArtifactStore(Path(directory))
            result = build_result()
            envelope = ReferenceResultEnvelope(result=result)
            content = RunArtifactStore._serialize(envelope.model_dump(mode="python"))
            digest = hashlib.sha256(content).hexdigest()
            collision_path = (
                Path(directory)
                / "artifacts"
                / "reference_result"
                / digest[:2]
                / f"{digest}.json"
            )
            collision_path.parent.mkdir(parents=True)
            collision_path.write_bytes(b"not-the-expected-content")

            with self.assertRaisesRegex(ReproducibilityError, "run artifact collision"):
                self._write(store, result=result)

    def test_rejects_immutable_manifest_collision(self) -> None:
        with TemporaryDirectory() as directory:
            store = RunArtifactStore(Path(directory))
            stored = self._write(store)
            manifest_path = Path(directory) / stored.manifest_path
            manifest_path.write_bytes(b"not-the-expected-manifest")

            with self.assertRaisesRegex(ReproducibilityError, "manifest collision"):
                self._write(store)

    def test_rejects_noncanonical_manifest_and_artifact_bytes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = RunArtifactStore(root)
            stored = self._write(store)
            manifest_path = root / stored.manifest_path

            pretty_manifest = json.dumps(
                json.loads(manifest_path.read_bytes()),
                indent=2,
                sort_keys=True,
            ).encode()
            pretty_manifest_hash = hashlib.sha256(pretty_manifest).hexdigest()
            noncanonical_manifest_path = manifest_path.with_name(
                f"20260811T010203000000Z-{pretty_manifest_hash}.json"
            )
            noncanonical_manifest_path.write_bytes(pretty_manifest)
            with self.assertRaisesRegex(ReproducibilityError, "not canonical JSON"):
                store.inspect_reference_result(noncanonical_manifest_path.relative_to(root))

            artifact_path = root / stored.artifact_path
            pretty_artifact = json.dumps(
                json.loads(artifact_path.read_bytes()),
                indent=2,
                sort_keys=True,
            ).encode()
            pretty_artifact_hash = hashlib.sha256(pretty_artifact).hexdigest()
            pretty_artifact_relative = (
                Path("artifacts")
                / "reference_result"
                / pretty_artifact_hash[:2]
                / f"{pretty_artifact_hash}.json"
            )
            pretty_artifact_path = root / pretty_artifact_relative
            pretty_artifact_path.parent.mkdir(parents=True)
            pretty_artifact_path.write_bytes(pretty_artifact)
            forged_manifest = RunArtifactManifest.model_validate(
                {
                    **stored.manifest.model_dump(mode="python"),
                    "artifact": {
                        **stored.manifest.artifact.model_dump(mode="python"),
                        "uri": pretty_artifact_relative.as_posix(),
                        "content_hash": pretty_artifact_hash,
                    },
                    "content_path": pretty_artifact_relative.as_posix(),
                }
            )
            forged_relative = self._write_canonical_manifest(root, forged_manifest)
            with self.assertRaisesRegex(ReproducibilityError, "not canonical JSON"):
                store.inspect_reference_result(forged_relative)

    def test_inspection_rejects_duplicate_keys_in_persisted_files(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = RunArtifactStore(root)
            stored = self._write(store)
            manifest_path = root / stored.manifest_path
            manifest_content = manifest_path.read_bytes()
            duplicated_manifest = manifest_content.replace(
                b'"run_id":',
                b'"run_id":"run_eeeeeeeeeeeeeeeeeeeeeeee","run_id":',
                1,
            )
            duplicate_hash = hashlib.sha256(duplicated_manifest).hexdigest()
            duplicate_path = manifest_path.with_name(
                f"20260811T010203000000Z-{duplicate_hash}.json"
            )
            duplicate_path.write_bytes(duplicated_manifest)
            with self.assertRaisesRegex(ReproducibilityError, "Invalid run artifact manifest"):
                store.inspect_reference_result(duplicate_path.relative_to(root))

            artifact_path = root / stored.artifact_path
            artifact_content = artifact_path.read_bytes()
            duplicated_artifact = artifact_content.replace(
                b'"kind":',
                b'"kind":"reference_result","kind":',
                1,
            )
            duplicate_artifact_hash = hashlib.sha256(duplicated_artifact).hexdigest()
            duplicate_artifact_relative = (
                Path("artifacts")
                / "reference_result"
                / duplicate_artifact_hash[:2]
                / f"{duplicate_artifact_hash}.json"
            )
            duplicate_artifact_path = root / duplicate_artifact_relative
            duplicate_artifact_path.parent.mkdir(parents=True)
            duplicate_artifact_path.write_bytes(duplicated_artifact)
            forged_manifest = RunArtifactManifest.model_validate(
                {
                    **stored.manifest.model_dump(mode="python"),
                    "artifact": {
                        **stored.manifest.artifact.model_dump(mode="python"),
                        "uri": duplicate_artifact_relative.as_posix(),
                        "content_hash": duplicate_artifact_hash,
                    },
                    "content_path": duplicate_artifact_relative.as_posix(),
                }
            )
            forged_relative = self._write_canonical_manifest(root, forged_manifest)
            with self.assertRaisesRegex(ReproducibilityError, "cannot be reconstructed"):
                store.inspect_reference_result(forged_relative)

    def test_verified_result_revalidates_unsafe_nested_models(self) -> None:
        with TemporaryDirectory() as directory:
            store = RunArtifactStore(Path(directory))
            verified = store.inspect_reference_result(self._write(store).manifest_path)

        unsafe_runtime = verified.manifest.runtime.model_copy(update={"worker_id": ""})
        unsafe_manifest = verified.manifest.model_copy(update={"runtime": unsafe_runtime})
        with self.assertRaises(ValidationError):
            VerifiedRunArtifact.model_validate(
                {**verified.model_dump(mode="python"), "manifest": unsafe_manifest}
            )

        unsafe_result = verified.reference_result.model_copy(
            update={"initial_cash": Decimal("-1")}
        )
        with self.assertRaises(ValidationError):
            VerifiedRunArtifact.model_validate(
                {**verified.model_dump(mode="python"), "reference_result": unsafe_result}
            )

        with self.assertRaisesRegex(ValidationError, "does not match manifest content hash"):
            VerifiedRunArtifact.model_validate(
                {
                    **verified.model_dump(mode="python"),
                    "reference_result": build_result(commission_bps=Decimal("10")),
                }
            )
        with self.assertRaisesRegex(ValidationError, "manifest hash"):
            VerifiedRunArtifact.model_validate(
                {**verified.model_dump(mode="python"), "manifest_hash": "f" * 64}
            )

    def test_concurrent_identical_and_different_content_publication(self) -> None:
        with TemporaryDirectory() as directory:
            store = RunArtifactStore(Path(directory))
            free = build_result()
            costly = build_result(commission_bps=Decimal("10"))
            barrier = Barrier(8)

            def publish(result):
                barrier.wait()
                return self._write(store, result=result)

            inputs = (free, free, free, free, costly, costly, costly, costly)
            with ThreadPoolExecutor(max_workers=8) as executor:
                stored = tuple(executor.map(publish, inputs))

            free_writes = stored[:4]
            costly_writes = stored[4:]
            self.assertEqual(len({item.artifact_path for item in free_writes}), 1)
            self.assertEqual(len({item.manifest_path for item in free_writes}), 1)
            self.assertEqual(len({item.artifact_path for item in costly_writes}), 1)
            self.assertEqual(len({item.manifest_path for item in costly_writes}), 1)
            self.assertNotEqual(free_writes[0].artifact_path, costly_writes[0].artifact_path)
            for item, expected in zip(stored, inputs, strict=True):
                self.assertEqual(
                    store.inspect_reference_result(item.manifest_path).reference_result,
                    expected,
                )

    def test_relative_identity_is_root_independent_and_posix_canonical(self) -> None:
        with TemporaryDirectory() as first_directory, TemporaryDirectory() as second_directory:
            first = self._write(RunArtifactStore(Path(first_directory)))
            second = self._write(RunArtifactStore(Path(second_directory)))

        self.assertEqual(first, second)
        self.assertNotIn("\\", first.artifact_path)
        self.assertNotIn("\\", first.manifest_path)

    def test_rejects_unknown_schemas_and_duplicate_json_keys(self) -> None:
        with self.assertRaises(ValidationError):
            ReferenceResultEnvelope.model_validate(
                {
                    "schema_version": "reference-result-v2",
                    "kind": "reference_result",
                    "result": build_result(),
                }
            )
        with self.assertRaises(ValidationError):
            RunArtifactManifest.model_validate(
                {
                    "manifest_version": "run-artifact-manifest-v2",
                    "experiment_id": EXPERIMENT_ID,
                    "run_id": RUN_ID,
                    "artifact": {
                        "kind": "reference_result",
                        "uri": "x",
                        "content_hash": "f" * 64,
                        "schema_version": "reference-result-v1",
                    },
                    "runtime": RUNTIME,
                    "engine": ENGINE,
                    "dataset": DATASET,
                    "created_at": CREATED_AT,
                    "content_path": "x",
                }
            )
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            RunArtifactStore._loads_strict(b'{"kind":"a","kind":"b"}')

    @staticmethod
    def _write(store: RunArtifactStore, *, result=None, created_at=CREATED_AT):
        return store.write_reference_result(
            result or build_result(),
            experiment_id=EXPERIMENT_ID,
            run_id=RUN_ID,
            runtime=RUNTIME,
            engine=ENGINE,
            dataset=DATASET,
            created_at=created_at,
        )

    @staticmethod
    def _write_canonical_manifest(root: Path, manifest: RunArtifactManifest) -> Path:
        content = RunArtifactStore._serialize(manifest.model_dump(mode="python"))
        digest = hashlib.sha256(content).hexdigest()
        stamp = manifest.created_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        relative = (
            Path("run_manifests")
            / manifest.run_id
            / manifest.artifact.content_hash
            / f"{stamp}-{digest}.json"
        )
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return relative
