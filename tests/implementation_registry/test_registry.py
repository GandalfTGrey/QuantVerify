from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from quantverify.core.models import EngineVersion, StrategyVersion
from quantverify.implementation_registry import (
    EngineImplementationRefV1,
    ImplementationRegistry,
    ImplementationRegistryIntegrityError,
    RuntimeDependencyRefV1,
    StrategyImplementationRefV1,
    builtin_implementation_registry,
    implementation_code_hash_v1,
)
from quantverify.implementation_registry.hashing import verify_static_source_closure
from quantverify.implementation_registry.registry import (
    _ENGINE_SOURCES,
    _STRATEGY_SOURCES,
)


def test_uint64_wire_hash_has_an_independent_golden() -> None:
    files = {
        "quantverify/a.py": b"A",
        "quantverify/pkg/b.py": b"BC",
    }
    payload = b"".join(
        (
            (16).to_bytes(8, "big"),
            b"quantverify/a.py",
            (1).to_bytes(8, "big"),
            b"A",
            (20).to_bytes(8, "big"),
            b"quantverify/pkg/b.py",
            (2).to_bytes(8, "big"),
            b"BC",
        )
    )
    assert implementation_code_hash_v1(files) == hashlib.sha256(payload).hexdigest()
    assert implementation_code_hash_v1(dict(reversed(tuple(files.items())))) == hashlib.sha256(
        payload
    ).hexdigest()


def test_builtin_registry_resolves_exact_installed_implementations() -> None:
    registry = builtin_implementation_registry()

    registry.verify_all()
    strategy = registry.resolve_strategy(registry.daily_trend_ref)
    engine = registry.resolve_engine(registry.reference_engine_ref)

    assert strategy.ref.entrypoint.qualname == "price_above_sma_targets"
    assert engine.ref.entrypoint.qualname == "LongFlatReferenceEngine.run"
    assert registry.daily_trend_ref.code_hash == (
        "80b0e34b5de86e52e982d2300712bd81b759ed318b6b224b76989089a32932a8"
    )
    assert registry.reference_engine_ref.code_hash == (
        "5dfd85839191a5ad93930733252a8bf36879c6478b68e441b960ee9b5c5af33f"
    )
    assert "quantverify/strategies/__init__.py" in registry.daily_trend_ref.source_paths
    assert "quantverify/engines/__init__.py" in registry.reference_engine_ref.source_paths
    assert "quantverify/core/numerics.py" in registry.daily_trend_ref.source_paths
    assert "quantverify/core/numerics.py" in registry.reference_engine_ref.source_paths
    assert tuple(item.package for item in registry.daily_trend_ref.runtime_dependencies) == (
        "annotated-types",
        "libmpdec",
        "pydantic",
        "pydantic-core",
        "python",
        "typing-extensions",
        "typing-inspection",
        "tzdata",
    )


