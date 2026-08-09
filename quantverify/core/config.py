"""Versioned configuration loading at the system boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from quantverify.core.exceptions import QuantVerifyError
from quantverify.core.models import ExperimentConfig

SUPPORTED_EXPERIMENT_SCHEMA_VERSIONS = frozenset({1})


class ConfigError(QuantVerifyError):
    """A configuration file cannot be parsed or validated."""


def load_experiment_config(path: str | Path) -> ExperimentConfig:
    """Load a versioned YAML experiment config with fail-closed validation."""
    config_path = Path(path)
    try:
        raw: Any = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Cannot read experiment config {config_path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in experiment config {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("Experiment config root must be a mapping")

    schema_version = raw.pop("schema_version", None)
    if schema_version not in SUPPORTED_EXPERIMENT_SCHEMA_VERSIONS:
        supported = ", ".join(map(str, sorted(SUPPORTED_EXPERIMENT_SCHEMA_VERSIONS)))
        raise ConfigError(
            f"Unsupported experiment schema_version {schema_version!r}; supported: {supported}"
        )

    try:
        return ExperimentConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"Invalid experiment config {config_path}: {exc}") from exc
