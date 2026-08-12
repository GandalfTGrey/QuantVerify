"""Derive truthful weekly/monthly bars from daily observations and a calendar."""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Sequence
from datetime import date, datetime, timedelta

from pydantic import ValidationError

from quantverify.core.enums import BarFrequency, PeriodCompleteness
from quantverify.core.exceptions import DataQualityError
from quantverify.core.models import SeriesDescriptor, SessionSchedule, TradingSession
from quantverify.data.models import DerivedPeriodBar, NormalizedBar


def derive_period_bars(
    bars: Sequence[NormalizedBar],
    *,
    expected_schedule: SessionSchedule,
    series: SeriesDescriptor,
    cutoff_at: datetime,
) -> tuple[DerivedPeriodBar, ...]:
    """Aggregate a causally available daily prefix into weekly/monthly bars.

    ``expected_schedule`` is the independent, complete calendar schedule for the
    requested range. ``bars`` must be its exact observed prefix; a middle gap is
    rejected instead of being hidden by aggregation. The final period may remain
    partial or missing-data evidence, but is not research-eligible by default.
    """

    schedule = _revalidate_schedule(expected_schedule)
    output_series = _revalidate_series(series)
    daily_bars = _revalidate_bars(bars)
    _validate_inputs(
        daily_bars,
        expected_schedule=schedule,
        series=output_series,
        cutoff_at=cutoff_at,
    )

    expected_groups = _group_sessions(schedule.sessions, output_series.frequency)
    bars_by_session = {bar.session: bar for bar in daily_bars}
    results: list[DerivedPeriodBar] = []
    for period_start, period_end, expected_sessions in expected_groups:
        observed = tuple(
            bars_by_session[item.session]
            for item in expected_sessions
            if item.session in bars_by_session
        )
        if not observed:
            first_expected_close = expected_sessions[0].session_close_at
            if cutoff_at >= first_expected_close:
                raise DataQualityError(
                    "Elapsed expected period has no daily observations: "
                    f"{period_start.isoformat()}..{period_end.isoformat()}"
                )
            continue

        actual_sessions = expected_sessions[: len(observed)]
        expected_period_schedule = SessionSchedule.create(
            requested_start=period_start,
            requested_end=period_end,
            calendar=schedule.calendar,
            sessions=expected_sessions,
        )
        actual_period_schedule = SessionSchedule.create(
            requested_start=period_start,
            requested_end=period_end,
            calendar=schedule.calendar,
            sessions=actual_sessions,
        )
        period_cutoff = (
            max(bar.available_at for bar in observed)
            if len(observed) == len(expected_sessions)
            else cutoff_at
        )
        results.append(
            DerivedPeriodBar(
                series=output_series,
                period_start=period_start,
                period_end=period_end,
                constituent_schedule=actual_period_schedule,
                expected_schedule=expected_period_schedule,
                constituent_available_at=tuple(bar.available_at for bar in observed),
                cutoff_at=period_cutoff,
                open=observed[0].open,
                high=max(bar.high for bar in observed),
                low=min(bar.low for bar in observed),
                close=observed[-1].close,
                volume=sum((bar.volume for bar in observed), start=observed[0].volume * 0),
            )
        )
    return tuple(results)


def require_complete_period_bars(
    period_bars: Sequence[DerivedPeriodBar],
) -> tuple[DerivedPeriodBar, ...]:
    """Fail closed unless every supplied period is complete and internally valid."""

    try:
        validated = tuple(
            DerivedPeriodBar.model_validate(bar.model_dump(mode="python"))
            for bar in period_bars
        )
    except ValidationError as exc:
        raise DataQualityError("Derived period bars failed integrity validation") from exc

    failures = tuple(
        (bar.period_start, bar.completeness)
        for bar in validated
        if bar.completeness is not PeriodCompleteness.COMPLETE
    )
    if failures:
        summary = ", ".join(f"{start.isoformat()}={status.value}" for start, status in failures)
        raise DataQualityError(f"Research requires COMPLETE period bars: {summary}")
    return validated


