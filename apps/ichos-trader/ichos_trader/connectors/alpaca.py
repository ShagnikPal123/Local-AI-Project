"""Alpaca's practice (paper) account as a broker, and nothing else.

Alpaca is the recommended first broker: stocks, ETFs and crypto behind one free API, with a free
practice account that fills against real prices. This adapter only ever talks to the **paper**
endpoint; the live one is refused in code, because Shagnik has not said yes to real money.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests

from ..access import secrets
from ..models import BrokerError, Fill, Order, Quote

PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL = "https://api.alpaca.markets"


class AlpacaPaper:
    name = "alpaca"

    def __init__(self, http: Optional[requests.Session] = None, base_url: str = PAPER_URL):
        if base_url.rstrip("/") != PAPER_URL:
            raise BrokerError("Only Alpaca's practice account is allowed. Real money is off.")
        self.http = http or requests.Session()
        self.base = base_url

    def money(self) -> str:
        return "practice"

    def _headers(self) -> Dict[str, str]:
        key, secret = secrets.get("alpaca_key_id"), secrets.get("alpaca_secret_key")
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

    def account(self) -> Dict[str, Any]:
        a = self._call("GET", "/v2/account")
        equity = float(a.get("equity", 0))
        start = float(a.get("last_equity", equity))
        return {"currency": a.get("currency", "USD"), "cash": float(a.get("cash", 0)), "equity": equity,
                "start": start, "pl": round(equity - start, 2), "pl_pct": round((equity / start - 1) * 100, 3) if start else 0.0,
                "peak": equity, "realized": 0.0, "fees": 0.0, "wins": 0, "losses": 0, "closed": 0, "win_rate": None,
                "created_at": 0, "money": "practice"}

    def positions(self) -> List[Dict[str, Any]]:
        out = []
        for p in self._call("GET", "/v2/positions"):
            qty, avg, price = float(p["qty"]), float(p["avg_entry_price"]), float(p["current_price"])
            out.append({"symbol": p["symbol"], "asset_class": "crypto" if p.get("asset_class") == "crypto" else "stock",
                        "qty": qty, "avg_price": avg, "price": price, "value": round(qty * price, 2),
                        "pl": round(float(p.get("unrealized_pl", 0)), 2),
                        "pl_pct": round(float(p.get("unrealized_plpc", 0)) * 100, 2), "bot": "", "opened_at": 0})
        return out

    def place(self, order: Order, quote: Quote) -> Fill:
        sent = self._call("POST", "/v2/orders", json={
            "symbol": order.symbol.replace("-", "/") if order.asset_class == "crypto" else order.symbol,
            "qty": f"{order.qty:.6f}", "side": order.side, "type": "market",
            "time_in_force": "gtc" if order.asset_class == "crypto" else "day"})
        price = float(sent.get("filled_avg_price") or quote.price)
        return Fill(sent.get("id", order.id), order.symbol, order.side, order.qty, price, 0.0, order.bot, order.reason,
                    "practice")
