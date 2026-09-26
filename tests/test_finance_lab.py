"""The finance lab: it can only spend its own money, and it practises before it acts."""

from __future__ import annotations

import math
import types

import pytest

from finance_lab import capital_guard, forecast, memory, node_map, simulator, strategies


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(capital_guard, "_path", lambda: tmp_path / "capital.json")
    monkeypatch.setattr(memory, "_path", lambda: tmp_path / "memory.json")
    node_map.reset()
    yield


def order(side="buy", symbol="AAPL", qty=1.0, by="ai", notional=0.0):
    """A stand-in for trading.brokers.OrderRequest — same three fields the guard reads."""
    return types.SimpleNamespace(
        symbol=symbol, side=side, qty=qty, notional=notional, requested_by=by,
        estimated_cost=lambda price: notional or qty * price,
    )


def rising(days=300, start=100.0, step=0.004):
    return [{"date": f"d{i}", "close": start * math.exp(step * i)} for i in range(days)]


def choppy(days=300, start=100.0):
    return [{"date": f"d{i}", "close": start * (1 + 0.05 * math.sin(i / 7))} for i in range(days)]


# --- the pot ---------------------------------------------------------------------------


def test_with_no_pot_the_lab_stays_out_of_the_way():
    """An unconfigured lab must not silently stop a trader the owner already uses."""
    allowed, reason = capital_guard.check_order(order(qty=1), 100.0)
    assert allowed is True
    assert "no money allocated" in reason.lower()
    assert "trading budgets" in reason.lower()


def test_it_cannot_spend_more_than_it_has():
    capital_guard.update_settings(allocated=1000, max_position_pct=100)
    ok, _ = capital_guard.check_order(order(qty=5), 100.0)
    assert ok is True
    refused, reason = capital_guard.check_order(order(qty=50), 100.0)
    assert refused is False
    assert "debt" in reason or "more than" in reason


def test_the_owners_own_orders_are_never_touched():
    allowed, reason = capital_guard.check_order(order(qty=1000, by="owner"), 100.0)
    assert allowed is True and "your own order" in reason.lower()


def test_one_symbol_cannot_take_the_whole_pot():
    capital_guard.update_settings(allocated=1000, max_position_pct=20)
    allowed, reason = capital_guard.check_order(order(qty=3), 100.0)   # $300 of a $200 cap
    assert allowed is False and "capped" in reason


def test_earnings_grow_what_it_may_use():
    capital_guard.update_settings(allocated=1000)
    before = capital_guard.pot()["total"]
    capital_guard.record_result("AAPL", 250.0)
    assert capital_guard.pot()["total"] == pytest.approx(before + 250)


def test_a_loss_is_written_down_as_a_lesson():
    capital_guard.update_settings(allocated=1000)
    capital_guard.record_result("AAPL", -120.0, why="Bought the top after a run.")
    lessons = capital_guard.lessons()
    assert lessons and "AAPL" in lessons[0]["what"]
    assert "top" in lessons[0]["lesson"]


def test_it_halves_its_size_while_it_is_losing():
    capital_guard.update_settings(allocated=1000, loss_stop_pct=40, max_position_pct=100)
    capital_guard.record_result("AAPL", -250.0)              # 25% down: past half the 40% stop
    money = capital_guard.pot()
    assert money["braking"] is True
    assert capital_guard.can_spend() == pytest.approx(money["cash"] / 2)


def test_past_the_loss_stop_it_stops_buying_and_says_why():
    capital_guard.update_settings(allocated=1000, loss_stop_pct=20)
    capital_guard.record_result("AAPL", -300.0)
    allowed, reason = capital_guard.check_order(order(qty=1), 10.0)
    assert allowed is False
    assert "stop" in reason.lower()
    assert capital_guard.pot()["stopped"] is True
    # And the owner can put it back to work.
    capital_guard.reset_stop()
    assert capital_guard.pot()["stopped"] is False


def test_it_never_sells_what_it_does_not_own():
    capital_guard.update_settings(allocated=1000)
    capital_guard.record_fill("AAPL", "buy", 2, 100.0)
    allowed, _ = capital_guard.check_order(order(side="sell", qty=2), 100.0)
    assert allowed is True
    refused, reason = capital_guard.check_order(order(side="sell", qty=9), 100.0)
    assert refused is False and "never sells" in reason


def test_a_broken_guard_never_blocks_the_owners_trading(monkeypatch):
    monkeypatch.setattr(capital_guard, "_check", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    allowed, reason = capital_guard.check_order(order(), 100.0)
    assert allowed is True and "skipped" in reason


# --- forecasting -----------------------------------------------------------------------


def test_a_forecast_is_a_cone_not_a_number():
    row = forecast.predict(rising(), horizon=10)
    assert row["ok"] is True
    assert len(row["days"]) == 10
    first = row["days"][0]
    assert first["low"] < first["mid"] < first["high"]
    assert row["band_pct"][0] < row["band_pct"][1]


def test_a_rising_series_forecasts_upwards():
    assert forecast.predict(rising(), horizon=20)["expected_change_pct"] > 0


def test_a_short_history_is_refused_rather_than_guessed():
    assert forecast.predict(rising(days=5))["ok"] is False


def test_the_regime_is_named_in_words():
    assert forecast.regime(rising()) == "rising"
    assert forecast.regime(choppy()) in {"quiet", "wild"}


def test_forecasting_lights_up_its_node():
    forecast.predict(rising(), horizon=5)
    row = next(n for n in node_map.map_now()["nodes"] if n["id"] == "forecast")
    assert row["count"] >= 1 and row["hot"] is True


# --- strategies and practice ------------------------------------------------------------


def test_every_strategy_gives_a_reason():
    for signal in strategies.read_all(rising()):
        assert signal["action"] in {"buy", "sell", "hold"}
        assert len(signal["why"]) > 10


def test_a_trend_follower_buys_a_trend():
    assert strategies.read("trend_sma", rising())["action"] == "buy"


def test_a_backtest_reports_against_buy_and_hold():
    result = strategies.backtest("trend_sma", rising())
    assert result["ok"] is True
    assert "buy_hold_pct" in result and "beat_holding_pct" in result
    assert result["trades"] >= 1


def test_training_fills_the_memory_and_advice_uses_it():
    history = rising(days=400)
    simulator.train(["TEST"], history_by_symbol={"TEST": history})
    table = memory.table()
    assert table, "training wrote nothing down"
    assert all(row["runs"] >= 1 for row in table)

    advice = simulator.advise("TEST", history=history)
    assert advice["ok"] is True
    assert advice["from_memory"] is True
    assert advice["strategy"] in strategies.names()
    assert "practice runs" in advice["why"]


def test_advice_says_so_when_it_has_not_practised():
    advice = simulator.advise("TEST", history=rising(days=200))
    assert advice["from_memory"] is False
    assert "Train the simulator" in advice["why"]
