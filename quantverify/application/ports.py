"""Inbound application ports intentionally independent of CLI and infrastructure."""

from __future__ import annotations

from typing import Protocol

from quantverify.application.contracts import (
    InspectResult,
    InspectRunCommand,
    PlanFixtureCommand,
    PlanResult,
)


class PlanFixtureHandler(Protocol):
    def handle(self, command: PlanFixtureCommand, /) -> PlanResult: ...


class InspectRunHandler(Protocol):
    def handle(self, command: InspectRunCommand, /) -> InspectResult: ...


# A RunFixtureHandler is deliberately absent. CORE-06 must first freeze the
# opening-equity/first-return convention, MetricInput lineage, and artifact v2.