def _revalidate_schedule(schedule: SessionSchedule) -> SessionSchedule:
    try:
        return SessionSchedule.model_validate(schedule.model_dump(mode="python"))
    except ValidationError as exc:
        raise DataQualityError("Expected session schedule failed integrity validation") from exc


def _revalidate_series(series: SeriesDescriptor) -> SeriesDescriptor:
    try:
        return SeriesDescriptor.model_validate(series.model_dump(mode="python"))
    except ValidationError as exc:
        raise DataQualityError("Series descriptor failed integrity validation") from exc


def _revalidate_bars(bars: Sequence[NormalizedBar]) -> tuple[NormalizedBar, ...]:
    try:
        return tuple(
            NormalizedBar.model_validate(bar.model_dump(mode="python")) for bar in bars
        )
    except ValidationError as exc:
        raise DataQualityError("Daily bars failed integrity validation") from exc


def _validate_inputs(
    bars: tuple[NormalizedBar, ...],
    *,
    expected_schedule: SessionSchedule,
    series: SeriesDescriptor,
    cutoff_at: datetime,
) -> None:
    if cutoff_at.tzinfo is None:
        raise DataQualityError("cutoff_at must be timezone-aware")
    if series.frequency not in (BarFrequency.WEEK, BarFrequency.MONTH):
        raise DataQualityError("Period derivation requires a weekly or monthly descriptor")
    if series.calendar != expected_schedule.calendar:
        raise DataQualityError("Series and expected schedule must use one calendar artifact")
    if not bars:
        raise DataQualityError("Period derivation requires at least one daily bar")
    if any(bar.asset != series.asset for bar in bars):
        raise DataQualityError("Every daily bar must match the series asset")
    if any(bar.source != bars[0].source for bar in bars):
        raise DataQualityError("Daily bars must not mix normalized data sources")
    _validate_complete_range(expected_schedule, series.frequency)

    expected_prefix = expected_schedule.sessions[: len(bars)]
    if len(bars) > len(expected_schedule.sessions) or tuple(
        bar.session for bar in bars
    ) != tuple(item.session for item in expected_prefix):
        raise DataQualityError("Daily bars must be an exact prefix of the expected schedule")
    for bar, session in zip(bars, expected_prefix, strict=True):
        if (
            bar.session_open_at != session.session_open_at
            or bar.session_close_at != session.session_close_at
        ):
            raise DataQualityError("Daily bar timestamps must match the expected schedule")
        if bar.available_at > cutoff_at:
            raise DataQualityError("Daily bar is not available at the requested cutoff")


def _validate_complete_range(schedule: SessionSchedule, frequency: BarFrequency) -> None:
    first_start, _ = _period_bounds(schedule.sessions[0].session, frequency)
    _, last_end = _period_bounds(schedule.sessions[-1].session, frequency)
    if schedule.requested_start != first_start or schedule.requested_end != last_end:
        raise DataQualityError(
            "Expected schedule requested range must cover complete period boundaries"
        )


def _group_sessions(
    sessions: tuple[TradingSession, ...],
    frequency: BarFrequency,
) -> tuple[tuple[date, date, tuple[TradingSession, ...]], ...]:
    groups: list[tuple[date, date, list[TradingSession]]] = []
    for session in sessions:
        period_start, period_end = _period_bounds(session.session, frequency)
        if not groups or groups[-1][0] != period_start:
            groups.append((period_start, period_end, [session]))
        else:
            groups[-1][2].append(session)
    return tuple((start, end, tuple(items)) for start, end, items in groups)


def _period_bounds(session: date, frequency: BarFrequency) -> tuple[date, date]:
    if frequency is BarFrequency.WEEK:
        start = session - timedelta(days=session.weekday())
        return start, start + timedelta(days=6)
    if frequency is BarFrequency.MONTH:
        start = session.replace(day=1)
        return start, session.replace(day=monthrange(session.year, session.month)[1])
    raise DataQualityError("Period derivation requires a weekly or monthly descriptor")
