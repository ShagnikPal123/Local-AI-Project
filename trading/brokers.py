"""Broker connections: Paper (built in), Alpaca (direct), SnapTrade (many brokerages through one API).

Every broker answers the same small interface so the guard, the autopilot and the
UI never care which one is active. Keys are stored with secret_store and never
returned; a connection test reports only what the broker said.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests

from trading import market, store


class BrokerError(RuntimeError):
    """The broker refused or could not be reached; the message is safe to show."""


@dataclass
class OrderRequest:
    symbol: str
    side: str  # buy | sell
    qty: Optional[float] = None
    notional: Optional[float] = None  # dollars instead of shares
    type: str = "market"  # market | limit
    limit_price: Optional[float] = None
    time_in_force: str = "day"
    requested_by: str = "owner"  # owner | ai
    reason: str = ""
    client_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])

    def validate(self) -> None:
        self.symbol = (self.symbol or "").strip().upper()
        if not self.symbol or not self.symbol.replace(".", "").replace("-", "").isalnum() or len(self.symbol) > 12:
            raise BrokerError("Give a valid ticker symbol, like AAPL.")
        if self.side not in ("buy", "sell"):
            raise BrokerError("Side must be buy or sell.")
        if self.type not in ("market", "limit"):
            raise BrokerError("Order type must be market or limit.")
        if self.type == "limit" and not (self.limit_price and self.limit_price > 0):
            raise BrokerError("A limit order needs a limit price.")
        if not ((self.qty and self.qty > 0) or (self.notional and self.notional > 0)):
            raise BrokerError("Say how many shares, or how many dollars.")

    def estimated_cost(self, price: float) -> float:
        if self.notional:
            return float(self.notional)
        return float(self.qty or 0) * float(self.limit_price or price)


def _secret(name: str) -> str:
    import secret_store

    try:
        return (secret_store.get_keys(name) or [""])[0]
    except Exception:  # noqa: BLE001 - an unreadable store means "not connected"
        return ""


def _set_secret(name: str, value: str) -> None:
    import secret_store

    secret_store.set_keys(name, [value])


def _delete_secret(name: str) -> None:
    import secret_store

    try:
        secret_store.set_keys(name, [])
    except Exception:  # noqa: BLE001
        pass


class Broker:
    name = "base"
    label = "Broker"
    kind = "api"
    fields: List[Dict[str, Any]] = []

    def connected(self) -> bool:
        return True

    def live(self) -> bool:
        return False

    def money(self) -> str:
        """``"practice"`` or ``"real"`` — the one thing that must never be ambiguous.

        The owner: "just make it clear which one is real and fake". Everything on
        screen and every sentence Nyx says about an order is labelled from here,
        so there is a single place that decides. A broker's own paper endpoint
        (Alpaca's) counts as practice.
        """
        return "real" if self.live() else "practice"

    def connect(self, values: Dict[str, str]) -> None:
        raise BrokerError("Nothing to connect.")

    def disconnect(self) -> None:
        pass

    def account(self) -> Dict[str, Any]:
        raise NotImplementedError

    def positions(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def orders(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def place(self, order: OrderRequest) -> Dict[str, Any]:
        raise NotImplementedError

    def cancel(self, order_id: str) -> None:
        raise NotImplementedError


# --- Paper ------------------------------------------------------------------------------------


def _paper_default() -> Dict[str, Any]:
    return {"cash": 100_000.0, "start_equity": 100_000.0, "positions": {}, "orders": [], "created_at": time.time(),
            "history": [], "realized": 0.0, "wins": 0, "losses": 0, "fees": 0.0, "benchmark": {}}


def _paper_state() -> Dict[str, Any]:
    """The practice account with every field present, however old the saved file is."""
    data = store.read("paper", _paper_default)
    for key, value in _paper_default().items():
        data.setdefault(key, value)
    return data


#: How true to life the practice account is. Real fills are never exactly the
#: quoted price: you cross the spread, and a market order moves a little against
#: you. Practising against perfect fills teaches the wrong lesson, so this is on
#: by default — and every number it applies is shown in the Trading tab.
def _realism_default() -> Dict[str, Any]:
    return {"realistic_fills": True, "spread_bps": 4.0, "slippage_bps": 3.0, "commission": 0.0,
            "queue_when_closed": True, "starting_cash": 100_000.0}


def paper_settings() -> Dict[str, Any]:
    settings = _realism_default()
    settings.update({k: v for k, v in store.read("paper_settings", _realism_default).items() if k in settings})
    return settings


def save_paper_settings(changes: Dict[str, Any]) -> Dict[str, Any]:
    current = paper_settings()
    limits = {"spread_bps": (0.0, 100.0), "slippage_bps": (0.0, 100.0), "commission": (0.0, 50.0),
              "starting_cash": (1.0, 10_000_000.0)}
    for key, (low, high) in limits.items():
        if key in changes:
            current[key] = round(min(high, max(low, float(changes[key]))), 2)
    for key in ("realistic_fills", "queue_when_closed"):
        if key in changes:
            current[key] = bool(changes[key])
    store.write("paper_settings", current)
    return current


def fill_price(price: float, side: str, settings: Optional[Dict[str, Any]] = None) -> float:
    """What a market order would really get: half the spread plus a little slippage, against you."""
    settings = settings or paper_settings()
    if not settings["realistic_fills"]:
        return round(price, 4)
    cost = (float(settings["spread_bps"]) / 2 + float(settings["slippage_bps"])) / 10_000
    return round(price * (1 + cost) if side == "buy" else price * (1 - cost), 4)


class PaperBroker(Broker):
    """Practice money at real market prices. Nothing moves, nothing leaves this PC.

    It is deliberately not a perfect simulator, because a perfect one flatters
    you: orders cross the spread and slip a little (``paper_settings``), an order
    given while the market is shut waits for the opening bell instead of filling
    on last night's price, and the equity curve is kept so the practice record
    can be compared with simply holding SPY.
    """

    name = "paper"
    label = "Practice money (simulated — no real money)"
    kind = "paper"

    def money(self) -> str:
        return "practice"

    def account(self) -> Dict[str, Any]:
        self._settle()
        data = _paper_state()
        value = 0.0
        for symbol, pos in data["positions"].items():
            try:
                value += pos["qty"] * market.quote(symbol)["price"]
            except market.MarketDataError:
                value += pos["qty"] * pos["avg_price"]
        equity = data["cash"] + value
        self._remember_equity(equity)
        return {"broker": self.name, "live": False, "money": "practice", "cash": round(data["cash"], 2),
                "equity": round(equity, 2), "buying_power": round(data["cash"], 2),
                "start_equity": data["start_equity"], "pl_total": round(equity - data["start_equity"], 2),
                "pl_pct": round((equity / data["start_equity"] - 1) * 100, 2) if data["start_equity"] else 0.0,
                "currency": "USD", "since": data.get("created_at") or 0.0}

    def _remember_equity(self, equity: float) -> None:
        """One equity point every 15 minutes, so the practice account has a real curve."""
        data = _paper_state()
        history: List[Dict[str, Any]] = data["history"]
        now = time.time()
        if history and now - float(history[-1]["at"]) < 900:
            return

        def change(saved: Dict[str, Any]) -> None:
            points = saved.setdefault("history", [])
            points.append({"at": now, "equity": round(equity, 2)})
            saved["history"] = points[-4000:]

        store.update("paper", _paper_default, change)

    def stats(self) -> Dict[str, Any]:
        """How the practice run is going — honestly, including what holding SPY would have done."""
        data = _paper_state()
        account = self.account()
        trades = [o for o in data["orders"] if o.get("status") == "filled"]
        closed = [o for o in trades if o.get("realized_pl") is not None]
        wins = [o for o in closed if float(o["realized_pl"]) > 0]
        curve = [point["equity"] for point in data["history"]]
        peak, drawdown = 0.0, 0.0
        for equity in curve:
            peak = max(peak, equity)
            drawdown = max(drawdown, (peak - equity) / peak * 100 if peak else 0.0)
        return {
            "start_equity": data["start_equity"], "equity": account["equity"], "pl": account["pl_total"],
            "pl_pct": account["pl_pct"], "trades": len(trades), "closed": len(closed),
            "win_rate": round(len(wins) / len(closed), 3) if closed else None,
            "realized": round(sum(float(o["realized_pl"]) for o in closed), 2),
            "fees": round(float(data.get("fees") or 0), 2), "max_drawdown_pct": round(drawdown, 2),
            "history": data["history"][-400:], "since": data.get("created_at") or 0.0,
            "benchmark": self._benchmark(data),
        }

    def _benchmark(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """What the same money would have done sitting in SPY since the practice account started."""
        try:
            rows = market.history("SPY", "1y")
        except Exception:  # noqa: BLE001 - the benchmark is a nicety, never an error
            return {}
        started = float(data.get("created_at") or 0)
        if not rows or not started:
            return {}
        stamp = time.strftime("%Y-%m-%d", time.localtime(started))
        before = [r for r in rows if str(r.get("date", "")) <= stamp]
        baseline = before[-1] if before else rows[0]  # the price on the day the practice run began
        change = rows[-1]["close"] / baseline["close"] - 1
        return {"symbol": "SPY", "change_pct": round(change * 100, 2),
                "would_be": round(float(data["start_equity"]) * (1 + change), 2)}

    def positions(self) -> List[Dict[str, Any]]:
        data = _paper_state()
        out = []
        for symbol, pos in sorted(data["positions"].items()):
            try:
                price = market.quote(symbol)["price"]
            except market.MarketDataError:
                price = pos["avg_price"]
            out.append({"symbol": symbol, "qty": round(pos["qty"], 6), "avg_price": round(pos["avg_price"], 4), "price": price,
                        "market_value": round(pos["qty"] * price, 2), "pl": round((price - pos["avg_price"]) * pos["qty"], 2),
                        "pl_pct": round((price / pos["avg_price"] - 1) * 100, 2) if pos["avg_price"] else 0.0})
        return out

    def orders(self) -> List[Dict[str, Any]]:
        self._settle()
        return list(reversed(_paper_state()["orders"][-60:]))

    def reset(self, cash: float = 100_000.0) -> None:
        """Start the practice account again with a chosen amount of pretend money."""
        store.write("paper", {**_paper_default(), "cash": float(cash), "start_equity": float(cash),
                              "created_at": time.time()})
        save_paper_settings({"starting_cash": float(cash)})

    def _execute(self, data: Dict[str, Any], record: Dict[str, Any], price: float) -> None:
        settings = paper_settings()
        filled = fill_price(price, record["side"], settings) if record["type"] == "market" else round(price, 4)
        fee = float(settings["commission"])
        qty = record["qty"] if record.get("qty") else round(record["notional"] / filled, 6)
        cost = qty * filled
        positions = data["positions"]
        if record["side"] == "buy":
            if cost + fee > data["cash"] + 1e-6:
                record.update(status="rejected",
                              note=f"Not enough practice cash: needs ${cost + fee:,.2f}, has ${data['cash']:,.2f}.")
                return
            pos = positions.setdefault(record["symbol"], {"qty": 0.0, "avg_price": 0.0})
            pos["avg_price"] = (pos["avg_price"] * pos["qty"] + cost) / (pos["qty"] + qty)
            pos["qty"] += qty
            data["cash"] -= cost + fee
        else:
            pos = positions.get(record["symbol"])
            if not pos or pos["qty"] + 1e-9 < qty:
                record.update(status="rejected", note="You can't sell more shares than you hold (no short selling in practice).")
                return
            pos["qty"] -= qty
            data["cash"] += cost - fee
            record["realized_pl"] = round((filled - pos["avg_price"]) * qty - fee, 2)
            data["realized"] = round(float(data.get("realized") or 0) + record["realized_pl"], 2)
            if pos["qty"] <= 1e-9:
                positions.pop(record["symbol"], None)
        data["fees"] = round(float(data.get("fees") or 0) + fee, 2)
        record.update(status="filled", filled_qty=qty, filled_price=filled, filled_at=time.time(), fee=fee,
                      quote_price=round(price, 4), slippage=round(filled - price, 4))

    def place(self, order: OrderRequest) -> Dict[str, Any]:
        order.validate()
        price = market.quote(order.symbol)["price"]
        settings = paper_settings()
        closed = settings["queue_when_closed"] and not market.us_market_open()
        record = {"id": uuid.uuid4().hex[:12], "symbol": order.symbol, "side": order.side, "qty": order.qty,
                  "notional": order.notional, "type": order.type, "limit_price": order.limit_price,
                  "status": "queued" if closed else "open", "requested_by": order.requested_by,
                  "reason": order.reason[:300], "created_at": time.time(), "broker": self.name, "money": "practice"}
        if closed:
            # A real market order given overnight does not fill overnight. Filling
            # it on a stale price is the single biggest lie a paper account can
            # tell, so it waits for the opening bell like the real thing.
            record["note"] = "Queued for the next opening bell — the market is closed."

        def change(data: Dict[str, Any]) -> Dict[str, Any]:
            if not closed and self._marketable(record, price):
                self._execute(data, record, self._trigger_price(record, price))
            data["orders"].append(record)
            data["orders"] = data["orders"][-500:]
            return record

        return store.update("paper", _paper_default, change)

    @staticmethod
    def _marketable(record: Dict[str, Any], price: float) -> bool:
        limit = record.get("limit_price") or 0
        if record["type"] == "market":
            return True
        return (record["side"] == "buy" and price <= limit) or (record["side"] == "sell" and price >= limit)

    @staticmethod
    def _trigger_price(record: Dict[str, Any], price: float) -> float:
        """A limit order fills at the better of the limit and the market."""
        if record["type"] == "market":
            return price
        limit = float(record.get("limit_price") or price)
        return min(price, limit) if record["side"] == "buy" else max(price, limit)

    def _settle(self) -> None:
        """Fill what the market now allows: queued orders at the open, limits when the price comes."""
        data = _paper_state()
        waiting = [o for o in data["orders"] if o.get("status") in ("open", "queued")]
        if not waiting:
            return
        is_open = market.us_market_open()

        def change(saved: Dict[str, Any]) -> None:
            for record in saved["orders"]:
                if record.get("status") not in ("open", "queued"):
                    continue
                if record["status"] == "queued":
                    if not is_open:
                        continue
                    record["status"] = "open"
                    record["note"] = "Filled at the opening bell."
                try:
                    price = market.quote(record["symbol"])["price"]
                except market.MarketDataError:
                    continue
                if self._marketable(record, price):
                    self._execute(saved, record, self._trigger_price(record, price))

        store.update("paper", _paper_default, change)

    def cancel(self, order_id: str) -> None:
        def change(data: Dict[str, Any]) -> None:
            for record in data["orders"]:
                if record["id"] == order_id and record["status"] in ("open", "queued"):
                    record["status"] = "canceled"
                    return
            raise BrokerError("That order is not open.")

        store.update("paper", _paper_default, change)


# --- Alpaca -----------------------------------------------------------------------------------


class AlpacaBroker(Broker):
    """Alpaca's trading API (alpaca.markets): free paper trading, and live accounts in the US."""

    name = "alpaca"
    label = "Alpaca"
    kind = "api"
    fields = [
        {"name": "key_id", "label": "API key ID", "secret": False},
        {"name": "secret_key", "label": "Secret key", "secret": True},
        {"name": "live", "label": "Live account (real money)", "type": "boolean"},
    ]
    signup_url = "https://app.alpaca.markets/signup"

    def _base(self) -> str:
        return "https://api.alpaca.markets" if self.live() else "https://paper-api.alpaca.markets"

    def connected(self) -> bool:
        return bool(_secret("alpaca_key_id") and _secret("alpaca_secret_key"))

    def live(self) -> bool:
        return _secret("alpaca_live") == "1"

    def connect(self, values: Dict[str, str]) -> None:
        key_id, secret = str(values.get("key_id", "")).strip(), str(values.get("secret_key", "")).strip()
        if not key_id or not secret:
            raise BrokerError("Alpaca needs both the API key ID and the secret key.")
        _set_secret("alpaca_key_id", key_id)
        _set_secret("alpaca_secret_key", secret)
        _set_secret("alpaca_live", "1" if str(values.get("live", "")).lower() in ("1", "true", "yes", "on") else "0")

    def disconnect(self) -> None:
        for name in ("alpaca_key_id", "alpaca_secret_key", "alpaca_live"):
            _delete_secret(name)

    def _call(self, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
        if not self.connected():
            raise BrokerError("Connect Alpaca first (Trading → Brokers).")
        try:
            response = requests.request(method, self._base() + path, json=body, timeout=15, headers={
                "APCA-API-KEY-ID": _secret("alpaca_key_id"), "APCA-API-SECRET-KEY": _secret("alpaca_secret_key")})
        except requests.RequestException as error:
            raise BrokerError(f"Alpaca could not be reached: {type(error).__name__}.") from error
        if response.status_code >= 400:
            try:
                message = response.json().get("message") or response.text[:200]
            except ValueError:
                message = response.text[:200]
            raise BrokerError(f"Alpaca said: {message} ({response.status_code}).")
        return response.json() if response.content else {}

    def account(self) -> Dict[str, Any]:
        a = self._call("GET", "/v2/account")
        equity, last = float(a.get("equity", 0)), float(a.get("last_equity", 0) or 0)
        return {"broker": self.name, "live": self.live(), "cash": float(a.get("cash", 0)), "equity": equity,
                "buying_power": float(a.get("buying_power", 0)), "pl_day": round(equity - last, 2) if last else None,
                "currency": a.get("currency", "USD"), "status": a.get("status")}

    def positions(self) -> List[Dict[str, Any]]:
        return [{"symbol": p["symbol"], "qty": float(p["qty"]), "avg_price": float(p["avg_entry_price"]), "price": float(p["current_price"]),
                 "market_value": float(p["market_value"]), "pl": float(p["unrealized_pl"]), "pl_pct": round(float(p["unrealized_plpc"]) * 100, 2)}
                for p in self._call("GET", "/v2/positions")]

    def orders(self) -> List[Dict[str, Any]]:
        return [{"id": o["id"], "symbol": o["symbol"], "side": o["side"], "qty": float(o["qty"]) if o.get("qty") else None,
                 "notional": float(o["notional"]) if o.get("notional") else None, "type": o["type"], "status": o["status"],
                 "limit_price": float(o["limit_price"]) if o.get("limit_price") else None,
                 "filled_price": float(o["filled_avg_price"]) if o.get("filled_avg_price") else None, "created_at": o.get("created_at"),
                 "client_order_id": o.get("client_order_id", ""), "broker": self.name} for o in self._call("GET", "/v2/orders?status=all&limit=60&direction=desc")]

    def place(self, order: OrderRequest) -> Dict[str, Any]:
        order.validate()
        body: Dict[str, Any] = {"symbol": order.symbol, "side": order.side, "type": order.type, "time_in_force": order.time_in_force,
                                "client_order_id": f"nyx-{'ai-' if order.requested_by == 'ai' else ''}{order.client_id}"}
        if order.notional:
            body["notional"] = str(round(order.notional, 2))
        else:
            body["qty"] = str(order.qty)
        if order.type == "limit":
            body["limit_price"] = str(order.limit_price)
        o = self._call("POST", "/v2/orders", body)
        return {"id": o["id"], "symbol": o["symbol"], "side": o["side"], "status": o["status"], "type": o["type"],
                "qty": order.qty, "notional": order.notional, "broker": self.name, "created_at": time.time()}

    def cancel(self, order_id: str) -> None:
        self._call("DELETE", f"/v2/orders/{order_id}")


# --- SnapTrade -------------------------------------------------------------------------------


SNAPTRADE_BROKERAGES = ["Robinhood", "Charles Schwab", "Fidelity", "Vanguard", "E*TRADE", "Interactive Brokers", "Webull",
                        "Tradier", "Public", "Wealthsimple", "Questrade", "Trading 212", "Kraken", "Coinbase", "Ally Invest",
                        "tastytrade", "Zerodha", "Stake"]


class SnapTradeBroker(Broker):
    """SnapTrade: one developer key connects the owner's own brokerage (Robinhood, Schwab, Fidelity…).

    Trading support depends on the brokerage — some are read-only through SnapTrade;
    the account list says which. Requests are signed with the consumer key.
    """

    name = "snaptrade"
    label = "SnapTrade (Robinhood, Schwab, Fidelity, Webull, E*TRADE, IBKR…)"
    kind = "aggregator"
    fields = [
        {"name": "client_id", "label": "Client ID", "secret": False},
        {"name": "consumer_key", "label": "Consumer key", "secret": True},
    ]
    signup_url = "https://dashboard.snaptrade.com/signup"
    base = "https://api.snaptrade.com/api/v1"

    def connected(self) -> bool:
        return bool(_secret("snaptrade_client_id") and _secret("snaptrade_consumer_key"))

    def live(self) -> bool:
        return True

    def connect(self, values: Dict[str, str]) -> None:
        client_id, key = str(values.get("client_id", "")).strip(), str(values.get("consumer_key", "")).strip()
        if not client_id or not key:
            raise BrokerError("SnapTrade needs the client ID and consumer key from dashboard.snaptrade.com.")
        _set_secret("snaptrade_client_id", client_id)
        _set_secret("snaptrade_consumer_key", key)

    def disconnect(self) -> None:
        for name in ("snaptrade_client_id", "snaptrade_consumer_key", "snaptrade_user_id", "snaptrade_user_secret", "snaptrade_account"):
            _delete_secret(name)

    @staticmethod
    def signature(consumer_key: str, path: str, query: str, body: Optional[Dict[str, Any]]) -> str:
        """SnapTrade request signature: HMAC-SHA256 over the sorted JSON of content, path and query."""
        payload = json.dumps({"content": body, "path": f"/api/v1{path}", "query": query}, separators=(",", ":"), sort_keys=True)
        return base64.b64encode(hmac.new(consumer_key.encode(), payload.encode(), hashlib.sha256).digest()).decode()

    def _call(self, method: str, path: str, body: Optional[Dict[str, Any]] = None, user: bool = True, extra: Optional[Dict[str, str]] = None) -> Any:
        if not self.connected():
            raise BrokerError("Add your SnapTrade client ID and consumer key first.")
        params = {"clientId": _secret("snaptrade_client_id"), "timestamp": str(int(time.time()))}
        if user:
            self._ensure_user()
            params.update(userId=_secret("snaptrade_user_id"), userSecret=_secret("snaptrade_user_secret"))
        params.update(extra or {})
        query = urlencode(params)
        headers = {"Signature": self.signature(_secret("snaptrade_consumer_key"), path, query, body), "Content-Type": "application/json"}
        try:
            response = requests.request(method, f"{self.base}{path}?{query}", data=json.dumps(body) if body is not None else None,
                                        headers=headers, timeout=20)
        except requests.RequestException as error:
            raise BrokerError(f"SnapTrade could not be reached: {type(error).__name__}.") from error
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail") or response.json().get("message") or response.text[:200]
            except ValueError:
                detail = response.text[:200]
            raise BrokerError(f"SnapTrade said: {detail} ({response.status_code}).")
        return response.json() if response.content else {}

    def _ensure_user(self) -> None:
        if _secret("snaptrade_user_id") and _secret("snaptrade_user_secret"):
            return
        user_id = f"nyx-{uuid.uuid4().hex[:12]}"
        created = self._call("POST", "/snapTrade/registerUser", {"userId": user_id}, user=False)
        _set_secret("snaptrade_user_id", created.get("userId", user_id))
        _set_secret("snaptrade_user_secret", created["userSecret"])

    def connection_portal(self) -> str:
        """The link where the owner signs in to their own brokerage (SnapTrade's hosted page)."""
        result = self._call("POST", "/snapTrade/login", {})
        url = result.get("redirectURI") or result.get("loginRedirectURI")
        if not url:
            raise BrokerError("SnapTrade did not return a connection link.")
        return url

    def _account_id(self) -> str:
        chosen = _secret("snaptrade_account")
        if chosen:
            return chosen
        accounts = self._call("GET", "/accounts")
        if not accounts:
            raise BrokerError("No brokerage connected yet — press “Connect a Brokerage” and sign in there.")
        _set_secret("snaptrade_account", accounts[0]["id"])
        return accounts[0]["id"]

    def accounts(self) -> List[Dict[str, Any]]:
        return [{"id": a["id"], "name": a.get("name"), "institution": a.get("institution_name"), "number": str(a.get("number", ""))[-4:]}
                for a in self._call("GET", "/accounts")]

    def account(self) -> Dict[str, Any]:
        account_id = self._account_id()
        balances = self._call("GET", f"/accounts/{account_id}/balances")
        cash = sum(float(b.get("cash") or 0) for b in balances)
        holdings = self.positions()
        equity = cash + sum(p["market_value"] for p in holdings)
        return {"broker": self.name, "live": True, "cash": round(cash, 2), "equity": round(equity, 2), "buying_power": round(cash, 2),
                "currency": (balances[0].get("currency") or {}).get("code", "USD") if balances else "USD"}

    def positions(self) -> List[Dict[str, Any]]:
        account_id = self._account_id()
        out = []
        for p in self._call("GET", f"/accounts/{account_id}/positions"):
            symbol = ((p.get("symbol") or {}).get("symbol") or {}).get("symbol") or str(p.get("symbol", ""))
            qty, price, avg = float(p.get("units") or 0), float(p.get("price") or 0), float(p.get("average_purchase_price") or 0)
            out.append({"symbol": symbol, "qty": qty, "avg_price": avg, "price": price, "market_value": round(qty * price, 2),
                        "pl": round((price - avg) * qty, 2) if avg else None, "pl_pct": round((price / avg - 1) * 100, 2) if avg else None})
        return out

    def orders(self) -> List[Dict[str, Any]]:
        account_id = self._account_id()
        return [{"id": o.get("brokerage_order_id"), "symbol": ((o.get("universal_symbol") or {}).get("symbol")), "side": str(o.get("action", "")).lower(),
                 "qty": float(o.get("total_quantity") or 0), "type": str(o.get("order_type", "")).lower(), "status": str(o.get("status", "")).lower(),
                 "broker": self.name} for o in self._call("GET", f"/accounts/{account_id}/orders", extra={"state": "all"})][:60]

    def place(self, order: OrderRequest) -> Dict[str, Any]:
        order.validate()
        body = {"account_id": self._account_id(), "action": order.side.upper(), "symbol": order.symbol,
                "order_type": "Market" if order.type == "market" else "Limit", "time_in_force": "Day",
                "units": order.qty, "notional_value": order.notional, "price": order.limit_price}
        placed = self._call("POST", "/trade/place", {k: v for k, v in body.items() if v is not None})
        return {"id": placed.get("brokerage_order_id"), "symbol": order.symbol, "side": order.side, "status": str(placed.get("status", "submitted")).lower(),
                "qty": order.qty, "notional": order.notional, "broker": self.name, "created_at": time.time()}

    def cancel(self, order_id: str) -> None:
        self._call("POST", f"/accounts/{self._account_id()}/orders/cancel", {"brokerage_order_id": order_id})


BROKERS: Dict[str, Broker] = {b.name: b for b in (PaperBroker(), AlpacaBroker(), SnapTradeBroker())}


def get(name: str) -> Broker:
    broker = BROKERS.get((name or "").strip().lower())
    if broker is None:
        raise BrokerError(f"Unknown broker {name!r}.")
    return broker


def describe() -> List[Dict[str, Any]]:
    return [{"name": b.name, "label": b.label, "kind": b.kind, "connected": b.connected(), "live": b.live() if b.connected() else False,
             "fields": b.fields, "signup_url": getattr(b, "signup_url", ""),
             "brokerages": SNAPTRADE_BROKERAGES if b.name == "snaptrade" else []} for b in BROKERS.values()]
