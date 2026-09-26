"""Trading (Request G1): the owner's rules hold, paper trading is honest, signals explain themselves.

No test reaches a broker or the network: prices come from a fake quote function.
"""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from trading import autopilot, brokers, guard, market, signals, store
from trading.brokers import BrokerError, OrderRequest

PRICES = {"AAPL": 200.0, "MSFT": 400.0, "TSLA": 250.0}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "folder", lambda: tmp_path)
    monkeypatch.setattr(market, "quote", lambda symbol: {"symbol": symbol.upper(), "price": PRICES[symbol.upper()],
                                                         "previous_close": PRICES[symbol.upper()], "change_pct": 0.0})
    monkeypatch.setattr(market, "us_market_open", lambda now=None: True)


def ai_rules(**ai):
    guard.save_settings({"ai": {"enabled": True, "approval": "never", **ai}})


def test_paper_account_fills_at_market_and_refuses_what_it_cannot_do():
    brokers.save_paper_settings({"realistic_fills": False})  # ideal fills; realism has its own tests
    result = guard.submit(OrderRequest(symbol="AAPL", side="buy", qty=10))
    assert result["status"] == "filled" and result["order_result"]["filled_price"] == 200.0
    account = brokers.get("paper").account()
    assert account["cash"] == 98_000.0 and account["equity"] == 100_000.0
    oversell = guard.submit(OrderRequest(symbol="AAPL", side="sell", qty=11))
    assert oversell["order_result"]["status"] == "rejected"


def test_ai_orders_wait_for_approval_by_default_and_expire_or_place_on_approve():
    guard.save_settings({"ai": {"enabled": True}})
    pending = guard.submit(OrderRequest(symbol="AAPL", side="buy", notional=200, requested_by="ai"))
    assert pending["status"] == "awaiting_approval"
    assert brokers.get("paper").positions() == []
    placed = guard.decide(pending["approval_id"], approve=True)
    assert placed["status"] == "filled" and brokers.get("paper").positions()[0]["symbol"] == "AAPL"
    with pytest.raises(BrokerError):
        guard.decide(pending["approval_id"], approve=True)


def test_ai_budget_limits_and_its_own_shares_only():
    ai_rules(max_per_trade=300, max_invested=500, max_trades_per_day=5)
    assert guard.submit(OrderRequest(symbol="AAPL", side="buy", notional=400, requested_by="ai"))["status"] == "refused"
    assert guard.submit(OrderRequest(symbol="AAPL", side="buy", notional=300, requested_by="ai"))["status"] == "filled"
    over_budget = guard.submit(OrderRequest(symbol="MSFT", side="buy", notional=300, requested_by="ai"))
    assert over_budget["status"] == "refused" and "budget" in over_budget["reasons"][0]

    guard.submit(OrderRequest(symbol="TSLA", side="buy", qty=4))  # the owner's own shares
    not_its_own = guard.submit(OrderRequest(symbol="TSLA", side="sell", qty=1, requested_by="ai"))
    assert not_its_own["status"] == "refused" and "only sell shares it bought" in not_its_own["reasons"][0]


def test_halt_stops_the_ai_and_live_accounts_need_the_typed_switch(monkeypatch):
    ai_rules()
    guard.halt("testing")
    assert guard.submit(OrderRequest(symbol="AAPL", side="buy", notional=100, requested_by="ai"))["status"] == "refused"
    assert guard.settings()["ai"]["enabled"] is False

    monkeypatch.setattr(brokers.PaperBroker, "live", lambda self: True)
    refused = guard.submit(OrderRequest(symbol="AAPL", side="buy", qty=1))
    assert refused["status"] == "refused" and "Live trading is off" in refused["reasons"][0]
    with pytest.raises(BrokerError):
        guard.save_settings({"live_enabled": True}, confirmation="yes")
    assert guard.save_settings({"live_enabled": True}, confirmation=guard.LIVE_CONFIRMATION)["live_enabled"] is True


def test_signals_are_explained_and_graded_honestly():
    rising = [100 * math.exp(0.004 * i) for i in range(120)]
    up = signals.analyse(rising, [1_000_000] * 120)
    assert up["signal"] == "buy" and any("20-day average" in r for r in up["reasons"])
    falling = list(reversed(rising))
    assert signals.analyse(falling)["signal"] == "sell"
    assert signals.analyse(rising[:10])["signal"] == "hold"

    store.write("predictions", {"predictions": [{"symbol": "AAPL", "signal": "buy", "confidence": 0.7, "price": 190.0,
                                                  "at": 0, "horizon_days": 5, "outcome": None}]})
    record = signals.score_track_record(now=10 * 86400)
    assert record["graded"] == 1 and record["hit_rate"] == 1.0


def test_autopilot_proposes_within_rules(monkeypatch):
    guard.save_settings({"ai": {"enabled": True, "approval": "always", "min_confidence": 0.6, "auto_discover": False}, "watchlist": ["AAPL"]})
    monkeypatch.setattr(signals, "signal_for", lambda symbol, record=True: {"symbol": symbol, "signal": "buy", "confidence": 0.8,
                                                                            "score": 0.6, "reasons": ["Uptrend."], "indicators": {"price": 200.0}})
    monkeypatch.setattr(autopilot, "research", lambda symbol, signal: {"thesis": "Fine.", "avoid": False})
    summary = autopilot.run_once()
    assert summary["actions"][0]["action"] == "buy" and summary["actions"][0]["result"] == "awaiting_approval"
    assert len(guard.pending_approvals()) == 1


def test_trading_routes_are_local_owner_only():
    import server

    local = TestClient(server.app, client=("127.0.0.1", 50006))
    assert local.get("/api/trading/state").status_code == 200
    remote = TestClient(server.app, client=("203.0.113.7", 50007))
    assert remote.post("/api/trading/orders", json={"symbol": "AAPL", "side": "buy", "qty": 1}).status_code in (401, 403)
