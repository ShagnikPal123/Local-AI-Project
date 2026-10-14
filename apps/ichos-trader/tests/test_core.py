"""The copied core still does what it did in the main app, plus the crypto and currency hours."""

from __future__ import annotations

import random
from datetime import datetime, timezone

from ichos_trader import config, store
from ichos_trader.core import clock, forecast, indicators, strategies


def _walk(n: int = 220, drift: float = 0.002, seed: int = 7):
    rng = random.Random(seed)
    prices = [100.0]
    for _ in range(n):
        prices.append(prices[-1] * (1 + rng.gauss(drift, 0.01)))
    return prices


def test_crypto_never_closes_and_currencies_rest_on_saturday():
    saturday = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
    assert clock.is_open("crypto", saturday)
    assert not clock.is_open("fx", saturday)
    assert not clock.is_open("stock", saturday)


def test_stocks_follow_the_nyse_calendar():
    christmas = datetime(2026, 12, 25, 16, 0, tzinfo=timezone.utc)
    weekday_noon_new_york = datetime(2026, 10, 14, 16, 0, tzinfo=timezone.utc)
    assert not clock.is_open("stock", christmas)
    assert clock.is_open("etf", weekday_noon_new_york)


def test_currencies_open_sunday_evening_new_york():
    sunday_6pm_new_york = datetime(2026, 10, 18, 22, 0, tzinfo=timezone.utc)
    assert clock.fx_open(sunday_6pm_new_york)


def test_a_steady_climb_reads_as_buy_with_reasons():
    result = indicators.analyse(_walk())
    assert result["signal"] == "buy"
    assert result["reasons"]


def test_backtests_use_the_right_year_length():
    prices = _walk()
    stocks = strategies.backtest("trend_sma", prices)
    crypto = strategies.backtest("trend_sma", prices, periods_per_year=365)
    assert stocks["ok"] and crypto["ok"]
    assert stocks["return_pct"] == crypto["return_pct"]
    assert stocks["per_year_pct"] != crypto["per_year_pct"]


def test_the_forecast_cone_is_ordered():
    cone = forecast.predict(_walk(), horizon=10, periods_per_year=365)
    assert cone["ok"]
    for day in cone["days"]:
        assert day["low"] <= day["mid"] <= day["high"]


def test_stores_live_in_the_data_folder_and_survive_a_reread(tmp_path):
    store.write("example", {"a": 1})
    assert store.read("example") == {"a": 1}
    assert (config.data_dir() / "example.json").exists()
    assert str(config.data_dir()).startswith(str(tmp_path))


def test_old_settings_files_still_load_with_new_defaults():
    settings = config.merged({"risk": 0.9, "shutdown": {"max_drawdown_pct": 5.0}})
    assert settings["risk"] == 0.9
    assert settings["shutdown"]["max_drawdown_pct"] == 5.0
    assert settings["shutdown"]["slow_cycles"] == 5
