"""Provider-independent market-data and quality-report models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from quantverify.core.models import AssetId, DomainModel

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
    event_at: datetime
    available_at: datetime
    open: PositiveDecimal
    high: PositiveDecimal
    low: PositiveDecimal
    close: PositiveDecimal
    volume: NonNegativeDecimal
    source: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_market_semantics(self) -> NormalizedBar:
        if self.event_at.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("event_at and available_at must be timezone-aware")
        if self.available_at < self.event_at:
            raise ValueError("available_at cannot be earlier than event_at")
        if self.high < self.low:
            raise ValueError("high must be greater than or equal to low")
        if not self.low <= self.open <= self.high:
            raise ValueError("open must be between low and high")
        if not self.low <= self.close <= self.high:
            raise ValueError("close must be between low and high")
        return self


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
