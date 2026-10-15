"""Market data: the simulated market behaves like a real one, live feeds parse what the APIs send,
and the hub routes, caches and contains failures. No real network anywhere."""

from __future__ import annotations

from ichos_trader.markets import MarketHub, SimulatedFeed, universe
from ichos_trader.markets.live import CoinbaseFeed, YahooFeed
from ichos_trader.models import Instrument, MarketDataError

NOW = 1_760_400_000.0


class FakeResponse:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    def json(self):
        return self._data


class FakeSession:
    """Answers by URL ending; anything unknown is a 404, like a real server."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append(url)
        for ending, data in self.routes.items():
            if url.endswith(ending):
                return FakeResponse(data)
        return FakeResponse({}, 404)


def test_the_universe_is_hundreds_of_markets_across_three_kinds():
    items = universe.everything()
    kinds = {i.asset_class for i in items}
    assert len(items) >= 200
    assert {"stock", "etf", "crypto", "fx"} <= kinds
    assert len({i.symbol for i in items}) == len(items)


def test_the_simulated_market_is_repeatable_and_sized_like_the_real_one():
    feed = SimulatedFeed(clock=lambda: NOW)
    first, again = feed.quote("BTC-USD"), feed.quote("BTC-USD")
    assert first.price == again.price
    assert 10_000 < first.price < 400_000
    assert first.bid < first.price < first.ask
    candles = feed.candles("AAPL", "1d", 120)
    assert len(candles) == 120
    assert all(c.low <= min(c.open, c.close) and c.high >= max(c.open, c.close) for c in candles)
    assert candles[0].t < candles[-1].t


def test_big_markets_have_tighter_spreads_than_small_ones():
    feed = SimulatedFeed(clock=lambda: NOW)
    assert feed.quote("BTC-USD").spread_bps < feed.quote("JASMY-USD").spread_bps


def test_the_simulated_book_is_ordered_best_first():
    book = SimulatedFeed(clock=lambda: NOW).book("ETH-USD", depth=10)
    assert len(book.bids) == len(book.asks) == 10
    assert book.bids[0][0] > book.bids[-1][0]
    assert book.asks[0][0] < book.asks[-1][0]
    assert book.bids[0][0] < book.asks[0][0]


def test_coinbase_answers_are_parsed_into_quote_candles_and_book():
    session = FakeSession({
        "/products": [{"id": "BTC-USD", "base_currency": "BTC", "quote_currency": "USD", "status": "online"},
                      {"id": "BTC-EUR", "base_currency": "BTC", "quote_currency": "EUR", "status": "online"}],
        "/BTC-USD/ticker": {"price": "100.0", "bid": "99.9", "ask": "100.1", "volume": "5000"},
        "/BTC-USD/stats": {"open": "95.0"},
        "/BTC-USD/candles": [[200, 98, 103, 99, 101, 10], [100, 95, 100, 96, 99, 12]],
        "/BTC-USD/book": {"bids": [["99.9", "1.5", 3]], "asks": [["100.1", "2.0", 1]]},
    })
    feed = CoinbaseFeed(session)
    assert [i.symbol for i in feed.instruments()] == ["BTC-USD"]
    quote = feed.quote("BTC-USD")
    assert quote.price == 100.0 and quote.change_pct == 5.26
    assert round(quote.spread_bps, 1) == 20.0
    candles = feed.candles("BTC-USD")
    assert [c.t for c in candles] == [100, 200] and candles[-1].close == 101
    assert feed.book("BTC-USD").bids == [(99.9, 1.5)]


def test_coinbase_down_falls_back_to_the_built_in_list():
    feed = CoinbaseFeed(FakeSession({}))
    assert len(feed.instruments()) == len(universe.crypto())


def test_yahoo_maps_currency_pairs_and_reads_the_chart():
    assert YahooFeed.ticker("EUR-USD") == "EURUSD=X"
    assert YahooFeed.ticker("BRK.B") == "BRK-B"
    chart = {"chart": {"result": [{"meta": {"regularMarketPrice": 110.0, "chartPreviousClose": 100.0},
                                   "timestamp": [1, 2],
                                   "indicators": {"quote": [{"open": [1, 2], "high": [2, 3], "low": [0.5, 1.5],
                                                             "close": [1.5, None], "volume": [10, 20]}]}}]}}
    feed = YahooFeed([Instrument("AAPL", "stock")], FakeSession({"/AAPL": chart}))
    assert feed.quote("AAPL").change_pct == 10.0
    assert len(feed.candles("AAPL")) == 1  # the bar with no close is dropped
    assert feed.book("AAPL") is None


def test_the_hub_routes_caches_and_contains_a_failing_market():
    sim = SimulatedFeed(clock=lambda: NOW)

    class Broken:
        name = "broken"

        def instruments(self):
            return [Instrument("BAD-USD", "crypto")]

        def quote(self, symbol):
            raise MarketDataError("no price")

    hub = MarketHub({"stock": sim, "etf": sim, "fx": sim, "crypto": Broken()}, clock=lambda: NOW)
    snaps = hub.snapshots([Instrument("AAPL", "stock"), Instrument("BAD-USD", "crypto")])
    assert snaps[0].quote and not snaps[0].error
    assert snaps[1].error == "no price"
    assert hub.snapshot(Instrument("AAPL", "stock")).quote is snaps[0].quote  # cached
    assert hub.source == "live"


def test_offline_means_every_price_is_simulated_and_says_so():
    hub = MarketHub()
    assert hub.source == "simulated"
    assert len(hub.instruments(["crypto", "stock", "etf"])) > 150
