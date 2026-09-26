"""Adaptive mode, the auto stock adder, lessons/cool-downs and the owner's schedule.

The owner's words: one button, hands-off, it chooses every value not given, adds and
researches stocks itself, no trade limit, and a $50 account must not go all-in on one
dead stock. No test touches the network: prices and signals are fakes.
"""

from __future__ import annotations

import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from trading import adaptive, autopilot, brokers, discovery, guard, lessons, market, signals, store
from trading.brokers import OrderRequest

PRICES = {"AAA": 20.0, "BBB": 30.0, "CCC": 40.0, "DDD": 50.0, "EEE": 60.0, "FFF": 70.0, "SPY": 500.0}


def fake_signal(symbol, kind="buy", score=0.6, confidence=0.8, vol=30.0):
    return {"symbol": symbol, "signal": kind, "score": score, "confidence": confidence, "reasons": ["Uptrend."],
            "indicators": {"price": PRICES.get(symbol, 10.0), "volatility": vol, "return_20d": 6.0, "rsi14": 55.0}}


SIGNALS = {}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "folder", lambda: tmp_path)
    monkeypatch.setattr(market, "quote", lambda symbol: {"symbol": symbol.upper(), "price": PRICES[symbol.upper()],
                                                         "previous_close": PRICES[symbol.upper()], "change_pct": 0.0})
    monkeypatch.setattr(market, "us_market_open", lambda now=None: True)
    monkeypatch.setattr(discovery, "_from_web", lambda limit=15: [])
    monkeypatch.setattr(autopilot, "research", lambda symbol, signal: {"thesis": "Fine.", "avoid": False})
    monkeypatch.setattr(autopilot, "ensure_running", lambda: True)  # no background schedule in tests

    def signal_for(symbol, record=True):
        symbol = symbol.upper()
        if symbol not in SIGNALS:
            raise market.MarketDataError(f"No price history for {symbol}.")
        return dict(SIGNALS[symbol], indicators=dict(SIGNALS[symbol]["indicators"]))

    monkeypatch.setattr(signals, "signal_for", signal_for)
    SIGNALS.clear()
    yield
    SIGNALS.clear()


# --- choosing values -----------------------------------------------------------------------


def resolve(**kw):
    args = dict(cash=50.0, ai_invested=0.0, ranked=[], track={}, lesson_summary={}, market_open=True)
    args.update(kw)
    return adaptive.resolve(**args)


def test_a_50_dollar_account_gets_its_own_budget_spread_over_several_stocks():
    values, why = resolve()
    assert 45 <= values["max_invested"] <= 50
    assert values["target_positions"] == 4
    assert values["max_per_trade"] <= values["max_invested"] * 0.4 + 0.01
    assert values["max_trades_per_day"] == adaptive.UNLIMITED_TRADES
    assert values["scan_minutes"] == 5
    assert "max_invested" in why and why["max_invested"]


def test_it_invests_less_when_the_market_falls_or_it_keeps_losing():
    calm, _ = resolve()
    falling, why = resolve(ranked=[fake_signal("SPY", kind="sell", score=-0.6)])
    assert falling["max_invested"] < calm["max_invested"] and "SPY" in why["max_invested"]
    losing, _ = resolve(track={"graded": 20, "hit_rate": 0.3}, lesson_summary={"exits": 6, "win_rate": 0.2, "losing_streak": 3})
    assert losing["max_invested"] < calm["max_invested"]
    assert losing["min_confidence"] > calm["min_confidence"]


def test_jumpy_stocks_get_wider_stops_than_calm_ones():
    calm, _ = resolve(ranked=[fake_signal("AAA", vol=16)])
    jumpy, _ = resolve(ranked=[fake_signal("AAA", vol=60)])
    assert jumpy["stop_loss_pct"] > calm["stop_loss_pct"]
    assert jumpy["take_profit_pct"] > jumpy["stop_loss_pct"]


def test_pins_win_and_adaptive_is_hands_off():
    guard.save_settings({"ai": {"adaptive": True, "adaptive_pins": {"max_invested": 30}, "approval": "always"}})
    store.write("adaptive", {"values": {"max_invested": 47.0, "max_per_trade": 18.0, "max_trades_per_day": adaptive.UNLIMITED_TRADES}})
    ai = guard.effective_ai()
    assert ai["max_invested"] == 30.0          # the owner's number
    assert ai["max_per_trade"] == 18.0          # the AI's choice
    assert ai["approval"] == "never" and ai["rotate"] and ai["auto_discover"]
    guard.save_settings({"ai": {"adaptive": False}})
    assert guard.effective_ai()["approval"] == "always"


