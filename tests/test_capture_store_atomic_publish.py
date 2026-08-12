from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest import TestCase
from unittest.mock import patch

from quantverify.core.exceptions import ReproducibilityError
from quantverify.data.capture import RawCapture
from quantverify.data.store import CaptureStore, DataLicenseProfile, StoredCapture

LICENSE = DataLicenseProfile(
    profile_id="fixture-personal-research-v1",
    permitted_uses=("local_research", "automated_testing"),
    redistribution_allowed=False,
)
STORED_AT = datetime(2026, 1, 2, 22, 1, tzinfo=UTC)


def capture() -> RawCapture:
    return RawCapture.from_records(
        provider="fixture",
        endpoint="daily",
        request={"symbol": "QQQ", "adjust": "raw"},
        records=[{"date": "2026-01-02", "close": "500"}],
        captured_at=datetime(2026, 1, 2, 22, tzinfo=UTC),
        schema_version="fixture-daily-v1",
    )


def temporary_objects(root: Path) -> list[Path]:
    return list(root.rglob(".quantverify-*"))


class CaptureStoreAtomicPublishTests(TestCase):
    def test_two_writers_publish_identical_capture_without_false_collision(self) -> None:
        original = capture()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = CaptureStore(root)
            barrier = Barrier(2)
            real_link = os.link

            def synchronized_link(source: str | Path, destination: str | Path) -> None:
                if "captures" in Path(destination).parts:
                    barrier.wait(timeout=5)
                real_link(source, destination)

            def write_once() -> StoredCapture:
                return store.write(
                    original,
                    adapter_version="fixture-adapter-1.0.0",
                    license_profile=LICENSE,
                    stored_at=STORED_AT,
                )

            with (
                patch("quantverify.data.store.os.link", side_effect=synchronized_link),
                ThreadPoolExecutor(max_workers=2) as executor,
            ):
                first_future = executor.submit(write_once)
                second_future = executor.submit(write_once)
                first = first_future.result(timeout=10)
                second = second_future.result(timeout=10)

            self.assertEqual(first.content_path, second.content_path)
            self.assertEqual(first.manifest_path, second.manifest_path)
            self.assertEqual((root / first.content_path).read_bytes(), original.content_bytes())
            self.assertTrue((root / first.manifest_path).is_file())
            self.assertEqual(temporary_objects(root), [])

    def test_publish_failure_never_exposes_partial_canonical_object(self) -> None:
        original = capture()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = CaptureStore(root)
            expected_path = (
                root
                / "captures"
                / original.provider
                / original.content_hash[:2]
                / f"{original.content_hash}.json"
            )

            with (
                patch(
                    "quantverify.data.store.os.link",
                    side_effect=OSError("simulated publish failure"),
                ),
                self.assertRaisesRegex(
                    ReproducibilityError,
                    "Atomic capture content publication failed",
                ),
            ):
                store.write(
                    original,
                    adapter_version="fixture-adapter-1.0.0",
                    license_profile=LICENSE,
                    stored_at=STORED_AT,
                )

            self.assertFalse(expected_path.exists())
            self.assertEqual(temporary_objects(root), [])
            self.assertFalse((root / "manifests").exists())

    def test_preexisting_partial_canonical_object_is_detected_not_overwritten(self) -> None:
        original = capture()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = CaptureStore(root)
            canonical_path = (
                root
                / "captures"
                / original.provider
                / original.content_hash[:2]
                / f"{original.content_hash}.json"
            )
            canonical_path.parent.mkdir(parents=True)
            canonical_path.write_bytes(b"legacy-partial-object")

            with self.assertRaisesRegex(
                ReproducibilityError,
                "Immutable capture content collision",
            ):
                store.write(
                    original,
                    adapter_version="fixture-adapter-1.0.0",
                    license_profile=LICENSE,
                    stored_at=STORED_AT,
                )

            self.assertEqual(canonical_path.read_bytes(), b"legacy-partial-object")
            self.assertEqual(temporary_objects(root), [])
            self.assertFalse((root / "manifests").exists())
