"""Market data and the market's clock: quotes, daily history, and when the US market is actually open.

Prices come through the existing keyless finance connector. The calendar is
worked out here rather than fetched, so the AI trader can schedule itself
offline: real New York daylight saving, NYSE holidays, and the 1 pm early
closes (Project Null N80 — "active 24/7 or until stop so the user doesn't have
to manually start when US markets open").
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

_CACHE: Dict[str, Any] = {}
_QUOTE_TTL = 20.0
_HISTORY_TTL = 900.0


class MarketDataError(RuntimeError):
    """No price could be fetched; the message says why."""


def _connector():
    from connectors.finance_connector import FinanceConnector

    return FinanceConnector()


def quote(symbol: str) -> Dict[str, Any]:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        raise MarketDataError("Give a ticker symbol, like AAPL.")
    cached = _CACHE.get(f"q:{symbol}")
    if cached and time.time() - cached[0] < _QUOTE_TTL:
        return cached[1]
    result = _connector().quote(symbol)
    rows = result.get("quotes") or result.get("data") or []
    if not result.get("success", True) or not rows:
        raise MarketDataError(result.get("error") or f"No price for {symbol} right now.")
    row = rows[0]
    price = float(row.get("close") or 0)
    if price <= 0:
        raise MarketDataError(f"No price for {symbol} right now.")
    previous = row.get("previous_close")
    data = {"symbol": symbol, "price": price, "previous_close": float(previous) if previous else None,
            "change_pct": round((price / float(previous) - 1) * 100, 2) if previous else None,
            "currency": row.get("currency", "USD"), "as_of": row.get("date", "")}
    _CACHE[f"q:{symbol}"] = (time.time(), data)
    return data


def history(symbol: str, range_: str = "6mo") -> List[Dict[str, Any]]:
    symbol = (symbol or "").strip().upper()
    cached = _CACHE.get(f"h:{symbol}:{range_}")
    if cached and time.time() - cached[0] < _HISTORY_TTL:
        return cached[1]
    result = _connector().history(symbol, range_)
    rows = result.get("rows") or result.get("history") or []
    if not rows:
        raise MarketDataError(result.get("error") or f"No price history for {symbol}.")
    clean = [{"date": r.get("date"), "close": float(r["close"]), "volume": float(r.get("volume") or 0)}
             for r in rows if r.get("close") is not None]
    _CACHE[f"h:{symbol}:{range_}"] = (time.time(), clean)
    return clean


def _new_york(now: datetime) -> datetime:
    """``now`` in New York time, with the real daylight-saving rule.

    The old version used "March to October = summer time", which is wrong for
    the first week of March and the first week of November — a week each year
    when the AI trader would have thought the market opened an hour late or
    closed an hour early. DST runs from the second Sunday in March at 07:00 UTC
    to the first Sunday in November at 06:00 UTC.
    """
    year = now.year
    march = datetime(year, 3, 8, 7, 0, tzinfo=timezone.utc)
    starts = march + timedelta(days=(6 - march.weekday()) % 7)  # second Sunday in March
    november = datetime(year, 11, 1, 6, 0, tzinfo=timezone.utc)
    ends = november + timedelta(days=(6 - november.weekday()) % 7)  # first Sunday in November
    daylight = starts <= now < ends
    return now.astimezone(timezone(timedelta(hours=-4 if daylight else -5)))


def _easter(year: int) -> date:
    """Gregorian Easter Sunday (the anonymous algorithm) — Good Friday is the only moving NYSE holiday."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    el = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * el) // 451
    return date(year, (h + el - 7 * m + 114) // 31, ((h + el - 7 * m + 114) % 31) + 1)


def _weekday_of(year: int, month: int, weekday: int, nth: int) -> date:
    """The ``nth`` ``weekday`` of a month (nth = -1 for the last one)."""
    if nth > 0:
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (nth - 1))
    last_day = (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1))
    return last_day - timedelta(days=(last_day.weekday() - weekday) % 7)


