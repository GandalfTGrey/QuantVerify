from __future__ import annotations

import os
import stat
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
        records=({"date": "2026-01-02", "close": "500"},),
        captured_at=datetime(2026, 1, 2, 22, tzinfo=UTC),
        schema_version="fixture-daily-v1",
    )


def write(store: CaptureStore, original: RawCapture | None = None) -> StoredCapture:
    return store.write(
        original or capture(),
        adapter_version="fixture-adapter-1.0.0",
        license_profile=LICENSE,
        stored_at=STORED_AT,
    )


def temporary_objects(root: Path) -> tuple[Path, ...]:
    return tuple(root.rglob(".quantverify-*"))


class CaptureStoreAtomicPublishTests(TestCase):
    def test_concurrent_identical_writers_publish_only_complete_objects(self) -> None:
        original = capture()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = CaptureStore(root)
            barrier = Barrier(8)

            def write_together() -> StoredCapture:
                barrier.wait(timeout=10)
                return write(store, original)

            with ThreadPoolExecutor(max_workers=8) as executor:
                stored = tuple(executor.map(lambda _: write_together(), range(8)))

            first = stored[0]
            self.assertTrue(all(item == first for item in stored))
            self.assertEqual((root / first.content_path).read_bytes(), original.content_bytes())
            self.assertTrue((root / first.manifest_path).is_file())
            self.assertEqual(temporary_objects(root), ())

    def test_link_failure_never_exposes_a_partial_canonical_object(self) -> None:
        original = capture()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            expected = (
                root
                / "captures"
                / original.provider
                / original.content_hash[:2]
                / f"{original.content_hash}.json"
            )
            with (
                patch("quantverify.data.store.os.link", side_effect=OSError("failure")),
                self.assertRaisesRegex(
                    ReproducibilityError, "Atomic capture content publication failed"
                ),
            ):
                write(CaptureStore(root), original)

            self.assertFalse(expected.exists())
            self.assertEqual(temporary_objects(root), ())
            self.assertFalse((root / "manifests").exists())

    def test_file_sync_failure_never_exposes_a_canonical_object(self) -> None:
        original = capture()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch("quantverify.data.store.os.fsync", side_effect=OSError("failure")),
                self.assertRaisesRegex(
                    ReproducibilityError, "Atomic capture content staging failed"
                ),
            ):
                write(CaptureStore(root), original)

            self.assertEqual(tuple(root.rglob("*.json")), ())
            self.assertEqual(temporary_objects(root), ())

    def test_fdopen_failure_closes_the_raw_descriptor(self) -> None:
        descriptor = 456
        with TemporaryDirectory() as directory:
            with (
                patch(
                    "quantverify.data.store.tempfile.mkstemp",
                    return_value=(descriptor, str(Path(directory) / ".quantverify-test")),
                ),
                patch("quantverify.data.store.os.fdopen", side_effect=OSError("failure")),
                patch("quantverify.data.store.os.close") as close,
                self.assertRaisesRegex(
                    ReproducibilityError, "Atomic capture content staging failed"
                ),
            ):
                write(CaptureStore(Path(directory)))

            close_calls = tuple((call.args, call.kwargs) for call in close.mock_calls)
            self.assertIn(((descriptor,), {}), close_calls)

    def test_directory_sync_failure_never_exposes_partial_bytes(self) -> None:
        original = capture()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(
                    CaptureStore,
                    "_fsync_directory_chain",
                    side_effect=OSError("failure"),
                ),
                self.assertRaisesRegex(
                    ReproducibilityError, "Atomic capture content directory sync failed"
                ),
            ):
                write(CaptureStore(root), original)

            capture_files = tuple((root / "captures").rglob("*.json"))
            self.assertEqual(len(capture_files), 1)
            self.assertEqual(capture_files[0].read_bytes(), original.content_bytes())
            self.assertEqual(temporary_objects(root), ())
            self.assertFalse((root / "manifests").exists())

            # A retry must re-run directory fsync even though the complete hard
            # link is already present from the failed attempt.
            with patch.object(CaptureStore, "_fsync_directory_chain") as directory_sync:
                stored = write(CaptureStore(root), original)
            self.assertTrue((root / stored.manifest_path).is_file())
            self.assertGreaterEqual(directory_sync.call_count, 4)

    def test_preexisting_partial_object_is_detected_and_not_overwritten(self) -> None:
        original = capture()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            canonical = (
                root
                / "captures"
                / original.provider
                / original.content_hash[:2]
                / f"{original.content_hash}.json"
            )
            canonical.parent.mkdir(parents=True)
            canonical.write_bytes(b"legacy-partial-object")

            with self.assertRaisesRegex(
                ReproducibilityError, "Immutable capture content collision"
            ):
                write(CaptureStore(root), original)

            self.assertEqual(canonical.read_bytes(), b"legacy-partial-object")
            self.assertEqual(temporary_objects(root), ())

    def test_preexisting_fifo_is_rejected_without_blocking_or_overwrite(self) -> None:
        original = capture()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            canonical = (
                root
                / "captures"
                / original.provider
                / original.content_hash[:2]
                / f"{original.content_hash}.json"
            )
            canonical.parent.mkdir(parents=True)
            os.mkfifo(canonical)

            with self.assertRaisesRegex(
                ReproducibilityError, "Immutable capture content collision"
            ):
                write(CaptureStore(root), original)

            self.assertTrue(stat.S_ISFIFO(canonical.stat(follow_symlinks=False).st_mode))
            self.assertEqual(temporary_objects(root), ())
            self.assertFalse((root / "manifests").exists())

    def test_preexisting_directory_or_internal_symlink_is_rejected(self) -> None:
        original = capture()
        for hostile_kind in ("directory", "symlink"):
            with self.subTest(hostile_kind=hostile_kind), TemporaryDirectory() as directory:
                root = Path(directory)
                canonical = (
                    root
                    / "captures"
                    / original.provider
                    / original.content_hash[:2]
                    / f"{original.content_hash}.json"
                )
                canonical.parent.mkdir(parents=True)
                if hostile_kind == "directory":
                    canonical.mkdir()
                else:
                    internal_target = root / "same-content.json"
                    internal_target.write_bytes(original.content_bytes())
                    canonical.symlink_to(internal_target)

                with self.assertRaisesRegex(
                    ReproducibilityError,
                    "Immutable capture content collision|contains a symbolic link",
                ):
                    write(CaptureStore(root), original)

                self.assertEqual(temporary_objects(root), ())

    def test_staging_setup_failure_is_wrapped_and_writes_no_object(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch("quantverify.data.store.tempfile.mkstemp", side_effect=OSError("failure")),
                self.assertRaisesRegex(
                    ReproducibilityError, "Atomic capture content staging failed"
                ),
            ):
                write(CaptureStore(root))

            self.assertEqual(tuple(root.rglob("*.json")), ())

    def test_temporary_cleanup_failure_is_wrapped_after_complete_publication(self) -> None:
        original = capture()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            real_unlink = Path.unlink

            def fail_for_temporary(path: Path, *, missing_ok: bool = False) -> None:
                if path.name.startswith(".quantverify-"):
                    raise OSError("failure")
                real_unlink(path, missing_ok=missing_ok)

            with (
                patch.object(Path, "unlink", fail_for_temporary),
                self.assertRaisesRegex(
                    ReproducibilityError, "staging cleanup failed"
                ),
            ):
                write(CaptureStore(root), original)

            canonical = tuple((root / "captures").rglob("*.json"))
            self.assertEqual(len(canonical), 1)
            self.assertEqual(canonical[0].read_bytes(), original.content_bytes())
            self.assertFalse((root / "manifests").exists())

    def test_cleanup_failure_does_not_mask_primary_publication_failure(self) -> None:
        with TemporaryDirectory() as directory:
            def fail_unlink(path: Path, *, missing_ok: bool = False) -> None:
                raise OSError(f"cannot unlink {path.name}; missing_ok={missing_ok}")

            with (
                patch("quantverify.data.store.os.link", side_effect=OSError("link failure")),
                patch.object(Path, "unlink", fail_unlink),
                self.assertRaisesRegex(
                    ReproducibilityError, "Atomic capture content publication failed"
                ) as raised,
            ):
                write(CaptureStore(Path(directory)))

            self.assertTrue(
                any("staging cleanup failed" in note for note in raised.exception.__notes__)
            )

    def test_staging_unlink_is_followed_by_directory_chain_sync(self) -> None:
        with TemporaryDirectory() as directory:
            with patch.object(CaptureStore, "_fsync_directory_chain") as sync:
                write(CaptureStore(Path(directory)))

            # Content and manifest each sync once after link and once after
            # removing the temporary directory entry.
            self.assertEqual(sync.call_count, 4)

    def test_existing_unreadable_object_fails_closed(self) -> None:
        original = capture()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = CaptureStore(root)
            first = write(store, original)
            real_open = os.open
            expected_content = (root / first.content_path).resolve()

            def fail_for_canonical(
                path: str | bytes | os.PathLike[str], flags: int, mode: int = 0o777
            ) -> int:
                if Path(path) == expected_content:
                    raise OSError("unreadable")
                return real_open(path, flags, mode)

            with (
                patch("quantverify.data.store.os.open", fail_for_canonical),
                self.assertRaisesRegex(
                    ReproducibilityError, "Immutable capture content collision"
                ),
            ):
                write(store, original)

            self.assertEqual(temporary_objects(root), ())

    def test_existing_verification_close_failure_uses_typed_error(self) -> None:
        original = capture()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = CaptureStore(root)
            write(store, original)
            real_close = os.close
            canonical_descriptor: int | None = None
            real_open = os.open

            def remember_canonical(
                path: str | bytes | os.PathLike[str], flags: int, mode: int = 0o777
            ) -> int:
                nonlocal canonical_descriptor
                descriptor = real_open(path, flags, mode)
                if Path(path).name == f"{original.content_hash}.json":
                    canonical_descriptor = descriptor
                return descriptor

            def fail_for_canonical(descriptor: int) -> None:
                if descriptor == canonical_descriptor:
                    real_close(descriptor)
                    raise OSError("close failure")
                real_close(descriptor)

            with (
                patch("quantverify.data.store.os.open", remember_canonical),
                patch("quantverify.data.store.os.close", fail_for_canonical),
                self.assertRaisesRegex(
                    ReproducibilityError, "Immutable capture content collision"
                ),
            ):
                write(store, original)

            self.assertEqual(temporary_objects(root), ())

    def test_directory_fsync_closes_the_descriptor_on_failure(self) -> None:
        with TemporaryDirectory() as directory:
            descriptor = 123
            with (
                patch("quantverify.data.store.os.open", return_value=descriptor),
                patch("quantverify.data.store.os.fsync", side_effect=OSError("failure")),
                patch("quantverify.data.store.os.close") as close,
                self.assertRaises(OSError),
            ):
                CaptureStore._fsync_directory(Path(directory))

            close.assert_called_once_with(descriptor)

    def test_directory_chain_syncs_leaf_ancestors_and_store_root(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            leaf = root / "captures" / "fixture" / "ab"
            leaf.mkdir(parents=True)
            with patch.object(CaptureStore, "_fsync_directory") as sync:
                CaptureStore(root)._fsync_directory_chain(leaf)

            self.assertEqual(
                tuple(call.args[0] for call in sync.call_args_list),
                (leaf, leaf.parent, leaf.parent.parent, root),
            )
