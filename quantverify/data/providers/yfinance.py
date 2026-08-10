"""Yahoo Finance daily-bar adapter for research-only cross validation.

The provider captures the provider-facing response once, then normalizes that
exact immutable capture offline. It deliberately does not promote ``Adj Close``
to an OHLC field: adjusted returns and corporate actions must be audited
separately before they can inform a research dataset.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from importlib import import_module
from typing import Any, Protocol, cast

from pydantic import ValidationError

from quantverify.core.enums import AssetClass
from quantverify.core.exceptions import DataQualityError, QuantVerifyError
from quantverify.core.models import AssetId
from quantverify.data.capture import RawCapture
from quantverify.data.models import NormalizedBar
from quantverify.data.providers.akshare import SessionResolver, USMarketSessionResolver


class YFinanceClient(Protocol):
    """Minimal yfinance surface used by this adapter."""

    def download(
        self,
        tickers: str,
        *,
        start: str,
        end: str,
        interval: str,
        auto_adjust: bool,
        actions: bool,
        progress: bool,
        threads: bool,
        group_by: str,
        multi_level_index: bool,
    ) -> Any:
        """Return a dataframe-like daily-price response."""


class YFinanceUSDailyProvider:
    """Load raw US daily bars from ``yfinance.download``.

    Yahoo Finance data is public-access research data with personal-use terms.
    This adapter therefore remains an explicitly labelled secondary source and
    cannot independently approve a production dataset.
    """

    source_name = "yfinance:download"
    capture_schema_version = "yfinance-download-raw-v1"
    _required_columns = frozenset({"date", "open", "high", "low", "close", "volume"})

    def __init__(
        self,
        client: YFinanceClient | None = None,
        session_resolver: SessionResolver | None = None,
    ) -> None:
        self._client = client
        self._session_resolver = session_resolver or USMarketSessionResolver()

    def load_daily(
        self,
        asset: AssetId,
        *,
        start: date,
        end: date,
    ) -> tuple[NormalizedBar, ...]:
        """Capture once and normalize the exact response offline."""

        capture = self.capture_daily(asset, start=start, end=end)
        return self.normalize_daily(asset, capture, start=start, end=end)

    def capture_daily(
        self,
        asset: AssetId,
        *,
        start: date,
        end: date,
    ) -> RawCapture:
        """Perform exactly one provider request and preserve its provider-facing rows."""

        self._validate_request(asset, start, end)
        request: dict[str, Any] = {
            "tickers": asset.symbol,
            "start": start.isoformat(),
            "end": (end + timedelta(days=1)).isoformat(),
            "interval": "1d",
            "auto_adjust": False,
            "actions": False,
            "progress": False,
            "threads": False,
            "group_by": "column",
            "multi_level_index": False,
        }
        response = self._get_client().download(**request)
        records = self._raw_records_from(response)
        return RawCapture.from_records(
            provider="yfinance",
            endpoint="download",
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
        start: date,
        end: date,
    ) -> tuple[NormalizedBar, ...]:
        """Normalize a previously captured response without provider access."""

        self._validate_request(asset, start, end)
        self._validate_capture(asset, capture)
        seen_sessions: set[date] = set()
        selected_records: list[tuple[int, date, Mapping[str, Any]]] = []
        for index, raw_record in enumerate(capture.records):
            record = self._canonicalize_record(raw_record)
            missing = self._required_columns.difference(record)
            if missing:
                columns = ", ".join(sorted(missing))
                raise DataQualityError(
                    f"yfinance row {index} is missing required columns: {columns}"
                )
            session = self._parse_session(record["date"], index)
            if session in seen_sessions:
                raise DataQualityError(
                    f"yfinance response has duplicate session: {session.isoformat()}"
                )
            seen_sessions.add(session)
            if session < start or session > end:
                message = (
                    f"yfinance row {index} is outside requested inclusive range: "
                    f"{session.isoformat()}"
                )
                raise DataQualityError(message)
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
                    source=f"{self.source_name}:raw",
                )
            except ValidationError as error:
                raise DataQualityError(
                    f"yfinance row {index} violates the normalized-bar contract: {error}"
                ) from error
            bars.append(bar)
        if not bars:
            raise DataQualityError("yfinance returned no bars for the requested range")
        return tuple(sorted(bars, key=lambda bar: bar.session))

    def fetch_daily_records(
        self,
        asset: AssetId,
        *,
        start: date,
        end: date,
    ) -> tuple[Mapping[str, Any], ...]:
        """Compatibility API returning canonical records from one raw capture.

        New ingestion workflows should use :meth:`capture_daily` directly so the
        exact provider-facing response and request provenance can be persisted.
        """

        capture = self.capture_daily(asset, start=start, end=end)
        return tuple(self._canonicalize_record(record) for record in capture.records)

    def _resolve_sessions(
        self, sessions: tuple[date, ...]
    ) -> dict[date, tuple[datetime, datetime]]:
        if isinstance(self._session_resolver, USMarketSessionResolver):
            return self._session_resolver.resolve_many(sessions)
        return {session: self._session_resolver.resolve(session) for session in sessions}

    def _get_client(self) -> YFinanceClient:
        if self._client is None:
            try:
                yfinance = import_module("yfinance")
            except ModuleNotFoundError as error:
                raise QuantVerifyError(
                    "yfinance ingestion requires the optional 'market-data' dependencies. "
                    "Install with: pip install -e '.[market-data]'"
                ) from error
            self._client = cast(YFinanceClient, yfinance)
        return self._client

    @staticmethod
    def _validate_request(asset: AssetId, start: date, end: date) -> None:
        if asset.asset_class not in {AssetClass.ETF, AssetClass.EQUITY}:
            raise DataQualityError("yfinance daily ingestion only supports equity or ETF assets")
        if start > end:
            raise DataQualityError("start must not be later than end")

    @staticmethod
    def _validate_capture(asset: AssetId, capture: RawCapture) -> None:
        if capture.provider != "yfinance" or capture.endpoint != "download":
            raise DataQualityError("capture does not belong to the yfinance download adapter")
        if capture.schema_version != YFinanceUSDailyProvider.capture_schema_version:
            raise DataQualityError(
                f"unsupported yfinance capture schema: {capture.schema_version!r}"
            )
        if capture.request.get("tickers") != asset.symbol:
            raise DataQualityError("capture ticker does not match requested asset")

    @classmethod
    def _raw_records_from(cls, response: Any) -> tuple[Mapping[str, Any], ...]:
        if not hasattr(response, "reset_index") or not hasattr(response, "empty"):
            raise DataQualityError("yfinance response must be a dataframe-like object")
        if response.empty:
            return ()
        flattened = response.reset_index()
        if not hasattr(flattened, "to_dict"):
            raise DataQualityError("yfinance response could not be converted to row records")
        rows = flattened.to_dict(orient="records")
        if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
            raise DataQualityError("yfinance response could not be converted to row records")
        return tuple(dict(row) for row in rows)

    @staticmethod
    def _canonicalize_record(record: Mapping[str, Any]) -> Mapping[str, Any]:
        aliases = {
            "date": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
        return {target: record.get(source) for target, source in aliases.items()}

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
                    f"yfinance row {index} has invalid date: {value!r}"
                ) from error

    @staticmethod
    def _parse_decimal(value: Any, field: str, index: int) -> Decimal:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError) as error:
            raise DataQualityError(
                f"yfinance row {index} has a non-numeric {field} value: {value!r}"
            ) from error
        if not parsed.is_finite():
            message = f"yfinance row {index} has a non-finite {field} value: {value!r}"
            raise DataQualityError(message)
        return parsed
