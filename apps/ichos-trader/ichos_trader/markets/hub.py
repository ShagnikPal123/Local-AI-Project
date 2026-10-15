"""The market hub: one place the bots ask for prices, whatever feed is behind it.

It does three jobs so the bots never have to:

* **Routing** - crypto goes to Coinbase, stocks and currencies to Yahoo, or everything to the
  simulated market when the trader is offline (``ICHOS_TRADER_OFFLINE=1``) or told to practise on
  it. ``source`` says which, and the dashboard shows it.
* **Speed** - hundreds of markets are fetched in parallel, and answers are kept for a short while
  (quotes and books 10 s, candles 5 min) so a one-minute cycle does not refetch a year of history.
* **Containment** - a market that fails comes back as a snapshot with ``error`` set. One bad market
  never stops a scan.
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .. import config
from ..models import Feed, Instrument, MarketDataError, Snapshot
from . import universe
from .live import CoinbaseFeed, YahooFeed
from .simulated import SimulatedFeed

QUOTE_TTL = 10.0
CANDLE_TTL = 300.0
#: Prices are fetched in parallel. Fetching waits on the network, not the processor, so a bigger
#: machine gets more at once; ``ICHOS_WORKERS`` sets it by hand.
WORKERS = int(os.environ.get("ICHOS_WORKERS") or min(64, (os.cpu_count() or 4) * 4))


class MarketHub:
    def __init__(self, feeds: Optional[Dict[str, Feed]] = None, clock: Callable[[], float] = time.time):
        self._clock = clock
        if feeds is None:
            feeds = self.default_feeds()
        self.feeds = feeds
        self._cache: Dict[Tuple[str, ...], Tuple[float, Any]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def default_feeds() -> Dict[str, Feed]:
        if config.offline():
            sim = SimulatedFeed()
            return {"stock": sim, "etf": sim, "crypto": sim, "fx": sim}
        yahoo = YahooFeed(universe.stocks() + universe.fx())
        return {"stock": yahoo, "etf": yahoo, "crypto": CoinbaseFeed(), "fx": yahoo}

    @property
    def source(self) -> str:
        """"simulated" when every price is make-believe, otherwise "live"."""
        return "simulated" if all(f.name == "sim" for f in self.feeds.values()) else "live"

    def instruments(self, classes: Iterable[str]) -> List[Instrument]:
        """Every market of the wanted kinds, no symbol twice."""
        wanted = set(classes)
        seen: Dict[str, Instrument] = {}
        for feed in {id(f): f for f in self.feeds.values()}.values():
            try:
                items = feed.instruments()
            except MarketDataError:
                continue
            for inst in items:
                if inst.asset_class in wanted and inst.symbol not in seen:
                    seen[inst.symbol] = inst
        return list(seen.values())

    def _cached(self, key: Tuple[str, ...], ttl: float, fetch: Callable[[], Any]) -> Any:
        now = self._clock()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]
        value = fetch()
        with self._lock:
            self._cache[key] = (now, value)
        return value

    def snapshot(self, inst: Instrument, interval: str = "1d", with_book: bool = True) -> Snapshot:
        feed = self.feeds.get(inst.asset_class)
        if feed is None:
            return Snapshot(inst, error=f"No feed for {inst.asset_class}.")
        try:
            quote = self._cached(("q", inst.symbol), QUOTE_TTL, lambda: feed.quote(inst.symbol))
            candles = self._cached(("c", inst.symbol, interval), CANDLE_TTL,
                                   lambda: feed.candles(inst.symbol, interval, 200))
            book = self._cached(("b", inst.symbol), QUOTE_TTL, lambda: feed.book(inst.symbol)) if with_book else None
        except MarketDataError as error:
            return Snapshot(inst, error=str(error))
        except Exception as error:  # noqa: BLE001 - a feed bug costs this market only
            return Snapshot(inst, error=f"{type(error).__name__}: {error}"[:200])
        return Snapshot(inst, quote, candles, book)

    def snapshots(self, instruments: List[Instrument], interval: str = "1d", with_book: bool = True) -> List[Snapshot]:
        """All of them, in parallel, in the order given."""
        if not instruments:
            return []
        with ThreadPoolExecutor(max_workers=min(WORKERS, len(instruments))) as pool:
            return list(pool.map(lambda i: self.snapshot(i, interval, with_book), instruments))
