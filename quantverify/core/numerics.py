"""Versioned Decimal environments for deterministic fixture execution."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import (
    ROUND_HALF_EVEN,
    Clamped,
    Context,
    DivisionByZero,
    FloatOperation,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    Subnormal,
    Underflow,
    localcontext,
)
from typing import Final

FIXTURE_EXECUTION_DECIMAL_ID: Final = "fixture-execution-decimal-v1"


def fixture_execution_decimal_context() -> Context:
    """Construct the complete, reviewed Decimal context used by fixture v1."""

    context = Context(
        prec=28,
        rounding=ROUND_HALF_EVEN,
        Emin=-999999,
        Emax=999999,
        capitals=1,
        clamp=0,
    )
    configured = {
        InvalidOperation: True,
        FloatOperation: False,
        DivisionByZero: True,
        Overflow: True,
        Underflow: False,
        Subnormal: False,
        Inexact: False,
        Rounded: False,
        Clamped: False,
    }
    for signal, enabled in configured.items():
        context.traps[signal] = enabled
    context.clear_flags()
    return context


@contextmanager
def fixture_execution_decimal() -> Iterator[Context]:
    """Run one numerical closure without reading or mutating the host context."""

    with localcontext(fixture_execution_decimal_context()) as active:
        active.clear_flags()
        yield active
