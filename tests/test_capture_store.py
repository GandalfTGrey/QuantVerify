from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from quantverify.core.exceptions import ReproducibilityError
from quantverify.data.capture import RawCapture
from quantverify.data.store import CaptureStore, DataLicenseProfile

LICENSE = DataLicenseProfile(
    profile_id="fixture-personal-research-v1",
    permitted_uses=("local_research", "automated_testing"),
    redistribution_allowed=False,
    terms_uri="https://example.test/terms",
)


def capture(*, symbol: str = "QQQ", captured_at: datetime | None = None) -> RawCapture:
    return RawCapture.from_records(
        provider="fixture",
        endpoint="daily",
        request={"symbol": symbol, "adjust": "raw"},
        records=[{"date": "2026-01-02", "close": "500", "native": "preserved"}],
        captured_at=captured_at or datetime(2026, 1, 2, 22, tzinfo=UTC),
        schema_version="fixture-daily-v1",
    )


class CaptureStoreTests(TestCase):
    def test_persists_and_replays_exact_capture_offline(self) -> None:
        original = capture()
        with TemporaryDirectory() as directory:
            store = CaptureStore(Path(directory))
            stored = store.write(
                original,
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=datetime(2026, 1, 2, 22, 1, tzinfo=UTC),
            )
            replayed = store.load(stored.manifest_path)
            content = json.loads((Path(directory) / stored.content_path).read_text())

        self.assertEqual(replayed.content_hash, original.content_hash)
        self.assertEqual(replayed.captured_at, original.captured_at)
        self.assertEqual(replayed.records[0]["native"], "preserved")
        self.assertEqual(content["request"], {"adjust": "raw", "symbol": "QQQ"})
        self.assertEqual(len(stored.manifest_hash), 64)
        self.assertEqual(stored.manifest.license_profile, LICENSE)
        with self.assertRaises(TypeError):
            replayed.records[0]["close"] = "999"  # type: ignore[index]
        with self.assertRaises(TypeError):
            stored.manifest.request["symbol"] = "DIA"  # type: ignore[index]

    def test_identical_content_reuses_object_but_keeps_observation_manifests(self) -> None:
        first = capture(captured_at=datetime(2026, 1, 2, 22, tzinfo=UTC))
        second = capture(captured_at=datetime(2026, 1, 3, 22, tzinfo=UTC))
        with TemporaryDirectory() as directory:
            store = CaptureStore(Path(directory))
            first_stored = store.write(
                first,
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=datetime(2026, 1, 2, 22, 1, tzinfo=UTC),
            )
            second_stored = store.write(
                second,
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=datetime(2026, 1, 3, 22, 1, tzinfo=UTC),
            )

        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(first_stored.content_path, second_stored.content_path)
        self.assertNotEqual(first_stored.manifest_path, second_stored.manifest_path)

    def test_request_semantics_produce_distinct_content_objects(self) -> None:
        with TemporaryDirectory() as directory:
            store = CaptureStore(Path(directory))
            qqq = store.write(
                capture(symbol="QQQ"),
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=datetime(2026, 1, 2, 22, 1, tzinfo=UTC),
            )
            dia = store.write(
                capture(symbol="DIA"),
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=datetime(2026, 1, 2, 22, 1, tzinfo=UTC),
            )

        self.assertNotEqual(qqq.content_path, dia.content_path)
        self.assertNotEqual(qqq.manifest.capture_hash, dia.manifest.capture_hash)

    def test_repeated_write_of_same_observation_is_idempotent(self) -> None:
        original = capture()
        with TemporaryDirectory() as directory:
            store = CaptureStore(Path(directory))
            first = store.write(
                original,
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=datetime(2026, 1, 2, 22, 1, tzinfo=UTC),
            )
            second = store.write(
                original,
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=datetime(2026, 1, 2, 22, 1, tzinfo=UTC),
            )

        self.assertEqual(first.manifest_path, second.manifest_path)
        self.assertEqual(first.manifest.stored_at, second.manifest.stored_at)

    def test_rejects_tampered_manifest_during_replay(self) -> None:
        with TemporaryDirectory() as directory:
            store = CaptureStore(Path(directory))
            stored = store.write(
                capture(),
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=datetime(2026, 1, 2, 22, 1, tzinfo=UTC),
            )
            manifest_path = Path(directory) / stored.manifest_path
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload["adapter_version"] = "tampered-adapter"
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ReproducibilityError, "manifest content hash"):
                store.load(stored.manifest_path)

    def test_rejects_tampered_content_during_replay(self) -> None:
        with TemporaryDirectory() as directory:
            store = CaptureStore(Path(directory))
            stored = store.write(
                capture(),
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=datetime(2026, 1, 2, 22, 1, tzinfo=UTC),
            )
            (Path(directory) / stored.content_path).write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(ReproducibilityError, "does not match manifest hash"):
                store.load(stored.manifest_path)

    def test_rejects_paths_outside_store_root(self) -> None:
        with TemporaryDirectory() as directory:
            store = CaptureStore(Path(directory))
            with self.assertRaisesRegex(ReproducibilityError, "must be relative"):
                store.load("../outside.json")

    def test_rejects_credentials_before_any_capture_is_persisted(self) -> None:
        unsafe_capture = RawCapture.from_records(
            provider="fixture",
            endpoint="daily",
            request={"symbol": "QQQ", "auth": {"api-key": "do-not-store"}},
            records=[{"close": "500"}],
            captured_at=datetime(2026, 1, 2, 22, tzinfo=UTC),
        )
        with TemporaryDirectory() as directory:
            store = CaptureStore(Path(directory))
            with self.assertRaisesRegex(
                ReproducibilityError, "prohibited credential field: request.auth.api-key"
            ):
                store.write(
                    unsafe_capture,
                    adapter_version="fixture-adapter-1.0.0",
                    license_profile=LICENSE,
                )
            self.assertFalse((Path(directory) / "captures").exists())