def test_adaptive_has_no_daily_trade_limit():
    brokers.get("paper").reset(1000)
    guard.save_settings({"ai": {"enabled": True, "adaptive": True, "max_trades_per_day": 5}})
    store.write("adaptive", {"values": {"max_invested": 900.0, "max_per_trade": 300.0, "max_trades_per_day": adaptive.UNLIMITED_TRADES,
                                        "daily_loss_stop_pct": 15.0}})
    store.write("ai_day", {"day": time.strftime("%Y-%m-%d"), "trades": 50, "research": 0, "start_equity": None})
    result = guard.submit(OrderRequest(symbol="AAA", side="buy", notional=20, requested_by="ai"))
    assert result["status"] == "filled"


# --- lessons --------------------------------------------------------------------------------


def test_a_loss_however_small_cools_the_symbol_off_and_repeats_cool_longer():
    now = time.time()
    lessons.record_exit("AAA", -0.4, "Signal turned sell", "signal", now=now)
    cool = lessons.cooldowns(now)
    assert "AAA" in cool and cool["AAA"]["until"] == pytest.approx(now + 3 * 86400)
    lessons.record_exit("AAA", -5.0, "Stop loss", "stop", now=now + 10)
    assert lessons.cooldowns(now + 20)["AAA"]["until"] == pytest.approx(now + 10 + 7 * 86400)
    lessons.record_exit("BBB", 4.0, "Take profit", "target", now=now)
    assert "BBB" not in lessons.cooldowns(now)
    assert lessons.cooldowns(now + 8 * 86400) == {}


def test_losing_streak_counts_the_latest_losses():
    now = time.time()
    lessons.record_exit("AAA", 3.0, "win", "target", now=now)
    lessons.record_exit("BBB", -1.0, "loss", "stop", now=now + 1)
    lessons.record_exit("CCC", -2.0, "loss", "stop", now=now + 2)
    assert lessons.summary(now + 3)["losing_streak"] == 2


# --- schedule -------------------------------------------------------------------------------


def stamp(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi).timestamp()


def test_schedule_window_and_overnight_window():
    weekdays = {"enabled": True, "days": [0, 1, 2, 3, 4], "start": "09:30", "end": "16:00"}
    assert adaptive.schedule_state(weekdays, stamp(2026, 9, 23, 10, 0))["inside"]       # Wednesday 10:00
    outside = adaptive.schedule_state(weekdays, stamp(2026, 9, 26, 10, 0))              # Saturday
    assert not outside["inside"] and datetime.fromtimestamp(outside["next_start"]).weekday() == 0
    overnight = {"enabled": True, "days": [0, 1, 2, 3, 4, 5, 6], "start": "22:00", "end": "06:00"}
    assert adaptive.schedule_state(overnight, stamp(2026, 9, 23, 23, 0))["inside"]
    assert adaptive.schedule_state(overnight, stamp(2026, 9, 24, 5, 0))["inside"]
    assert not adaptive.schedule_state(overnight, stamp(2026, 9, 24, 12, 0))["inside"]
    assert adaptive.schedule_state({"enabled": False}, time.time())["inside"]


def test_plan_next_rests_outside_the_schedule_and_keeps_its_keys():
    rules = guard.save_settings({"ai": {"enabled": True, "run_mode": "always",
                                        "schedule": {"enabled": True, "days": [5], "start": "01:00", "end": "01:05"}}})
    now = stamp(2026, 9, 23, 12, 0)  # a Wednesday; only Saturdays 01:00–01:05 are on
    plan = autopilot._plan_next(rules, now=now)
    assert plan["scan"] is False and plan["sleep"] > 0 and "schedule" in plan["resting"]
    with pytest.raises(brokers.BrokerError):
        guard.save_settings({"ai": {"schedule": {"enabled": True, "start": "25:00", "end": "10:00"}}})


# --- the auto stock adder -----------------------------------------------------------------


