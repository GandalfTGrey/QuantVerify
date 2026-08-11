from __future__ import annotations

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
)
SECRET_VALUE = "super-secret-value-that-must-never-appear-in-errors"


def capture_with_request(request: dict[str, object]) -> RawCapture:
    return RawCapture.from_records(
        provider="fixture",
        endpoint="daily",
        request=request,
        records=[{"date": "2026-01-02", "close": "500"}],
        captured_at=datetime(2026, 1, 2, 22, tzinfo=UTC),
        schema_version="fixture-daily-v1",
    )


class CaptureStoreSecretGuardTests(TestCase):
    def test_rejects_common_credential_aliases_recursively_before_disk_write(self) -> None:
        cases: tuple[tuple[str, dict[str, object], str], ...] = (
            ("camel access token", {"accessToken": SECRET_VALUE}, "request.accessToken"),
            ("camel client secret", {"clientSecret": SECRET_VALUE}, "request.clientSecret"),
            (
                "prefixed api key header",
                {"headers": {"X-Api-Key": SECRET_VALUE}},
                "request.headers.X-Api-Key",
            ),
            (
                "camel api key header",
                {"headers": {"xApiKey": SECRET_VALUE}},
                "request.headers.xApiKey",
            ),
            (
                "compact api key",
                {"query": {"apikey": SECRET_VALUE}},
                "request.query.apikey",
            ),
            (
                "bearer token",
                {"query": {"bearer_token": SECRET_VALUE}},
                "request.query.bearer_token",
            ),
            (
                "auth token in sequence",
                {"params": [{"authToken": SECRET_VALUE}]},
                "request.params[0].authToken",
            ),
            (
                "authorization header",
                {"headers": {"Authorization": SECRET_VALUE}},
                "request.headers.Authorization",
            ),
            (
                "private key camel case",
                {"privateKey": SECRET_VALUE},
                "request.privateKey",
            ),
            (
                "cookie family",
                {"Cookie": SECRET_VALUE},
                "request.Cookie",
            ),
            (
                "password family",
                {"db_password": SECRET_VALUE},
                "request.db_password",
            ),
        )

        for label, request, expected_path in cases:
            with self.subTest(label=label), TemporaryDirectory() as directory:
                store = CaptureStore(Path(directory))
                with self.assertRaises(ReproducibilityError) as captured_error:
                    store.write(
                        capture_with_request(request),
                        adapter_version="fixture-adapter-1.0.0",
                        license_profile=LICENSE,
                    )

                error_text = str(captured_error.exception)
                self.assertIn(expected_path, error_text)
                self.assertNotIn(SECRET_VALUE, error_text)
                self.assertFalse((Path(directory) / "captures").exists())
                self.assertFalse((Path(directory) / "manifests").exists())

    def test_allows_non_credential_words_with_similar_substrings(self) -> None:
        safe_request: dict[str, object] = {
            "symbol": "QQQ",
            "api_version": "v2",
            "key_metric": "close",
            "tokenizer": "none",
            "secretary": "public-metadata",
            "access_mode": "public",
            "private_mode": False,
        }
        with TemporaryDirectory() as directory:
            stored = CaptureStore(Path(directory)).write(
                capture_with_request(safe_request),
                adapter_version="fixture-adapter-1.0.0",
                license_profile=LICENSE,
                stored_at=datetime(2026, 1, 2, 22, 1, tzinfo=UTC),
            )

            self.assertTrue((Path(directory) / stored.content_path).exists())
            self.assertTrue((Path(directory) / stored.manifest_path).exists())
