"""Built-in exact implementation registry for fixture replay."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import __libmpdec_version__
from importlib.metadata import PackageNotFoundError, version
from sys import version_info
from typing import Any, Generic, TypeVar

from pydantic import ValidationError

from quantverify.core.exceptions import QuantVerifyError
from quantverify.core.models import EngineVersion, StrategyVersion
from quantverify.implementation_registry.hashing import (
    implementation_code_hash_v1,
    package_source_reader,
    verify_static_source_closure,
)
from quantverify.implementation_registry.models import (
    EngineImplementationRefV1,
    ImplementationEntrypointV1,
    RuntimeDependencyRefV1,
    StrategyImplementationRefV1,
)


class ImplementationRegistryIntegrityError(QuantVerifyError):
    """A requested implementation cannot prove its exact installed code closure."""


TRef = TypeVar("TRef", StrategyImplementationRefV1, EngineImplementationRefV1)


@dataclass(frozen=True)
class ResolvedImplementation(Generic[TRef]):
    ref: TRef


_STRATEGY_SOURCES = (
    "quantverify/__init__.py",
    "quantverify/core/__init__.py",
    "quantverify/core/enums.py",
    "quantverify/core/exceptions.py",
    "quantverify/core/identity.py",
    "quantverify/core/models.py",
    "quantverify/core/numerics.py",
    "quantverify/data/__init__.py",
    "quantverify/data/capture.py",
    "quantverify/data/models.py",
    "quantverify/data/quality/__init__.py",
    "quantverify/data/quality/identity.py",
    "quantverify/data/quality/models.py",
    "quantverify/data/quality/policy.py",
    "quantverify/data/quality/provenance.py",
    "quantverify/data/quality/suite.py",
    "quantverify/data/snapshots.py",
    "quantverify/data/store.py",
    "quantverify/data/validation.py",
    "quantverify/features/__init__.py",
    "quantverify/features/donchian.py",
    "quantverify/features/momentum.py",
    "quantverify/features/moving_average.py",
    "quantverify/features/rsi.py",
    "quantverify/research/__init__.py",
    "quantverify/research/frequency/__init__.py",
    "quantverify/research/frequency/resample.py",
    "quantverify/strategies/__init__.py",
    "quantverify/strategies/donchian.py",
    "quantverify/strategies/dual_momentum.py",
    "quantverify/strategies/monthly_sma.py",
    "quantverify/strategies/rsi_pullback.py",
    "quantverify/strategies/trend.py",
    "quantverify/strategies/weekly_dual_ma.py",
)
_ENGINE_SOURCES = (
    "quantverify/__init__.py",
    "quantverify/core/__init__.py",
    "quantverify/core/enums.py",
    "quantverify/core/exceptions.py",
    "quantverify/core/identity.py",
    "quantverify/core/models.py",
    "quantverify/core/numerics.py",
    "quantverify/data/__init__.py",
    "quantverify/data/capture.py",
    "quantverify/data/models.py",
    "quantverify/data/quality/__init__.py",
    "quantverify/data/quality/identity.py",
    "quantverify/data/quality/models.py",
    "quantverify/data/quality/policy.py",
    "quantverify/data/quality/provenance.py",
    "quantverify/data/quality/suite.py",
    "quantverify/data/snapshots.py",
    "quantverify/data/store.py",
    "quantverify/data/validation.py",
    "quantverify/engines/__init__.py",
    "quantverify/engines/reference.py",
)

# Updated only by the reviewed build-time closure command; callers cannot supply these.
_DAILY_TREND_CODE_HASH = "80b0e34b5de86e52e982d2300712bd81b759ed318b6b224b76989089a32932a8"
_REFERENCE_ENGINE_CODE_HASH = "5dfd85839191a5ad93930733252a8bf36879c6478b68e441b960ee9b5c5af33f"

_PACKAGE_SOURCE_CATALOG = (
    "quantverify/__init__.py",
    "quantverify/application/__init__.py",
    "quantverify/application/contracts.py",
    "quantverify/application/ports.py",
    "quantverify/artifacts/__init__.py",
    "quantverify/artifacts/store.py",
    "quantverify/core/__init__.py",
    "quantverify/core/config.py",
    "quantverify/core/enums.py",
    "quantverify/core/exceptions.py",
    "quantverify/core/identity.py",
    "quantverify/core/models.py",
    "quantverify/core/numerics.py",
    "quantverify/core/ports.py",
    "quantverify/data/__init__.py",
    "quantverify/data/capture.py",
    "quantverify/data/models.py",
    "quantverify/data/providers/__init__.py",
    "quantverify/data/providers/akshare.py",
    "quantverify/data/providers/yfinance.py",
    "quantverify/data/quality/__init__.py",
    "quantverify/data/quality/identity.py",
    "quantverify/data/quality/models.py",
    "quantverify/data/quality/policy.py",
    "quantverify/data/quality/provenance.py",
    "quantverify/data/quality/suite.py",
    "quantverify/data/snapshots.py",
    "quantverify/data/store.py",
    "quantverify/data/validation.py",
    "quantverify/engines/__init__.py",
    "quantverify/engines/reference.py",
    "quantverify/features/__init__.py",
    "quantverify/features/donchian.py",
    "quantverify/features/momentum.py",
    "quantverify/features/moving_average.py",
    "quantverify/features/rsi.py",
    "quantverify/fixtures/__init__.py",
    "quantverify/fixtures/models.py",
    "quantverify/fixtures/registry.py",
    "quantverify/fixtures/resources/__init__.py",
    "quantverify/implementation_registry/__init__.py",
    "quantverify/implementation_registry/hashing.py",
    "quantverify/implementation_registry/models.py",
    "quantverify/implementation_registry/registry.py",
    "quantverify/metrics/__init__.py",
    "quantverify/metrics/calculator.py",
    "quantverify/metrics/models.py",
    "quantverify/metrics/returns.py",
    "quantverify/metrics/v2_calculator.py",
    "quantverify/metrics/v2_identity.py",
    "quantverify/metrics/v2_models.py",
    "quantverify/research/__init__.py",
    "quantverify/research/frequency/__init__.py",
    "quantverify/research/frequency/resample.py",
    "quantverify/strategies/__init__.py",
    "quantverify/strategies/donchian.py",
    "quantverify/strategies/dual_momentum.py",
    "quantverify/strategies/monthly_sma.py",
    "quantverify/strategies/rsi_pullback.py",
    "quantverify/strategies/trend.py",
    "quantverify/strategies/weekly_dual_ma.py",
)

# Exact reviewed lockless-CI environments. Dependency updates require a registry review.
_REVIEWED_DISTRIBUTION_DEPENDENCY_SETS = (
    (
        ("annotated-types", "0.7.0"),
        ("pydantic", "2.12.5"),
        ("pydantic-core", "2.41.5"),
        ("typing-extensions", "4.15.0"),
        ("typing-inspection", "0.4.2"),
        ("tzdata", "2025.1"),
    ),
    (
        ("annotated-types", "0.8.0"),
        ("pydantic", "2.13.4"),
        ("pydantic-core", "2.46.4"),
        ("typing-extensions", "4.16.0"),
        ("typing-inspection", "0.4.4"),
        ("tzdata", "2026.3"),
    ),
)
_REVIEWED_RUNTIME_COHORTS = frozenset(
    (distributions, python_version, libmpdec_version)
    for distributions in _REVIEWED_DISTRIBUTION_DEPENDENCY_SETS
    for python_version, libmpdec_version in (
        ("3.11", "2.5.1"),
        ("3.11", "4.0.0"),
        ("3.12", "2.5.1"),
        ("3.12", "4.0.0"),
        ("3.13", "2.5.1"),
        ("3.13", "4.0.0"),
    )
)

_DISTRIBUTION_PACKAGES = (
    "annotated-types",
    "pydantic",
    "pydantic-core",
    "typing-extensions",
    "typing-inspection",
    "tzdata",
)


def is_reviewed_runtime_dependency_cohort(
    dependencies: tuple[RuntimeDependencyRefV1, ...],
) -> bool:
    """Return whether one exact immutable dependency tuple is a reviewed cohort."""

    try:
        if not isinstance(dependencies, tuple):
            return False
        validated = tuple(
            RuntimeDependencyRefV1.model_validate(item.model_dump(mode="python"))
            for item in dependencies
        )
        if validated != tuple(sorted(validated, key=lambda item: item.package)):
            return False
        by_package = {item.package: item.version for item in validated}
        if len(by_package) != len(validated):
            return False
        observed_distributions = tuple(
            (package, by_package[package]) for package in _DISTRIBUTION_PACKAGES
        )
        observed_cohort = (
            observed_distributions,
            by_package["python"],
            by_package["libmpdec"],
        )
    except (AttributeError, KeyError, TypeError, ValueError, ValidationError):
        return False
    return (
        set(by_package) == {*_DISTRIBUTION_PACKAGES, "python", "libmpdec"}
        and observed_cohort in _REVIEWED_RUNTIME_COHORTS
    )


class ImplementationRegistry:
    """Exact resolver whose trust root is the immutable built-in table."""

    def __init__(self) -> None:
        failed = False
        reader: Any | None = None
        try:
            reader = package_source_reader()
            self._runtime_dependencies()
        except (AttributeError, OSError, TypeError, ValueError, ValidationError):
            failed = True
        if failed or reader is None:
            raise ImplementationRegistryIntegrityError(
                "built-in implementation registry failed integrity validation"
            ) from None
        self._reader = reader

    @property
    def daily_trend_ref(self) -> StrategyImplementationRefV1:
        return self._expected_strategy_ref()

    @property
    def reference_engine_ref(self) -> EngineImplementationRefV1:
        return self._expected_engine_ref()

    def resolve_strategy(
        self, requested: StrategyImplementationRefV1
    ) -> ResolvedImplementation[StrategyImplementationRefV1]:
        failed = False
        try:
            self._require_immutable_ref(requested)
            validated = StrategyImplementationRefV1.model_validate(
                requested.model_dump(mode="python")
            )
            expected = self._expected_strategy_ref()
            if validated != expected:
                raise ValueError
            self._verify_strategy()
        except (AttributeError, OSError, TypeError, ValueError, ValidationError):
            failed = True
        if failed:
            raise ImplementationRegistryIntegrityError(
                "strategy implementation failed registry integrity validation"
            ) from None
        return ResolvedImplementation(ref=expected)

    def resolve_engine(
        self, requested: EngineImplementationRefV1
    ) -> ResolvedImplementation[EngineImplementationRefV1]:
        failed = False
        try:
            self._require_immutable_ref(requested)
            validated = EngineImplementationRefV1.model_validate(
                requested.model_dump(mode="python")
            )
            expected = self._expected_engine_ref()
            if validated != expected:
                raise ValueError
            self._verify_engine()
        except (AttributeError, OSError, TypeError, ValueError, ValidationError):
            failed = True
        if failed:
            raise ImplementationRegistryIntegrityError(
                "engine implementation failed registry integrity validation"
            ) from None
        return ResolvedImplementation(ref=expected)

    def strategy_version(self) -> StrategyVersion:
        ref = self._expected_strategy_ref()
        return StrategyVersion(
            strategy_id=ref.strategy_id,
            version=ref.version,
            code_hash=ref.code_hash,
        )

    def engine_version(self) -> EngineVersion:
        ref = self._expected_engine_ref()
        return EngineVersion(engine_id=ref.engine_id, version=ref.version)

    def resolve_versions(
        self, strategy: StrategyVersion, engine: EngineVersion
    ) -> tuple[
        ResolvedImplementation[StrategyImplementationRefV1],
        ResolvedImplementation[EngineImplementationRefV1],
    ]:
        failed = False
        try:
            validated_strategy = StrategyVersion.model_validate(
                strategy.model_dump(mode="python")
            )
            validated_engine = EngineVersion.model_validate(engine.model_dump(mode="python"))
            if validated_strategy != self.strategy_version():
                raise ValueError
            if validated_engine != self.engine_version():
                raise ValueError
        except (AttributeError, TypeError, ValueError, ValidationError):
            failed = True
        if failed:
            raise ImplementationRegistryIntegrityError(
                "fixture run spec failed implementation registry validation"
            ) from None
        return (
            self.resolve_strategy(self.daily_trend_ref),
            self.resolve_engine(self.reference_engine_ref),
        )

    def verify_all(self) -> None:
        failed = False
        try:
            self._runtime_dependencies()
            self._verify_strategy()
            self._verify_engine()
        except (OSError, TypeError, ValueError):
            failed = True
        if failed:
            raise ImplementationRegistryIntegrityError(
                "built-in implementation registry failed integrity validation"
            ) from None

    def _verify_strategy(self) -> None:
        contents = verify_static_source_closure(
            roots=("quantverify/strategies/trend.py",),
            declared_paths=_STRATEGY_SOURCES,
            read_bytes=self._reader,
            package_source_catalog=_PACKAGE_SOURCE_CATALOG,
        )
        if implementation_code_hash_v1(contents) != _DAILY_TREND_CODE_HASH:
            raise ValueError("strategy implementation bytes do not match the registry")

    def _verify_engine(self) -> None:
        contents = verify_static_source_closure(
            roots=("quantverify/engines/reference.py",),
            declared_paths=_ENGINE_SOURCES,
            read_bytes=self._reader,
            package_source_catalog=_PACKAGE_SOURCE_CATALOG,
        )
        if implementation_code_hash_v1(contents) != _REFERENCE_ENGINE_CODE_HASH:
            raise ValueError("engine implementation bytes do not match the registry")

    @staticmethod
    def _require_immutable_ref(
        requested: StrategyImplementationRefV1 | EngineImplementationRefV1,
    ) -> None:
        if (
            not isinstance(requested, (StrategyImplementationRefV1, EngineImplementationRefV1))
            or not isinstance(requested.source_paths, tuple)
            or not isinstance(requested.resource_paths, tuple)
            or not isinstance(requested.runtime_dependencies, tuple)
            or any(
                not isinstance(dependency, RuntimeDependencyRefV1)
                for dependency in requested.runtime_dependencies
            )
        ):
            raise ValueError("implementation ref must remain deeply immutable")

    def _expected_strategy_ref(self) -> StrategyImplementationRefV1:
        return StrategyImplementationRefV1(
            strategy_id="daily_trend",
            version="1.0.0",
            code_hash=_DAILY_TREND_CODE_HASH,
            source_paths=_STRATEGY_SOURCES,
            runtime_dependencies=self._runtime_dependencies(),
            entrypoint=ImplementationEntrypointV1(
                module="quantverify.strategies.trend",
                qualname="price_above_sma_targets",
            ),
        )

    def _expected_engine_ref(self) -> EngineImplementationRefV1:
        return EngineImplementationRefV1(
            engine_id="reference",
            version="0.1.0",
            code_hash=_REFERENCE_ENGINE_CODE_HASH,
            source_paths=_ENGINE_SOURCES,
            runtime_dependencies=self._runtime_dependencies(),
            entrypoint=ImplementationEntrypointV1(
                module="quantverify.engines.reference",
                qualname="LongFlatReferenceEngine.run",
            ),
        )

    @staticmethod
    def _runtime_dependencies() -> tuple[RuntimeDependencyRefV1, ...]:
        dependencies: list[RuntimeDependencyRefV1] = []
        failed = False
        for package in _DISTRIBUTION_PACKAGES:
            try:
                installed_version = version(package)
            except PackageNotFoundError:
                failed = True
                break
            dependencies.append(
                RuntimeDependencyRefV1(package=package, version=installed_version)
            )
        dependencies.extend(
            (
                RuntimeDependencyRefV1(package="libmpdec", version=__libmpdec_version__),
                RuntimeDependencyRefV1(
                    package="python", version=f"{version_info.major}.{version_info.minor}"
                ),
            )
        )
        dependencies.sort(key=lambda item: item.package)
        if failed or not is_reviewed_runtime_dependency_cohort(tuple(dependencies)):
            raise ImplementationRegistryIntegrityError(
                "implementation runtime dependencies are not reviewed"
            ) from None
        return tuple(dependencies)


def builtin_implementation_registry() -> ImplementationRegistry:
    """Return a fresh resolver so no mutable cache can become authority."""

    failed = False
    registry: ImplementationRegistry | None = None
    try:
        registry = ImplementationRegistry()
    except (AttributeError, OSError, TypeError, ValueError, ValidationError):
        failed = True
    if failed or registry is None:
        raise ImplementationRegistryIntegrityError(
            "built-in implementation registry failed integrity validation"
        ) from None
    return registry
