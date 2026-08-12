"""Explicit, offline-only fixture manifest loading and registry lookup."""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib import resources
from types import MappingProxyType
from typing import Any, Final

from pydantic import ValidationError

from quantverify.core.exceptions import QuantVerifyError
from quantverify.fixtures.models import FixtureManifest, LoadedFixture

MAX_MANIFEST_BYTES: Final = 2 * 1024 * 1024
BUILTIN_FIXTURE_ID: Final = "qqq-sma3-daily-v1"
_BUILTIN_RESOURCE: Final = "qqq_sma3_daily_v1.json"


class FixtureError(QuantVerifyError):
    """Base error for fixture manifest integrity and explicit lookup failures."""


class FixtureIntegrityError(FixtureError):
    """A supplied fixture manifest cannot be reconstructed and verified."""


class FixtureNotFoundError(FixtureError):
    """An exact fixture identifier is not present in the configured registry."""


def load_fixture_manifest(document: str | bytes) -> LoadedFixture:
    """Load one manifest document without resolving paths or contacting providers."""

    if isinstance(document, str):
        encoded = document.encode("utf-8")
    elif isinstance(document, bytes):
        encoded = document
    else:
        raise FixtureIntegrityError("fixture manifest must be UTF-8 JSON bytes or text")
    if not encoded or len(encoded) > MAX_MANIFEST_BYTES:
        raise FixtureIntegrityError("fixture manifest size is invalid")
    try:
        raw = json.loads(encoded.decode("utf-8"), object_pairs_hook=_unique_object)
        manifest = FixtureManifest.model_validate(raw)
        loaded = LoadedFixture(manifest=manifest)
        return LoadedFixture.model_validate(loaded.model_dump(mode="python"))
    except FixtureIntegrityError:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValidationError,
        TypeError,
        ValueError,
    ) as exc:
        raise FixtureIntegrityError("fixture manifest failed integrity validation") from exc


class FixtureRegistry:
    """Immutable exact-ID registry; it never scans directories or selects aliases."""

    def __init__(self, manifests: Mapping[str, str | bytes]) -> None:
        loaded: dict[str, LoadedFixture] = {}
        for registered_id, document in manifests.items():
            if registered_id in loaded:
                raise FixtureIntegrityError("fixture registry identifiers must be unique")
            fixture = load_fixture_manifest(document)
            if registered_id != fixture.fixture_id:
                raise FixtureIntegrityError(
                    "fixture registry identifier must equal manifest fixture_id"
                )
            loaded[registered_id] = fixture
        self._fixtures: Mapping[str, LoadedFixture] = MappingProxyType(loaded)

    @classmethod
    def builtin(cls) -> FixtureRegistry:
        """Create the fixed packaged registry without filesystem path discovery."""

        document = (
            resources.files("quantverify.fixtures.resources")
            .joinpath(_BUILTIN_RESOURCE)
            .read_bytes()
        )
        return cls({BUILTIN_FIXTURE_ID: document})

    @property
    def fixture_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._fixtures))

    def resolve(self, fixture_id: str) -> LoadedFixture:
        """Resolve one exact identifier and return a freshly revalidated value."""

        if not isinstance(fixture_id, str) or fixture_id.casefold() == "latest":
            raise FixtureNotFoundError("fixture identifier is not registered")
        try:
            stored = self._fixtures[fixture_id]
        except KeyError:
            raise FixtureNotFoundError("fixture identifier is not registered") from None
        try:
            return LoadedFixture.model_validate(stored.model_dump(mode="python"))
        except (AttributeError, TypeError, ValueError) as exc:
            raise FixtureIntegrityError("registered fixture failed integrity validation") from exc


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FixtureIntegrityError(f"duplicate fixture manifest key: {key!r}")
        result[key] = value
    return result
