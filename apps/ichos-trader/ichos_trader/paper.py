"""The practice account: fake money, real prices, real costs.

The owner: "trade with fake money and make theoretical amounts which can be really helpful so that it
won't have to learn on the fly." Practice only teaches the right lesson if it is not flattering, so
like the main app's practice account (``trading/brokers.py`` PaperBroker) every fill pays:

* **the spread** - buys fill at the ask and sells at the bid when the feed has them, otherwise at
  the price plus or minus a typical half spread;
* **slippage** - a market order moves the price a little against you (2 bp);
* **fees** - what a real broker would charge: about 0.25% a side for crypto, nothing for US stocks.

It holds stocks, ETFs, crypto and currency pairs side by side, in one currency (USD by default).
Markets priced in another currency (USD-JPY is priced in yen) are watched and ranked but not
bought here yet; the trader says so instead of guessing an exchange rate.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from . import store
from .models import BrokerError, Fill, Order, Quote

FEE_BPS = {"crypto": 25.0, "stock": 0.0, "etf": 0.0, "fx": 0.0}
SLIPPAGE_BPS = 2.0
#: Used when the quote has no bid/ask: a typical half spread by kind of market, in bp.
HALF_SPREAD_BPS = {"crypto": 5.0, "stock": 2.0, "etf": 1.0, "fx": 0.5}
CURVE_EVERY = 300.0


def _default(cash: float = 10_000.0, currency: str = "USD") -> Dict[str, Any]:
    now = time.time()
    return {"currency": currency, "cash": cash, "start": cash, "positions": {}, "fills": [], "curve": [],
            "realized": 0.0, "wins": 0, "losses": 0, "fees": 0.0, "created_at": now, "peak": cash}


class PaperAccount:
    """The built-in broker. ``name`` "sim" is what settings call it."""

    name = "sim"
    label = "Practice account (simulated money)"

    def __init__(self, clock=time.time):
        self._clock = clock
        self._prices: Dict[str, float] = {}

    def money(self) -> str:
        return "practice"

    # --- state ------------------------------------------------------------------------------

    def _state(self) -> Dict[str, Any]:
        data = store.read("paper", _default)
        for key, value in _default().items():
            data.setdefault(key, value)
        return data

    def reset(self, cash: float = 10_000.0, currency: str = "USD") -> Dict[str, Any]:
        if not 1 <= float(cash) <= 100_000_000:
            raise BrokerError("Starting cash must be between 1 and 100,000,000.")
        store.write("paper", _default(float(cash), currency))
        return self.account()

    def mark(self, prices: Dict[str, float]) -> None:
        """Latest prices for valuing what is held, and one equity point every 5 minutes."""
        self._prices.update({k: v for k, v in prices.items() if v and v > 0})
        equity = self.account()["equity"]
        now = self._clock()

        def change(data: Dict[str, Any]) -> None:
            data["peak"] = max(float(data.get("peak") or 0), equity)
            if not data["curve"] or now - data["curve"][-1]["t"] >= CURVE_EVERY:
                data["curve"] = (data["curve"] + [{"t": now, "equity": round(equity, 2)}])[-3000:]

        store.update("paper", _default, change)

    # --- reading ----------------------------------------------------------------------------

    def positions(self) -> List[Dict[str, Any]]:
        out = []
        for symbol, pos in self._state()["positions"].items():
            price = self._prices.get(symbol, pos["avg_price"])
            value = pos["qty"] * price
            cost = pos["qty"] * pos["avg_price"]
            out.append({"symbol": symbol, "asset_class": pos.get("asset_class", "stock"), "qty": pos["qty"],
                        "avg_price": pos["avg_price"], "price": price, "value": round(value, 2),
                        "pl": round(value - cost, 2), "pl_pct": round((value / cost - 1) * 100, 2) if cost else 0.0,
                        "bot": pos.get("bot", ""), "opened_at": pos.get("opened_at", 0)})
        return sorted(out, key=lambda p: -p["value"])

    def account(self) -> Dict[str, Any]:
        data = self._state()
        held = sum(p["value"] for p in self.positions())
        equity = data["cash"] + held
        closed = data["wins"] + data["losses"]
        return {"currency": data["currency"], "cash": round(data["cash"], 2), "equity": round(equity, 2),
                "start": data["start"], "pl": round(equity - data["start"], 2),
                "pl_pct": round((equity / data["start"] - 1) * 100, 3) if data["start"] else 0.0,
                "peak": max(float(data.get("peak") or 0), equity), "realized": round(data["realized"], 2),
                "fees": round(data["fees"], 2), "wins": data["wins"], "losses": data["losses"], "closed": closed,
                "win_rate": round(data["wins"] / closed, 3) if closed else None, "created_at": data["created_at"],
                "money": "practice"}

    def fills(self, limit: int = 50) -> List[Dict[str, Any]]:
        return list(reversed(self._state()["fills"][-limit:]))

    def curve(self) -> List[Dict[str, float]]:
        return list(self._state()["curve"])

    # --- trading ----------------------------------------------------------------------------

    @staticmethod
    def fill_price(order: Order, quote: Quote) -> float:
        """Cross the spread, then slip a little, always against you."""
        half = HALF_SPREAD_BPS.get(order.asset_class, 2.0) / 10_000
        if order.side == "buy":
            base = quote.ask if quote.ask else quote.price * (1 + half)
            return base * (1 + SLIPPAGE_BPS / 10_000)
        base = quote.bid if quote.bid else quote.price * (1 - half)
        return base * (1 - SLIPPAGE_BPS / 10_000)

    def place(self, order: Order, quote: Quote) -> Fill:
        if order.side not in ("buy", "sell") or order.qty <= 0:
            raise BrokerError("An order needs a side (buy or sell) and a quantity above zero.")
        price = self.fill_price(order, quote)
        fee_rate = FEE_BPS.get(order.asset_class, 0.0) / 10_000
        result: Dict[str, Any] = {}

        def change(data: Dict[str, Any]) -> None:
            positions = data["positions"]
            gross = order.qty * price
            fee = gross * fee_rate
            if order.side == "buy":
                if gross + fee > data["cash"] + 1e-9:
                    raise BrokerError(f"Not enough practice cash: needs {gross + fee:,.2f}, has {data['cash']:,.2f}.")
                pos = positions.get(order.symbol, {"qty": 0.0, "avg_price": 0.0, "asset_class": order.asset_class,
                                                   "bot": order.bot, "opened_at": self._clock()})
                total = pos["qty"] + order.qty
                pos["avg_price"] = (pos["qty"] * pos["avg_price"] + gross) / total
                pos["qty"] = total
                positions[order.symbol] = pos
                data["cash"] -= gross + fee
                realized = None
            else:
                pos = positions.get(order.symbol)
                if not pos or order.qty > pos["qty"] + 1e-9:
                    raise BrokerError(f"Can't sell {order.qty:g} {order.symbol}: it holds {pos['qty'] if pos else 0:g}. "
                                      "No short selling.")
                realized = (price - pos["avg_price"]) * order.qty - fee
                data["realized"] += realized
                data["wins" if realized > 0 else "losses"] += 1
                pos["qty"] -= order.qty
                if pos["qty"] <= 1e-12:
                    positions.pop(order.symbol)
                data["cash"] += gross - fee
            data["fees"] += fee
            fill = Fill(order.id, order.symbol, order.side, order.qty, round(price, 8), round(fee, 4), order.bot,
                        order.reason, "practice", self._clock())
            row = fill.to_dict()
            row["asset_class"] = order.asset_class
            row["realized"] = None if realized is None else round(realized, 2)
            data["fills"] = (data["fills"] + [row])[-2000:]
            result["fill"] = fill

        store.update("paper", _default, change)
        return result["fill"]

    def held(self, symbol: str) -> float:
        pos = self._state()["positions"].get(symbol)
        return float(pos["qty"]) if pos else 0.0

    def owner_of(self, symbol: str) -> Optional[str]:
        pos = self._state()["positions"].get(symbol)
        return pos.get("bot") if pos else None
