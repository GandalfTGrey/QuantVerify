from decimal import Decimal
from unittest import TestCase

from quantverify.core.exceptions import DataQualityError
from quantverify.engines.reference import LongFlatReferenceEngine, TradeSide
from quantverify.metrics import maximum_drawdown, total_return
from quantverify.strategies import price_above_sma_targets
from tests.test_trend_strategy import load_bars


class ReferenceEngineGoldenTests(TestCase):
    def setUp(self) -> None:
        self.bars = load_bars()[:7]
        self.targets = price_above_sma_targets(self.bars, window=3)
        self.engine = LongFlatReferenceEngine()

    def test_zero_cost_trade_timing_and_equity_are_hand_verifiable(self) -> None:
        result = self.engine.run(
            self.bars,
            self.targets,
            initial_cash=Decimal("10300"),
        )
        self.assertEqual([trade.side for trade in result.trades], [TradeSide.BUY, TradeSide.SELL])
        self.assertEqual(result.trades[0].executed_at, self.bars[3].session_open_at)
        self.assertEqual(result.trades[0].quantity, Decimal("100"))
        self.assertEqual(result.trades[1].executed_at, self.bars[6].session_open_at)
        self.assertEqual(result.final_equity, Decimal("9800"))
        self.assertEqual(result.total_commission, Decimal("0"))
        self.assertEqual(result.total_slippage, Decimal("0"))

    def test_metrics_follow_version_one_sign_convention(self) -> None:
        result = self.engine.run(
            self.bars,
            self.targets,
            initial_cash=Decimal("10300"),
        )
        equity = tuple(point.equity for point in result.points)
        self.assertEqual(total_return(equity), Decimal("9800") / Decimal("10300") - 1)
        self.assertEqual(maximum_drawdown(equity), Decimal("9800") / Decimal("10500") - 1)

    def test_costs_reduce_final_equity(self) -> None:
        free = self.engine.run(self.bars, self.targets, initial_cash=Decimal("10300"))
        costly = self.engine.run(
            self.bars,
            self.targets,
            initial_cash=Decimal("10300"),
            commission_bps=Decimal("10"),
            slippage_bps=Decimal("5"),
        )
        self.assertLess(costly.final_equity, free.final_equity)
        self.assertGreater(costly.total_commission, 0)
        self.assertGreater(costly.total_slippage, 0)

    def test_rejects_out_of_order_or_duplicate_bars(self) -> None:
        invalid_sequences = (
            (self.bars[1], self.bars[0]),
            (self.bars[0], self.bars[0]),
        )
        for bars in invalid_sequences:
            with (
                self.subTest(sessions=tuple(bar.session for bar in bars)),
                self.assertRaisesRegex(DataQualityError, "strictly ordered by session"),
            ):
                self.engine.run(bars, (), initial_cash=Decimal("10300"))
