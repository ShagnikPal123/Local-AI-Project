"""Ranking prefers markets that are easy to trade and look good, and every measure has a sane value."""

from __future__ import annotations

import time

from ichos_trader import latency, ranking
from ichos_trader.markets import MarketHub, SimulatedFeed
from ichos_trader.models import Book, Candle, Instrument, Quote, Snapshot

NOW = 1_760_400_000.0


def _candles(n=60, start=100.0, step=0.5, volume=1_000_000):
    out, price = [], start
    for i in range(n):
        out.append(Candle(i * 86400.0, price, price * 1.01, price * 0.99, price + step * 0.8, volume))
        price += step
    return out


def _snap(symbol="AAA", spread=(99.99, 100.01), volume=5e7, book=None, candles=None, kind="stock"):
    quote = Quote(symbol, 100.0, spread[0], spread[1], volume / 100.0, 1.0, NOW)
    return Snapshot(Instrument(symbol, kind), quote, candles or _candles(), book)


def test_liquid_tight_markets_score_higher_than_thin_wide_ones():
    deep = ranking.microstructure(_snap(volume=5e9))
    thin = ranking.microstructure(_snap(spread=(99.0, 101.0), volume=2e5))
    assert deep["liquidity"] > 0.9 > 0.1 > thin["liquidity"]
    assert deep["spread_bps"] < 3 and thin["spread_bps"] > 150
    assert deep["tradability"] > thin["tradability"]
    assert any("Wide spread" in n for n in thin["notes"])


def test_the_book_gives_depth_and_flow_when_there_is_one():
    book = Book("AAA", bids=[(99.9, 300.0), (99.5, 300.0)], asks=[(100.1, 100.0), (100.5, 100.0)])
    row = ranking.microstructure(_snap(book=book))
    assert row["depth_source"] == "book"
    assert round(row["depth_usd"]) == round(99.9 * 300 + 99.5 * 300 + 100.1 * 100 + 100.5 * 100)
    assert row["flow"] > 0.4  # three times more resting on the bid: buyers


def test_without_bid_ask_or_book_spread_and_flow_are_estimated_from_bars():
    snap = Snapshot(Instrument("AAA", "stock"), Quote("AAA", 100.0), _candles())
    row = ranking.microstructure(snap)
    assert row["spread_source"] == "estimated" and row["depth_source"] == "estimated"
    assert row["spread_bps"] > 0
    assert row["flow"] > 0  # every bar closed in the top of its range


def test_corwin_schultz_finds_a_wider_spread_in_jumpier_ranges():
    calm = ranking.corwin_schultz_bps(_candles())
    jumpy = [Candle(c.t, c.open, c.high * 1.02, c.low * 0.98, c.close, c.volume) for c in _candles()]
    assert ranking.corwin_schultz_bps(jumpy) > calm


def test_rank_orders_by_score_and_skips_markets_without_a_price():
    hub = MarketHub({k: SimulatedFeed(clock=lambda: NOW) for k in ("stock", "etf", "crypto", "fx")}, clock=lambda: NOW)
    items = hub.instruments(["crypto", "stock"])[:40]
    rows = ranking.rank(hub.snapshots(items) + [Snapshot(Instrument("ZZZ", "stock"), error="down")])
    assert len(rows) == 40
    assert [r["score"] for r in rows] == sorted((r["score"] for r in rows), reverse=True)
    top = rows[0]
    for key in ("liquidity", "spread_bps", "depth_usd", "flow", "tradability", "signal", "sparkline", "open"):
        assert key in top


def test_speed_is_graded_against_the_stated_targets():
    assert latency.grade("decision_ms", 3) == "fast"
    assert latency.grade("decision_ms", 300) == "ok"
    assert latency.grade("cycle_ms", 20_000) == "slow"
    watch = latency.Stopwatch()
    with watch.stage("fetch"):
        time.sleep(0.002)
    assert watch.stages["fetch"] >= 1.5
    recorder = latency.Recorder()
    recorder.add(800.0, 2.0, watch.stages, 287)
    summary = recorder.summary()
    assert summary["grade"] == "fast" and "287-market" in summary["words"]
