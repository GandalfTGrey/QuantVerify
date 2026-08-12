import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from pydantic import ValidationError

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
