"""Fail-closed cross-provider validation without data blending."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from quantverify.core.exceptions import DataQualityError
from quantverify.data.models import (
    CrossSourceCheck,
    CrossSourcePolicy,
    DataQualityReport,
    DataQualityStatus,
    NormalizedBar,
)


class CrossSourceValidator:
    def __init__(self, policy: CrossSourcePolicy | None = None) -> None:
        self._policy = policy or CrossSourcePolicy()

    def compare(
        self,
        primary: Sequence[NormalizedBar],
        secondary: Sequence[NormalizedBar],
    ) -> DataQualityReport:
        if not primary and not secondary:
            raise DataQualityError("At least one source must contain bars")

        primary_by_session = self._index(primary, label="primary")
        secondary_by_session = self._index(secondary, label="secondary")
        all_bars = [*primary, *secondary]
        asset = all_bars[0].asset
        if any(bar.asset != asset for bar in all_bars):
            raise DataQualityError("Cross-source comparison requires one identical asset")

        primary_name = primary[0].source if primary else "primary_missing"
        secondary_name = secondary[0].source if secondary else "secondary_missing"
        sessions = sorted(primary_by_session.keys() | secondary_by_session.keys())
        checks = tuple(
            self._compare_session(
                session,
                primary_by_session.get(session),
                secondary_by_session.get(session),
                primary_name,
                secondary_name,
            )
            for session in sessions
        )
        counts = {status: 0 for status in DataQualityStatus}
        for check in checks:
            counts[check.status] += 1

        if counts[DataQualityStatus.FAIL] or counts[DataQualityStatus.MISSING]:
            overall = DataQualityStatus.FAIL
        elif counts[DataQualityStatus.WARNING]:
            overall = DataQualityStatus.WARNING
        else:
            overall = DataQualityStatus.PASS

        return DataQualityReport(
            asset=asset,
            policy_version=self._policy.policy_version,
            overall_status=overall,
            total_sessions=len(sessions),
            overlapping_sessions=len(sessions) - counts[DataQualityStatus.MISSING],
            pass_count=counts[DataQualityStatus.PASS],
            warning_count=counts[DataQualityStatus.WARNING],
            fail_count=counts[DataQualityStatus.FAIL],
            missing_count=counts[DataQualityStatus.MISSING],
            checks=checks,
        )

    @staticmethod
    def _index(bars: Sequence[NormalizedBar], *, label: str) -> dict[date, NormalizedBar]:
        indexed: dict[date, NormalizedBar] = {}
        for bar in bars:
            if bar.session in indexed:
                raise DataQualityError(f"Duplicate {label} session: {bar.session}")
            indexed[bar.session] = bar
        return indexed

    def _compare_session(
        self,
        session: date,
        primary: NormalizedBar | None,
        secondary: NormalizedBar | None,
        primary_name: str,
        secondary_name: str,
    ) -> CrossSourceCheck:
        if primary is None or secondary is None:
            return CrossSourceCheck(
                session=session,
                primary_source=primary_name,
                secondary_source=secondary_name,
                primary_close=primary.close if primary else None,
                secondary_close=secondary.close if secondary else None,
                status=DataQualityStatus.MISSING,
                reason="session is absent from one source",
            )

        difference_bps = abs(primary.close - secondary.close) / primary.close * Decimal("10000")
        if difference_bps <= self._policy.pass_tolerance_bps:
            status = DataQualityStatus.PASS
        elif difference_bps <= self._policy.warning_tolerance_bps:
            status = DataQualityStatus.WARNING
        else:
            status = DataQualityStatus.FAIL

        return CrossSourceCheck(
            session=session,
            primary_source=primary.source,
            secondary_source=secondary.source,
            primary_close=primary.close,
            secondary_close=secondary.close,
            difference_bps=difference_bps,
            status=status,
        )
