"""Framework-independent domain models for reproducible research."""

from __future__ import annotations

from datetime import UTC, date, datetime
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
    SessionLabelPolicy,
)
from quantverify.core.identity import full_hash, stable_hash

NonNegativeDecimal = Annotated[Decimal, Field(ge=0)]
PositionWeight = Annotated[Decimal, Field(allow_inf_nan=False)]


class DomainModel(BaseModel):
    """Base model: immutable, strict about unknown input, and serialization friendly."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
        str_strip_whitespace=True,
    )


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


class CalendarArtifactRef(DomainModel):
    """Immutable provenance and label semantics for an exchange calendar artifact."""

    calendar_id: str = Field(min_length=1, max_length=128)
    calendar_version: str = Field(min_length=1, max_length=64)
    timezone: str = Field(min_length=1, max_length=64)
    session_label_policy: SessionLabelPolicy
    source_id: str = Field(min_length=1, max_length=128)
    source_version: str = Field(min_length=1, max_length=64)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_timezone(self) -> CalendarArtifactRef:
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone: {self.timezone}") from exc
        return self


class SessionSchedule(DomainModel):
    """Exact expected sessions for an input range, not an inferred row sequence."""

    requested_start: date
    requested_end: date
    calendar: CalendarArtifactRef
    sessions: tuple[TradingSession, ...] = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @classmethod
    def create(
        cls,
        *,
        requested_start: date,
        requested_end: date,
        calendar: CalendarArtifactRef,
        sessions: tuple[TradingSession, ...],
    ) -> SessionSchedule:
        validated_calendar = CalendarArtifactRef.model_validate(
            calendar.model_dump(mode="python")
        )
        validated_sessions = tuple(
            TradingSession.model_validate(item.model_dump(mode="python"))
            for item in sessions
        )
        payload = cls._content_payload(
            requested_start=requested_start,
            requested_end=requested_end,
            calendar=validated_calendar,
            sessions=validated_sessions,
        )
        return cls(
            requested_start=requested_start,
            requested_end=requested_end,
            calendar=validated_calendar,
            sessions=validated_sessions,
            content_hash=full_hash(payload),
        )

    @model_validator(mode="after")
    def validate_schedule(self) -> SessionSchedule:
        if self.requested_start > self.requested_end:
            raise ValueError("requested_start must not be later than requested_end")

        timezone = ZoneInfo(self.calendar.timezone)
        policy = self.calendar.session_label_policy
        for trading_session in self.sessions:
            if not self.requested_start <= trading_session.session <= self.requested_end:
                raise ValueError("session label must be contained in the requested range")
            if policy is SessionLabelPolicy.CLOSE_LOCAL_DATE:
                expected_label = trading_session.session_close_at.astimezone(timezone).date()
                if trading_session.session != expected_label:
                    raise ValueError("session label must match the local close date")
            elif policy is SessionLabelPolicy.OPEN_LOCAL_DATE:
                expected_label = trading_session.session_open_at.astimezone(timezone).date()
                if trading_session.session != expected_label:
                    raise ValueError("session label must match the local open date")

        for previous, current in zip(self.sessions, self.sessions[1:], strict=False):
            if previous.session >= current.session:
                raise ValueError("sessions must be strictly ordered by session date")
            if previous.session_close_at >= current.session_open_at:
                raise ValueError("sessions must not overlap or run backwards")
        expected_hash = full_hash(
            self._content_payload(
                requested_start=self.requested_start,
                requested_end=self.requested_end,
                calendar=self.calendar,
                sessions=self.sessions,
            )
        )
        if self.content_hash != expected_hash:
            raise ValueError("session schedule content hash does not match its sessions")
        return self

    @staticmethod
    def _content_payload(
        *,
        requested_start: date,
        requested_end: date,
        calendar: CalendarArtifactRef,
        sessions: tuple[TradingSession, ...],
    ) -> dict[str, Any]:
        return {
            "requested_start": requested_start,
            "requested_end": requested_end,
            "calendar": calendar,
            "sessions": tuple(
                {
                    "session": item.session,
                    "session_open_at": item.session_open_at.astimezone(UTC),
                    "session_close_at": item.session_close_at.astimezone(UTC),
                }
                for item in sessions
            ),
        }

    @property
    def schedule_id(self) -> str:
        if not isinstance(self.sessions, tuple):
            raise ValueError("sessions must remain an immutable tuple")
        validated = type(self).model_validate(self.model_dump(mode="python"))
        return stable_hash(validated.content_hash, namespace="session-schedule")


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
    calendar: CalendarArtifactRef

    @property
    def descriptor_id(self) -> str:
        validated = type(self).model_validate(self.model_dump(mode="python"))
        return stable_hash(validated, namespace="series-descriptor")


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
