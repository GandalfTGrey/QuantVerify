from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from unittest import TestCase

from pydantic import ValidationError

from quantverify.core.enums import (
    AdjustmentMode,
    AssetClass,
    BarFrequency,
    SeriesSourceKind,
    SessionLabelPolicy,
)
from quantverify.core.models import (
    AssetId,
    CalendarArtifactRef,
    SeriesDescriptor,
    SessionSchedule,
    TradingSession,
)
from quantverify.data.models import DerivedPeriodBar

ASSET = AssetId(symbol="QQQ", venue="XNAS", asset_class=AssetClass.ETF, currency="USD")


def calendar_ref(**updates: object) -> CalendarArtifactRef:
    values: dict[str, object] = {
        "calendar_id": "XNAS",
        "calendar_version": "2026a",
        "timezone": "America/New_York",
        "session_label_policy": SessionLabelPolicy.CLOSE_LOCAL_DATE,
        "source_id": "independent-calendar-fixture",
        "source_version": "1",
        "content_hash": "c" * 64,
    }
    values.update(updates)
    return CalendarArtifactRef.model_validate(values)


def session(day: int, *, offset: timezone = UTC) -> TradingSession:
    open_utc = datetime(2026, 1, day, 14, 30, tzinfo=UTC)
    close_utc = datetime(2026, 1, day, 21, 0, tzinfo=UTC)
    return TradingSession(
        session=date(2026, 1, day),
        session_open_at=open_utc.astimezone(offset),
        session_close_at=close_utc.astimezone(offset),
    )


def week_sessions() -> tuple[TradingSession, ...]:
    return tuple(session(day) for day in range(5, 10))


def schedule(
    sessions: tuple[TradingSession, ...] | None = None,
    *,
    calendar: CalendarArtifactRef | None = None,
    requested_start: date = date(2026, 1, 5),
    requested_end: date = date(2026, 1, 11),
) -> SessionSchedule:
    return SessionSchedule(
        requested_start=requested_start,
        requested_end=requested_end,
        calendar=calendar or calendar_ref(),
        sessions=sessions or week_sessions(),
    )


def descriptor(frequency: BarFrequency = BarFrequency.WEEK, **updates: object) -> SeriesDescriptor:
    values: dict[str, object] = {
        "asset": ASSET,
        "frequency": frequency,
        "adjustment_mode": AdjustmentMode.RAW,
        "source_kind": SeriesSourceKind.FIXTURE,
        "source_id": "qqq-daily-golden",
        "source_content_hash": "a" * 64,
        "source_schema_version": "normalized-bar-v1",
        "producer_id": "calendar-ohlcv",
        "producer_version": "1",
        "calendar": calendar_ref(),
    }
    values.update(updates)
    return SeriesDescriptor.model_validate(values)


def period_bar(**updates: object) -> DerivedPeriodBar:
    expected = schedule()
    values: dict[str, object] = {
        "series": descriptor(),
        "period_start": date(2026, 1, 5),
        "period_end": date(2026, 1, 11),
        "constituent_schedule": expected,
        "expected_schedule": expected,
        "constituent_available_at": tuple(
            item.session_close_at + timedelta(minutes=5) for item in expected.sessions
        ),
        "cutoff_at": datetime(2026, 1, 9, 22, 0, tzinfo=UTC),
        "open": Decimal("100"),
        "high": Decimal("106"),
        "low": Decimal("99"),
        "close": Decimal("105"),
        "volume": Decimal("6000"),
    }
    values.update(updates)
    return DerivedPeriodBar.model_validate(values)


