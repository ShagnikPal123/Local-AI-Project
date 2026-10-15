"""Any currency: prices are converted into the account's currency before anyone reads them."""

from __future__ import annotations

import pytest

from ichos_trader import currency, settings, store
from ichos_trader.engine import Engine
from ichos_trader.markets import SimulatedFeed
from ichos_trader.markets.hub import MarketHub
from ichos_trader.models import Candle, Instrument, Quote, Snapshot

NOW = 1_800_000_000.0


def fx(pair, price):
    return Snapshot(Instrument(pair, "fx", pair, pair.split("-")[1], "x"), Quote(pair, price))


def test_rates_walk_across_pairs():
    worth = currency.rates([fx("EUR-USD", 1.25), fx("USD-JPY", 100.0)], "EUR")
    assert worth["EUR"] == 1.0
    assert worth["USD"] == pytest.approx(0.8)          # 1 USD = 0.8 EUR
    assert worth["JPY"] == pytest.approx(0.008)        # 1 JPY = 0.01 USD = 0.008 EUR


def test_a_snapshot_is_repriced_and_unreachable_currencies_are_refused():
    snap = Snapshot(Instrument("AAPL", "stock", "Apple", "USD", "x"), Quote("AAPL", 200.0, 199.0, 201.0),
                    [Candle(0, 190, 210, 180, 200, 5)])
    eur = currency.to_base(snap, "EUR", {"EUR": 1.0, "USD": 0.8})
    assert eur.instrument.quote_currency == "EUR"
    assert (eur.quote.price, eur.quote.bid, eur.quote.ask) == pytest.approx((160.0, 159.2, 160.8))
    assert eur.candles[0].close == pytest.approx(160.0) and eur.candles[0].volume == 5
    assert "No exchange rate" in currency.to_base(snap, "ZAR", {"ZAR": 1.0}).error
    assert currency.to_base(snap, "USD", {}) is snap


def test_an_account_in_euros_trades_dollar_markets_in_euros():
    settings.save({"markets": {"crypto": True, "stocks": False, "fx": False}, "learn_first": False,
                   "base_currency": "EUR"})
    sim = SimulatedFeed(lambda: NOW)
    eng = Engine(MarketHub(feeds={"crypto": sim, "stock": sim, "etf": sim, "fx": sim}, clock=lambda: NOW),
                 clock=lambda: NOW)
    eng.broker.reset(10_000, "EUR")
    result = eng.run_cycle()
    assert result["orders"]
    dash = eng.dashboard()
    assert dash["money"]["currency"] == "EUR"
    rate = currency.rates(eng.hub.snapshots([i for i in eng.hub.instruments(["fx"]) if i.symbol == "EUR-USD"]), "EUR")
    btc = next(s for s in eng.hub.snapshots([i for i in eng.hub.instruments(["crypto"]) if i.symbol == "BTC-USD"]))
    row = next((m for m in dash["markets"] if m["symbol"] == "BTC-USD"), None)
    if row:  # BTC is shown in euros, not dollars
        assert row["price"] == pytest.approx(btc.quote.price * rate["USD"], rel=1e-6)
    assert all(f["money"] == "practice" for f in store.read("paper")["fills"])


def test_the_account_currency_is_a_checked_setting():
    assert settings.save({"base_currency": "eur"})["base_currency"] == "EUR"
    assert settings.save({"base_currency": "XYZ"})["base_currency"] == "EUR"
