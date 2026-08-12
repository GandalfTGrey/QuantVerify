from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from pydantic import ValidationError

from quantverify.core.exceptions import ReproducibilityError
from quantverify.data.capture import RawCapture
from quantverify.data.store import (
    CaptureManifest,
    CaptureStore,
    DataLicenseProfile,
    VerifiedCapture,
)

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


def assert_exception_chain_excludes(test: TestCase, error: BaseException, marker: str) -> None:
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        test.assertNotIn(marker, str(current))
        current = current.__cause__ or current.__context__


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
            "manifest hash does not match its manifest",
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
            "manifest hash does not match its manifest",
        ):
            VerifiedCapture(
                capture=capture(),
                manifest=stored.manifest,
                manifest_hash="f" * 64,
                content_path=stored.content_path,
                manifest_path=stored.manifest_path,
            )

    def test_verified_capture_rejects_self_consistent_arbitrary_manifest_hash(self) -> None:
        with TemporaryDirectory() as directory:
            stored = CaptureStore(Path(directory)).write(
                capture(),
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=STORED_AT,
            )
        arbitrary_hash = "f" * 64
        arbitrary_path = str(
            Path(stored.manifest_path).with_name(
                f"{CAPTURED_AT.strftime('%Y%m%dT%H%M%S%fZ')}-{arbitrary_hash}.json"
            )
        )

        with self.assertRaisesRegex(
            ValidationError, "manifest hash does not match its manifest"
        ):
            VerifiedCapture(
                capture=capture(),
                manifest=stored.manifest,
                manifest_hash=arbitrary_hash,
                content_path=stored.content_path,
                manifest_path=arbitrary_path,
            )

    def test_verified_capture_rejects_captured_at_mismatch(self) -> None:
        original = capture(captured_at=CAPTURED_AT + timedelta(minutes=1))
        with TemporaryDirectory() as directory:
            stored = CaptureStore(Path(directory)).write(
                capture(),
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=STORED_AT,
            )

        with self.assertRaisesRegex(ValidationError, "captured_at"):
            VerifiedCapture(
                capture=original,
                manifest=stored.manifest,
                manifest_hash=stored.manifest_hash,
                content_path=stored.content_path,
                manifest_path=stored.manifest_path,
            )

    def test_verified_capture_revalidates_unsafe_nested_models(self) -> None:
        with TemporaryDirectory() as directory:
            stored = CaptureStore(Path(directory)).write(
                capture(),
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=STORED_AT,
            )
        unsafe_license = LICENSE.model_copy(update={"permitted_uses": ()})
        unsafe_manifest = stored.manifest.model_copy(
            update={"license_profile": unsafe_license}
        )
        unsafe_capture = capture().model_copy(update={"request": ["invalid"]})

        for capture_input, manifest_input in (
            (capture(), unsafe_manifest),
            (unsafe_capture, stored.manifest),
        ):
            with (
                self.subTest(capture=capture_input, manifest=manifest_input),
                self.assertRaises((ValidationError, TypeError)),
            ):
                VerifiedCapture(
                    capture=capture_input,
                    manifest=manifest_input,
                    manifest_hash=stored.manifest_hash,
                    content_path=stored.content_path,
                    manifest_path=stored.manifest_path,
                )

    def test_direct_verified_capture_rejects_self_consistent_credentials(self) -> None:
        secret_marker = "verified-direct-secret-marker"
        unsafe_capture = RawCapture.from_records(
            provider="fixture",
            endpoint="daily",
            request={"api_key": secret_marker},
            records=[{"date": "2026-01-02", "close": "500"}],
            captured_at=CAPTURED_AT,
            schema_version="fixture-daily-v1",
        )
        content_hash = unsafe_capture.content_hash
        content_relative = (
            Path("captures") / "fixture" / content_hash[:2] / f"{content_hash}.json"
        )
        manifest = CaptureManifest(
            capture_hash=content_hash,
            provider="fixture",
            endpoint="daily",
            request={"api_key": secret_marker},
            capture_schema_version="fixture-daily-v1",
            adapter_version="fixture-adapter-1.0.0",
            captured_at=CAPTURED_AT,
            stored_at=STORED_AT,
            record_count=1,
            content_path=content_relative.as_posix(),
            license_profile=LICENSE,
        )
        manifest_bytes = canonical_json(manifest.model_dump(mode="json"))
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        manifest_relative = (
            Path("manifests")
            / "fixture"
            / content_hash
            / f"{CAPTURED_AT.strftime('%Y%m%dT%H%M%S%fZ')}-{manifest_hash}.json"
        )

        with self.assertRaisesRegex(
            ValidationError, "verified capture contains prohibited credential field"
        ) as raised:
            VerifiedCapture(
                capture=unsafe_capture,
                manifest=manifest,
                manifest_hash=manifest_hash,
                content_path=content_relative.as_posix(),
                manifest_path=manifest_relative.as_posix(),
            )

        assert_exception_chain_excludes(self, raised.exception, secret_marker)

    def test_replay_rejects_fully_rehashed_credential_capture(self) -> None:
        secret_marker = "verified-replay-secret-marker"
        unsafe_capture = RawCapture.from_records(
            provider="fixture",
            endpoint="daily",
            request={"headers": [{"api_key": secret_marker}]},
            records=[{"date": "2026-01-02", "close": "500"}],
            captured_at=CAPTURED_AT,
            schema_version="fixture-daily-v1",
        )
        content = unsafe_capture.content_bytes()
        content_hash = hashlib.sha256(content).hexdigest()
        content_relative = (
            Path("captures") / "fixture" / content_hash[:2] / f"{content_hash}.json"
        )
        manifest = CaptureManifest(
            capture_hash=content_hash,
            provider="fixture",
            endpoint="daily",
            request={"headers": [{"api_key": secret_marker}]},
            capture_schema_version="fixture-daily-v1",
            adapter_version="fixture-adapter-1.0.0",
            captured_at=CAPTURED_AT,
            stored_at=STORED_AT,
            record_count=1,
            content_path=content_relative.as_posix(),
            license_profile=LICENSE,
        )
        manifest_bytes = canonical_json(manifest.model_dump(mode="json"))
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        manifest_relative = (
            Path("manifests")
            / "fixture"
            / content_hash
            / f"{CAPTURED_AT.strftime('%Y%m%dT%H%M%S%fZ')}-{manifest_hash}.json"
        )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_bytes(root, content_relative, content)
            write_bytes(root, manifest_relative, manifest_bytes)
            with self.assertRaisesRegex(
                ReproducibilityError, "Verified capture failed integrity validation"
            ) as raised:
                CaptureStore(root).load_verified(manifest_relative)

            assert_exception_chain_excludes(self, raised.exception, secret_marker)

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

    def test_manifest_parse_failure_never_leaks_persisted_secret_input(self) -> None:
        secret_marker = "persisted-manifest-secret-marker"
        hostile_documents = (
            f'{{"token.{secret_marker}":1,"token.{secret_marker}":2}}'.encode(),
            f'{{"field":"{secret_marker}"'.encode(),
        )
        for hostile in hostile_documents:
            with self.subTest(hostile=hostile), TemporaryDirectory() as directory:
                root = Path(directory)
                manifest_hash = hashlib.sha256(hostile).hexdigest()
                relative = Path("manifests") / f"hostile-{manifest_hash}.json"
                write_bytes(root, relative, hostile)

                with self.assertRaisesRegex(
                    ReproducibilityError, "Invalid capture manifest"
                ) as raised:
                    CaptureStore(root).load_verified(relative)

                assert_exception_chain_excludes(self, raised.exception, secret_marker)

    def test_rejects_rehashed_noncanonical_manifest_bytes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = CaptureStore(root)
            stored = store.write(
                capture(),
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=STORED_AT,
            )
            payload = stored.manifest.model_dump(mode="json")
            noncanonical = json.dumps(payload, indent=2, sort_keys=False).encode()
            manifest_hash = hashlib.sha256(noncanonical).hexdigest()
            relative = Path(stored.manifest_path).with_name(
                f"{CAPTURED_AT.strftime('%Y%m%dT%H%M%S%fZ')}-{manifest_hash}.json"
            )
            write_bytes(root, relative, noncanonical)

            with self.assertRaisesRegex(
                ReproducibilityError, "Verified capture failed integrity validation"
            ):
                store.load_verified(relative)

    def test_replay_rejects_fifo_manifest_without_blocking(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fifo = root / "manifest.json"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(ReproducibilityError, "Invalid capture manifest"):
                CaptureStore(root).load_verified("manifest.json")

    def test_replay_rejects_fifo_content_without_blocking(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = CaptureStore(root)
            stored = store.write(
                capture(),
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=STORED_AT,
            )
            content_path = root / stored.content_path
            content_path.unlink()
            os.mkfifo(content_path)

            with self.assertRaisesRegex(ReproducibilityError, "Capture content is unavailable"):
                store.load_verified(stored.manifest_path)

    def test_replay_wraps_manifest_descriptor_close_failure(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = CaptureStore(root)
            stored = store.write(
                capture(),
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=STORED_AT,
            )
            real_close = os.close

            def close_then_fail(descriptor: int) -> None:
                real_close(descriptor)
                raise OSError("simulated close failure")

            with (
                patch("quantverify.data.store.os.close", side_effect=close_then_fail),
                self.assertRaisesRegex(ReproducibilityError, "Invalid capture manifest"),
            ):
                store.load_verified(stored.manifest_path)

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

    def test_content_parse_failure_never_leaks_persisted_secret_input(self) -> None:
        secret_marker = "persisted-content-secret-marker"
        hostile_content = f'{{"field":"{secret_marker}"'.encode()
        content_hash = hashlib.sha256(hostile_content).hexdigest()
        content_relative = (
            Path("captures") / "fixture" / content_hash[:2] / f"{content_hash}.json"
        )
        manifest = CaptureManifest(
            capture_hash=content_hash,
            provider="fixture",
            endpoint="daily",
            request={"symbol": "QQQ"},
            capture_schema_version="fixture-daily-v1",
            adapter_version="fixture-adapter-1.0.0",
            captured_at=CAPTURED_AT,
            stored_at=STORED_AT,
            record_count=1,
            content_path=content_relative.as_posix(),
            license_profile=LICENSE,
        )
        manifest_bytes = canonical_json(manifest.model_dump(mode="json"))
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        manifest_relative = (
            Path("manifests")
            / "fixture"
            / content_hash
            / f"{CAPTURED_AT.strftime('%Y%m%dT%H%M%S%fZ')}-{manifest_hash}.json"
        )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_bytes(root, content_relative, hostile_content)
            write_bytes(root, manifest_relative, manifest_bytes)
            with self.assertRaisesRegex(
                ReproducibilityError, "Capture content cannot be reconstructed"
            ) as raised:
                CaptureStore(root).load_verified(manifest_relative)

            assert_exception_chain_excludes(self, raised.exception, secret_marker)

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

    def test_replay_preserves_legacy_canonical_non_utc_manifest(self) -> None:
        singapore = timezone(timedelta(hours=8))
        legacy_capture = capture(captured_at=CAPTURED_AT.astimezone(singapore))
        content = legacy_capture.content_bytes()
        content_hash = hashlib.sha256(content).hexdigest()
        content_relative = (
            Path("captures") / "fixture" / content_hash[:2] / f"{content_hash}.json"
        )
        legacy_manifest = CaptureManifest(
            capture_hash=content_hash,
            provider=legacy_capture.provider,
            endpoint=legacy_capture.endpoint,
            request=legacy_capture.request,
            capture_schema_version=legacy_capture.schema_version,
            adapter_version="fixture-adapter-1.0.0",
            captured_at=CAPTURED_AT.astimezone(singapore),
            stored_at=STORED_AT.astimezone(singapore),
            record_count=len(legacy_capture.records),
            content_path=content_relative.as_posix(),
            license_profile=LICENSE,
        )
        manifest_bytes = canonical_json(legacy_manifest.model_dump(mode="json"))
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        stamp = CAPTURED_AT.strftime("%Y%m%dT%H%M%S%fZ")
        manifest_relative = (
            Path("manifests")
            / "fixture"
            / content_hash
            / f"{stamp}-{manifest_hash}.json"
        )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_bytes(root, content_relative, content)
            write_bytes(root, manifest_relative, manifest_bytes)
            store = CaptureStore(root)
            verified = store.load_verified(manifest_relative)
            compatibility_capture = store.load(manifest_relative)

        self.assertEqual(verified.manifest_hash, manifest_hash)
        self.assertEqual(verified.manifest.captured_at.utcoffset(), timedelta(hours=8))
        self.assertEqual(verified.manifest.stored_at.utcoffset(), timedelta(hours=8))
        self.assertEqual(verified.capture, compatibility_capture)
