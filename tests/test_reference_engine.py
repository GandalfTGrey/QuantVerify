import decimal
from decimal import Decimal
from unittest import TestCase

from quantverify.core.exceptions import DataQualityError
from quantverify.engines.reference import LongFlatReferenceEngine, TradeSide
from quantverify.metrics import maximum_drawdown, total_return
from quantverify.strategies import price_above_sma_targets
from tests.test_trend_strategy import (
    decimal_context_state,
    load_bars,
    load_schedule,
    replace_bar,
)


class ReferenceEngineGoldenTests(TestCase):
    def setUp(self) -> None:
        self.bars = load_bars()[:7]
        self.targets = price_above_sma_targets(
            self.bars,
            window=3,
            schedule=load_schedule(session_count=len(self.bars)),
        )
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

    def test_complete_result_is_independent_of_host_decimal_context(self) -> None:
        expected = self.engine.run(
            self.bars,
            self.targets,
            initial_cash=Decimal("10300"),
            commission_bps=Decimal("10"),
            slippage_bps=Decimal("5"),
        )
        original = decimal.getcontext().copy()
        try:
            for precision in (5, 10, 28, 50):
                for rounding in (
                    decimal.ROUND_UP,
                    decimal.ROUND_DOWN,
                    decimal.ROUND_HALF_EVEN,
                ):
                    with self.subTest(precision=precision, rounding=rounding):
                        host = decimal.getcontext()
                        host.prec = precision
                        host.rounding = rounding
                        host.traps[decimal.Inexact] = True
                        host.flags[decimal.Rounded] = True
                        before = decimal_context_state(host)
                        actual = self.engine.run(
                            self.bars,
                            self.targets,
                            initial_cash=Decimal("10300"),
                            commission_bps=Decimal("10"),
                            slippage_bps=Decimal("5"),
                        )
                        self.assertEqual(actual, expected)
                        self.assertEqual(decimal_context_state(decimal.getcontext()), before)
        finally:
            decimal.setcontext(original)

    def test_failure_restores_host_decimal_context(self) -> None:
        original = decimal.getcontext().copy()
        try:
            host = decimal.getcontext()
            host.prec = 5
            host.rounding = decimal.ROUND_DOWN
            host.flags[decimal.Inexact] = True
            before = decimal_context_state(host)
            extreme = list(self.bars)
            extreme[3] = replace_bar(
                extreme[3],
                high=Decimal("9E+999999"),
                close=Decimal("9E+999999"),
            )
            with self.assertRaisesRegex(
                DataQualityError, "numerical execution failed"
            ) as captured:
                self.engine.run(
                    tuple(extreme),
                    self.targets,
                    initial_cash=Decimal("9E+999999"),
                )
            self.assertIsNone(captured.exception.__cause__)
            self.assertIsNone(captured.exception.__context__)
            self.assertEqual(decimal_context_state(decimal.getcontext()), before)
        finally:
            decimal.setcontext(original)
