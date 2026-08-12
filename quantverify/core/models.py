"""Framework-independent domain models for reproducible research."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from itertools import pairwise
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


class EligibleInterval(DomainModel):
    """One inclusive, exact-session interval proved by one A3 report replay."""

    start_session: date
    end_session: date
    session_count: int = Field(ge=1)
    expected_sessions_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    quality_report_id: str = Field(pattern=r"^dqr_[a-f0-9]{24}$")
    quality_report_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    warning_finding_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_interval(self) -> EligibleInterval:
        if self.start_session > self.end_session:
            raise ValueError("eligible interval start must not follow its end")
        if len(self.warning_finding_ids) != len(set(self.warning_finding_ids)):
            raise ValueError("warning finding identities must be unique")
        if tuple(sorted(self.warning_finding_ids)) != self.warning_finding_ids:
            raise ValueError("warning finding identities must be sorted")
        if any(
            not re.fullmatch(r"dqf_[a-f0-9]{24}", finding_id)
            for finding_id in self.warning_finding_ids
        ):
            raise ValueError("warning finding identity is invalid")
        return self


class DatasetReleaseRef(DomainModel):
    """Scientific reference shape; Gold authenticity requires a verified resolver."""

    release_schema_version: str = Field(
        default="dataset-release-ref-v1", pattern=r"^dataset-release-ref-v1$"
    )
    asset: AssetId
    frequency: BarFrequency
    adjustment_mode: AdjustmentMode
    normalized_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    normalized_schema_version: str = Field(min_length=1, max_length=64)
    normalizer_id: str = Field(min_length=1, max_length=128)
    normalizer_version: str = Field(min_length=1, max_length=128)
    selected_evidence_id: str = Field(pattern=r"^dqe_[a-f0-9]{24}$")
    selected_normalized_input_id: str = Field(pattern=r"^dqi_[a-f0-9]{24}$")
    quality_suite_id: str = Field(min_length=1, max_length=64)
    quality_suite_version: str = Field(min_length=1, max_length=32)
    quality_policy_id: str = Field(min_length=1, max_length=64)
    quality_policy_version: str = Field(min_length=1, max_length=64)
    quality_policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    calendar: CalendarArtifactRef
    schedule_id: str = Field(pattern=r"^session-schedule_[a-f0-9]{24}$")
    schedule_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    schedule_requested_start: date
    schedule_requested_end: date
    schedule_session_count: int = Field(ge=1)
    eligible_intervals: tuple[EligibleInterval, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_release_semantics(self) -> DatasetReleaseRef:
        if self.frequency is not BarFrequency.DAY:
            raise ValueError("DatasetReleaseRef v1 requires daily normalized data")
        if self.adjustment_mode is not AdjustmentMode.RAW:
            raise ValueError("DatasetReleaseRef v1 requires RAW adjustment semantics")
        if (
            self.quality_suite_id != "quantverify-quality-suite"
            or self.quality_suite_version != "2"
        ):
            raise ValueError("DatasetReleaseRef v1 requires the accepted A3 suite")
        if self.schedule_requested_start > self.schedule_requested_end:
            raise ValueError("release schedule range is invalid")
        intervals = self.eligible_intervals
        if tuple(
            sorted(
                intervals,
                key=lambda item: (
                    item.start_session,
                    item.end_session,
                    item.quality_report_id,
                ),
            )
        ) != intervals:
            raise ValueError("eligible intervals must be sorted by start session")
        if any(
            interval.start_session < self.schedule_requested_start
            or interval.end_session > self.schedule_requested_end
            for interval in intervals
        ):
            raise ValueError("eligible interval must fit the pinned schedule range")
        report_ids = tuple(interval.quality_report_id for interval in intervals)
        if len(report_ids) != len(set(report_ids)):
            raise ValueError("each eligible interval requires a distinct quality report")
        if sum(interval.session_count for interval in intervals) > self.schedule_session_count:
            raise ValueError("eligible interval sessions exceed the pinned schedule")
        for previous, current in pairwise(intervals):
            if previous.end_session >= current.start_session:
                raise ValueError("eligible intervals must not overlap")
        return self

    def supports_consumed_schedule(self, schedule: SessionSchedule) -> bool:
        """Structurally gate a verified consumed schedule against one interval."""

        self._require_immutable_sequences()
        validated = type(self).model_validate(self.model_dump(mode="python"))
        try:
            consumed = SessionSchedule.model_validate(schedule.model_dump(mode="python"))
        except (AttributeError, TypeError, ValueError):
            raise ValueError("consumed schedule failed integrity validation") from None
        if consumed.calendar != validated.calendar:
            return False
        if (
            consumed.requested_start < validated.schedule_requested_start
            or consumed.requested_end > validated.schedule_requested_end
        ):
            return False
        first = consumed.sessions[0].session
        last = consumed.sessions[-1].session
        return any(
            interval.start_session <= first <= last <= interval.end_session
            for interval in validated.eligible_intervals
        )

    @property
    def release_id(self) -> str:
        self._require_immutable_sequences()
        validated = type(self).model_validate(self.model_dump(mode="python"))
        return stable_hash(validated, namespace="drel")

    def _require_immutable_sequences(self) -> None:
        if not isinstance(self.eligible_intervals, tuple) or any(
            not isinstance(interval, EligibleInterval)
            or not isinstance(interval.warning_finding_ids, tuple)
            for interval in self.eligible_intervals
        ):
            raise ValueError("release sequences must remain immutable tuples")


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
    dataset: DataSnapshot | DatasetReleaseRef
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

    @model_validator(mode="after")
    def validate_dataset_frequency(self) -> ExperimentConfig:
        if (
            isinstance(self.dataset, DatasetReleaseRef)
            and self.frequency is not self.dataset.frequency
        ):
            raise ValueError("experiment frequency must match its DatasetReleaseRef")
        return self

    @property
    def experiment_id(self) -> str:
        validated = type(self).model_validate(self.model_dump(mode="python"))
        return stable_hash(validated, namespace="exp")


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
