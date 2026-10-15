"""Mira, the mild skeptic: reads every buy before it goes.

Shagnik: "add a mild skeptic since if a trade really looks fishy and it has an extremely high
chance of failing it should make sure to alert and make decisions."

Mild means two levels:

* **Stop** - only for things that very often end badly: a spread several times wider than a market
  like this should have, almost nobody trading it, a straight-up spike that looks like a pump, or a
  price that is stale.
* **Shrink** - for doubts: a wide-ish spread, sellers pushing hard, the price signal and the
  strategy disagreeing, or a big move already today. The order goes out smaller and the reason is
  written in the thinking feed.

The ``skeptic`` dial (0 easy-going, 1 strict) moves every threshold. Sells are never stopped:
getting out is always allowed.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

from ..models import Order

#: A day's move that looks like a pump, by kind of market (percent).
PUMP = {"crypto": 30.0, "stock": 18.0, "etf": 8.0, "fx": 3.0}
STALE_SECONDS = 300.0


def review(order: Order, row: Optional[Dict[str, Any]], advice: Optional[Dict[str, Any]], strictness: float,
           quote_at: float = 0.0, now: float = 0.0) -> Tuple[float, str, str]:
    """``(size_multiplier, level, reason)``: 0 = stopped ("veto"), below 1 = shrunk ("warn"), 1 = fine."""
    if order.side == "sell":
        return 1.0, "info", ""
    if not row:
        return 0.0, "veto", f"No fresh ranking for {order.symbol}; not buying blind."
    now = now or time.time()
    loose = 1.5 - max(0.0, min(1.0, strictness))  # 1.5 easy-going .. 0.5 strict
    if quote_at and now - quote_at > STALE_SECONDS:
        return 0.0, "veto", f"The price for {order.symbol} is {int(now - quote_at)} s old."
    spread_limit = 25.0 * loose
    if row["spread_bps"] > spread_limit * 3:
        return 0.0, "veto", f"Spread {row['spread_bps']:.0f} bp is far too wide; the round trip alone would cost {row['spread_bps'] / 50:.1f}%."
    if row["liquidity"] < 0.15 / loose:
        return 0.0, "veto", f"Almost nobody trades {order.symbol} (about ${row['dollar_volume']:,.0f} a day)."
    move = abs(row.get("change_pct") or 0.0)
    pump = PUMP.get(row["asset_class"], 15.0) * loose
    if (row.get("change_pct") or 0) > pump:
        return 0.0, "veto", f"Up {move:.0f}% today: that looks like a pump, and pumps usually reverse."

    size, doubts = 1.0, []
    if row["spread_bps"] > spread_limit:
        size *= 0.5
        doubts.append(f"spread {row['spread_bps']:.0f} bp")
    if row["flow"] < -0.4:
        size *= 0.6
        doubts.append(f"sellers pushing ({row['flow']:+.2f})")
    if advice and advice.get("action") == "sell":
        size *= 0.5
        doubts.append(f"{advice.get('title', 'the strategy')} says sell")
    elif row["signal"] == "sell":
        size *= 0.5
        doubts.append("the price signal says sell")
    if move > pump / 2:
        size *= 0.7
        doubts.append(f"already moved {move:.0f}% today")
    if not doubts:
        return 1.0, "info", ""
    return round(size, 3), "warn", "Shrinking: " + ", ".join(doubts) + "."
