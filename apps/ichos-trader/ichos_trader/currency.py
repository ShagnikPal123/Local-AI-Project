"""Any market, any currency: every price is turned into the account's currency before anyone reads it.

The owner: "It should be able to invest in any market and any currency." A pair like USD-JPY is priced
in yen, and an account can be kept in euros. Rather than teach every bot about currencies, the engine
converts each snapshot into the account's currency once, right after the scan, using the currency
pairs it already fetched. After that, ranking, the traders, the rules and the practice account all
see one currency, and the rule "only buy what is priced in the account's currency" always holds.

Rates come from a walk over the pairs (EUR-USD and USD-JPY give EUR in JPY too). A market whose
currency cannot be reached is left out with a clear reason rather than priced wrongly.
"""

from __future__ import annotations

from collections import deque
from dataclasses import replace
from typing import Dict, Iterable, List

from .models import Book, Candle, Instrument, Snapshot

#: Pairs fetched only to price other markets when the account's currency needs them.
RATE_PAIRS = ["EUR-USD", "GBP-USD", "USD-JPY", "USD-CHF", "AUD-USD", "USD-CAD", "NZD-USD", "USD-MXN", "USD-INR",
              "USD-CNY", "USD-SGD", "USD-HKD", "USD-SEK", "USD-NOK", "USD-ZAR"]


def rates(snaps: Iterable[Snapshot], base: str) -> Dict[str, float]:
    """How much one unit of each reachable currency is worth in ``base``."""
    edges: Dict[str, Dict[str, float]] = {}
    for snap in snaps:
        if snap.error or not snap.quote or snap.instrument.asset_class != "fx" or "-" not in snap.symbol:
            continue
        left, right = snap.symbol.split("-", 1)
        price = float(snap.quote.price or 0)
        if price > 0:  # 1 left = price right
            edges.setdefault(left, {})[right] = price
            edges.setdefault(right, {})[left] = 1 / price
    worth = {base: 1.0}
    todo = deque([base])
    while todo:
        here = todo.popleft()
        for there, price in edges.get(here, {}).items():
            if there not in worth:
                worth[there] = worth[here] / price  # 1 there = (1/price) here
                todo.append(there)
    return worth


def to_base(snap: Snapshot, base: str, worth: Dict[str, float]) -> Snapshot:
    """The same market with every price in ``base``. Unreachable currencies come back as an error."""
    currency = snap.instrument.quote_currency or base
    if snap.error or currency == base:
        return snap
    rate = worth.get(currency)
    inst = Instrument(snap.instrument.symbol, snap.instrument.asset_class, snap.instrument.name, base,
                      snap.instrument.venue)
    if not rate:
        return Snapshot(inst, error=f"No exchange rate from {currency} to {base}.")
    quote = snap.quote and replace(snap.quote, price=snap.quote.price * rate,
                                   bid=snap.quote.bid and snap.quote.bid * rate,
                                   ask=snap.quote.ask and snap.quote.ask * rate)
    candles: List[Candle] = [Candle(c.t, c.open * rate, c.high * rate, c.low * rate, c.close * rate, c.volume)
                             for c in snap.candles]
    book = snap.book and Book(snap.book.symbol, [(p * rate, s) for p, s in snap.book.bids],
                              [(p * rate, s) for p, s in snap.book.asks], snap.book.at)
    return Snapshot(inst, quote, candles, book)


def needs_rates(instruments: Iterable[Instrument], base: str) -> bool:
    return any((i.quote_currency or base) != base for i in instruments) or base != "USD"