class SessionScheduleTests(TestCase):
    def test_schedule_identity_binds_calendar_and_exact_sessions(self) -> None:
        left = schedule()
        changed_session = schedule((*week_sessions()[:-1], session(10)))
        changed_version = schedule(calendar=calendar_ref(calendar_version="2026b"))

        self.assertNotEqual(left.schedule_id, changed_session.schedule_id)
        self.assertNotEqual(left.schedule_id, changed_version.schedule_id)

    def test_equivalent_instant_offsets_have_the_same_schedule_identity(self) -> None:
        utc_schedule = schedule()
        shanghai = timezone(timedelta(hours=8))
        offset_schedule = schedule(tuple(session(day, offset=shanghai) for day in range(5, 10)))
        self.assertEqual(utc_schedule.schedule_id, offset_schedule.schedule_id)

    def test_schedule_identity_has_a_fixed_golden_value(self) -> None:
        self.assertEqual(
            schedule().schedule_id,
            "session-schedule_f05dfbbc0acc6bfb5acbd68b",
        )

    def test_rejects_duplicate_or_out_of_order_sessions(self) -> None:
        with self.assertRaisesRegex(ValidationError, "strictly ordered"):
            schedule((session(5), session(5)))

    def test_rejects_unknown_timezone(self) -> None:
        with self.assertRaisesRegex(ValidationError, "unknown IANA timezone"):
            calendar_ref(timezone="Mars/Olympus_Mons")

    def test_rejects_session_label_timestamp_misalignment(self) -> None:
        january_label_february_times = TradingSession(
            session=date(2026, 1, 5),
            session_open_at=datetime(2026, 2, 5, 14, 30, tzinfo=UTC),
            session_close_at=datetime(2026, 2, 5, 21, 0, tzinfo=UTC),
        )
        with self.assertRaisesRegex(ValidationError, "local close date"):
            schedule((january_label_february_times,))

    def test_dst_and_half_day_sessions_use_exchange_local_close_labels(self) -> None:
        dst_schedule = SessionSchedule(
            requested_start=date(2026, 3, 6),
            requested_end=date(2026, 3, 9),
            calendar=calendar_ref(),
            sessions=(
                TradingSession(
                    session=date(2026, 3, 6),
                    session_open_at=datetime(2026, 3, 6, 14, 30, tzinfo=UTC),
                    session_close_at=datetime(2026, 3, 6, 21, 0, tzinfo=UTC),
                ),
                TradingSession(
                    session=date(2026, 3, 9),
                    session_open_at=datetime(2026, 3, 9, 13, 30, tzinfo=UTC),
                    session_close_at=datetime(2026, 3, 9, 20, 0, tzinfo=UTC),
                ),
            ),
        )
        half_day = SessionSchedule(
            requested_start=date(2026, 11, 27),
            requested_end=date(2026, 11, 27),
            calendar=calendar_ref(),
            sessions=(
                TradingSession(
                    session=date(2026, 11, 27),
                    session_open_at=datetime(2026, 11, 27, 14, 30, tzinfo=UTC),
                    session_close_at=datetime(2026, 11, 27, 18, 0, tzinfo=UTC),
                ),
            ),
        )
        self.assertEqual(len(dst_schedule.sessions), 2)
        self.assertEqual(len(half_day.sessions), 1)

    def test_identity_rejects_unsafe_model_copy_updates(self) -> None:
        unsafe_schedule = schedule().model_copy(update={"sessions": []})
        with self.assertRaisesRegex(ValueError, "immutable tuple"):
            _ = unsafe_schedule.schedule_id


class SeriesDescriptorTests(TestCase):
    def test_frequency_and_lineage_change_descriptor_identity(self) -> None:
        weekly = descriptor(BarFrequency.WEEK)
        monthly = descriptor(BarFrequency.MONTH)
        revised_source = descriptor(source_content_hash="b" * 64)

        self.assertNotEqual(weekly.descriptor_id, monthly.descriptor_id)
        self.assertNotEqual(weekly.descriptor_id, revised_source.descriptor_id)

    def test_identity_revalidates_unsafe_model_copy(self) -> None:
        unsafe = descriptor().model_copy(update={"source_content_hash": "not-a-hash"})
        with self.assertRaises(ValidationError):
            _ = unsafe.descriptor_id


class DerivedPeriodBarTests(TestCase):
    def test_complete_period_contract_and_content_identity(self) -> None:
        bar = period_bar()
        changed_close = period_bar(close=Decimal("104"))
        self.assertTrue(bar.complete)
        self.assertEqual(bar.available_at, datetime(2026, 1, 9, 21, 5, tzinfo=UTC))
        self.assertNotEqual(bar.period_bar_id, changed_close.period_bar_id)

    def test_partial_period_is_derived_from_actual_expected_sessions(self) -> None:
        actual = schedule(week_sessions()[:-1])
        bar = period_bar(
            constituent_schedule=actual,
            constituent_available_at=tuple(
                item.session_close_at + timedelta(minutes=5) for item in actual.sessions
            ),
            cutoff_at=datetime(2026, 1, 8, 22, 0, tzinfo=UTC),
        )
        self.assertFalse(bar.complete)
        self.assertEqual(bar.constituent_count, 4)
        self.assertEqual(bar.expected_constituent_count, 5)

    def test_daily_frequency_cannot_masquerade_as_derived_period(self) -> None:
        with self.assertRaisesRegex(ValidationError, "weekly or monthly"):
            period_bar(series=descriptor(BarFrequency.DAY))

    def test_constituent_availability_is_a_verified_watermark(self) -> None:
        early = tuple(item.session_close_at - timedelta(minutes=1) for item in week_sessions())
        with self.assertRaisesRegex(ValidationError, "cannot precede"):
            period_bar(constituent_available_at=early)

        late = tuple(item.session_close_at + timedelta(minutes=5) for item in week_sessions())
        with self.assertRaisesRegex(ValidationError, "later than cutoff"):
            period_bar(
                constituent_available_at=late,
                cutoff_at=datetime(2026, 1, 9, 21, 1, tzinfo=UTC),
            )

    def test_period_boundary_and_schedule_subset_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValidationError, "Monday through Sunday"):
            period_bar(period_start=date(2026, 1, 6))
        outsider = schedule((*week_sessions()[:-1], session(10)))
        with self.assertRaisesRegex(ValidationError, "exact subset"):
            period_bar(constituent_schedule=outsider)

    def test_monthly_period_uses_natural_calendar_boundary(self) -> None:
        january = schedule(
            requested_start=date(2026, 1, 1),
            requested_end=date(2026, 1, 31),
        )
        bar = period_bar(
            series=descriptor(BarFrequency.MONTH),
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            constituent_schedule=january,
            expected_schedule=january,
        )
        self.assertTrue(bar.complete)

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
