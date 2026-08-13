"""Immutable contracts for the versioned implementation registry."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from quantverify.core.models import DomainModel

_HASH_PATTERN = r"^[a-f0-9]{64}$"


def validate_registry_path(value: str) -> str:
    """Validate one byte-addressed package path without normalizing it."""

    if type(value) is not str or not value or not value.isascii():
        raise ValueError("implementation path must be non-empty strict ASCII")
    if value.startswith("/") or "\\" in value or "%" in value:
        raise ValueError("implementation path must be canonical POSIX relative")
    parts = value.split("/")
    if any(
        not part
        or part in {".", ".."}
        or part.casefold() == "latest"
        or any(ord(character) <= 32 or ord(character) == 127 for character in part)
        for part in parts
    ):
        raise ValueError("implementation path must be canonical POSIX relative")
    if not value.startswith("quantverify/"):
        raise ValueError("implementation path must belong to quantverify")
    return value


def _validate_paths(values: tuple[str, ...], *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ValueError("implementation paths must remain an immutable tuple")
    if not allow_empty and not values:
        raise ValueError("implementation source paths must not be empty")
    validated = tuple(validate_registry_path(value) for value in values)
    if validated != tuple(sorted(validated)) or len(set(validated)) != len(validated):
        raise ValueError("implementation paths must be sorted and unique")
    return validated


class RuntimeDependencyRefV1(DomainModel):
    """One exact third-party runtime dependency observed by a resolver."""

    schema_version: Literal["runtime-dependency-ref-v1"] = "runtime-dependency-ref-v1"
    package: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,127}$")
    version: str = Field(min_length=1, max_length=128)

    @field_validator("package", "version", mode="before")
    @classmethod
    def require_canonical_text(cls, value: object) -> object:
        if type(value) is not str or value != value.strip():
            raise ValueError("runtime dependency text must remain canonical")
        return value


class ImplementationEntrypointV1(DomainModel):
    """A fixed import target; it is data, never an already-loaded callable authority."""

    schema_version: Literal["implementation-entrypoint-v1"] = "implementation-entrypoint-v1"
    module: str = Field(pattern=r"^quantverify(?:\.[a-z][a-z0-9_]*)+$")
    qualname: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*$")

    @field_validator("module", "qualname", mode="before")
    @classmethod
    def require_canonical_text(cls, value: object) -> object:
        if type(value) is not str or value != value.strip():
            raise ValueError("implementation entrypoint text must remain canonical")
        return value


class StrategyImplementationRefV1(DomainModel):
    registry_schema_version: Literal["implementation-registry-v1"] = (
        "implementation-registry-v1"
    )
    strategy_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    version: str = Field(min_length=1, max_length=64)
    code_hash: str = Field(pattern=_HASH_PATTERN)
    source_paths: tuple[str, ...] = Field(min_length=1)
    resource_paths: tuple[str, ...] = ()
    runtime_dependencies: tuple[RuntimeDependencyRefV1, ...] = Field(min_length=1)
    entrypoint: ImplementationEntrypointV1

    @field_validator("strategy_id", "version", "code_hash", mode="before")
    @classmethod
    def require_canonical_text(cls, value: object) -> object:
        if type(value) is not str or value != value.strip():
            raise ValueError("implementation text must remain canonical")
        return value

    @model_validator(mode="after")
    def validate_paths(self) -> StrategyImplementationRefV1:
        _validate_paths(self.source_paths, allow_empty=False)
        _validate_paths(self.resource_paths, allow_empty=True)
        if self.resource_paths:
            raise ValueError("implementation-registry-v1 supports resource-free entries only")
        if set(self.source_paths) & set(self.resource_paths):
            raise ValueError("implementation source and resource paths must not overlap")
        if any(not path.endswith(".py") for path in self.source_paths):
            raise ValueError("implementation source paths must identify Python source")
        if any(
            not path.endswith((".json", ".yaml", ".yml", ".csv"))
            for path in self.resource_paths
        ):
            raise ValueError("implementation resource path has an unsupported suffix")
        if tuple(sorted(self.runtime_dependencies, key=lambda item: item.package)) != (
            self.runtime_dependencies
        ) or len({item.package for item in self.runtime_dependencies}) != len(
            self.runtime_dependencies
        ):
            raise ValueError("runtime dependencies must be sorted and unique")
        return self


class EngineImplementationRefV1(DomainModel):
    registry_schema_version: Literal["implementation-registry-v1"] = (
        "implementation-registry-v1"
    )
    engine_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    version: str = Field(min_length=1, max_length=64)
    code_hash: str = Field(pattern=_HASH_PATTERN)
    source_paths: tuple[str, ...] = Field(min_length=1)
    resource_paths: tuple[str, ...] = ()
    runtime_dependencies: tuple[RuntimeDependencyRefV1, ...] = Field(min_length=1)
    entrypoint: ImplementationEntrypointV1

    @field_validator("engine_id", "version", "code_hash", mode="before")
    @classmethod
    def require_canonical_text(cls, value: object) -> object:
        if type(value) is not str or value != value.strip():
            raise ValueError("implementation text must remain canonical")
        return value

    @model_validator(mode="after")
    def validate_paths(self) -> EngineImplementationRefV1:
        _validate_paths(self.source_paths, allow_empty=False)
        _validate_paths(self.resource_paths, allow_empty=True)
        if self.resource_paths:
            raise ValueError("implementation-registry-v1 supports resource-free entries only")
        if set(self.source_paths) & set(self.resource_paths):
            raise ValueError("implementation source and resource paths must not overlap")
        if any(not path.endswith(".py") for path in self.source_paths):
            raise ValueError("implementation source paths must identify Python source")
        if any(
            not path.endswith((".json", ".yaml", ".yml", ".csv"))
            for path in self.resource_paths
        ):
            raise ValueError("implementation resource path has an unsupported suffix")
        if tuple(sorted(self.runtime_dependencies, key=lambda item: item.package)) != (
            self.runtime_dependencies
        ) or len({item.package for item in self.runtime_dependencies}) != len(
            self.runtime_dependencies
        ):
            raise ValueError("runtime dependencies must be sorted and unique")
        return self
