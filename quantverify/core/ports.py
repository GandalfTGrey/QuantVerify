"""Hexagonal architecture ports owned by the domain/application core."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from quantverify.core.models import ArtifactRef, ExperimentConfig, TargetPosition


class DataProvider(Protocol):
    def load(self, config: ExperimentConfig) -> ArtifactRef: ...


class Strategy(Protocol):
    def generate_targets(
        self,
        market_data: ArtifactRef,
        parameters: Mapping[str, Any],
    ) -> Sequence[TargetPosition]: ...


class ResearchEngine(Protocol):
    def run(
        self,
        config: ExperimentConfig,
        market_data: ArtifactRef,
        targets: Sequence[TargetPosition],
    ) -> Sequence[ArtifactRef]: ...


class ResultStore(Protocol):
    def save_run(
        self,
        *,
        experiment_id: str,
        run_id: str,
        artifacts: Sequence[ArtifactRef],
    ) -> None: ...
