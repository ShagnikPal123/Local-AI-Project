"""The front bots: each trader owns a pot of money and a kind of market, and turns picks into orders.

Two styles:

* **spread** (Vega on crypto, Nova on stocks): holds up to three markets, the best-ranked ones the
  ranking and the advisor both like, splitting its pot between them.
* **rotate** (Orion): holds one or two of the strongest coins and swaps the weakest out when a
  clearly stronger one appears (a score lead of ``ROTATE_EDGE``). Swapping costs two spreads and two
  fees, so the edge has to be clear.

Every trader sells by itself, without waiting for the signal to flip all the way: at the stop-loss
(cut a loser), at the take-profit (keep a win), or when the advisor's strategy says sell.

How bold it is follows the **risk** dial: higher risk lowers the bar a pick must clear and makes
each position bigger. Orders still go through the skeptic and the hard rules after this.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..models import Order

ROTATE_EDGE = 0.08
MIN_TRADABILITY = 0.35


def _bar(risk: float) -> float:
    """How good a pick's opportunity must be, from 0.35 (careful) down to 0.15 (bold)."""
    return 0.35 - 0.2 * max(0.0, min(1.0, risk))


def decide(trader: Dict[str, Any], rows: Dict[str, Dict[str, Any]], advice: Dict[str, Dict[str, Any]],
           positions: List[Dict[str, Any]], account: Dict[str, Any], settings: Dict[str, Any],
           taken: set, team: Any) -> List[Order]:
    """This trader's orders for the cycle: exits first, then a rotation, then new buys."""
    mine = [p for p in positions if p.get("bot") == trader["name"]]
    orders: List[Order] = []
    risk = float(settings.get("risk", 0.5))
    stop, target = float(settings.get("stop_loss_pct", 4.0)), float(settings.get("take_profit_pct", 8.0))

    def sell(pos: Dict[str, Any], why: str) -> None:
        orders.append(Order(pos["symbol"], "sell", pos["qty"], pos["asset_class"], trader["name"], why))
        team.notes.add(trader, f"Selling {pos['symbol']}: {why}", "trade", pos["symbol"])

    keep = []
    for pos in mine:
        row, tip = rows.get(pos["symbol"]), advice.get(pos["symbol"], {})
        if pos["pl_pct"] <= -stop:
            sell(pos, f"stop-loss, down {pos['pl_pct']:.1f}% (limit -{stop:.0f}%).")
        elif pos["pl_pct"] >= target:
            sell(pos, f"take-profit, up {pos['pl_pct']:.1f}% (target +{target:.0f}%).")
        elif tip.get("action") == "sell" and tip.get("strength", 0) >= 0.5:
            sell(pos, f"{tip['title']} says sell: {tip['why']}")
        elif row and row["signal"] == "sell" and row["confidence"] >= 0.65:
            sell(pos, f"the signal turned to sell ({row['confidence']:.0%}).")
        else:
            keep.append(pos)

    hold_max = 2 if trader.get("style") == "rotate" else 3
    candidates = sorted(
        (r for r in rows.values()
         if r["asset_class"] in trader["classes"] and r["open"] and r["symbol"] not in taken
         and r["tradability"] >= MIN_TRADABILITY and r["opportunity"] >= _bar(risk)
         and (r["signal"] == "buy" or advice.get(r["symbol"], {}).get("action") == "buy")),
        key=lambda r: -r["score"])

    if trader.get("style") == "rotate" and len(keep) >= hold_max and candidates:
        weakest = min(keep, key=lambda p: rows.get(p["symbol"], {}).get("score", 0))
        best = candidates[0]
        held_score = rows.get(weakest["symbol"], {}).get("score", 0)
        if best["score"] > held_score + ROTATE_EDGE:
            sell(weakest, f"rotating into {best['symbol']} (score {best['score']:.2f} vs {held_score:.2f}).")
            keep.remove(weakest)

    pot = float(trader.get("share", 0)) * float(account.get("equity") or 0)
    free = pot - sum(p["value"] for p in keep)
    slots = hold_max - len(keep)
    for row in candidates[:max(0, slots)]:
        if free < 1:
            break
        notional = min(free, free / slots * (0.6 + 0.8 * risk))
        qty = notional / row["price"]
        tip = advice.get(row["symbol"], {})
        why = (f"rank {row['score']:.2f}, {row['signal']} {row['confidence']:.0%}, "
               f"spread {row['spread_bps']:.1f} bp" + (f"; {tip['title']}: {tip['why']}" if tip else ""))
        orders.append(Order(row["symbol"], "buy", qty, row["asset_class"], trader["name"], why))
        team.notes.add(trader, f"Want to buy {row['symbol']} with ${notional:,.0f}: {why}", "idea", row["symbol"])
        taken.add(row["symbol"])
        free -= notional
        slots -= 1
    held = ", ".join(p["symbol"] for p in keep) or "nothing"
    team.set_doing(trader, f"Holding {held}; {len(orders)} order(s) this cycle.")
    return orders
