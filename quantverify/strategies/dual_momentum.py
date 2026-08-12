"""Signal-only S5 monthly dual-momentum reference strategy."""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from typing import Literal

from pydantic import model_validator

from quantverify.core.enums import AdjustmentMode, AssetClass, BarFrequency
from quantverify.core.exceptions import DataQualityError
from quantverify.core.identity import stable_hash
from quantverify.core.models import AssetId, DomainModel, SeriesDescriptor
from quantverify.data.models import DerivedPeriodBar
from quantverify.features.momentum import trailing_total_return
from quantverify.research.frequency import require_complete_period_bars

S5_LOOKBACK_MONTHS = 12
S5_ZERO_HURDLE = Decimal("0")
S5_HURDLE_POLICY_ID: Literal["strict-positive-zero-v1"] = "strict-positive-zero-v1"
S5_SIGNAL_SCHEMA_VERSION: Literal["1"] = "1"
S5_STRATEGY_VERSION: Literal["1"] = "1"


class DualMomentumReason(StrEnum):
    """Closed reasons for the signal-only S5 decision."""

    RISK_ON = "risk_on"
    CASH = "cash_non_positive"
    TIE = "relative_tie"


class DualMomentumSignal(DomainModel):
    """Immutable S5 research signal without execution or position semantics."""

    schema_version: Literal["1"] = S5_SIGNAL_SCHEMA_VERSION
    strategy_version: Literal["1"] = S5_STRATEGY_VERSION
    observed_period_start: date
    observed_period_end: date
    decision_at: datetime
    qqq_asset: AssetId
    dia_asset: AssetId
    qqq_return: Decimal
    dia_return: Decimal
    selected_asset: AssetId | None
    reason: DualMomentumReason
    hurdle: Decimal = S5_ZERO_HURDLE
    hurdle_policy_id: Literal["strict-positive-zero-v1"] = S5_HURDLE_POLICY_ID

    @model_validator(mode="after")
    def validate_signal_semantics(self) -> DualMomentumSignal:
        if self.observed_period_start.day != 1 or self.observed_period_end != date(
            self.observed_period_start.year,
            self.observed_period_start.month,
            monthrange(self.observed_period_start.year, self.observed_period_start.month)[1],
        ):
            raise ValueError("observed period must be one complete natural month")
        if self.decision_at.tzinfo is None:
            raise ValueError("decision_at must be timezone-aware")
        if not self.qqq_return.is_finite() or not self.dia_return.is_finite():
            raise ValueError("momentum returns must be finite")
        if self.qqq_return <= Decimal("-1") or self.dia_return <= Decimal("-1"):
            raise ValueError("momentum returns must be greater than -1")
        if self.hurdle != S5_ZERO_HURDLE:
            raise ValueError("S5 v1 requires the versioned zero hurdle")
        _validate_canonical_asset(self.qqq_asset, symbol="QQQ", venue="XNAS")
        _validate_canonical_asset(self.dia_asset, symbol="DIA", venue="ARCX")

        if self.qqq_return == self.dia_return:
            if self.reason is not DualMomentumReason.TIE or self.selected_asset is not None:
                raise ValueError("equal relative momentum requires explicit tie/no selection")
            return self

        winner = self.qqq_asset if self.qqq_return > self.dia_return else self.dia_asset
        winner_return = max(self.qqq_return, self.dia_return)
        if winner_return > self.hurdle:
            if (
                self.reason is not DualMomentumReason.RISK_ON
                or self.selected_asset != winner
            ):
                raise ValueError("positive winning momentum requires the winning asset")
        elif self.reason is not DualMomentumReason.CASH or self.selected_asset is not None:
            raise ValueError("non-positive winning momentum requires cash/no selection")
        return self

    @property
    def signal_id(self) -> str:
        """Return semantic signal identity, not source-lineage evidence identity.

        Experiment and artifact identities must separately bind the two input
        descriptor identities and their immutable source lineage.
        """

        validated = type(self).model_validate(self.model_dump(mode="python"))
        payload = validated.model_dump(mode="python")
        payload["decision_at"] = validated.decision_at.astimezone(UTC)
        return stable_hash(payload, namespace="dual-momentum-signal")


