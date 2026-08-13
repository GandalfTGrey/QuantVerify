"""Byte-level hashing and static-closure verification for registry v1."""

from __future__ import annotations

import ast
import hashlib
import os
import stat
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from quantverify.implementation_registry.models import validate_registry_path

_DYNAMIC_CALLS = {
    "__import__",
    "compile",
    "eval",
    "exec",
    "import_module",
    "importlib.import_module",
    "run_module",
    "run_path",
    "runpy.run_module",
    "runpy.run_path",
}
_IMPORT_HOOK_ATTRIBUTES = {"meta_path", "path_hooks"}


def implementation_code_hash_v1(files: Mapping[str, bytes]) -> str:
    """Hash exact path/content pairs using the ADR-0013 uint64 wire format."""

    ordered_paths = tuple(sorted(files))
    if not ordered_paths:
        raise ValueError("implementation closure must not be empty")
    if len(ordered_paths) != len(files):
        raise ValueError("implementation closure paths must be unique")
    digest = hashlib.sha256()
    for path in ordered_paths:
        validate_registry_path(path)
        content = files[path]
        if type(content) is not bytes:
            raise ValueError("implementation content must be exact bytes")
        path_bytes = path.encode("ascii")
        digest.update(len(path_bytes).to_bytes(8, byteorder="big", signed=False))
        digest.update(path_bytes)
        digest.update(len(content).to_bytes(8, byteorder="big", signed=False))
        digest.update(content)
    return digest.hexdigest()


def package_source_reader() -> Callable[[str], bytes]:
    """Return a no-follow reader anchored at the installed quantverify package."""

    package_root = Path(__file__).absolute().parents[1]

    def read(path: str) -> bytes:
        validate_registry_path(path)
        parts = tuple(path.split("/")[1:])
        if not parts:
            raise ValueError("implementation source path must identify a file")
        directory_descriptor = _open_absolute_directory_no_follow(package_root)
        descriptor: int | None = None
        try:
            for part in parts[:-1]:
                next_descriptor = os.open(
                    part,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=directory_descriptor,
                )
                os.close(directory_descriptor)
                directory_descriptor = next_descriptor
            descriptor = os.open(
                parts[-1],
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_descriptor,
            )
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise ValueError("implementation source must be a regular file")
            chunks: list[bytes] = []
            remaining = opened.st_size
            while remaining:
                chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                if not chunk:
                    raise ValueError("implementation source ended before its declared size")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                raise ValueError("implementation source exceeded its declared size")
            return b"".join(chunks)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(directory_descriptor)

    return read


def _open_absolute_directory_no_follow(path: Path) -> int:
    if not path.is_absolute():
        raise ValueError("installed package root must be absolute")
    descriptor = os.open(
        "/",
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        for part in path.parts[1:]:
            next_descriptor = os.open(
                part,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def verify_static_source_closure(
    *,
    roots: Sequence[str],
    declared_paths: tuple[str, ...],
    read_bytes: Callable[[str], bytes],
    package_source_catalog: tuple[str, ...] | None = None,
) -> dict[str, bytes]:
    """Derive direct static imports, including package initializers, and compare exactly."""

    if not isinstance(declared_paths, tuple):
        raise ValueError("declared source paths must remain an immutable tuple")
    declared = set(declared_paths)
    catalog = set(package_source_catalog or declared_paths)
    pending: list[str] = []
    for root in roots:
        validate_registry_path(root)
        pending.extend(_package_initializers(root, declared))
        pending.append(root)
    discovered: set[str] = set()
    contents: dict[str, bytes] = {}
    while pending:
        path = pending.pop()
        if path in discovered:
            continue
        if path not in declared:
            raise ValueError("implementation closure contains an undeclared project source")
        content = read_bytes(path)
        try:
            tree = ast.parse(content, filename=path)
        except (SyntaxError, ValueError):
            raise ValueError("implementation source is not valid static Python") from None
        _reject_dynamic_execution(tree)
        discovered.add(path)
        contents[path] = content
        for module in _imported_modules(tree, catalog):
            pending.extend(_module_source_paths(module, declared, catalog))
    if discovered != declared:
        raise ValueError("implementation closure contains declared but unreachable sources")
    return {path: contents[path] for path in sorted(contents)}


def _package_initializers(path: str, available: set[str]) -> list[str]:
    parts = path.split("/")[:-1]
    initializers: list[str] = []
    for index in range(1, len(parts) + 1):
        candidate = "/".join((*parts[:index], "__init__.py"))
        if candidate not in available:
            raise ValueError("implementation closure omits an executed package initializer")
        initializers.append(candidate)
    return initializers


def _module_source_paths(
    module: str, available: set[str], catalog: set[str]
) -> list[str]:
    if module != "quantverify" and not module.startswith("quantverify."):
        return []
    base = module.replace(".", "/")
    module_file = f"{base}.py"
    package_file = f"{base}/__init__.py"
    candidate = module_file if module_file in catalog else package_file
    if candidate not in catalog or candidate not in available:
        raise ValueError("implementation closure omits an imported project source")
    return [*_package_initializers(candidate, available), candidate]


def _imported_modules(tree: ast.AST, catalog: set[str]) -> tuple[str, ...]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported = {alias.name for alias in node.names}
            if any(
                name.split(".", 1)[0] in {"builtins", "importlib", "pkgutil", "runpy"}
                for name in imported
            ):
                raise ValueError("implementation closure forbids dynamic import facilities")
            modules.update(imported)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module.split(".", 1)[0] in {
                "builtins",
                "importlib",
                "pkgutil",
                "runpy",
            }:
                raise ValueError("implementation closure forbids dynamic import facilities")
            modules.add(node.module)
            for alias in node.names:
                candidate = f"{node.module}.{alias.name}".replace(".", "/")
                if f"{candidate}.py" in catalog or f"{candidate}/__init__.py" in catalog:
                    modules.add(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.level:
            raise ValueError("implementation closure forbids relative imports")
    return tuple(sorted(modules))


def _reject_dynamic_execution(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name in _DYNAMIC_CALLS or any(
                name.endswith(f".{dynamic}") for dynamic in _DYNAMIC_CALLS
            ):
                raise ValueError("implementation closure forbids dynamic execution")
        if isinstance(node, ast.Attribute) and node.attr in _IMPORT_HOOK_ATTRIBUTES:
            raise ValueError("implementation closure forbids import hooks")
        if isinstance(node, ast.Name) and node.id in {"__builtins__", "globals", "locals"}:
            raise ValueError("implementation closure forbids dynamic namespace access")


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""
