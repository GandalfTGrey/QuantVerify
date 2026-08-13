import decimal
from unittest import TestCase

from quantverify.core.numerics import (
    FIXTURE_EXECUTION_DECIMAL_ID,
    fixture_execution_decimal_context,
)


class FixtureExecutionDecimalContractTests(TestCase):
    def test_versioned_context_is_complete_and_does_not_read_host_state(self) -> None:
        original = decimal.getcontext().copy()
        try:
            host = decimal.getcontext()
            host.prec = 5
            host.rounding = decimal.ROUND_UP
            host.traps[decimal.Inexact] = True
            host.flags[decimal.Rounded] = True

            actual = fixture_execution_decimal_context()
            self.assertEqual(FIXTURE_EXECUTION_DECIMAL_ID, "fixture-execution-decimal-v1")
            self.assertEqual(actual.prec, 28)
            self.assertEqual(actual.rounding, decimal.ROUND_HALF_EVEN)
            self.assertEqual((actual.Emin, actual.Emax), (-999999, 999999))
            self.assertEqual((actual.capitals, actual.clamp), (1, 0))
            self.assertEqual(
                {signal for signal, enabled in actual.traps.items() if enabled},
                {decimal.InvalidOperation, decimal.DivisionByZero, decimal.Overflow},
            )
            self.assertFalse(any(actual.flags.values()))
        finally:
            decimal.setcontext(original)
