"""The shared shapes every part of the trader passes around.

One file, so the market feeds, the ranking, the bots, the brokers and the dashboard all agree on
what a quote or an order looks like. Plain dataclasses with ``to_dict`` for the API; nothing here
does any work.

Symbols are written the way people say them:

* stocks and ETFs: ``AAPL``, ``SPY``
* crypto: ``BTC-USD``, ``ETH-USD`` (base-quote, a dash between)
* currencies: ``EUR-USD`` (also base-quote, so "how many USD for one EUR")
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable

ASSET_CLASSES = ("stock", "etf", "crypto", "fx")


@dataclass
class Instrument:
    """Something that can be traded."""

    symbol: str
    asset_class: str                 # one of ASSET_CLASSES
    name: str = ""
    quote_currency: str = "USD"
    venue: str = ""                  # where the price comes from: "yahoo", "coinbase", "kraken", "sim"…

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Quote:
    """The price right now. ``bid``/``ask`` are filled when the feed gives them (crypto does)."""

    symbol: str
    price: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume_24h: Optional[float] = None    # in units of the instrument, over the last day
    change_pct: Optional[float] = None    # versus 24 hours (or the previous close) ago
    at: float = field(default_factory=time.time)

    @property
    def spread_bps(self) -> Optional[float]:
        """Bid-ask spread in basis points (1 bp = 0.01%), when both sides are known."""
        if self.bid and self.ask and self.ask >= self.bid > 0:
            mid = (self.bid + self.ask) / 2
            return (self.ask - self.bid) / mid * 10_000
        return None

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["spread_bps"] = None if self.spread_bps is None else round(self.spread_bps, 2)
        return out


@dataclass
class Candle:
    """One bar of price history."""

    t: float          # bar start, unix seconds
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Book:
    """An order book snapshot: the best bids and asks, best first, as (price, size) pairs."""

    symbol: str
    bids: List[Tuple[float, float]]
    asks: List[Tuple[float, float]]
    at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {"symbol": self.symbol, "bids": [list(b) for b in self.bids], "asks": [list(a) for a in self.asks],
                "at": self.at}


@dataclass
class Snapshot:
    """Everything known about one market at one moment: what ranking and the bots read."""

    instrument: Instrument
    quote: Optional[Quote] = None
    candles: List[Candle] = field(default_factory=list)
    book: Optional[Book] = None
    error: str = ""

    @property
    def symbol(self) -> str:
        return self.instrument.symbol

    @property
    def closes(self) -> List[float]:
        return [c.close for c in self.candles if c.close > 0]


@dataclass
class Order:
    """What a bot wants to do. ``qty`` is in units of the instrument (shares, coins)."""

    symbol: str
    side: str                          # "buy" | "sell"
    qty: float
    asset_class: str = "stock"
    bot: str = ""                      # the bot that asked for it
    reason: str = ""
    limit_price: Optional[float] = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Fill:
    """What actually happened to an order."""

    order_id: str
    symbol: str
    side: str
    qty: float
    price: float
    fee: float = 0.0
    bot: str = ""
    reason: str = ""
    money: str = "practice"            # "practice" | "real" - never ambiguous
    at: float = field(default_factory=time.time)

    @property
    def value(self) -> float:
        return self.qty * self.price

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["value"] = round(self.value, 2)
        return out


@dataclass
class BotNote:
    """One line of what a bot is thinking, for the dashboard's live feed."""

    bot: str
    role: str
    text: str
    level: str = "info"                # "info" | "idea" | "trade" | "warn" | "veto"
    symbol: str = ""
    at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BrokerError(RuntimeError):
    """The broker refused or could not be reached. The message is safe to show the owner."""


@runtime_checkable
class Broker(Protocol):
    """Anything that can hold money and fill orders: the built-in practice account or a real broker."""

    name: str
    label: str

    def money(self) -> str:
        """``"practice"`` or ``"real"``."""

    def account(self) -> Dict[str, Any]:
        """``{"currency", "cash", "equity", "start_equity", "pl", "pl_pct"}`` at least."""

    def positions(self) -> List[Dict[str, Any]]:
        """``[{"symbol", "asset_class", "qty", "avg_price", "price", "value", "pl", "pl_pct"}]``."""

    def place(self, order: Order, quote: Quote) -> Fill:
        """Fill (or send) one order at today's price. Raises ``BrokerError`` when refused."""


@runtime_checkable
class Feed(Protocol):
    """A source of market data for one or more asset classes."""

    name: str

    def instruments(self) -> List[Instrument]:
        """Every market this feed can price."""

    def quote(self, symbol: str) -> Quote:
        """The price now. Raises ``MarketDataError`` when there is none."""

    def candles(self, symbol: str, interval: str = "1d", limit: int = 200) -> List[Candle]:
        """Oldest first. ``interval`` is "1h" or "1d"."""

    def book(self, symbol: str, depth: int = 50) -> Optional[Book]:
        """The order book, or ``None`` when this feed has no book (stocks on free feeds)."""


class MarketDataError(RuntimeError):
    """No price could be fetched. The message says why, in plain words."""
