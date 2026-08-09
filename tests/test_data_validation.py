from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest import TestCase

from pydantic import ValidationError

from quantverify.core.enums import AssetClass
from quantverify.core.exceptions import DataQualityError
from quantverify.core.models import AssetId
from quantverify.data.models import DataQualityStatus, NormalizedBar
from quantverify.data.validation import CrossSourceValidator

ASSET = AssetId(symbol="QQQ", venue="XNAS", asset_class=AssetClass.ETF, currency="USD")


def make_bar(
    session: date,
    close: str,
    *,
    source: str,
    asset: AssetId = ASSET,
) -> NormalizedBar:
    event_at = datetime(session.year, session.month, session.day, 21, tzinfo=UTC)
    close_value = Decimal(close)
    return NormalizedBar(
        asset=asset,
        session=session,
        event_at=event_at,
        available_at=event_at + timedelta(minutes=5),
        open=close_value,
        high=close_value,
        low=close_value,
        close=close_value,
        volume=Decimal("1000"),
        source=source,
    )


class NormalizedBarTests(TestCase):
    def test_rejects_invalid_ohlc(self) -> None:
        session = date(2026, 1, 2)
        event_at = datetime(2026, 1, 2, 21, tzinfo=UTC)
        with self.assertRaisesRegex(ValidationError, "open must be between"):
            NormalizedBar(
                asset=ASSET,
                session=session,
                event_at=event_at,
                available_at=event_at,
                open=Decimal("101"),
                high=Decimal("100"),
                low=Decimal("99"),
                close=Decimal("100"),
                volume=Decimal("1"),
                source="fixture",
            )


class CrossSourceValidatorTests(TestCase):
    def setUp(self) -> None:
        self.validator = CrossSourceValidator()
        self.session = date(2026, 1, 2)

    def test_passes_close_within_ten_basis_points(self) -> None:
        report = self.validator.compare(
            [make_bar(self.session, "100", source="tushare")],
            [make_bar(self.session, "100.05", source="akshare")],
        )
        self.assertEqual(report.overall_status, DataQualityStatus.PASS)
        self.assertEqual(report.pass_count, 1)

    def test_warns_between_ten_and_fifty_basis_points(self) -> None:
        report = self.validator.compare(
            [make_bar(self.session, "100", source="tushare")],
            [make_bar(self.session, "100.25", source="akshare")],
        )
        self.assertEqual(report.overall_status, DataQualityStatus.WARNING)
        self.assertEqual(report.warning_count, 1)

    def test_fails_above_fifty_basis_points(self) -> None:
        report = self.validator.compare(
            [make_bar(self.session, "100", source="tushare")],
            [make_bar(self.session, "101", source="akshare")],
        )
        self.assertEqual(report.overall_status, DataQualityStatus.FAIL)
        self.assertEqual(report.fail_count, 1)

    def test_missing_session_is_a_fail_closed_result(self) -> None:
        report = self.validator.compare(
            [make_bar(self.session, "100", source="tushare")],
            [],
        )
        self.assertEqual(report.overall_status, DataQualityStatus.FAIL)
        self.assertEqual(report.missing_count, 1)

    def test_rejects_duplicate_sessions(self) -> None:
        bar = make_bar(self.session, "100", source="tushare")
        with self.assertRaisesRegex(DataQualityError, "Duplicate primary session"):
            self.validator.compare([bar, bar], [])

    def test_rejects_mixed_assets(self) -> None:
        dia = AssetId(symbol="DIA", venue="ARCX", asset_class=AssetClass.ETF, currency="USD")
        with self.assertRaisesRegex(DataQualityError, "one identical asset"):
            self.validator.compare(
                [make_bar(self.session, "100", source="tushare")],
                [make_bar(self.session, "100", source="akshare", asset=dia)],
            )