def test_tickers_are_pulled_from_news_text_without_common_words():
    text = "Shares of Acme (NASDAQ: ACME) jumped. $ZOOM rallied. The CEO said the ETF (SPY) and AI stocks … (NYSE: BOLT)"
    found = discovery.tickers_in(text)
    assert {"ACME", "ZOOM", "SPY", "BOLT"} <= set(found)
    assert not {"CEO", "ETF", "AI"} & set(found)


def test_discovery_adds_the_best_and_never_removes_the_owners_symbols(monkeypatch):
    monkeypatch.setattr(discovery, "UNIVERSE", ["AAA", "BBB", "CCC", "DDD", "EEE"])
    SIGNALS.update({"AAA": fake_signal("AAA", score=0.9, confidence=0.9), "BBB": fake_signal("BBB", score=0.7),
                    "CCC": fake_signal("CCC", kind="hold", score=0.1, confidence=0.55), "DDD": fake_signal("DDD", score=0.5, confidence=0.7),
                    "EEE": fake_signal("EEE", score=0.8, confidence=0.85), "OWN": fake_signal("OWN", kind="sell", score=-0.8)})
    rules = guard.save_settings({"watchlist": ["OWN"], "ai": {"discover_max_add": 2, "min_confidence": 0.65}})
    found = discovery.discover(rules, guard.effective_ai(rules), held=set(), force=True, web=False)
    assert [a["symbol"] for a in found["added"]] == ["AAA", "EEE"]
    watch = guard.settings()["watchlist"]
    assert "OWN" in watch                     # the owner's pick stays even though it's a sell
    assert "CCC" not in watch


def test_discovery_drops_what_it_added_once_it_turns_bad_and_skips_research_red_flags(monkeypatch):
    monkeypatch.setattr(discovery, "UNIVERSE", ["AAA", "BBB"])
    SIGNALS.update({"AAA": fake_signal("AAA", score=0.9, confidence=0.9), "BBB": fake_signal("BBB", score=0.8, confidence=0.85)})
    rules = guard.save_settings({"watchlist": ["SPY"], "ai": {"discover_max_add": 5}})
    SIGNALS["SPY"] = fake_signal("SPY")
    flagged = lambda symbol, signal: {"avoid": symbol == "BBB", "thesis": "Pending fraud probe."}
    found = discovery.discover(rules, guard.effective_ai(rules), held=set(), force=True, research_fn=flagged, web=False, now=1_000_000)
    assert [a["symbol"] for a in found["added"]] == ["AAA"] and found["skipped"][0]["symbol"] == "BBB"
    SIGNALS["AAA"] = fake_signal("AAA", kind="sell", score=-0.7)
    later = discovery.discover(guard.settings(), guard.effective_ai(), held=set(), force=True, web=False, now=1_000_000 + 3 * 86400)
    assert any(r["symbol"] == "AAA" for r in later["removed"])
    assert "AAA" not in guard.settings()["watchlist"] and "SPY" in guard.settings()["watchlist"]


# --- the whole thing, hands-off ------------------------------------------------------------


def test_hands_off_50_dollars_spreads_out_then_stops_out_learns_and_cools_off():
    for symbol in ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF"):
        SIGNALS[symbol] = fake_signal(symbol, score=0.7, confidence=0.8)
    guard.save_settings({"watchlist": ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]})
    result = autopilot.set_adaptive(True, starting_cash=50)
    assert result["adaptive"]["on"] and guard.settings()["ai"]["enabled"]
    try:
        summary = autopilot.run_once()
    finally:
        autopilot.stop("test over")  # the schedule thread must not keep running
    buys = [a for a in summary["actions"] if a["action"] == "buy" and a["result"] == "filled"]
    assert len(buys) >= 3, summary["actions"]
    positions = brokers.get("paper").positions()
    assert max(p["market_value"] for p in positions) <= 50 * 0.41
    assert brokers.get("paper").account()["cash"] >= 0

    victim = positions[0]["symbol"]
    PRICES[victim] = PRICES[victim] * 0.7   # a 30% drop
    try:
        guard.save_settings({"ai": {"enabled": True}})
        second = autopilot.run_once()
    finally:
        autopilot.stop("test over")
        PRICES[victim] = PRICES[victim] / 0.7
    sold = [a for a in second["actions"] if a["symbol"] == victim and a["action"] == "sell"]
    assert sold and "Stop loss" in sold[0]["why"] and "lesson" in sold[0]
    assert victim in lessons.cooldowns()
    assert not any(a["symbol"] == victim and a["action"] == "buy" for a in second["actions"])


