"""Versioned policies used to turn quality evidence into range eligibility."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from quantverify.core.models import DomainModel

NonNegativeDecimal = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


class CrossSourceRequirement(StrEnum):
    OPTIONAL = "optional"
    REQUIRED = "required"


class QualityPolicy(DomainModel):
    policy_id: str = Field(
        default="market-data-research-v2",
        pattern=r"^[a-z][a-z0-9._-]{1,63}$",
    )
    version: str = Field(default="1", min_length=1, max_length=64)
    cross_source_requirement: CrossSourceRequirement = CrossSourceRequirement.OPTIONAL
    price_pass_tolerance_bps: NonNegativeDecimal = Decimal("10")
    price_warning_tolerance_bps: NonNegativeDecimal = Decimal("50")
    revision_blocks_requested_range: bool = False

    @model_validator(mode="after")
    def validate_tolerances(self) -> QualityPolicy:
        if self.price_pass_tolerance_bps > self.price_warning_tolerance_bps:
            raise ValueError("pass tolerance must not exceed warning tolerance")
        return self

    @property
    def minimum_sources_per_session(self) -> int:
        if self.cross_source_requirement is CrossSourceRequirement.REQUIRED:
            return 2
        return 1
