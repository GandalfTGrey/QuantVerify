from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from quantverify.core.exceptions import ReproducibilityError
from quantverify.data.capture import RawCapture
from quantverify.data.store import CaptureStore, DataLicenseProfile

LICENSE = DataLicenseProfile(
    profile_id="fixture-personal-research-v1",
    permitted_uses=("local_research",),
    redistribution_allowed=False,
)


def capture_with_request(request: object) -> RawCapture:
    return RawCapture.from_records(
        provider="fixture",
        endpoint="daily",
        request=request,  # type: ignore[arg-type]
        records=({"date": "2026-01-02", "close": "500"},),
        captured_at=datetime(2026, 1, 2, 22, tzinfo=UTC),
    )


def write(store: CaptureStore, capture: RawCapture, **overrides: object) -> None:
    arguments: dict[str, object] = {
        "adapter_version": "fixture-adapter-1.0.0",
        "license_profile": LICENSE,
        "stored_at": datetime(2026, 1, 2, 22, 1, tzinfo=UTC),
    }
    arguments.update(overrides)
    store.write(capture, **arguments)  # type: ignore[arg-type]


class CaptureStoreIntegrityTests(TestCase):
    def test_rejects_encoded_unicode_and_vendor_credential_aliases_without_writes(self) -> None:
        aliases = (
            "apikey",
            "key",
            "XAPIKey",
            "X-APIKEY",
            "X-PRIVATEKEY",
            "api%5Fkey",
            "api%255Fkey",
            "api%2525255Fkey",
            "api\uff05\uff15\uff26key",
            "api\uff055Fkey",
            "api%EF%BC%85%EF%BC%95%EF%BC%A6key",
            "\uff41\uff50\uff49\uff05\uff15\uff26\uff4b\uff45\uff59",
            "\uff41\uff50\uff49\uff3f\uff4b\uff45\uff59",
            "Ocp-Apim-Subscription-Key",
            "X-Functions-Key",
            "X-Amz-Credential",
            "X-Amz-Signature",
            "secretAccessKey",
            "security-token",
            "consumer_key",
            "signing-key",
            "encryptionKey",
            "service-key",
            "appkey",
            "appsecret",
            "subscriptionkey",
            "functionskey",
            "oauth2accesstoken",
            "awssecretaccesskey",
            "myapikey",
            "prefixclientsecret",
            "xfunctionskey",
            "dbpassword",
            "mytoken",
            "vendorsignature",
            "XAPIKey2",
            "api_key2",
        )
        for alias in aliases:
            with self.subTest(alias=alias), TemporaryDirectory() as directory:
                root = Path(directory)
                store = CaptureStore(root)
                unsafe = capture_with_request(
                    {"symbol": "QQQ", "headers": [{alias: "credential-value-marker"}]}
                )

                with self.assertRaisesRegex(
                    ReproducibilityError, "prohibited credential field"
                ) as raised:
                    write(store, unsafe)

                message = str(raised.exception)
                self.assertNotIn(alias, message)
                self.assertNotIn("credential-value-marker", message)
                self.assertEqual(tuple(root.iterdir()), ())

    def test_rejection_never_echoes_a_secret_embedded_in_the_key_name(self) -> None:
        secret_marker = "super-secret-material"
        unsafe = capture_with_request({f"token.{secret_marker}": "value-secret-marker"})
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ReproducibilityError) as raised:
                write(CaptureStore(root), unsafe)

            message = str(raised.exception)
            self.assertNotIn(secret_marker, message)
            self.assertNotIn("value-secret-marker", message)
            self.assertEqual(tuple(root.iterdir()), ())

    def test_allows_noncredential_near_miss_keys(self) -> None:
        safe = capture_with_request(
            {
                "tokenizer": "wordpiece",
                "secretary": "role",
                "api_version": "v1",
                "key_metric": "close",
                "metric_key": "volume",
                "monkey": "not-a-tokenized-key",
                "sort_key": "date",
                "partition_key": "symbol",
                "date_key": "session",
                "group_key": "venue",
                "access_mode": "read",
                "private_mode": False,
                "schema_fingerprint": "fixture",
            }
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write(CaptureStore(root), safe)
            self.assertTrue((root / "captures").is_dir())
            self.assertTrue((root / "manifests").is_dir())

    def test_allows_a_key_with_no_semantic_tokens(self) -> None:
        safe = capture_with_request({"---": "separator-only metadata"})
        with TemporaryDirectory() as directory:
            write(CaptureStore(Path(directory)), safe)

    def test_revalidates_unsafe_capture_copies_before_any_write(self) -> None:
        valid = capture_with_request({"symbol": "QQQ"})
        unsafe_copies = (
            valid.model_copy(update={"request": ["not", "a", "mapping"]}),
            valid.model_copy(update={"records": "not-a-record-sequence"}),
            valid.model_copy(update={"provider": ""}),
            valid.model_copy(update={"captured_at": datetime(2026, 1, 2, 22)}),
        )
        for unsafe in unsafe_copies:
            with self.subTest(unsafe=unsafe), TemporaryDirectory() as directory:
                root = Path(directory)
                with self.assertRaisesRegex(
                    ReproducibilityError, "RawCapture failed integrity validation"
                ):
                    write(CaptureStore(root), unsafe)
                self.assertEqual(tuple(root.iterdir()), ())

    def test_malformed_capture_does_not_chain_raw_credential_input(self) -> None:
        secret_marker = "raw-credential-input-marker"
        valid = capture_with_request({"symbol": "QQQ"})
        unsafe = valid.model_copy(update={"request": [{"token": secret_marker}]})
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(
                ReproducibilityError, "RawCapture failed integrity validation"
            ) as raised:
                write(CaptureStore(root), unsafe)

            self.assertNotIn(secret_marker, str(raised.exception))
            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)
            self.assertEqual(tuple(root.iterdir()), ())

    def test_revalidates_license_and_manifest_inputs_before_any_write(self) -> None:
        valid = capture_with_request({"symbol": "QQQ"})
        invalid_license = LICENSE.model_copy(update={"permitted_uses": ()})
        invalid_arguments = (
            {"license_profile": invalid_license},
            {"adapter_version": ""},
            {"stored_at": "2026-01-02T22:01:00Z"},
            {"stored_at": datetime(2026, 1, 2, 21, 59, tzinfo=UTC)},
        )
        for arguments in invalid_arguments:
            with self.subTest(arguments=arguments), TemporaryDirectory() as directory:
                root = Path(directory)
                with self.assertRaises(ReproducibilityError):
                    write(CaptureStore(root), valid, **arguments)
                self.assertEqual(tuple(root.iterdir()), ())

    def test_missing_or_invalid_replay_inputs_fail_closed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = CaptureStore(root)
            with self.assertRaisesRegex(ReproducibilityError, "Invalid capture manifest"):
                store.load("manifests/missing.json")

            invalid_manifest = b"not-json"
            manifest_hash = hashlib.sha256(invalid_manifest).hexdigest()
            manifest_path = root / "manifests" / f"fixture-{manifest_hash}.json"
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_bytes(invalid_manifest)
            with self.assertRaisesRegex(ReproducibilityError, "Invalid capture manifest"):
                store.load(manifest_path.relative_to(root))

    def test_missing_content_and_immutable_collision_fail_closed(self) -> None:
        original = capture_with_request({"symbol": "QQQ"})
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = CaptureStore(root)
            stored = store.write(
                original,
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=datetime(2026, 1, 2, 22, 1, tzinfo=UTC),
            )
            content_path = root / stored.content_path
            content_path.unlink()
            with self.assertRaisesRegex(ReproducibilityError, "content is unavailable"):
                store.load(stored.manifest_path)

            content_path.parent.mkdir(parents=True, exist_ok=True)
            content_path.write_bytes(b"collision")
            with self.assertRaisesRegex(
                ReproducibilityError, "Immutable capture content collision"
            ):
                write(store, original)

    def test_rejects_symlink_escape_from_store_root(self) -> None:
        with TemporaryDirectory() as directory, TemporaryDirectory() as outside:
            root = Path(directory)
            (root / "escape").symlink_to(Path(outside), target_is_directory=True)
            with self.assertRaisesRegex(ReproducibilityError, "escapes its root"):
                CaptureStore(root).load("escape/manifest.json")