def test_adaptive_off_stops_the_trader_and_keeps_the_owners_rules():
    guard.save_settings({"ai": {"max_invested": 777}})
    autopilot.set_adaptive(True)
    autopilot.set_adaptive(False)
    rules = guard.settings()
    assert rules["ai"]["adaptive"] is False and rules["ai"]["enabled"] is False
    assert rules["ai"]["max_invested"] == 777


def test_adaptive_routes_are_local_owner_only():
    import server

    local = TestClient(server.app, client=("127.0.0.1", 50016))
    assert local.get("/api/trading/adaptive").status_code == 200
    remote = TestClient(server.app, client=("203.0.113.7", 50017))
    assert remote.post("/api/trading/adaptive", json={"on": True}).status_code in (401, 403)
    assert remote.post("/api/trading/discover").status_code in (401, 403)
    assert remote.get("/api/trading/adaptive").status_code in (401, 403)


# --- research: the verdict, the cache, and not wasting a turned-down slot -------------------


def test_the_echoed_instruction_is_not_a_red_flag_only_the_last_verdict_counts():
    thinking = ("We need to decide. The prompt says end with VERDICT: OK or VERDICT: AVOID. Nothing alarming in the news; "
                "earnings are three weeks away.\nVERDICT: OK")
    assert autopilot.read_verdict(thinking)["avoid"] is False
    assert autopilot.read_verdict("<think>maybe VERDICT: AVOID?</think>Strong demand.\nVERDICT: OK")["avoid"] is False
    assert autopilot.read_verdict("SEC fraud probe announced Tuesday.\nVERDICT: AVOID")["avoid"] is True
    unclear = autopilot.read_verdict("The stock rose on sector strength. I'd need to look at VERDICT: OK or VERDICT: AVOID")
    assert unclear["avoid"] is False and "No clear verdict" in unclear["thesis"]


def test_a_flagged_pick_hands_its_slot_to_the_next_one_and_research_is_cached(monkeypatch):
    calls = []

    def research(symbol, signal):
        calls.append(symbol)
        return {"avoid": symbol in ("AAA", "BBB"), "thesis": "Probe." if symbol in ("AAA", "BBB") else "Fine.", "model": "fake"}

    monkeypatch.setattr(autopilot, "research", research)
    for symbol, score in (("AAA", 0.95), ("BBB", 0.9), ("CCC", 0.7), ("DDD", 0.65), ("EEE", 0.6), ("FFF", 0.55)):
        SIGNALS[symbol] = fake_signal(symbol, score=score, confidence=0.8)
    guard.save_settings({"watchlist": list(SIGNALS)})
    autopilot.set_adaptive(True, starting_cash=50)
    summary = autopilot.run_once()
    bought = {a["symbol"] for a in summary["actions"] if a["action"] == "buy" and a["result"] == "filled"}
    assert {"AAA", "BBB"}.isdisjoint(bought)
    assert len(bought) >= 3, summary["actions"]   # the two flagged slots went to the next picks
    before = len(calls)
    autopilot.run_once()
    assert not {"AAA", "BBB"} & set(calls[before:])  # red flags are remembered for hours, not re-researched
    autopilot.stop("test over")


def test_orders_queued_overnight_count_against_the_money_and_phantom_holdings_are_fixed(monkeypatch):
    monkeypatch.setattr(market, "us_market_open", lambda now=None: False)
    for symbol in ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF"):
        SIGNALS[symbol] = fake_signal(symbol, score=0.7, confidence=0.8)
    guard.save_settings({"watchlist": list(SIGNALS)})
    autopilot.set_adaptive(True, starting_cash=50, pins={"target_positions": 8})  # more slots than money
    autopilot.run_once()
    autopilot.run_once()
    queued = [o for o in brokers.get("paper").orders() if o["status"] == "queued"]
    assert queued and sum(float(o["notional"]) for o in queued) <= 50.0

    store.write("ai_positions", {"symbols": {**store.read("ai_positions", lambda: {"symbols": {}})["symbols"], "ZZZ": 3.0}})
    summary = autopilot.run_once()
    assert any(a["symbol"] == "ZZZ" and a["action"] == "fix" for a in summary["actions"])
    assert "ZZZ" not in store.read("ai_positions", lambda: {"symbols": {}})["symbols"]
    autopilot.stop("test over")
