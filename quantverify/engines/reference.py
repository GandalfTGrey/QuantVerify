"""Small transparent engine used to lock down golden backtest semantics."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import Field

from quantverify.core.exceptions import DataQualityError
from quantverify.core.models import AssetId, DomainModel, TargetPosition
from quantverify.data.models import NormalizedBar

NonNegativeDecimal = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
PositiveDecimal = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]


class TradeSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class ReferenceTrade(DomainModel):
    asset: AssetId
    side: TradeSide
    executed_at: datetime
    reference_price: PositiveDecimal
    execution_price: PositiveDecimal
    quantity: PositiveDecimal
    commission: NonNegativeDecimal
    slippage_cost: NonNegativeDecimal


class PortfolioPoint(DomainModel):
    session: date
    timestamp: datetime
    close: PositiveDecimal
    cash: NonNegativeDecimal
    quantity: NonNegativeDecimal
    equity: PositiveDecimal
    target_weight: Decimal
    actual_weight: Decimal


class ReferenceResult(DomainModel):
    asset: AssetId
    initial_cash: PositiveDecimal
    points: tuple[PortfolioPoint, ...]
    trades: tuple[ReferenceTrade, ...]
    total_commission: NonNegativeDecimal
    total_slippage: NonNegativeDecimal

    @property
    def final_equity(self) -> Decimal:
        return self.points[-1].equity


class LongFlatReferenceEngine:
    """A deliberately narrow engine for 0%/100% single-asset target weights."""

    def run(
        self,
        bars: Sequence[NormalizedBar],
        targets: Sequence[TargetPosition],
        *,
        initial_cash: Decimal,
        commission_bps: Decimal = Decimal("0"),
        slippage_bps: Decimal = Decimal("0"),
    ) -> ReferenceResult:
        if not bars:
            raise DataQualityError("Reference engine requires at least one bar")
        if initial_cash <= 0 or not initial_cash.is_finite():
            raise ValueError("initial_cash must be positive and finite")
        for label, value in (
            ("commission_bps", commission_bps),
            ("slippage_bps", slippage_bps),
        ):
            if value < 0 or not value.is_finite():
                raise ValueError(f"{label} must be non-negative and finite")
        if slippage_bps >= Decimal("10000"):
            raise ValueError("slippage_bps must be less than 10000")

        asset = bars[0].asset
        if any(bar.asset != asset for bar in bars):
            raise DataQualityError("Reference engine bars must contain one identical asset")
        if any(target.asset != asset for target in targets):
            raise DataQualityError("Reference engine targets must match the bar asset")

        opens = {bar.session_open_at for bar in bars}
        targets_by_time: dict[datetime, TargetPosition] = {}
        for requested_target in targets:
            if requested_target.weight not in (Decimal("0"), Decimal("1")):
                raise ValueError("Reference engine only supports long/flat target weights")
            if requested_target.effective_at not in opens:
                raise DataQualityError("Every target must match an available session open")
            if requested_target.effective_at in targets_by_time:
                raise DataQualityError(
                    f"Duplicate target effective_at: {requested_target.effective_at}"
                )
            targets_by_time[requested_target.effective_at] = requested_target

        commission_rate = commission_bps / Decimal("10000")
        slippage_rate = slippage_bps / Decimal("10000")
        cash = initial_cash
        quantity = Decimal("0")
        target_weight = Decimal("0")
        points: list[PortfolioPoint] = []
        trades: list[ReferenceTrade] = []

        for bar in bars:
            effective_target = targets_by_time.get(bar.session_open_at)
            if effective_target is not None and effective_target.weight != target_weight:
                if effective_target.weight == Decimal("1"):
                    trade, cash, quantity = self._buy(
                        bar,
                        cash=cash,
                        commission_rate=commission_rate,
                        slippage_rate=slippage_rate,
                    )
                else:
                    trade, cash, quantity = self._sell(
                        bar,
                        quantity=quantity,
                        commission_rate=commission_rate,
                        slippage_rate=slippage_rate,
                    )
                trades.append(trade)
                target_weight = effective_target.weight

            asset_value = quantity * bar.close
            equity = cash + asset_value
            actual_weight = asset_value / equity if equity else Decimal("0")
            points.append(
                PortfolioPoint(
                    session=bar.session,
                    timestamp=bar.session_close_at,
                    close=bar.close,
                    cash=cash,
                    quantity=quantity,
                    equity=equity,
                    target_weight=target_weight,
                    actual_weight=actual_weight,
                )
            )

        return ReferenceResult(
            asset=asset,
            initial_cash=initial_cash,
            points=tuple(points),
            trades=tuple(trades),
            total_commission=sum((trade.commission for trade in trades), Decimal("0")),
            total_slippage=sum((trade.slippage_cost for trade in trades), Decimal("0")),
        )

    @staticmethod
    def _buy(
        bar: NormalizedBar,
        *,
        cash: Decimal,
        commission_rate: Decimal,
        slippage_rate: Decimal,
    ) -> tuple[ReferenceTrade, Decimal, Decimal]:
        execution_price = bar.open * (Decimal("1") + slippage_rate)
        gross_notional = cash / (Decimal("1") + commission_rate)
        commission = cash - gross_notional
        quantity = gross_notional / execution_price
        trade = ReferenceTrade(
            asset=bar.asset,
            side=TradeSide.BUY,
            executed_at=bar.session_open_at,
            reference_price=bar.open,
            execution_price=execution_price,
            quantity=quantity,
            commission=commission,
            slippage_cost=quantity * (execution_price - bar.open),
        )
        return trade, Decimal("0"), quantity

    @staticmethod
    def _sell(
        bar: NormalizedBar,
        *,
        quantity: Decimal,
        commission_rate: Decimal,
        slippage_rate: Decimal,
    ) -> tuple[ReferenceTrade, Decimal, Decimal]:
        execution_price = bar.open * (Decimal("1") - slippage_rate)
        gross_proceeds = quantity * execution_price
        commission = gross_proceeds * commission_rate
        trade = ReferenceTrade(
            asset=bar.asset,
            side=TradeSide.SELL,
            executed_at=bar.session_open_at,
            reference_price=bar.open,
            execution_price=execution_price,
            quantity=quantity,
            commission=commission,
            slippage_cost=quantity * (bar.open - execution_price),
        )
        return trade, gross_proceeds - commission, Decimal("0")