def test_registry_module_does_not_import_implementations_before_verification() -> None:
    import subprocess
    import sys

    source_root = Path(__file__).resolve().parents[2]

    completed = subprocess.run(
        (
            sys.executable,
            "-I",
            "-c",
            f"import sys; sys.path.insert(0, {str(source_root)!r}); "
            "import quantverify.implementation_registry; "
            "assert 'quantverify.strategies' not in sys.modules; "
            "assert 'quantverify.engines' not in sys.modules",
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_registry_rejects_unknown_or_unsafe_refs_with_fixed_public_error() -> None:
    registry = builtin_implementation_registry()
    forged = registry.daily_trend_ref.model_copy(update={"code_hash": "f" * 64})

    with pytest.raises(ImplementationRegistryIntegrityError) as captured:
        registry.resolve_strategy(forged)

    assert captured.value.args == (
        "strategy implementation failed registry integrity validation",
    )
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    with pytest.raises(ValueError):
        StrategyImplementationRefV1(
            strategy_id="daily_trend",
            version="latest",
            code_hash="f" * 64,
            source_paths=("quantverify/../secret.py",),
            runtime_dependencies=registry.daily_trend_ref.runtime_dependencies,
            entrypoint=registry.daily_trend_ref.entrypoint,
        )


def test_refs_round_trip_json_but_resolver_rejects_unsafe_mutable_copy() -> None:
    registry = builtin_implementation_registry()
    strategy = StrategyImplementationRefV1.model_validate(
        registry.daily_trend_ref.model_dump(mode="json")
    )
    engine = EngineImplementationRefV1.model_validate(
        registry.reference_engine_ref.model_dump(mode="json")
    )
    assert strategy == registry.daily_trend_ref
    assert engine == registry.reference_engine_ref

    mutable = strategy.model_copy(update={"source_paths": list(strategy.source_paths)})
    with pytest.raises(ImplementationRegistryIntegrityError):
        registry.resolve_strategy(mutable)


@pytest.mark.parametrize(
    ("path", "message"),
    (
        ("", "non-empty strict ASCII"),
        ("quantverify/space name.py", "canonical POSIX"),
        ("quantverify/LATEST/x.py", "canonical POSIX"),
        ("quantverify/é.py", "strict ASCII"),
        ("outside/x.py", "belong to quantverify"),
    ),
)
def test_ref_path_contract_rejects_noncanonical_values(path: str, message: str) -> None:
    registry = builtin_implementation_registry()
    with pytest.raises(ValueError, match=message):
        StrategyImplementationRefV1(
            strategy_id="daily_trend",
            version="1.0.0",
            code_hash="f" * 64,
            source_paths=(path,),
            runtime_dependencies=registry.daily_trend_ref.runtime_dependencies,
            entrypoint=registry.daily_trend_ref.entrypoint,
        )


def test_ref_contract_rejects_unsorted_duplicate_and_invalid_resource_paths() -> None:
    registry = builtin_implementation_registry()
    dependencies = (RuntimeDependencyRefV1(package="pydantic", version="2"),)
    entrypoint = registry.reference_engine_ref.entrypoint
    with pytest.raises(ValueError, match="sorted and unique"):
        EngineImplementationRefV1(
            engine_id="reference",
            version="1",
            code_hash="f" * 64,
            source_paths=("quantverify/z.py", "quantverify/a.py"),
            runtime_dependencies=dependencies,
            entrypoint=entrypoint,
        )
    with pytest.raises(ValueError, match="resource-free"):
        EngineImplementationRefV1(
            engine_id="reference",
            version="1",
            code_hash="f" * 64,
            source_paths=("quantverify/a.py",),
            resource_paths=("quantverify/resource.bin",),
            runtime_dependencies=dependencies,
            entrypoint=entrypoint,
        )
    with pytest.raises(ValueError, match="runtime dependencies"):
        EngineImplementationRefV1(
            engine_id="reference",
            version="1",
            code_hash="f" * 64,
            source_paths=("quantverify/a.py",),
            runtime_dependencies=(
                RuntimeDependencyRefV1(package="tzdata", version="1"),
                RuntimeDependencyRefV1(package="pydantic", version="2"),
            ),
            entrypoint=entrypoint,
        )


def test_static_closure_requires_package_initializers_and_exact_reachability() -> None:
    source = {
        "quantverify/__init__.py": b"",
        "quantverify/pkg/__init__.py": b"from quantverify.pkg.worker import run\n",
        "quantverify/pkg/worker.py": b"from quantverify.core import thing\n",
        "quantverify/core/__init__.py": b"thing = 1\n",
    }

    with pytest.raises(ValueError, match="package initializer"):
        verify_static_source_closure(
            roots=("quantverify/pkg/worker.py",),
            declared_paths=(
                "quantverify/__init__.py",
                "quantverify/core/__init__.py",
                "quantverify/pkg/worker.py",
            ),
            read_bytes=source.__getitem__,
        )
    closure = verify_static_source_closure(
        roots=("quantverify/pkg/worker.py",),
        declared_paths=tuple(sorted(source)),
        read_bytes=source.__getitem__,
    )
    assert tuple(closure) == tuple(sorted(source))


def test_static_closure_detects_from_package_import_submodule() -> None:
    source = {
        "quantverify/__init__.py": b"",
        "quantverify/pkg/__init__.py": b"",
        "quantverify/pkg/root.py": b"from quantverify.dep import worker\n",
        "quantverify/dep/__init__.py": b"",
        "quantverify/dep/worker.py": b"VALUE = 1\n",
    }
    catalog = tuple(sorted(source))
    without_worker = tuple(path for path in catalog if path != "quantverify/dep/worker.py")

    with pytest.raises(ValueError, match="imported project source"):
        verify_static_source_closure(
            roots=("quantverify/pkg/root.py",),
            declared_paths=without_worker,
            package_source_catalog=catalog,
            read_bytes=source.__getitem__,
        )


@pytest.mark.parametrize(
    "statement",
    (
        "__import__('quantverify.core')",
        "import importlib\nimportlib.import_module('quantverify.core')",
        "exec('pass')",
        "import sys\nsys.meta_path.clear()",
        "from builtins import exec as safe\nsafe('pass')",
        "getattr(__builtins__, '__import__')('quantverify.core')",
    ),
)
def test_static_closure_rejects_dynamic_import_and_execution(statement: str) -> None:
    source = {
        "quantverify/__init__.py": b"",
        "quantverify/pkg/__init__.py": b"",
        "quantverify/pkg/worker.py": statement.encode(),
    }
    with pytest.raises(ValueError):
        verify_static_source_closure(
            roots=("quantverify/pkg/worker.py",),
            declared_paths=tuple(sorted(source)),
            read_bytes=source.__getitem__,
        )


def test_shared_numeric_helper_changes_both_code_hashes() -> None:
    root = Path(__file__).resolve().parents[2]
    strategy = {path: (root / path).read_bytes() for path in _STRATEGY_SOURCES}
    engine = {path: (root / path).read_bytes() for path in _ENGINE_SOURCES}
    strategy["quantverify/core/numerics.py"] += b"# mutation\n"
    engine["quantverify/core/numerics.py"] += b"# mutation\n"

    assert implementation_code_hash_v1(strategy) != (
        "80b0e34b5de86e52e982d2300712bd81b759ed318b6b224b76989089a32932a8"
    )
    assert implementation_code_hash_v1(engine) != (
        "5dfd85839191a5ad93930733252a8bf36879c6478b68e441b960ee9b5c5af33f"
    )


def test_installed_byte_drift_fails_before_entrypoint_resolution() -> None:
    registry = builtin_implementation_registry()
    original = registry._reader

    def changed(path: str) -> bytes:
        content = original(path)
        return content + b"# drift\n" if path == "quantverify/core/numerics.py" else content

    with patch.object(registry, "_reader", changed):
        with pytest.raises(ImplementationRegistryIntegrityError):
            registry.resolve_strategy(registry.daily_trend_ref)
        with pytest.raises(ImplementationRegistryIntegrityError):
            registry.resolve_engine(registry.reference_engine_ref)


def test_runtime_dependency_or_engine_hash_copy_cannot_resolve() -> None:
    registry = builtin_implementation_registry()
    dependency = registry.daily_trend_ref.runtime_dependencies[0].model_copy(
        update={"version": "999.0.0"}
    )
    forged_strategy = registry.daily_trend_ref.model_copy(
        update={
            "runtime_dependencies": (
                dependency,
                *registry.daily_trend_ref.runtime_dependencies[1:],
            )
        }
    )
    forged_engine = registry.reference_engine_ref.model_copy(update={"code_hash": "e" * 64})

    with pytest.raises(ImplementationRegistryIntegrityError):
        registry.resolve_strategy(forged_strategy)
    with pytest.raises(ImplementationRegistryIntegrityError):
        registry.resolve_engine(forged_engine)


def test_registry_owns_exact_legacy_version_compatibility_adapter() -> None:
    registry = builtin_implementation_registry()
    strategy, engine = registry.resolve_versions(
        registry.strategy_version(), registry.engine_version()
    )
    assert strategy.ref == registry.daily_trend_ref
    assert engine.ref == registry.reference_engine_ref

    with pytest.raises(ImplementationRegistryIntegrityError):
        registry.resolve_versions(
            StrategyVersion(
                strategy_id="daily_trend", version="1.0.0", code_hash="a" * 64
            ),
            registry.engine_version(),
        )
    with pytest.raises(ImplementationRegistryIntegrityError):
        registry.resolve_versions(
            registry.strategy_version(),
            EngineVersion(engine_id="reference", version="latest"),
        )


def test_registry_never_returns_a_preloaded_callable_as_authority() -> None:
    registry = builtin_implementation_registry()
    resolved = registry.resolve_strategy(registry.daily_trend_ref)

    assert not hasattr(resolved, "callable")
    assert resolved.ref.entrypoint.module == "quantverify.strategies.trend"


def test_private_cached_state_cannot_replace_static_registry_authority() -> None:
    registry = builtin_implementation_registry()
    registry.__dict__["_dependencies"] = (
        RuntimeDependencyRefV1(package="evil", version="1"),
    )
    registry.__dict__["_strategy_ref"] = registry.daily_trend_ref.model_copy(
        update={"code_hash": "f" * 64}
    )

    registry.verify_all()
    assert registry.daily_trend_ref.code_hash == (
        "80b0e34b5de86e52e982d2300712bd81b759ed318b6b224b76989089a32932a8"
    )


def test_unreviewed_installed_runtime_version_cannot_become_authority() -> None:
    from importlib import metadata

    from quantverify.implementation_registry import registry as registry_module

    real_version = metadata.version

    def unsupported(package: str) -> str:
        if package == "pydantic":
            return "99.0.0"
        return real_version(package)

    with (
        patch.object(registry_module, "version", unsupported),
        pytest.raises(ImplementationRegistryIntegrityError) as captured,
    ):
        builtin_implementation_registry()
    assert captured.value.args == (
        "implementation runtime dependencies are not reviewed",
    )
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_builtin_constructor_failures_are_fixed_typed_and_nonleaking() -> None:
    from quantverify.implementation_registry import registry as registry_module

    with (
        patch.object(
            registry_module,
            "package_source_reader",
            side_effect=OSError("SECRET-PATH"),
        ),
        pytest.raises(ImplementationRegistryIntegrityError) as captured,
    ):
        builtin_implementation_registry()
    assert captured.value.args == (
        "built-in implementation registry failed integrity validation",
    )
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert getattr(captured.value, "__notes__", None) is None

    with (
        patch.object(
            registry_module,
            "package_source_reader",
            side_effect=OSError("SECRET-PATH"),
        ),
        pytest.raises(ImplementationRegistryIntegrityError) as direct,
    ):
        ImplementationRegistry()
    assert direct.value.args == captured.value.args
    assert direct.value.__cause__ is None
    assert direct.value.__context__ is None
    assert getattr(direct.value, "__notes__", None) is None
