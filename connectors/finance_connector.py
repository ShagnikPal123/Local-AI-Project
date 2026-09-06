"""Finance connector for live market data: stock quotes, history, and market status.

Keyless public sources only: Yahoo Finance chart JSON as the primary feed with
Stooq CSV as a fallback. Every call is gated by the shared web-access
permission and connectivity checks so offline mode stays offline.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from connectors.base import BaseConnector, ConnectorManifest
from connectivity import is_online
import web_access

_TIMEOUT = 10
_YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
_STOOQ_QUOTE_URL = "https://stooq.com/q/l/"
_STOOQ_HISTORY_URL = "https://stooq.com/q/d/l/"
_USER_AGENT = {"User-Agent": "Mozilla/5.0"}

_HISTORY_RANGES = {"1mo", "3mo", "6mo", "1y", "2y", "5y"}
_STOOQ_DAYS = {"1mo": 22, "3mo": 66, "6mo": 132, "1y": 260, "2y": 520, "5y": 1300}


class FinanceConnector(BaseConnector):
    """Live market data: quotes, history, and US market open/close status."""

    def __init__(self) -> None:
        self._manifest = ConnectorManifest(
            name="finance",
            description=(
                "Live stock and market data: quotes, historical prices, and "
                "US market open/close status (keyless feeds: Yahoo + Stooq)."
            ),
            permissions=["read", "network"],
            is_offline=False,
            requires_auth=False,
            is_write=False,
            risk_level="low",
        )

    @property
    def manifest(self) -> ConnectorManifest:
        return self._manifest

    def is_available(self) -> bool:
        return web_access.is_enabled()

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        """Normalize a ticker: keep Yahoo-style pairs, add .us for Stooq."""
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return ""
        return symbol

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        if action == "quote":
            return self.quote(params.get("symbols", ""))
        if action == "history":
            return self.history(params.get("symbol", ""), params.get("range", "3mo"))
        if action == "market_status":
            return self.market_status()
        return {"success": False, "error": f"Unknown action '{action}' for finance connector."}

    # ------------------------------------------------------------------
    # Parsers (pure, unit-testable)
    # ------------------------------------------------------------------

    @staticmethod
    def parse_yahoo_quote(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract the latest quote from a Yahoo chart API payload."""
        result = ((payload.get("chart") or {}).get("result") or [None])[0]
        if not result:
            return []
        meta = result.get("meta", {})
        price = meta.get("regularMarketPrice")
        if price is None:
            return []
        previous = meta.get("chartPreviousClose") or meta.get("previousClose")
        timestamp = meta.get("regularMarketTime") or 0
        date = (
            datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
            if timestamp
            else ""
        )
        return [
            {
                "symbol": meta.get("symbol", "?"),
                "date": date,
                "open": None,
                "high": None,
                "low": None,
                "close": float(price),
                "previous_close": float(previous) if previous is not None else None,
                "currency": meta.get("currency", "USD"),
            }
        ]

    @staticmethod
    def parse_yahoo_history(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract OHLCV rows from a Yahoo chart API payload."""
        result = ((payload.get("chart") or {}).get("result") or [None])[0]
        if not result:
            return []
        timestamps = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []
        rows: List[Dict[str, Any]] = []
        for index, ts in enumerate(timestamps):
            if index >= len(closes) or closes[index] is None:
                continue
            rows.append(
                {
                    "date": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"),
                    "open": FinanceConnector._to_float(opens[index]) if index < len(opens) else None,
                    "high": FinanceConnector._to_float(highs[index]) if index < len(highs) else None,
                    "low": FinanceConnector._to_float(lows[index]) if index < len(lows) else None,
                    "close": FinanceConnector._to_float(closes[index]),
                    "volume": FinanceConnector._to_float(volumes[index]) if index < len(volumes) else None,
                }
            )
        return rows

    @staticmethod
    def parse_quote_csv(text: str) -> List[Dict[str, Any]]:
        """Parse Stooq quote CSV into rows of quote data."""
        rows: List[Dict[str, Any]] = []
        try:
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                symbol = (row.get("Symbol") or "").strip()
                close_raw = (row.get("Close") or "").strip()
                if not symbol or close_raw in ("", "N/D"):
                    continue
                rows.append(
                    {
                        "symbol": symbol,
                        "date": row.get("Date", "").strip(),
                        "open": FinanceConnector._to_float(row.get("Open")),
                        "high": FinanceConnector._to_float(row.get("High")),
                        "low": FinanceConnector._to_float(row.get("Low")),
                        "close": FinanceConnector._to_float(close_raw),
                        "volume": FinanceConnector._to_float(row.get("Volume")),
                    }
                )
        except csv.Error:
            return []
        return rows

    @staticmethod
    def parse_history_csv(text: str) -> List[Dict[str, Any]]:
        """Parse Stooq daily history CSV (Date,Open,High,Low,Close,Volume)."""
        rows: List[Dict[str, Any]] = []
        try:
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                date = (row.get("Date") or "").strip()
                close_raw = (row.get("Close") or "").strip()
                if not date or not close_raw:
                    continue
                rows.append(
                    {
                        "date": date,
                        "open": FinanceConnector._to_float(row.get("Open")),
                        "high": FinanceConnector._to_float(row.get("High")),
                        "low": FinanceConnector._to_float(row.get("Low")),
                        "close": FinanceConnector._to_float(close_raw),
                        "volume": FinanceConnector._to_float(row.get("Volume")),
                    }
                )
        except csv.Error:
            return []
        return rows

    @staticmethod
    def _to_float(value: Optional[str]) -> Optional[float]:
        try:
            return float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def quote(self, symbols: str) -> Dict[str, Any]:
        """Fetch live quotes for one or more comma-separated symbols."""
        if not symbols or not symbols.strip():
            return {"success": False, "error": "Provide at least one symbol (e.g. AAPL, MSFT)."}
        if not self.is_available() or not is_online():
            return {"success": False, "error": "Web access is required for live market data."}

        cleaned = [s.strip() for s in symbols.split(",") if s.strip()]
        quotes: List[Dict[str, Any]] = []
        for symbol in cleaned[:5]:
            payload = self._fetch_yahoo(symbol, range="5d", interval="1d")
            if payload is not None:
                parsed = self.parse_yahoo_quote(payload)
                if parsed:
                    quotes.extend(parsed)
                    continue
            # Fallback: Stooq CSV.
            stooq = self._fetch_stooq_quote(symbol)
            if stooq is not None:
                quotes.extend(stooq)

        if not quotes:
            return {"success": False, "error": "No quotes found for the requested symbols."}
        return {"success": True, "quotes": quotes, "source": "yahoo"}

    def history(self, symbol: str, range: str = "3mo") -> Dict[str, Any]:
        """Fetch daily price history for a symbol (range: 1mo, 3mo, 6mo, 1y, 2y, 5y)."""
        symbol = (symbol or "").strip()
        if not symbol:
            return {"success": False, "error": "Provide a symbol (e.g. AAPL)."}
        if not self.is_available() or not is_online():
            return {"success": False, "error": "Web access is required for live market data."}
        if range not in _HISTORY_RANGES:
            return {"success": False, "error": f"Range must be one of: {', '.join(sorted(_HISTORY_RANGES))}."}

        payload = self._fetch_yahoo(symbol, range=range, interval="1d")
        if payload is not None:
            rows = self.parse_yahoo_history(payload)
            if rows:
                return {"success": True, "symbol": symbol, "range": range, "rows": rows, "source": "yahoo"}

        # Fallback: Stooq daily CSV, trimmed to the requested range.
        try:
            response = requests.get(
                _STOOQ_HISTORY_URL,
                params={"s": f"{symbol.lower()}.us", "i": "d"},
                timeout=_TIMEOUT,
            )
            response.raise_for_status()
        except requests.RequestException:
            return {"success": False, "error": "History feed unreachable. Try again when online."}

        rows = self.parse_history_csv(response.text)
        if not rows:
            return {"success": False, "error": f"No history found for symbol '{symbol}'."}
        trimmed = rows[-_STOOQ_DAYS[range] :]
        return {"success": True, "symbol": symbol, "range": range, "rows": trimmed, "source": "stooq"}

    def market_status(self) -> Dict[str, Any]:
        """Return whether US stock markets are currently open (Eastern Time)."""
        now = datetime.now(timezone.utc)
        # US Eastern: UTC-4 during daylight saving (Mar-Nov), UTC-5 otherwise.
        eastern_offset = -4 if (3 <= now.month <= 11) else -5
        minute_eastern = (now.hour + eastern_offset) * 60 + now.minute
        minute_eastern %= 24 * 60
        is_weekday = now.weekday() < 5
        is_open = is_weekday and 9 * 60 + 30 <= minute_eastern <= 16 * 60
        return {
            "success": True,
            "open": is_open,
            "timezone": "America/New_York (approx)",
            "note": "Holiday closures are not detected automatically.",
        }

    # ------------------------------------------------------------------
    # Feed helpers
    # ------------------------------------------------------------------

    def _fetch_yahoo(self, symbol: str, range: str, interval: str) -> Optional[Dict[str, Any]]:
        try:
            response = requests.get(
                _YAHOO_CHART_URL + self.normalize_symbol(symbol),
                params={"range": range, "interval": interval},
                timeout=_TIMEOUT,
                headers=_USER_AGENT,
            )
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            return None

    def _fetch_stooq_quote(self, symbol: str) -> Optional[List[Dict[str, Any]]]:
        try:
            response = requests.get(
                _STOOQ_QUOTE_URL,
                params={"s": f"{symbol.lower()}.us", "f": "sd2t2ohlcv", "h": "", "e": "csv"},
                timeout=_TIMEOUT,
            )
            response.raise_for_status()
        except requests.RequestException:
            return None
        rows = self.parse_quote_csv(response.text)
        return rows or None
