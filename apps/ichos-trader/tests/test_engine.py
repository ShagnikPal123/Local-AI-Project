"""The engine runs whole cycles on the simulated market: learn first, trade, explain, stop itself."""

from __future__ import annotations

import pytest

from ichos_trader import engine as engine_mod, settings, store, watchdog
from ichos_trader.engine import Engine
from ichos_trader.markets import SimulatedFeed
from ichos_trader.markets.hub import MarketHub

NOW = 1_800_000_000.0


def make(now=NOW, quotes_at=None, **cfg):
    settings.save({"markets": {"crypto": True, "stocks": False, "fx": False}, **cfg})
    sim = SimulatedFeed(lambda: quotes_at or now)
    hub = MarketHub(feeds={"crypto": sim, "stock": sim, "etf": sim, "fx": sim}, clock=lambda: now)
    return Engine(hub, clock=lambda: now)


def test_learn_first_holds_every_buy_until_the_playbook_is_full():
    eng = make()
    first = eng.run_cycle()
    assert first["learning"] and first["orders"] == []
    for _ in range(10):
        result = eng.run_cycle()
        if not result["learning"]:
            break
    assert not result["learning"]
    fills = [o for o in result["orders"] if o["side"] == "buy"]
    assert fills, "after learning, the traders should buy something on the simulated market"
    assert all(f["money"] == "practice" for f in fills)


def test_without_learn_first_it_trades_on_the_first_cycle():
    eng = make(learn_first=False)
    assert eng.run_cycle()["orders"]


def test_the_dashboard_has_every_field_the_screen_draws():
    eng = make(learn_first=False)
    eng.run_cycle()
    dash = eng.dashboard()
    for key in ("state", "state_words", "stopped_reason", "money_kind", "money", "win_rate", "equity_curve", "scanned",
                "markets", "positions", "trades", "bots", "bots_running", "thinking", "plan", "predictions",
                "prediction_record", "research", "speed", "learning", "theme", "updated_at"):
        assert key in dash, key
    assert dash["money_kind"] == "practice" and dash["market_source"] == "simulated"
    assert dash["state"] == "off" and dash["scanned"] >= 50
    assert len(dash["markets"]) == engine_mod.TOP and dash["markets"][0]["score"] >= dash["markets"][-1]["score"]
    assert dash["predictions"] and dash["research"] and dash["plan"]["focus"]
    assert dash["speed"]["grade"] in ("fast", "ok", "slow") and dash["speed"]["stages"]["fetch"] >= 0
    money = dash["money"]
    assert set(money) >= {"equity", "today_pl", "predicted_pl_pct", "predicted_band_pct", "predicted_horizon_h"}
    traders = [b for b in dash["bots"] if b["role"] == "trader"]
    assert sum(b["pot"] for b in traders) == pytest.approx(money["equity"], rel=0.01)
    assert any(b["role"] == "skeptic" for b in dash["bots"])


def test_predictions_are_graded_after_a_day():
    eng = make(learn_first=False)
    eng.run_cycle()
    made = len(eng.state["predictions"])
    later = make(now=NOW + 25 * 3600, learn_first=False)
    later.run_cycle()
    record = later.dashboard()["prediction_record"]
    assert record["graded"] == made and 0 <= record["right"] <= made


def test_old_prices_pause_trading():
    eng = make(learn_first=False, quotes_at=NOW - 3600)
    result = eng.run_cycle()
    assert result["orders"] == []
    settings.save({"running": True})
    assert eng.status()["state"] == "paused"


def test_the_watchdog_shuts_it_down_and_a_restart_does_not_undo_that(monkeypatch):
    eng = make(learn_first=False)
    settings.save({"running": True})
    monkeypatch.setattr(watchdog, "check", lambda **_: "Shut down: the money fell 11% from its best.")
    eng.run_cycle()
    dash = eng.dashboard()
    assert dash["state"] == "shutdown" and "fell 11%" in dash["stopped_reason"]
    launched = []
    monkeypatch.setattr(eng, "_launch", lambda: launched.append(1))
    Engine(eng.hub, clock=eng.clock).resume_if_running()
    assert launched == []


def test_the_loop_outlives_a_failing_cycle(monkeypatch):
    eng = make()
    settings.save({"running": True})
    monkeypatch.setattr(engine_mod, "ERROR_BACKOFF", (0.01,))
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("feed hiccup")
        eng.stop("")

    monkeypatch.setattr(eng, "run_cycle", flaky)
    eng._loop()
    assert len(calls) == 2 and "feed hiccup" in eng.state["last_error"]


def test_flatten_sells_everything():
    eng = make(learn_first=False)
    eng.run_cycle()
    assert eng.broker.positions()
    assert eng.flatten() >= 1 and eng.broker.positions() == []
    assert store.read("paper")["fills"][-1]["bot"] == "Owner"


def test_every_holding_gets_a_prediction_and_the_curve_reaches_now():
    eng = make(learn_first=False)
    eng.run_cycle()
    dash = eng.dashboard()
    held = {p["symbol"] for p in dash["positions"]}
    predicted = {p["symbol"] for p in dash["predictions"] if not p["graded"]}
    assert held and held <= predicted
    assert dash["money"]["predicted_band_pct"][0] <= dash["money"]["predicted_pl_pct"] <= dash["money"]["predicted_band_pct"][1]
    assert len(dash["equity_curve"]) >= 2 and dash["equity_curve"][-1]["t"] == NOW