def monthly_dual_momentum_signals(
    series: Sequence[Sequence[DerivedPeriodBar]],
) -> tuple[DualMomentumSignal, ...]:
    """Return S5 signals from exactly the aligned QQQ and DIA monthly series."""

    if len(series) != 2:
        raise DataQualityError("S5 requires exactly two monthly series")
    first = require_complete_period_bars(series[0])
    second = require_complete_period_bars(series[1])
    if not first or not second:
        raise DataQualityError("S5 requires two non-empty monthly series")

    _validate_one_series(first)
    _validate_one_series(second)
    by_symbol = _bind_assets(first, second)
    qqq = by_symbol["QQQ"]
    dia = by_symbol["DIA"]
    _validate_cross_series(qqq, dia)

    qqq_returns = trailing_total_return(
        tuple(bar.close for bar in qqq),
        lookback=S5_LOOKBACK_MONTHS,
    )
    dia_returns = trailing_total_return(
        tuple(bar.close for bar in dia),
        lookback=S5_LOOKBACK_MONTHS,
    )

    signals: list[DualMomentumSignal] = []
    for index in range(S5_LOOKBACK_MONTHS, len(qqq)):
        qqq_return = qqq_returns[index]
        dia_return = dia_returns[index]
        if qqq_return is None or dia_return is None:  # pragma: no cover - feature invariant
            raise DataQualityError("S5 momentum feature violated its warm-up contract")
        selected_asset, reason = _selection(
            qqq_asset=qqq[index].series.asset,
            dia_asset=dia[index].series.asset,
            qqq_return=qqq_return,
            dia_return=dia_return,
        )
        dependencies = (
            *qqq[index - S5_LOOKBACK_MONTHS : index + 1],
            *dia[index - S5_LOOKBACK_MONTHS : index + 1],
        )
        signals.append(
            DualMomentumSignal(
                observed_period_start=qqq[index].period_start,
                observed_period_end=qqq[index].period_end,
                decision_at=max(bar.available_at for bar in dependencies),
                qqq_asset=qqq[index].series.asset,
                dia_asset=dia[index].series.asset,
                qqq_return=qqq_return,
                dia_return=dia_return,
                selected_asset=selected_asset,
                reason=reason,
            )
        )
    return tuple(signals)


def _validate_one_series(bars: tuple[DerivedPeriodBar, ...]) -> None:
    descriptor = bars[0].series
    if descriptor.frequency is not BarFrequency.MONTH:
        raise DataQualityError("S5 requires monthly derived period bars")
    if descriptor.adjustment_mode is not AdjustmentMode.TOTAL_RETURN:
        raise DataQualityError("S5 requires TOTAL_RETURN adjustment")
    if any(bar.series != descriptor for bar in bars):
        raise DataQualityError("Each S5 asset requires one immutable series descriptor")
    for previous, current in pairwise(bars):
        if current.period_start != _next_month(previous.period_start):
            raise DataQualityError("S5 monthly bars must cover consecutive natural months")


def _bind_assets(
    first: tuple[DerivedPeriodBar, ...],
    second: tuple[DerivedPeriodBar, ...],
) -> dict[str, tuple[DerivedPeriodBar, ...]]:
    assets = (first[0].series.asset, second[0].series.asset)
    if {asset.symbol for asset in assets} != {"QQQ", "DIA"} or assets[0] == assets[1]:
        raise DataQualityError("S5 requires distinct QQQ and DIA series")
    by_symbol = {first[0].series.asset.symbol: first, second[0].series.asset.symbol: second}
    try:
        _validate_canonical_asset(by_symbol["QQQ"][0].series.asset, symbol="QQQ", venue="XNAS")
        _validate_canonical_asset(by_symbol["DIA"][0].series.asset, symbol="DIA", venue="ARCX")
    except ValueError as exc:
        raise DataQualityError("S5 requires canonical QQQ and DIA USD ETF assets") from exc
    return by_symbol


def _validate_cross_series(
    qqq: tuple[DerivedPeriodBar, ...],
    dia: tuple[DerivedPeriodBar, ...],
) -> None:
    if len(qqq) != len(dia):
        raise DataQualityError("S5 QQQ and DIA series must have equal aligned length")

    qqq_descriptor = qqq[0].series
    dia_descriptor = dia[0].series
    if _shared_semantics(qqq_descriptor) != _shared_semantics(dia_descriptor):
        raise DataQualityError(
            "S5 series must share source kind, schema, producer and verified calendar"
        )

    for qqq_bar, dia_bar in zip(qqq, dia, strict=True):
        if (
            qqq_bar.period_start != dia_bar.period_start
            or qqq_bar.period_end != dia_bar.period_end
        ):
            raise DataQualityError("S5 QQQ and DIA periods must be exactly aligned")
        if qqq_bar.expected_schedule != dia_bar.expected_schedule:
            raise DataQualityError("S5 paired periods must share one exact expected schedule")


def _shared_semantics(descriptor: SeriesDescriptor) -> tuple[object, ...]:
    return (
        descriptor.frequency,
        descriptor.adjustment_mode,
        descriptor.source_kind,
        descriptor.source_schema_version,
        descriptor.producer_id,
        descriptor.producer_version,
        descriptor.calendar,
    )


def _selection(
    *,
    qqq_asset: AssetId,
    dia_asset: AssetId,
    qqq_return: Decimal,
    dia_return: Decimal,
) -> tuple[AssetId | None, DualMomentumReason]:
    if qqq_return == dia_return:
        return None, DualMomentumReason.TIE
    selected = qqq_asset if qqq_return > dia_return else dia_asset
    selected_return = max(qqq_return, dia_return)
    if selected_return > S5_ZERO_HURDLE:
        return selected, DualMomentumReason.RISK_ON
    return None, DualMomentumReason.CASH


def _validate_canonical_asset(asset: AssetId, *, symbol: str, venue: str) -> None:
    if (
        asset.symbol != symbol
        or asset.venue != venue
        or asset.asset_class is not AssetClass.ETF
        or asset.currency != "USD"
    ):
        raise ValueError(f"S5 requires canonical {symbol}/{venue}/USD/ETF identity")


def _next_month(month_start: date) -> date:
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1)
    return date(month_start.year, month_start.month + 1, 1)
