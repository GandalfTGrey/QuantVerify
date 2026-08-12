"""Framework-independent domain models for reproducible research."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

from quantverify.core.enums import (
    AdjustmentMode,
    AssetClass,
    BarFrequency,
    DecisionTime,
    ExecutionPrice,
    SeriesSourceKind,
)
from quantverify.core.identity import stable_hash

NonNegativeDecimal = Annotated[Decimal, Field(ge=0)]
PositionWeight = Annotated[Decimal, Field(allow_inf_nan=False)]


class DomainModel(BaseModel):
    """Base model: immutable, strict about unknown input, and serialization friendly."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class AssetId(DomainModel):
    symbol: str = Field(min_length=1, max_length=64)
    venue: str = Field(min_length=1, max_length=32)
    asset_class: AssetClass
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class TimeRange(DomainModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_range(self) -> TimeRange:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        if self.start >= self.end:
            raise ValueError("start must be earlier than end")
        return self


class TradingSession(DomainModel):
    """One actual exchange session with executable open and close timestamps."""

    session: date
    session_open_at: datetime
    session_close_at: datetime

    @model_validator(mode="after")
    def validate_times(self) -> TradingSession:
        if self.session_open_at.tzinfo is None or self.session_close_at.tzinfo is None:
            raise ValueError("session timestamps must be timezone-aware")
        if self.session_open_at >= self.session_close_at:
            raise ValueError("session_open_at must be earlier than session_close_at")
        return self


class SessionSchedule(DomainModel):
    """Exact expected sessions for an input range, not an inferred row sequence."""

    calendar_id: str = Field(min_length=1, max_length=128)
    calendar_version: str = Field(min_length=1, max_length=64)
    timezone: str = Field(min_length=1, max_length=64)
    sessions: tuple[TradingSession, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_schedule(self) -> SessionSchedule:
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone: {self.timezone}") from exc

        for previous, current in zip(self.sessions, self.sessions[1:], strict=False):
            if previous.session >= current.session:
                raise ValueError("sessions must be strictly ordered by session date")
            if previous.session_close_at >= current.session_open_at:
                raise ValueError("sessions must not overlap or run backwards")
        return self

    @property
    def schedule_id(self) -> str:
        return stable_hash(self, namespace="session-schedule")


class SeriesDescriptor(DomainModel):
    """Versioned market-series semantics and immutable upstream lineage."""

    asset: AssetId
    frequency: BarFrequency
    adjustment_mode: AdjustmentMode
    source_kind: SeriesSourceKind
    source_id: str = Field(min_length=1, max_length=128)
    source_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_schema_version: str = Field(min_length=1, max_length=32)
    producer_id: str = Field(min_length=1, max_length=128)
    producer_version: str = Field(min_length=1, max_length=64)
    calendar_id: str = Field(min_length=1, max_length=128)
    calendar_version: str = Field(min_length=1, max_length=64)

    @property
    def series_id(self) -> str:
        return stable_hash(self, namespace="market-series")


class DataSnapshot(DomainModel):
    dataset_id: str = Field(min_length=1, max_length=128)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    schema_version: str = Field(min_length=1, max_length=32)
    source: str = Field(min_length=1, max_length=128)
    captured_at: datetime
    adjustment_mode: AdjustmentMode

    @model_validator(mode="after")
    def validate_timestamp(self) -> DataSnapshot:
        if self.captured_at.tzinfo is None:
            raise ValueError("captured_at must be timezone-aware")
        return self


class StrategyVersion(DomainModel):
    strategy_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    version: str = Field(min_length=1, max_length=64)
    code_hash: str = Field(pattern=r"^[a-f0-9]{7,64}$")


class CostModel(DomainModel):
    commission_bps: NonNegativeDecimal = Decimal("0")
    slippage_bps: NonNegativeDecimal = Decimal("0")
    minimum_commission: NonNegativeDecimal = Decimal("0")
    stamp_duty_bps: NonNegativeDecimal = Decimal("0")


class ExecutionAssumptions(DomainModel):
    """Causal boundary between an observed signal and an executable position."""

    decision_time: DecisionTime = DecisionTime.BAR_CLOSE
    execution_price: ExecutionPrice = ExecutionPrice.NEXT_OPEN
    signal_lag_bars: int = Field(default=1, ge=1)
    allow_fractional: bool = True


class ValidationConfig(DomainModel):
    train_fraction: float = Field(default=0.6, gt=0, lt=1)
    validation_fraction: float = Field(default=0.2, gt=0, lt=1)
    test_fraction: float = Field(default=0.2, gt=0, lt=1)
    purge_bars: int = Field(default=0, ge=0)
    embargo_bars: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_fractions(self) -> ValidationConfig:
        total = self.train_fraction + self.validation_fraction + self.test_fraction
        if abs(total - 1.0) > 1e-9:
            raise ValueError("train, validation, and test fractions must sum to 1")
        return self


class EngineVersion(DomainModel):
    engine_id: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=64)


class ExperimentConfig(DomainModel):
    """Scientific intent. Equal configs must always receive the same experiment ID."""

    strategy: StrategyVersion
    universe_id: str = Field(min_length=1, max_length=128)
    dataset: DataSnapshot
    period: TimeRange
    frequency: BarFrequency
    parameters: dict[str, Any] = Field(default_factory=dict)
    benchmark_id: str = Field(min_length=1, max_length=128)
    cost_model: CostModel = Field(default_factory=CostModel)
    execution: ExecutionAssumptions = Field(default_factory=ExecutionAssumptions)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    engine: EngineVersion
    base_currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    random_seed: int = Field(default=0, ge=0, le=2**32 - 1)

    @property
    def experiment_id(self) -> str:
        return stable_hash(self, namespace="exp")


class RuntimeContext(DomainModel):
    """Execution environment. It changes run identity, not scientific intent."""

    source_commit: str = Field(pattern=r"^[a-f0-9]{7,64}$")
    environment_lock_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    worker_id: str = Field(min_length=1, max_length=128)


class ExperimentIdentity(DomainModel):
    experiment_id: str
    run_id: str

    @classmethod
    def create(cls, config: ExperimentConfig, runtime: RuntimeContext) -> ExperimentIdentity:
        experiment_id = config.experiment_id
        run_id = stable_hash(
            {"experiment_id": experiment_id, "runtime": runtime},
            namespace="run",
        )
        return cls(experiment_id=experiment_id, run_id=run_id)


class TargetPosition(DomainModel):
    asset: AssetId
    decision_at: datetime
    effective_at: datetime
    weight: PositionWeight

    @model_validator(mode="after")
    def validate_causality(self) -> TargetPosition:
        if self.decision_at.tzinfo is None or self.effective_at.tzinfo is None:
            raise ValueError("decision_at and effective_at must be timezone-aware")
        if self.effective_at <= self.decision_at:
            raise ValueError("effective_at must be later than decision_at")
        return self


class ArtifactRef(DomainModel):
    kind: str = Field(min_length=1, max_length=64)
    uri: str = Field(min_length=1, max_length=2048)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    schema_version: str = Field(min_length=1, max_length=32)
