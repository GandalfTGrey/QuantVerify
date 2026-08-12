"""Versioned DTOs at the fixture-only application boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import IntEnum, StrEnum
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, Field, StrictInt, model_serializer, model_validator

from quantverify.core.enums import BarFrequency, DecisionTime, ExecutionPrice
from quantverify.core.identity import stable_hash
from quantverify.core.models import (
    ArtifactRef,
    DataSnapshot,
    DomainModel,
    ExperimentConfig,
    RuntimeContext,
)
from quantverify.metrics.models import (
    AnnualizationPolicy,
    ReturnBasis,
    RiskFreePolicy,
)


class PlanDisposition(StrEnum):
    STRUCTURALLY_READY = "structurally_ready"


class ArtifactTrustScope(StrEnum):
    ARTIFACT_V1_INTEGRITY_ONLY = "artifact_v1_integrity_only"


class ApplicationErrorCode(StrEnum):
    CONFIG_INVALID = "config_invalid"
    FIXTURE_REJECTED = "fixture_rejected"
    REAL_DATA_UNAVAILABLE = "real_data_unavailable"
    PREFLIGHT_REJECTED = "preflight_rejected"
    EXECUTION_FAILED = "execution_failed"
    ARTIFACT_FAILED = "artifact_failed"
    INTERNAL_ERROR = "internal_error"


class CliExitCode(IntEnum):
    SUCCESS = 0
    CONFIG_INVALID = 2
    PREFLIGHT_REJECTED = 3
    EXECUTION_FAILED = 4
    ARTIFACT_FAILED = 5
    INTERNAL_ERROR = 70


_ERROR_EXIT_CODES = {
    ApplicationErrorCode.CONFIG_INVALID: CliExitCode.CONFIG_INVALID,
    ApplicationErrorCode.FIXTURE_REJECTED: CliExitCode.PREFLIGHT_REJECTED,
    ApplicationErrorCode.REAL_DATA_UNAVAILABLE: CliExitCode.PREFLIGHT_REJECTED,
    ApplicationErrorCode.PREFLIGHT_REJECTED: CliExitCode.PREFLIGHT_REJECTED,
    ApplicationErrorCode.EXECUTION_FAILED: CliExitCode.EXECUTION_FAILED,
    ApplicationErrorCode.ARTIFACT_FAILED: CliExitCode.ARTIFACT_FAILED,
    ApplicationErrorCode.INTERNAL_ERROR: CliExitCode.INTERNAL_ERROR,
}


def _scientific_identity_value(value: Any) -> Any:
    """Normalize numeric semantics without changing legacy global identities."""

    if isinstance(value, BaseModel):
        return _scientific_identity_value(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return {
            key: _scientific_identity_value(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_scientific_identity_value(item) for item in value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("fixture scientific identity requires finite Decimals")
        if value == 0:
            return "0"
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("fixture scientific identity requires aware datetimes")
        return value.astimezone(UTC)
    return value


class ApplicationFailure(DomainModel):
    """Sanitized machine-readable failure; raw exception text is never a field."""

    schema_version: Literal["application-failure-v1"] = "application-failure-v1"
    code: ApplicationErrorCode

    @property
    def exit_code(self) -> int:
        validated = self._safe_revalidated()
        return int(_ERROR_EXIT_CODES[validated.code])

    def _safe_revalidated(self) -> ApplicationFailure:
        try:
            return type(self).model_validate(
                {"schema_version": self.schema_version, "code": self.code}
            )
        except (TypeError, ValueError):
            return type(self)(code=ApplicationErrorCode.INTERNAL_ERROR)

    @model_serializer(mode="wrap")
    def serialize_validated(self, handler: Any) -> Any:
        return handler(self._safe_revalidated())


class ConsumedSessionRange(DomainModel):
    """Exact schedule identity and inclusive session labels consumed by a run."""

    schema_version: Literal["consumed-session-range-v1"] = "consumed-session-range-v1"
    start_session: date
    end_session: date
    session_count: StrictInt = Field(ge=1)
    schedule_id: str = Field(pattern=r"^session-schedule_[a-f0-9]{24}$")
    schedule_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_bounds(self) -> ConsumedSessionRange:
        if self.start_session > self.end_session:
            raise ValueError("consumed session start must not follow its end")
        return self


class DailyTrendParameters(DomainModel):
    """Only strategy parameter shape admitted by fixture-run-spec v1."""

    schema_version: Literal["daily-trend-parameters-v1"] = "daily-trend-parameters-v1"
    window: StrictInt = Field(gt=0)


class ReferenceExecutionSpec(DomainModel):
    schema_version: Literal["reference-execution-v1"] = "reference-execution-v1"
    initial_cash: Decimal = Field(gt=0, allow_inf_nan=False)


class FixtureMetricPolicy(DomainModel):
    """All non-observation inputs required to calculate MetricSet v1."""

    schema_version: Literal["fixture-metric-policy-v1"] = "fixture-metric-policy-v1"
    return_basis: ReturnBasis
    annualization: AnnualizationPolicy
    volatility_ddof: StrictInt = Field(ge=0)
    risk_free: RiskFreePolicy


class FixtureRunSpec(DomainModel):
    """Complete scientific intent that is missing from legacy ExperimentConfig."""

    schema_version: Literal["fixture-run-spec-v1"] = "fixture-run-spec-v1"
    mode: Literal["fixture"] = "fixture"
    fixture_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
    experiment: ExperimentConfig
    strategy_parameters: DailyTrendParameters
    consumed_sessions: ConsumedSessionRange
    execution: ReferenceExecutionSpec
    metrics: FixtureMetricPolicy

    @model_validator(mode="after")
    def validate_fixture_capability(self) -> FixtureRunSpec:
        if self.fixture_id.casefold() == "latest":
            raise ValueError("implicit latest fixture selection is forbidden")
        if not isinstance(self.experiment.dataset, DataSnapshot):
            raise ValueError("fixture mode requires a legacy DataSnapshot")
        if self.fixture_id != self.experiment.dataset.dataset_id:
            raise ValueError("fixture_id must equal the DataSnapshot dataset_id")
        if self.experiment.dataset.source != "fixture":
            raise ValueError("fixture mode requires an explicitly declared fixture source")
        if self.experiment.frequency is not BarFrequency.DAY:
            raise ValueError("fixture-run-spec v1 requires daily input")
        if self.experiment.strategy.strategy_id != "daily_trend":
            raise ValueError("fixture-run-spec v1 supports only daily_trend")
        raw_window = self.experiment.parameters.get("window")
        if type(raw_window) is not int:
            raise ValueError("daily_trend window must be a strict non-bool integer")
        expected_parameters = {"window": self.strategy_parameters.window}
        if self.experiment.parameters != expected_parameters:
            raise ValueError("daily_trend parameters must contain only a strict window")
        if self.experiment.engine.engine_id != "reference":
            raise ValueError("fixture-run-spec v1 requires the reference engine")
        if (
            self.experiment.cost_model.minimum_commission != 0
            or self.experiment.cost_model.stamp_duty_bps != 0
        ):
            raise ValueError("reference engine does not support declared fixed or stamp costs")
        assumptions = self.experiment.execution
        if (
            assumptions.decision_time is not DecisionTime.BAR_CLOSE
            or assumptions.execution_price is not ExecutionPrice.NEXT_OPEN
            or assumptions.signal_lag_bars != 1
            or not assumptions.allow_fractional
        ):
            raise ValueError("fixture-run-spec v1 requires the accepted execution assumptions")
        return self

    @property
    def fixture_run_spec_id(self) -> str:
        validated = type(self).model_validate(self.model_dump(mode="python"))
        payload = {
            "schema_version": validated.schema_version,
            "mode": validated.mode,
            "fixture_id": validated.fixture_id,
            "experiment": validated.experiment,
            "strategy_parameters": validated.strategy_parameters,
            "consumed_sessions": validated.consumed_sessions,
            "execution": validated.execution,
            "metrics": validated.metrics,
        }
        return stable_hash(
            _scientific_identity_value(payload),
            namespace="fixture-run-spec",
        )

    def run_id(self, runtime: RuntimeContext) -> str:
        validated_runtime = RuntimeContext.model_validate(runtime.model_dump(mode="python"))
        return stable_hash(
            {
                "fixture_run_spec_id": self.fixture_run_spec_id,
                "runtime": validated_runtime,
            },
            namespace="run",
        )


class PlanFixtureCommand(DomainModel):
    schema_version: Literal["plan-fixture-command-v1"] = "plan-fixture-command-v1"
    spec: FixtureRunSpec
    runtime: RuntimeContext


class RunFixtureCommand(DomainModel):
    """Reserved command shape; no run handler exists before CORE-06/artifact v2."""

    schema_version: Literal["run-fixture-command-v1"] = "run-fixture-command-v1"
    spec: FixtureRunSpec
    runtime: RuntimeContext


class InspectRunCommand(DomainModel):
    schema_version: Literal["inspect-run-command-v1"] = "inspect-run-command-v1"
    manifest_path: str = Field(min_length=1, max_length=2048)

    @model_validator(mode="after")
    def validate_portable_relative_path(self) -> InspectRunCommand:
        if "\\" in self.manifest_path:
            raise ValueError("manifest_path must use portable POSIX separators")
        if any(ord(character) < 32 or ord(character) == 127 for character in self.manifest_path):
            raise ValueError("manifest_path must not contain control characters")
        path = PurePosixPath(self.manifest_path)
        if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
            raise ValueError("manifest_path must be a canonical relative path")
        if any(part.casefold() == "latest" for part in path.parts) or (
            path.stem.casefold() == "latest"
        ):
            raise ValueError("implicit latest manifest selection is forbidden")
        if path.as_posix() != self.manifest_path or path.suffix != ".json":
            raise ValueError("manifest_path must be a canonical JSON path")
        return self


class PlanResult(DomainModel):
    schema_version: Literal["fixture-plan-result-v1"] = "fixture-plan-result-v1"
    disposition: Literal[PlanDisposition.STRUCTURALLY_READY] = (
        PlanDisposition.STRUCTURALLY_READY
    )
    command: PlanFixtureCommand
    experiment_id: str = Field(pattern=r"^exp_[a-f0-9]{12,64}$")
    fixture_run_spec_id: str = Field(pattern=r"^fixture-run-spec_[a-f0-9]{24}$")
    run_id: str = Field(pattern=r"^run_[a-f0-9]{12,64}$")

    @classmethod
    def create(cls, command: PlanFixtureCommand) -> PlanResult:
        validated = PlanFixtureCommand.model_validate(command.model_dump(mode="python"))
        return cls(
            command=validated,
            experiment_id=validated.spec.experiment.experiment_id,
            fixture_run_spec_id=validated.spec.fixture_run_spec_id,
            run_id=validated.spec.run_id(validated.runtime),
        )

    @model_validator(mode="after")
    def validate_derived_identities(self) -> PlanResult:
        command = PlanFixtureCommand.model_validate(self.command.model_dump(mode="python"))
        if self.experiment_id != command.spec.experiment.experiment_id:
            raise ValueError("plan experiment_id does not match its command")
        if self.fixture_run_spec_id != command.spec.fixture_run_spec_id:
            raise ValueError("plan fixture_run_spec_id does not match its command")
        if self.run_id != command.spec.run_id(command.runtime):
            raise ValueError("plan run_id does not match its command")
        return self

    def _revalidated(self) -> PlanResult:
        return type(self).model_validate(
            {
                "schema_version": self.schema_version,
                "disposition": self.disposition,
                "command": self.command,
                "experiment_id": self.experiment_id,
                "fixture_run_spec_id": self.fixture_run_spec_id,
                "run_id": self.run_id,
            }
        )

    @model_serializer(mode="wrap")
    def serialize_validated(self, handler: Any) -> Any:
        try:
            validated = self._revalidated()
        except (TypeError, ValueError):
            raise ValueError("PlanResult failed integrity validation") from None
        return handler(validated)


class InspectResult(DomainModel):
    """Portable summary; authority comes from the handler's verified store read."""

    schema_version: Literal["inspect-result-v1"] = "inspect-result-v1"
    integrity_status: Literal["verified"] = "verified"
    trust_scope: Literal[ArtifactTrustScope.ARTIFACT_V1_INTEGRITY_ONLY] = (
        ArtifactTrustScope.ARTIFACT_V1_INTEGRITY_ONLY
    )
    experiment_id: str = Field(pattern=r"^exp_[a-f0-9]{12,64}$")
    run_id: str = Field(pattern=r"^run_[a-f0-9]{12,64}$")
    artifact: ArtifactRef
    manifest_path: str = Field(min_length=1, max_length=2048)
    manifest_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    point_count: int = Field(ge=0)
    trade_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_manifest_path(self) -> InspectResult:
        ArtifactRef.model_validate(self.artifact.model_dump(mode="python"))
        InspectRunCommand(manifest_path=self.manifest_path)
        return self

    def _revalidated(self) -> InspectResult:
        return type(self).model_validate(
            {
                "schema_version": self.schema_version,
                "integrity_status": self.integrity_status,
                "trust_scope": self.trust_scope,
                "experiment_id": self.experiment_id,
                "run_id": self.run_id,
                "artifact": self.artifact,
                "manifest_path": self.manifest_path,
                "manifest_hash": self.manifest_hash,
                "point_count": self.point_count,
                "trade_count": self.trade_count,
            }
        )

    @model_serializer(mode="wrap")
    def serialize_validated(self, handler: Any) -> Any:
        try:
            validated = self._revalidated()
        except (TypeError, ValueError):
            raise ValueError("InspectResult failed integrity validation") from None
        return handler(validated)
