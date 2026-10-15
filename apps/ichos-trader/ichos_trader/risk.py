"""The hard rules every order passes, which no bot and no setting can switch off.

Carried over from the main app's finance lab capital guard (``finance_lab/capital_guard.py``):
"it can only access the money it has and the money it earns". In order:

1. **No real money.** A broker whose money is real refuses every order until the owner turns real
   trading on himself. There is no switch for it in this version at all.
2. **No borrowing.** A buy must fit in the cash it has; there is no margin path in the code.
3. **No short selling.** It can only sell what it holds.
4. **One market can't sink it.** No market grows past ``max_position_pct`` of the money, and no
   more than ``max_positions`` markets are held at once.
5. **One currency.** Only markets priced in the account's currency are bought.
6. **It brakes as it loses.** Past half the shut-down drawdown, every new buy is halved.

``check`` returns the quantity it allows (maybe smaller than asked) and the reasons, so the bots'
thinking feed shows exactly why an order changed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .models import Instrument, Order, Quote


def check(order: Order, quote: Quote, inst: Instrument, account: Dict[str, Any], positions: List[Dict[str, Any]],
          settings: Dict[str, Any], money: str = "practice") -> Tuple[float, List[str]]:
    """``(allowed_qty, reasons)``. ``allowed_qty`` 0 means refused."""
    if money != "practice":
        return 0.0, ["Real money is off. Only the owner can turn it on, and this version has no switch for it."]
    held = {p["symbol"]: p for p in positions}
    price = quote.ask or quote.price
    if order.side == "sell":
        have = float(held.get(order.symbol, {}).get("qty", 0.0))
        if have <= 0:
            return 0.0, [f"Nothing to sell: it holds no {order.symbol} (no short selling)."]
        return min(order.qty, have), []

    reasons: List[str] = []
    if inst.quote_currency != account.get("currency", "USD"):
        return 0.0, [f"{order.symbol} is priced in {inst.quote_currency}; the practice account is in "
                     f"{account.get('currency', 'USD')}."]
    if order.symbol not in held and len(held) >= int(settings.get("max_positions", 8)):
        return 0.0, [f"Already holding {len(held)} markets, the most it may."]
    qty = order.qty
    equity = float(account.get("equity") or 0)
    cap = equity * float(settings.get("max_position_pct", 0.2))
    already = float(held.get(order.symbol, {}).get("value", 0.0))
    if already + qty * price > cap:
        qty = max(0.0, (cap - already) / price)
        reasons.append(f"Trimmed so {order.symbol} stays under {settings.get('max_position_pct', 0.2):.0%} of the money.")
    peak = float(account.get("peak") or equity)
    brake = float((settings.get("shutdown") or {}).get("max_drawdown_pct", 10.0)) / 2
    if peak and equity < peak * (1 - brake / 100):
        qty /= 2
        reasons.append(f"Down more than {brake:.0f}% from its best, so buys are halved.")
    cash = float(account.get("cash") or 0) * 0.995  # leave room for the fee
    if qty * price > cash:
        qty = max(0.0, cash / price)
        reasons.append("Trimmed to the cash it has: no borrowing.")
    if qty * price < 1.0:
        return 0.0, reasons + ["Too small to be worth a trade (under 1 dollar)."]
    return qty, reasons
