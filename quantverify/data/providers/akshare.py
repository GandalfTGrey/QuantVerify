"""AkShare US daily-bar adapter with explicit calendar and adjustment semantics.

The adapter captures one provider response and normalizes that exact capture
offline. It deliberately returns provider-labelled bars instead of treating an
AkShare response as verified research data. Callers must persist the capture and
run cross-source validation before creating a research dataset.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from importlib import import_module
from typing import Any, Protocol, cast

from pydantic import ValidationError

from quantverify.core.enums import AdjustmentMode, AssetClass
from quantverify.core.exceptions import DataQualityError, QuantVerifyError
from quantverify.core.models import AssetId
from quantverify.data.capture import RawCapture
from quantverify.data.models import NormalizedBar


class AkShareAdjustment(StrEnum):
    """AkShare adjustment argument with its QuantVerify data semantics."""

    RAW = ""
    QFQ = "qfq"

    @property
    def adjustment_mode(self) -> AdjustmentMode:
        """Return the strongest adjustment claim supported by this adapter."""

        if self is AkShareAdjustment.RAW:
            return AdjustmentMode.RAW
        # Do not call AkShare's qfq output total return until dividends and the
        # vendor's adjustment-factor semantics have been independently audited.
        return AdjustmentMode.SPLIT_ADJUSTED


class AkShareClient(Protocol):
    """Minimal AkShare surface used by this adapter, enabling deterministic tests."""

    def stock_us_daily(self, symbol: str, adjust: str = "") -> Any:
        """Return a dataframe-like US daily-price response."""


class SessionResolver(Protocol):
    """Resolve an actual exchange session to UTC trading timestamps."""

    def resolve(self, session: date) -> tuple[datetime, datetime]:
        """Return the open and close instants for one valid trading session."""


class USMarketSessionResolver:
    """US equity session resolver backed by ``pandas_market_calendars``.

    ``NYSE`` is used as the default US equity schedule. QQQ (XNAS) and DIA
    (ARCX) share its regular days and early-close schedule for M1 purposes. A
    source row on a non-session date is rejected rather than assigned a
    fabricated timestamp.
    """

    def __init__(self, calendar_name: str = "NYSE") -> None:
        self._calendar_name = calendar_name
        self._calendar: Any | None = None

    def resolve(self, session: date) -> tuple[datetime, datetime]:
        return self.resolve_many((session,))[session]

    def resolve_many(self, sessions: tuple[date, ...]) -> dict[date, tuple[datetime, datetime]]:
        """Resolve a group at once so full-history ingestion uses one schedule query."""

        if not sessions:
            return {}
        unique_sessions = tuple(sorted(set(sessions)))
        calendar = self._get_calendar()
        schedule = calendar.schedule(start_date=unique_sessions[0], end_date=unique_sessions[-1])
        resolved: dict[date, tuple[datetime, datetime]] = {}
        for session, row in schedule.iterrows():
            session_date = session.date()
            if session_date in unique_sessions:
                session_open = self._to_utc_datetime(row["market_open"])
                session_close = self._to_utc_datetime(row["market_close"])
                if session_open >= session_close:
                    raise DataQualityError(
                        f"Invalid exchange calendar interval for {session_date.isoformat()}"
                    )
                resolved[session_date] = (session_open, session_close)
        missing_sessions = sorted(set(unique_sessions).difference(resolved))
        if missing_sessions:
            missing = ", ".join(session.isoformat() for session in missing_sessions[:5])
            raise DataQualityError(
                f"AkShare returned non-{self._calendar_name} sessions: {missing}; "
                "the response cannot be timestamped safely"
            )
        return resolved

    def _get_calendar(self) -> Any:
        if self._calendar is None:
            try:
                market_calendars = import_module("pandas_market_calendars")
            except ModuleNotFoundError as error:
                raise QuantVerifyError(
                    "AkShare ingestion requires the optional 'market-data' dependencies. "
                    "Install with: pip install -e '.[market-data]'"
                ) from error
            self._calendar = market_calendars.get_calendar(self._calendar_name)
        return self._calendar

    @staticmethod
    def _to_utc_datetime(value: Any) -> datetime:
        candidate = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
        if not isinstance(candidate, datetime) or candidate.tzinfo is None:
            raise DataQualityError("Exchange calendar returned a timezone-naive timestamp")
        return candidate.astimezone(UTC)


class AkShareUSDailyProvider:
    """Capture, validate, and normalize AkShare ``stock_us_daily`` responses.

    This is an ingestion adapter, not a validation bypass. Its output source
    remains explicitly labelled ``akshare`` and is meant to enter the secondary
    side of the M1 comparison until an approved research dataset is released.
    """

    source_name = "akshare:stock_us_daily"
    capture_schema_version = "akshare-stock-us-daily-raw-v1"
    _required_columns = frozenset({"date", "open", "high", "low", "close", "volume"})

    def __init__(
        self,
        client: AkShareClient | None = None,
        session_resolver: SessionResolver | None = None,
    ) -> None:
        self._client = client
        self._session_resolver = session_resolver or USMarketSessionResolver()

    def load_daily(
        self,
        asset: AssetId,
        *,
        start: date | None = None,
        end: date | None = None,
        adjustment: AkShareAdjustment = AkShareAdjustment.RAW,
    ) -> tuple[NormalizedBar, ...]:
        """Capture once and normalize the exact response offline."""

        capture = self.capture_daily(asset, adjustment=adjustment)
        return self.normalize_daily(asset, capture, start=start, end=end)

    def capture_daily(
        self,
        asset: AssetId,
        *,
        adjustment: AkShareAdjustment = AkShareAdjustment.RAW,
    ) -> RawCapture:
        """Perform exactly one AkShare call and preserve the returned rows."""

        self._validate_request(asset, None, None)
        request = {"symbol": asset.symbol, "adjust": adjustment.value}
        response = self._get_client().stock_us_daily(**request)
        records = self._records_from(response)
        return RawCapture.from_records(
            provider="akshare",
            endpoint="stock_us_daily",
            request=request,
            records=records,
            captured_at=datetime.now(UTC),
            schema_version=self.capture_schema_version,
        )

    def normalize_daily(
        self,
        asset: AssetId,
        capture: RawCapture,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> tuple[NormalizedBar, ...]:
        """Normalize a previously captured AkShare response without network access."""

        self._validate_request(asset, start, end)
        adjustment = self._validate_capture(asset, capture)
        selected_records: list[tuple[int, date, Mapping[str, Any]]] = []
        seen_sessions: set[date] = set()

        for index, record in enumerate(capture.records):
            missing = self._required_columns.difference(record)
            if missing:
                columns = ", ".join(sorted(missing))
                raise DataQualityError(
                    f"AkShare row {index} is missing required columns: {columns}"
                )
            session = self._parse_session(record["date"], index)
            if session in seen_sessions:
                raise DataQualityError(
                    f"AkShare response has duplicate session: {session.isoformat()}"
                )
            seen_sessions.add(session)

            if (start is not None and session < start) or (end is not None and session > end):
                continue
            selected_records.append((index, session, record))

        session_times = self._resolve_sessions(tuple(session for _, session, _ in selected_records))
        bars: list[NormalizedBar] = []
        for index, session, record in selected_records:
            session_open_at, session_close_at = session_times[session]
            try:
                bar = NormalizedBar(
                    asset=asset,
                    session=session,
                    session_open_at=session_open_at,
                    session_close_at=session_close_at,
                    available_at=session_close_at,
                    open=self._parse_decimal(record["open"], "open", index),
                    high=self._parse_decimal(record["high"], "high", index),
                    low=self._parse_decimal(record["low"], "low", index),
                    close=self._parse_decimal(record["close"], "close", index),
                    volume=self._parse_decimal(record["volume"], "volume", index),
                    source=f"{self.source_name}:{adjustment.name.lower()}",
                )
            except ValidationError as error:
                raise DataQualityError(
                    f"AkShare row {index} violates the normalized-bar contract: {error}"
                ) from error
            bars.append(bar)

        return tuple(sorted(bars, key=lambda bar: bar.session))

    def _resolve_sessions(
        self, sessions: tuple[date, ...]
    ) -> dict[date, tuple[datetime, datetime]]:
        if isinstance(self._session_resolver, USMarketSessionResolver):
            return self._session_resolver.resolve_many(sessions)
        return {session: self._session_resolver.resolve(session) for session in sessions}

    def fetch_daily_records(
        self,
        asset: AssetId,
        *,
        adjustment: AkShareAdjustment = AkShareAdjustment.RAW,
    ) -> tuple[Mapping[str, Any], ...]:
        """Compatibility API returning records from exactly one raw capture."""

        return self.capture_daily(asset, adjustment=adjustment).records

    def _get_client(self) -> AkShareClient:
        if self._client is None:
            try:
                akshare = import_module("akshare")
            except ModuleNotFoundError as error:
                raise QuantVerifyError(
                    "AkShare is not installed. Install with: pip install -e '.[market-data]'"
                ) from error
            self._client = cast(AkShareClient, akshare)
        return self._client

    @staticmethod
    def _validate_request(asset: AssetId, start: date | None, end: date | None) -> None:
        if asset.asset_class not in {AssetClass.ETF, AssetClass.EQUITY}:
            raise DataQualityError("AkShare stock_us_daily only supports equity or ETF assets")
        if start is not None and end is not None and start > end:
            raise DataQualityError("start must not be later than end")

    @staticmethod
    def _validate_capture(asset: AssetId, capture: RawCapture) -> AkShareAdjustment:
        if capture.provider != "akshare" or capture.endpoint != "stock_us_daily":
            raise DataQualityError("capture does not belong to the AkShare stock_us_daily adapter")
        if capture.request.get("symbol") != asset.symbol:
            raise DataQualityError("capture symbol does not match requested asset")
        adjust = capture.request.get("adjust")
        try:
            return AkShareAdjustment(str(adjust))
        except ValueError as error:
            raise DataQualityError(f"capture has unsupported AkShare adjustment: {adjust!r}") from error

    @staticmethod
    def _records_from(response: Any) -> tuple[Mapping[str, Any], ...]:
        if not hasattr(response, "to_dict"):
            raise DataQualityError("AkShare response must be a dataframe-like object with to_dict")
        records = response.to_dict(orient="records")
        records_are_mappings = isinstance(records, list) and all(
            isinstance(record, Mapping) for record in records
        )
        if not records_are_mappings:
            raise DataQualityError("AkShare response could not be converted to row records")
        return tuple(dict(record) for record in records)

    @staticmethod
    def _parse_session(value: Any, index: int) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value))
        except ValueError as error:
            try:
                return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
            except ValueError:
                raise DataQualityError(
                    f"AkShare row {index} has invalid date: {value!r}"
                ) from error

    @staticmethod
    def _parse_decimal(value: Any, field: str, index: int) -> Decimal:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError) as error:
            raise DataQualityError(
                f"AkShare row {index} has a non-numeric {field} value: {value!r}"
            ) from error
        if not parsed.is_finite():
            raise DataQualityError(f"AkShare row {index} has a non-finite {field} value: {value!r}")
        return parsed
