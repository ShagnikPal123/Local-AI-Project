"""Alpaca's practice (paper) account as a broker, and nothing else.

Alpaca is the recommended first broker: stocks, ETFs and crypto behind one free API, with a free
practice account that fills against real prices. This adapter only ever talks to the **paper**
endpoint; the live one is refused in code until the owner says yes to real money.

Three rules make it behave the way a real account would need, even though the person may hold
other things in the same account:

* **It only sees what it bought.** Positions are the account's positions that the trader's own
  ledger says it opened, and never more than the quantity it bought. The person's own shares are
  invisible to the bots, so the manager and "sell everything" can't touch them.
* **It only uses the budget.** With a budget, the cash the bots see is the budget plus what they
  have earned, minus what they have invested, and never more than the account really has.
* **Every fill is written down here**, with the bot that placed it, because Alpaca does not know
  which bot asked.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

import requests

from .. import store
from ..access import secrets
from ..models import BrokerError, Fill, Order, Quote

PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL = "https://api.alpaca.markets"
KEYS = ("alpaca_key_id", "alpaca_secret_key")
CURVE_EVERY = 300.0


def _ledger() -> Dict[str, Any]:
    return {"held": {}, "fills": [], "curve": [], "realized": 0.0, "wins": 0, "losses": 0, "peak": 0.0,
            "created_at": time.time()}


def _symbol(raw: str, asset_class: str) -> str:
    """Alpaca writes BTC/USD or BTCUSD; the trader writes BTC-USD."""
    if asset_class != "crypto":
        return raw
    if "/" in raw:
        return raw.replace("/", "-")
    return raw[:-3] + "-USD" if raw.endswith("USD") else raw


class Alpaca:
    name = "alpaca"

    def __init__(self, http: Optional[requests.Session] = None, budget: float = 0.0, base_url: str = PAPER_URL,
                 clock: Callable[[], float] = time.time):
        if base_url.rstrip("/") != PAPER_URL:
            raise BrokerError("Only Alpaca's practice account is allowed. Real money is off.")
        self.kind = "practice"
        self.base = PAPER_URL
        self.http = http or requests.Session()
        self.budget = max(0.0, float(budget or 0))
        self.label = "Alpaca practice account"
        self._clock = clock
        self._store = "alpaca_practice"

    def money(self) -> str:
        return self.kind

    # --- talking to Alpaca ------------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        key, secret = (secrets.get(n) for n in KEYS)
        if not key or not secret:
            raise BrokerError("Alpaca is not connected: add the practice keys on the Connectors page.")
        return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            reply = self.http.request(method, self.base + path, headers=self._headers(), timeout=10, **kwargs)
        except requests.RequestException as error:
            raise BrokerError("Could not reach Alpaca.") from error
        if reply.status_code in (401, 403):
            raise BrokerError("Alpaca refused the keys. Check they are the practice (paper) keys.")
        if reply.status_code >= 400:
            raise BrokerError(f"Alpaca said no ({reply.status_code}).")
        return reply.json()

    def test(self) -> str:
        account = self._call("GET", "/v2/account")
        return f"Connected to the practice account ({account.get('currency', 'USD')} {float(account.get('equity', 0)):,.2f})."

    # --- what the bots see ------------------------------------------------------------------

    def _book(self) -> Dict[str, Any]:
        data = store.read(self._store, _ledger)
        for key, value in _ledger().items():
            data.setdefault(key, value)
        return data

    def positions(self) -> List[Dict[str, Any]]:
        held = self._book()["held"]
        out = []
        for p in self._call("GET", "/v2/positions"):
            kind = "crypto" if p.get("asset_class") == "crypto" else "stock"
            symbol = _symbol(p["symbol"], kind)
            mine = held.get(symbol)
            if not mine:
                continue  # the person's own holding: not the bots' to see or sell
            qty = min(float(p["qty"]), float(mine["qty"]))
            avg, price = float(mine.get("avg_price") or p["avg_entry_price"]), float(p["current_price"])
            value, cost = qty * price, qty * avg
            out.append({"symbol": symbol, "asset_class": mine.get("asset_class", kind), "qty": qty, "avg_price": avg,
                        "price": price, "value": round(value, 2), "pl": round(value - cost, 2),
                        "pl_pct": round((value / cost - 1) * 100, 2) if cost else 0.0, "bot": mine.get("bot", ""),
                        "opened_at": mine.get("opened_at", 0)})
        return sorted(out, key=lambda p: -p["value"])

    def account(self) -> Dict[str, Any]:
        a = self._call("GET", "/v2/account")
        book, mine = self._book(), self.positions()
        cash_all, equity_all = float(a.get("cash", 0)), float(a.get("equity", 0))
        value = sum(p["value"] for p in mine)
        if self.budget:
            cost = sum(p["qty"] * p["avg_price"] for p in mine)
            cash = max(0.0, min(cash_all, self.budget + book["realized"] - cost))
            equity, start = cash + value, self.budget
        else:
            cash, equity = cash_all, equity_all
            start = float(a.get("last_equity", equity_all)) or equity_all
        closed = book["wins"] + book["losses"]
        return {"currency": a.get("currency", "USD"), "cash": round(cash, 2), "equity": round(equity, 2),
                "start": start, "pl": round(equity - start, 2),
                "pl_pct": round((equity / start - 1) * 100, 3) if start else 0.0,
                "peak": max(float(book.get("peak") or 0), equity), "realized": round(book["realized"], 2),
                "fees": 0.0, "wins": book["wins"], "losses": book["losses"], "closed": closed,
                "win_rate": round(book["wins"] / closed, 3) if closed else None, "created_at": book["created_at"],
                "money": self.kind, "budget": self.budget or None}

    def fills(self, limit: int = 50) -> List[Dict[str, Any]]:
        return list(reversed(self._book()["fills"][-limit:]))

    def curve(self) -> List[Dict[str, float]]:
        return list(self._book()["curve"])

    def mark(self, prices: Dict[str, float]) -> None:
        """One equity point every 5 minutes, and the best point so far for the watchdog."""
        try:
            equity = self.account()["equity"]
        except BrokerError:
            return
        now = self._clock()

        def change(data: Dict[str, Any]) -> None:
            data["peak"] = max(float(data.get("peak") or 0), equity)
            if not data["curve"] or now - data["curve"][-1]["t"] >= CURVE_EVERY:
                data["curve"] = (data["curve"] + [{"t": now, "equity": round(equity, 2)}])[-3000:]

        store.update(self._store, _ledger, change)

    # --- trading ----------------------------------------------------------------------------

    def place(self, order: Order, quote: Quote) -> Fill:
        if order.asset_class == "fx":
            raise BrokerError("Alpaca does not trade currencies.")
        held = self._book()["held"].get(order.symbol)
        qty = order.qty
        if order.side == "sell":
            qty = min(qty, float(held["qty"]) if held else 0.0)
            if qty <= 0:
                raise BrokerError(f"The trader only sells what it bought, and it holds no {order.symbol}.")
        sent = self._call("POST", "/v2/orders", json={
            "symbol": order.symbol.replace("-", "/") if order.asset_class == "crypto" else order.symbol,
            "qty": f"{qty:.6f}", "side": order.side, "type": "market",
            "time_in_force": "gtc" if order.asset_class == "crypto" else "day"})
        price = float(sent.get("filled_avg_price") or quote.price)
        fill = Fill(sent.get("id", order.id), order.symbol, order.side, qty, price, 0.0, order.bot, order.reason,
                    self.kind, self._clock())

        def change(data: Dict[str, Any]) -> None:
            pos = data["held"].get(order.symbol)
            realized = None
            if order.side == "buy":
                pos = pos or {"qty": 0.0, "avg_price": 0.0, "asset_class": order.asset_class, "bot": order.bot,
                              "opened_at": fill.at}
                total = pos["qty"] + qty
                pos["avg_price"] = (pos["qty"] * pos["avg_price"] + qty * price) / total
                pos["qty"] = total
                data["held"][order.symbol] = pos
            elif pos:
                realized = (price - pos["avg_price"]) * qty
                data["realized"] += realized
                data["wins" if realized > 0 else "losses"] += 1
                pos["qty"] -= qty
                if pos["qty"] <= 1e-12:
                    data["held"].pop(order.symbol)
            row = fill.to_dict()
            row["asset_class"] = order.asset_class
            row["realized"] = None if realized is None else round(realized, 2)
            data["fills"] = (data["fills"] + [row])[-2000:]

        store.update(self._store, _ledger, change)
        return fill

    def held(self, symbol: str) -> float:
        pos = self._book()["held"].get(symbol)
        return float(pos["qty"]) if pos else 0.0

    def owner_of(self, symbol: str) -> Optional[str]:
        pos = self._book()["held"].get(symbol)
        return pos.get("bot") if pos else None


#: The name the first pass used; practice is still the default.
AlpacaPaper = Alpaca
