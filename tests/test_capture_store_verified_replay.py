from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from pydantic import ValidationError

from quantverify.core.exceptions import ReproducibilityError
from quantverify.data.capture import RawCapture
from quantverify.data.store import CaptureStore, DataLicenseProfile, VerifiedCapture

LICENSE = DataLicenseProfile(
    profile_id="fixture-personal-research-v1",
    permitted_uses=("local_research", "automated_testing"),
    redistribution_allowed=False,
    terms_uri="https://example.test/terms",
)
CAPTURED_AT = datetime(2026, 1, 2, 22, tzinfo=UTC)
STORED_AT = datetime(2026, 1, 2, 22, 1, tzinfo=UTC)


def capture(
    *,
    captured_at: datetime = CAPTURED_AT,
    close: str = "500",
) -> RawCapture:
    return RawCapture.from_records(
        provider="fixture",
        endpoint="daily",
        request={"symbol": "QQQ", "adjust": "raw"},
        records=[{"date": "2026-01-02", "close": close, "native": "preserved"}],
        captured_at=captured_at,
        schema_version="fixture-daily-v1",
    )


def canonical_json(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def write_bytes(root: Path, relative: Path, content: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class CaptureStoreVerifiedReplayTests(TestCase):
    def test_load_verified_preserves_manifest_hash_license_and_paths(self) -> None:
        original = capture()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = CaptureStore(root)
            stored = store.write(
                original,
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=STORED_AT,
            )

            verified = store.load_verified(stored.manifest_path)
            compatibility_capture = store.load(stored.manifest_path)

        self.assertEqual(verified.capture.content_hash, original.content_hash)
        self.assertEqual(verified.manifest, stored.manifest)
        self.assertEqual(verified.manifest_hash, stored.manifest_hash)
        self.assertEqual(verified.content_path, stored.content_path)
        self.assertEqual(verified.manifest_path, stored.manifest_path)
        self.assertEqual(verified.manifest.license_profile, LICENSE)
        self.assertEqual(verified.manifest.adapter_version, "fixture-adapter-1.0.0")
        self.assertEqual(compatibility_capture, verified.capture)

    def test_verified_capture_rejects_manual_lineage_mismatch(self) -> None:
        with TemporaryDirectory() as directory:
            stored = CaptureStore(Path(directory)).write(
                capture(),
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=STORED_AT,
            )

        with self.assertRaisesRegex(ValidationError, "verified capture lineage mismatch"):
            VerifiedCapture(
                capture=capture(close="501"),
                manifest=stored.manifest,
                manifest_hash=stored.manifest_hash,
                content_path=stored.content_path,
                manifest_path=stored.manifest_path,
            )

    def test_verified_capture_rejects_noncanonical_content_path(self) -> None:
        with TemporaryDirectory() as directory:
            stored = CaptureStore(Path(directory)).write(
                capture(),
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=STORED_AT,
            )
        wrong_path = "captures/fixture/not-canonical.json"
        manipulated_manifest = stored.manifest.model_copy(
            update={"content_path": wrong_path}
        )

        with self.assertRaisesRegex(
            ValidationError,
            "verified capture content path is not canonical",
        ):
            VerifiedCapture(
                capture=capture(),
                manifest=manipulated_manifest,
                manifest_hash=stored.manifest_hash,
                content_path=wrong_path,
                manifest_path=stored.manifest_path,
            )

    def test_verified_capture_rejects_manifest_hash_path_mismatch(self) -> None:
        with TemporaryDirectory() as directory:
            stored = CaptureStore(Path(directory)).write(
                capture(),
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=STORED_AT,
            )

        with self.assertRaisesRegex(
            ValidationError,
            "verified capture manifest path is not canonical",
        ):
            VerifiedCapture(
                capture=capture(),
                manifest=stored.manifest,
                manifest_hash="f" * 64,
                content_path=stored.content_path,
                manifest_path=stored.manifest_path,
            )

    def test_rejects_duplicate_manifest_key_even_with_matching_filename_hash(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = CaptureStore(root)
            stored = store.write(
                capture(),
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=STORED_AT,
            )
            original_bytes = (root / stored.manifest_path).read_bytes()
            duplicate_bytes = b'{"provider":"fixture",' + original_bytes[1:]
            duplicate_hash = hashlib.sha256(duplicate_bytes).hexdigest()
            stamp = CAPTURED_AT.strftime("%Y%m%dT%H%M%S%fZ")
            duplicate_relative = (
                Path("manifests")
                / "fixture"
                / stored.manifest.capture_hash
                / f"{stamp}-{duplicate_hash}.json"
            )
            write_bytes(root, duplicate_relative, duplicate_bytes)

            with self.assertRaisesRegex(ReproducibilityError, "Invalid capture manifest"):
                store.load_verified(duplicate_relative)

    def test_rejects_duplicate_content_key_after_hash_and_manifest_are_consistent(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = CaptureStore(root)
            stored = store.write(
                capture(),
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=STORED_AT,
            )
            original_content = (root / stored.content_path).read_bytes()
            duplicate_content = b'{"provider":"fixture",' + original_content[1:]
            duplicate_content_hash = hashlib.sha256(duplicate_content).hexdigest()
            content_relative = (
                Path("captures")
                / "fixture"
                / duplicate_content_hash[:2]
                / f"{duplicate_content_hash}.json"
            )
            write_bytes(root, content_relative, duplicate_content)

            manifest_payload = stored.manifest.model_dump(mode="json")
            manifest_payload["capture_hash"] = duplicate_content_hash
            manifest_payload["content_path"] = content_relative.as_posix()
            manifest_bytes = canonical_json(manifest_payload)
            manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
            stamp = CAPTURED_AT.strftime("%Y%m%dT%H%M%S%fZ")
            manifest_relative = (
                Path("manifests")
                / "fixture"
                / duplicate_content_hash
                / f"{stamp}-{manifest_hash}.json"
            )
            write_bytes(root, manifest_relative, manifest_bytes)

            with self.assertRaisesRegex(
                ReproducibilityError,
                "Capture content cannot be reconstructed",
            ):
                store.load_verified(manifest_relative)

    def test_rejects_valid_manifest_bytes_from_noncanonical_directory(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = CaptureStore(root)
            stored = store.write(
                capture(),
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=STORED_AT,
            )
            manifest_bytes = (root / stored.manifest_path).read_bytes()
            filename = Path(stored.manifest_path).name
            wrong_relative = Path("manifests") / "fixture" / "wrong" / filename
            write_bytes(root, wrong_relative, manifest_bytes)

            with self.assertRaisesRegex(
                ReproducibilityError,
                "Capture manifest path is not canonical",
            ):
                store.load_verified(wrong_relative)

    def test_rejects_manifest_with_noncanonical_content_path(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = CaptureStore(root)
            stored = store.write(
                capture(),
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=STORED_AT,
            )
            manifest_payload = stored.manifest.model_dump(mode="json")
            manifest_payload["content_path"] = "captures/fixture/not-canonical.json"
            manifest_bytes = canonical_json(manifest_payload)
            manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
            stamp = CAPTURED_AT.strftime("%Y%m%dT%H%M%S%fZ")
            manifest_relative = (
                Path("manifests")
                / "fixture"
                / stored.manifest.capture_hash
                / f"{stamp}-{manifest_hash}.json"
            )
            write_bytes(root, manifest_relative, manifest_bytes)

            with self.assertRaisesRegex(
                ReproducibilityError,
                "Capture manifest content path is not canonical",
            ):
                store.load_verified(manifest_relative)

    def test_equivalent_timezone_instants_produce_identical_manifest_identity(self) -> None:
        singapore = timezone(timedelta(hours=8))
        captured_sg = CAPTURED_AT.astimezone(singapore)
        stored_sg = STORED_AT.astimezone(singapore)
        first_capture = capture(captured_at=CAPTURED_AT)
        second_capture = capture(captured_at=captured_sg)

        with TemporaryDirectory() as directory:
            store = CaptureStore(Path(directory))
            first = store.write(
                first_capture,
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=STORED_AT,
            )
            second = store.write(
                second_capture,
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=stored_sg,
            )

        self.assertEqual(first_capture.content_hash, second_capture.content_hash)
        self.assertEqual(first.manifest_hash, second.manifest_hash)
        self.assertEqual(first.manifest_path, second.manifest_path)
        self.assertEqual(first.manifest.captured_at, CAPTURED_AT)
        self.assertEqual(first.manifest.stored_at, STORED_AT)
        self.assertEqual(second.manifest.captured_at, CAPTURED_AT)
        self.assertEqual(second.manifest.stored_at, STORED_AT)