def _observed(day: date) -> date:
    """A holiday on a Saturday is taken on the Friday, on a Sunday the Monday."""
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def market_holidays(year: int) -> Dict[date, str]:
    """NYSE full-day closures for a year, by date."""
    easter = _easter(year)
    days = {
        _observed(date(year, 1, 1)): "New Year's Day",
        _weekday_of(year, 1, 0, 3): "Martin Luther King, Jr. Day",
        _weekday_of(year, 2, 0, 3): "Washington's Birthday",
        easter - timedelta(days=2): "Good Friday",
        _weekday_of(year, 5, 0, -1): "Memorial Day",
        _observed(date(year, 6, 19)): "Juneteenth",
        _observed(date(year, 7, 4)): "Independence Day",
        _weekday_of(year, 9, 0, 1): "Labor Day",
        _weekday_of(year, 11, 3, 4): "Thanksgiving",
        _observed(date(year, 12, 25)): "Christmas",
    }
    return {day: name for day, name in days.items() if day.weekday() < 5}


def _early_close(day: date) -> bool:
    """1 pm closes: the day before Independence Day, the day after Thanksgiving, Christmas Eve."""
    if day.weekday() >= 5 or day in market_holidays(day.year):
        return False
    if day == _weekday_of(day.year, 11, 3, 4) + timedelta(days=1):
        return True
    if day.month == 7 and day.day == 3:
        return True
    return day.month == 12 and day.day == 24


def session(now: Optional[datetime] = None) -> Dict[str, Any]:
    """What the US market is doing right now, and when it next changes.

    Everything that schedules itself (the AI trader's run modes, the countdown
    in the Trading tab) reads this one answer instead of re-deriving the clock.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    local = _new_york(now)
    day = local.date()
    holidays = market_holidays(day.year)
    minutes = local.hour * 60 + local.minute
    close_minutes = 13 * 60 if _early_close(day) else 16 * 60
    holiday = holidays.get(day)
    weekend = local.weekday() >= 5

    if weekend or holiday:
        phase, reason = "closed", (f"Closed — {holiday}." if holiday else "Closed — weekend.")
    elif minutes < 4 * 60:
        phase, reason = "closed", "Closed — overnight."
    elif minutes < 9 * 60 + 30:
        phase, reason = "pre", "Pre-market (4:00–9:30 New York)."
    elif minutes < close_minutes:
        phase, reason = "regular", "US market is open."
    elif minutes < 20 * 60:
        phase, reason = "after", "After-hours (until 8:00 pm New York)."
    else:
        phase, reason = "closed", "Closed for the day."
    if _early_close(day) and phase in ("regular", "after"):
        reason += " Early close at 1 pm."

    return {"phase": phase, "open": phase == "regular", "reason": reason, "new_york": local.isoformat(timespec="minutes"),
            "holiday": holiday or "", "early_close": _early_close(day),
            "next_open": next_open(now).timestamp(), "next_close": _next_close(now).timestamp()}


def next_open(now: Optional[datetime] = None) -> datetime:
    """When the next regular session starts (UTC). Today's open if it has not happened yet."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    for ahead in range(0, 10):
        local = _new_york(now) + timedelta(days=ahead)
        day = local.date()
        if local.weekday() >= 5 or day in market_holidays(day.year):
            continue
        opens = local.replace(hour=9, minute=30, second=0, microsecond=0)
        if opens.timestamp() > now.timestamp():
            return opens.astimezone(timezone.utc)
    return now + timedelta(days=1)  # pragma: no cover - ten closed days in a row cannot happen


def _next_close(now: Optional[datetime] = None) -> datetime:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    for ahead in range(0, 10):
        local = _new_york(now) + timedelta(days=ahead)
        day = local.date()
        if local.weekday() >= 5 or day in market_holidays(day.year):
            continue
        hour = 13 if _early_close(day) else 16
        closes = local.replace(hour=hour, minute=0, second=0, microsecond=0)
        if closes.timestamp() > now.timestamp():
            return closes.astimezone(timezone.utc)
    return now + timedelta(days=1)  # pragma: no cover


def us_market_open(now: Optional[datetime] = None) -> bool:
    """Regular US session: Mon–Fri 9:30–16:00 New York, minus NYSE holidays and early closes."""
    return bool(session(now)["open"])
