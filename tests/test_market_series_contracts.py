from datetime import UTC, date, datetime
from decimal import Decimal
from unittest import TestCase

from pydantic import ValidationError

from quantverify.core.enums import (
    AdjustmentMode,
    AssetClass,
    BarFrequency,
    SeriesSourceKind,
)
from quantverify.core.models import (
    AssetId,
    SeriesDescriptor,
    SessionSchedule,
    TradingSession,
)
from quantverify.data.models import DerivedPeriodBar

ASSET = AssetId(symbol="QQQ", venue="XNAS", asset_class=AssetClass.ETF, currency="USD")


def session(day: int) -> TradingSession:
    return TradingSession(
        session=date(2026, 1, day),
        session_open_at=datetime(2026, 1, day, 14, 30, tzinfo=UTC),
        session_close_at=datetime(2026, 1, day, 21, 0, tzinfo=UTC),
    )


def descriptor(frequency: BarFrequency = BarFrequency.WEEK) -> SeriesDescriptor:
    return SeriesDescriptor(
        asset=ASSET,
        frequency=frequency,
        adjustment_mode=AdjustmentMode.RAW,
        source_kind=SeriesSourceKind.FIXTURE,
        source_id="qqq-daily-golden",
        source_content_hash="a" * 64,
        source_schema_version="normalized-bar-v1",
        producer_id="calendar-ohlcv",
        producer_version="1",
        calendar_id="XNAS",
        calendar_version="golden-v1",
    )


def period_bar(**updates: object) -> DerivedPeriodBar:
    values: dict[str, object] = {
        "series": descriptor(),
        "period_start": date(2026, 1, 5),
        "period_end": date(2026, 1, 11),
        "constituent_start": date(2026, 1, 5),
        "constituent_end": date(2026, 1, 9),
        "constituent_count": 5,
        "expected_constituent_count": 5,
        "constituent_schedule_id": f"session-schedule_{'c' * 24}",
        "expected_schedule_id": f"session-schedule_{'c' * 24}",
        "period_open_at": datetime(2026, 1, 5, 14, 30, tzinfo=UTC),
        "period_close_at": datetime(2026, 1, 9, 21, 0, tzinfo=UTC),
        "available_at": datetime(2026, 1, 9, 21, 5, tzinfo=UTC),
        "open": Decimal("100"),
        "high": Decimal("106"),
        "low": Decimal("99"),
        "close": Decimal("105"),
        "volume": Decimal("6000"),
        "complete": True,
    }
    values.update(updates)
    return DerivedPeriodBar.model_validate(values)


class SessionScheduleTests(TestCase):
    def test_schedule_identity_binds_calendar_and_exact_sessions(self) -> None:
        left = SessionSchedule(
            calendar_id="XNAS",
            calendar_version="2026a",
            timezone="America/New_York",
            sessions=(session(5), session(6)),
        )
        changed_session = left.model_copy(update={"sessions": (session(5), session(7))})
        changed_version = left.model_copy(update={"calendar_version": "2026b"})

        self.assertNotEqual(left.schedule_id, changed_session.schedule_id)
        self.assertNotEqual(left.schedule_id, changed_version.schedule_id)

    def test_rejects_duplicate_or_out_of_order_sessions(self) -> None:
        with self.assertRaisesRegex(ValidationError, "strictly ordered"):
            SessionSchedule(
                calendar_id="XNAS",
                calendar_version="2026a",
                timezone="America/New_York",
                sessions=(session(5), session(5)),
            )

    def test_rejects_unknown_timezone(self) -> None:
        with self.assertRaisesRegex(ValidationError, "unknown IANA timezone"):
            SessionSchedule(
                calendar_id="XNAS",
                calendar_version="2026a",
                timezone="Mars/Olympus_Mons",
                sessions=(session(5),),
            )


class SeriesDescriptorTests(TestCase):
    def test_frequency_and_lineage_change_series_identity(self) -> None:
        weekly = descriptor(BarFrequency.WEEK)
        monthly = weekly.model_copy(update={"frequency": BarFrequency.MONTH})
        revised_source = weekly.model_copy(update={"source_content_hash": "b" * 64})

        self.assertNotEqual(weekly.series_id, monthly.series_id)
        self.assertNotEqual(weekly.series_id, revised_source.series_id)


class DerivedPeriodBarTests(TestCase):
    def test_complete_period_contract(self) -> None:
        bar = period_bar()
        self.assertTrue(bar.complete)
        self.assertEqual(bar.series.frequency, BarFrequency.WEEK)

    def test_partial_period_must_be_marked_incomplete(self) -> None:
        bar = period_bar(
            constituent_count=4,
            constituent_schedule_id=f"session-schedule_{'d' * 24}",
            complete=False,
        )
        self.assertFalse(bar.complete)

        with self.assertRaisesRegex(ValidationError, "complete must match"):
            period_bar(
                constituent_count=4,
                constituent_schedule_id=f"session-schedule_{'d' * 24}",
                complete=True,
            )

    def test_equal_counts_do_not_hide_wrong_constituent_sessions(self) -> None:
        with self.assertRaisesRegex(ValidationError, "complete must match"):
            period_bar(
                constituent_schedule_id=f"session-schedule_{'d' * 24}",
                complete=True,
            )

    def test_daily_frequency_cannot_masquerade_as_derived_period(self) -> None:
        with self.assertRaisesRegex(ValidationError, "weekly or monthly"):
            period_bar(series=descriptor(BarFrequency.DAY))

    def test_availability_cannot_precede_period_close(self) -> None:
        with self.assertRaisesRegex(ValidationError, "available_at"):
            period_bar(available_at=datetime(2026, 1, 9, 20, 59, tzinfo=UTC))

    def test_invalid_period_ranges_and_counts_fail_closed(self) -> None:
        invalid_cases = (
            ({"constituent_start": date(2026, 1, 4)}, "constituent range"),
            ({"constituent_count": 6}, "cannot exceed"),
        )
        for updates, message in invalid_cases:
            with self.subTest(updates=updates), self.assertRaisesRegex(
                ValidationError, message
            ):
                period_bar(**updates)

    def test_invalid_period_timestamps_fail_closed(self) -> None:
        invalid_cases = (
            ({"period_open_at": datetime(2026, 1, 5, 14, 30)}, "timezone-aware"),
            (
                {"period_open_at": datetime(2026, 1, 9, 21, 0, tzinfo=UTC)},
                "earlier than",
            ),
        )
        for updates, message in invalid_cases:
            with self.subTest(updates=updates), self.assertRaisesRegex(
                ValidationError, message
            ):
                period_bar(**updates)

    def test_invalid_period_ohlc_fails_closed(self) -> None:
        invalid_cases = (
            ({"high": Decimal("98")}, "high must"),
            ({"open": Decimal("98")}, "open must"),
            ({"close": Decimal("107")}, "close must"),
        )
        for updates, message in invalid_cases:
            with self.subTest(updates=updates), self.assertRaisesRegex(
                ValidationError, message
            ):
                period_bar(**updates)
