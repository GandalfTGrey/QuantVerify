"""Provider-independent market-data and quality-report models."""

from __future__ import annotations

from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from quantverify.core.enums import BarFrequency
from quantverify.core.identity import stable_hash
from quantverify.core.models import AssetId, DomainModel, SeriesDescriptor, SessionSchedule

PositiveDecimal = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


class DataQualityStatus(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    MISSING = "missing"


class NormalizedBar(DomainModel):
    """A daily bar whose event and availability times are explicit."""

    asset: AssetId
    session: date
    session_open_at: datetime
    session_close_at: datetime
    available_at: datetime
    open: PositiveDecimal
    high: PositiveDecimal
    low: PositiveDecimal
    close: PositiveDecimal
    volume: NonNegativeDecimal
    source: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_market_semantics(self) -> NormalizedBar:
        timestamps = (self.session_open_at, self.session_close_at, self.available_at)
        if any(timestamp.tzinfo is None for timestamp in timestamps):
            raise ValueError("session and availability timestamps must be timezone-aware")
        if self.session_open_at >= self.session_close_at:
            raise ValueError("session_open_at must be earlier than session_close_at")
        if self.available_at < self.session_close_at:
            raise ValueError("available_at cannot be earlier than session_close_at")
        if self.high < self.low:
            raise ValueError("high must be greater than or equal to low")
        if not self.low <= self.open <= self.high:
            raise ValueError("open must be between low and high")
        if not self.low <= self.close <= self.high:
            raise ValueError("close must be between low and high")
        return self


class DerivedPeriodBar(DomainModel):
    """A causal weekly/monthly bar derived from an immutable source series."""

    series: SeriesDescriptor
    period_start: date
    period_end: date
    constituent_schedule: SessionSchedule
    expected_schedule: SessionSchedule
    constituent_available_at: tuple[datetime, ...] = Field(min_length=1)
    cutoff_at: datetime
    open: PositiveDecimal
    high: PositiveDecimal
    low: PositiveDecimal
    close: PositiveDecimal
    volume: NonNegativeDecimal

    @model_validator(mode="after")
    def validate_period_semantics(self) -> DerivedPeriodBar:
        if self.series.frequency not in (BarFrequency.WEEK, BarFrequency.MONTH):
            raise ValueError("derived period bars require weekly or monthly frequency")
        self._validate_period_bounds()
        if self.constituent_schedule.calendar != self.expected_schedule.calendar:
            raise ValueError("constituent and expected schedules must use one calendar artifact")
        if self.series.calendar != self.expected_schedule.calendar:
            raise ValueError("series and period schedules must use one calendar artifact")
        for schedule in (self.constituent_schedule, self.expected_schedule):
            if (
                schedule.requested_start != self.period_start
                or schedule.requested_end != self.period_end
            ):
                raise ValueError("period schedules must cover the complete period boundary")

        actual_sessions = self.constituent_schedule.sessions
        expected_sessions = self.expected_schedule.sessions
        expected_by_label = {item.session: item for item in expected_sessions}
        matching_expected = tuple(
            expected_by_label.get(item.session) for item in actual_sessions
        )
        if matching_expected != actual_sessions:
            raise ValueError("constituent sessions must be an exact subset of expected sessions")
        if len(self.constituent_available_at) != len(actual_sessions):
            raise ValueError("constituent availability count must match constituent sessions")
        if self.cutoff_at.tzinfo is None or any(
            timestamp.tzinfo is None for timestamp in self.constituent_available_at
        ):
            raise ValueError("cutoff and constituent availability must be timezone-aware")
        for trading_session, available_at in zip(
            actual_sessions,
            self.constituent_available_at,
            strict=True,
        ):
            if available_at < trading_session.session_close_at:
                raise ValueError("constituent availability cannot precede its session close")
            if available_at > self.cutoff_at:
                raise ValueError("constituent availability cannot be later than cutoff")
        if self.high < self.low:
            raise ValueError("high must be greater than or equal to low")
        if not self.low <= self.open <= self.high:
            raise ValueError("open must be between low and high")
        if not self.low <= self.close <= self.high:
            raise ValueError("close must be between low and high")
        return self

    def _validate_period_bounds(self) -> None:
        if self.series.frequency is BarFrequency.WEEK:
            if self.period_start.weekday() != 0 or self.period_end != self.period_start + timedelta(
                days=6
            ):
                raise ValueError("weekly period must use a Monday through Sunday boundary")
        elif (
            self.period_start.day != 1
            or self.period_end.day != monthrange(self.period_end.year, self.period_end.month)[1]
            or (self.period_start.year, self.period_start.month)
            != (self.period_end.year, self.period_end.month)
        ):
            raise ValueError("monthly period must use one natural calendar month")

    @property
    def constituent_start(self) -> date:
        return self.constituent_schedule.sessions[0].session

    @property
    def constituent_end(self) -> date:
        return self.constituent_schedule.sessions[-1].session

    @property
    def constituent_count(self) -> int:
        return len(self.constituent_schedule.sessions)

    @property
    def expected_constituent_count(self) -> int:
        return len(self.expected_schedule.sessions)

    @property
    def period_open_at(self) -> datetime:
        return self.constituent_schedule.sessions[0].session_open_at

    @property
    def period_close_at(self) -> datetime:
        return self.constituent_schedule.sessions[-1].session_close_at

    @property
    def available_at(self) -> datetime:
        return max(self.constituent_available_at)

    @property
    def complete(self) -> bool:
        return self.constituent_schedule.sessions == self.expected_schedule.sessions

    @property
    def period_bar_id(self) -> str:
        payload = {
            "series": self.series,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "constituent_schedule_id": self.constituent_schedule.schedule_id,
            "expected_schedule_id": self.expected_schedule.schedule_id,
            "constituent_available_at": tuple(
                timestamp.astimezone(UTC) for timestamp in self.constituent_available_at
            ),
            "cutoff_at": self.cutoff_at.astimezone(UTC),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }
        return stable_hash(payload, namespace="period-bar")


class CrossSourcePolicy(DomainModel):
    """Versioned tolerances for comparing the same raw field across providers."""

    policy_version: str = Field(default="1", min_length=1, max_length=32)
    pass_tolerance_bps: NonNegativeDecimal = Decimal("10")
    warning_tolerance_bps: NonNegativeDecimal = Decimal("50")

    @model_validator(mode="after")
    def validate_tolerances(self) -> CrossSourcePolicy:
        if self.pass_tolerance_bps > self.warning_tolerance_bps:
            raise ValueError("pass tolerance must not exceed warning tolerance")
        return self


class CrossSourceCheck(DomainModel):
    session: date
    primary_source: str
    secondary_source: str
    primary_close: Decimal | None = None
    secondary_close: Decimal | None = None
    difference_bps: Decimal | None = None
    status: DataQualityStatus
    reason: str | None = None


class DataQualityReport(DomainModel):
    asset: AssetId
    policy_version: str
    overall_status: DataQualityStatus
    total_sessions: int = Field(ge=0)
    overlapping_sessions: int = Field(ge=0)
    pass_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    fail_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    checks: tuple[CrossSourceCheck, ...]
