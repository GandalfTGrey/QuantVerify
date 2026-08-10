"""Exceptions with stable semantics for adapters and callers."""


class QuantVerifyError(Exception):
    """Base error for all expected QuantVerify failures."""


class DataQualityError(QuantVerifyError):
    """Input data violates a declared data contract."""


class ReproducibilityError(QuantVerifyError):
    """A run cannot prove or reproduce its lineage."""


class LookaheadRiskError(QuantVerifyError):
    """A requested calculation would use information unavailable at decision time."""
