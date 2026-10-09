"""The trading desk (U16): several AI traders, each with its own pot, strategy and market — and the money drifting
toward whichever is doing best."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from trading import desk, store
from trading.brokers import OrderRequest

PRICES = {"AAPL": 100.0, "MSFT": 200.0, "SPY": 400.0, "KO": 50.0}


def rising(n=80, start=50.0):
    return [{"close": start * (1 + 0.01 * i)} for i in range(n)]


def falling(n=80, start=150.0):
    return [{"close": start * (1 - 0.006 * i)} for i in range(n)]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "folder", lambda: tmp_path)
    yield


class Broker:
    def __init__(self):
        self.orders = []

    def submit(self, order: OrderRequest):
        order.validate()
        self.orders.append(order)
        return {"status": "filled", "price_at_request": PRICES.get(order.symbol, 100.0), "reasons": []}


AI = {"max_invested": 1000.0, "max_per_trade": 500.0, "max_position_pct": 0.5}


def two_agents():
    return [{"name": "Trend", "strategy": "momentum", "market": "watchlist", "share": 0.5},
            {"name": "Index", "strategy": "momentum", "market": "watchlist", "share": 0.5}]


def test_each_trader_spends_only_its_own_pot_and_every_order_goes_through_the_guard():
    desk.configure(enabled=True, agents=two_agents())
    broker = Broker()
    out = desk.run(AI, watchlist=["AAPL", "MSFT"], submit=broker.submit, history=lambda s: rising(),
                   quote=lambda s: PRICES[s], ai_owned={})
    buys = [o for o in broker.orders if o.side == "buy"]
    assert buys and all(o.requested_by == "ai" for o in buys)
    rows = {r["name"]: r for r in out["agents"]}
    for name in ("Trend", "Index"):
        assert 0 < rows[name]["cost"] <= rows[name]["pot"] + 0.01 == 500.01
    assert all("Trend" in o.reason or "Index" in o.reason for o in buys), "every order says which trader placed it"


def test_a_trader_sells_what_its_strategy_turns_against_and_books_the_result():
    desk.configure(enabled=True, agents=two_agents()[:1])
    broker = Broker()
    desk.run(AI, watchlist=["AAPL"], submit=broker.submit, history=lambda s: rising(), quote=lambda s: PRICES[s],
             ai_owned={})
    held = desk.state()["ledger"]
    agent_id = desk.state()["agents"][0]["id"]
    assert "AAPL" in held[agent_id]["holdings"]
    PRICES["AAPL"] = 120.0
    try:
        out = desk.run(AI, watchlist=["AAPL"], submit=broker.submit, history=lambda s: falling(),
                       quote=lambda s: PRICES[s], ai_owned={"AAPL": 999})
    finally:
        PRICES["AAPL"] = 100.0
    assert any(a["action"] == "sell" and a["symbol"] == "AAPL" for a in out["actions"])
    book = desk.state()["ledger"][agent_id]
    assert "AAPL" not in book["holdings"] and book["realized"] > 0


def test_a_refused_order_changes_nothing_in_the_ledger():
    desk.configure(enabled=True, agents=two_agents()[:1])
    desk.run(AI, watchlist=["AAPL"], submit=lambda o: {"status": "refused", "reasons": ["Over the daily limit."]},
             history=lambda s: rising(), quote=lambda s: PRICES[s], ai_owned={})
    assert not any(desk.state()["ledger"][a]["holdings"] for a in desk.state()["ledger"])


def test_money_drifts_from_the_worst_trader_to_the_best_inside_the_bounds():
    desk.configure(enabled=True, agents=two_agents())
    data = desk.state()
    good, bad = data["agents"]
    data["ledger"] = {good["id"]: {"holdings": {"AAPL": 1.0}, "cost": {"AAPL": 50.0}, "realized": 0.0, "trades": 1},
                      bad["id"]: {"holdings": {"KO": 1.0}, "cost": {"KO": 100.0}, "realized": 0.0, "trades": 1}}
    moved = desk.rebalance(data, quote=lambda s: PRICES[s])
    assert moved and moved["to"] == good["name"] and moved["from"] == bad["name"]
    assert good["share"] == pytest.approx(0.55) and bad["share"] == pytest.approx(0.45)
    for _ in range(40):
        desk.rebalance(data, quote=lambda s: PRICES[s])
    assert bad["share"] >= desk.MIN_SHARE - 1e-9 and good["share"] <= desk.MAX_SHARE + 1e-9


def test_configuring_normalises_shares_and_refuses_an_empty_desk():
    view = desk.configure(agents=[{"name": "A", "share": 3}, {"name": "B", "share": 1}])
    shares = sorted(a["share"] for a in view["agents"])
    assert shares == pytest.approx([0.25, 0.75])
    with pytest.raises(ValueError):
        desk.configure(agents=[])


def test_desk_routes_are_local_owner_only(monkeypatch):
    import server

    monkeypatch.setattr(desk, "_safe_quote", lambda s: 100.0)
    local = TestClient(server.app, client=("127.0.0.1", 50031))
    assert local.get("/api/trading/desk").status_code == 200
    remote = TestClient(server.app, client=("203.0.113.9", 50032))
    assert remote.get("/api/trading/desk").status_code in (401, 403)
    assert remote.put("/api/trading/desk", json={"enabled": True}).status_code in (401, 403)


def test_with_the_desk_on_the_trader_s_scan_hands_over_to_it(monkeypatch):
    from trading import autopilot, guard, market

    monkeypatch.setattr(market, "us_market_open", lambda now=None: True)
    monkeypatch.setattr(autopilot, "ensure_running", lambda: True)
    calls = []
    monkeypatch.setattr(desk, "run", lambda ai, **kw: calls.append(kw) or {
        "actions": [{"agent": "Trend", "symbol": "AAPL", "action": "buy", "why": "test"}], "shift": None,
        "agents": [{"name": "Trend", "pot": 500.0, "gain": 0.0, "pct": 0.0, "trades": 1}]})
    guard.save_settings({"ai": {"enabled": True}})
    desk.configure(enabled=True)

    summary = autopilot.run_once(force=True)

    assert calls, "the desk ran instead of the single picker"
    assert summary["desk"]["agents"][0]["name"] == "Trend"
    assert any(a.get("agent") == "Trend" for a in summary["actions"])


def test_one_failing_order_costs_that_order_not_the_desk_s_run():
    desk.configure(enabled=True, agents=two_agents())

    def flaky(order):
        if order.symbol == "AAPL":
            raise RuntimeError("no price for AAPL")
        return {"status": "filled", "price_at_request": PRICES[order.symbol], "reasons": []}

    out = desk.run(AI, watchlist=["AAPL", "MSFT"], submit=flaky, history=lambda s: rising(),
                   quote=lambda s: PRICES[s], ai_owned={})
    assert any(a["result"] == "error" and a["symbol"] == "AAPL" for a in out["actions"] if a["action"] == "buy")
    assert any(a["result"] == "filled" and a["symbol"] == "MSFT" for a in out["actions"] if a["action"] == "buy")


def test_a_holding_the_account_no_longer_has_is_let_go_without_an_order():
    desk.configure(enabled=True, agents=two_agents()[:1])
    data = desk.state()
    agent_id = data["agents"][0]["id"]
    data["ledger"] = {agent_id: {"holdings": {"AAPL": 2.0}, "cost": {"AAPL": 200.0}, "realized": 0.0, "trades": 1}}
    desk._save(data)
    broker = Broker()
    out = desk.run(AI, watchlist=[], submit=broker.submit, history=lambda s: falling(), quote=lambda s: PRICES[s],
                   ai_owned={})
    assert not [o for o in broker.orders if o.side == "sell"]
    assert any(a["action"] == "gone" for a in out["actions"])
    assert "AAPL" not in desk.state()["ledger"][agent_id]["holdings"]
