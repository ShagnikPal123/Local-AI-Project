"""The AI trader's run modes and the practice account (Project Null N80, N81).

The owner: "allow a mode for active 24/7 or until stop so the user doesnt ahve to
manually start when US markets open" and "make the simulation … a bit better, just
make it clear which oen is real and fake".

Nothing here reaches a broker, the network or a real clock.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from trading import autopilot, brokers, guard, market, store
from trading.brokers import BrokerError, OrderRequest

PRICES = {"AAPL": 200.0, "MSFT": 400.0}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "folder", lambda: tmp_path)
    monkeypatch.setattr(market, "quote", lambda symbol: {"symbol": symbol.upper(), "price": PRICES[symbol.upper()],
                                                         "previous_close": PRICES[symbol.upper()], "change_pct": 0.0})
    autopilot._STATE.update(started_at=0.0, last_scan_at=0.0, next_scan_at=0.0, resting="", scans=0, stopped_reason="")
    yield
    # A test that starts the schedule must not leave its thread scanning afterwards: it would
    # trade in the next test's store, and once the store patch is undone, in the real one.
    thread = autopilot._THREAD
    if thread is not None and thread.is_alive():
        autopilot.stop("test over")
        thread.join(timeout=5)
    autopilot._THREAD = None


def open_market(monkeypatch, is_open: bool) -> None:
    monkeypatch.setattr(market, "us_market_open", lambda now=None: is_open)


# --- the market's own clock ---------------------------------------------------------


def test_the_calendar_knows_holidays_daylight_saving_and_early_closes():
    # 2026: July 4 falls on a Saturday, so the NYSE closes on Friday the 3rd.
    assert market.market_holidays(2026)[market._observed(__import__("datetime").date(2026, 7, 4))] == "Independence Day"
    assert str(market._easter(2026)) == "2026-04-05"  # Good Friday = April 3

    # The old code called March "summer time" from the 1st: 14:00 UTC is 9:00 in New
    # York in early March (shut), not 10:00 (open).
    early_march = market.session(datetime(2026, 3, 2, 14, 0, tzinfo=timezone.utc))
    assert early_march["open"] is False and early_march["phase"] == "pre"
    after_dst = market.session(datetime(2026, 3, 9, 14, 0, tzinfo=timezone.utc))
    assert after_dst["open"] is True

    thanksgiving = market.session(datetime(2026, 11, 26, 15, 0, tzinfo=timezone.utc))
    assert thanksgiving["open"] is False and "Thanksgiving" in thanksgiving["reason"]
    # The Friday after Thanksgiving stops at 1 pm New York (18:00 UTC).
    assert market.session(datetime(2026, 11, 27, 17, 0, tzinfo=timezone.utc))["open"] is True
    assert market.session(datetime(2026, 11, 27, 19, 0, tzinfo=timezone.utc))["open"] is False


def test_next_open_skips_weekends_and_holidays():
    friday_night = datetime(2026, 9, 18, 23, 0, tzinfo=timezone.utc)
    assert market.next_open(friday_night).strftime("%Y-%m-%d %H:%M") == "2026-09-21 13:30"  # Monday 9:30 New York
    before_christmas = datetime(2026, 12, 24, 20, 0, tzinfo=timezone.utc)
    assert market.next_open(before_christmas).strftime("%Y-%m-%d") == "2026-12-28"  # Christmas is Friday


# --- run modes ----------------------------------------------------------------------


def test_market_mode_sleeps_until_the_opening_bell_instead_of_polling(monkeypatch):
    open_market(monkeypatch, False)
    guard.save_settings({"ai": {"enabled": True, "run_mode": "market", "scan_minutes": 30}})
    plan = autopilot._plan_next(guard.settings())
    assert plan["scan"] is False
    assert "opens" in plan["resting"] or "market opens" in plan["resting"]
    assert plan["sleep"] > 60  # not a busy 30-minute poll against a shut market

    open_market(monkeypatch, True)
    assert autopilot._plan_next(guard.settings())["scan"] is True


def test_always_mode_keeps_working_when_the_market_is_shut_only_slower(monkeypatch):
    open_market(monkeypatch, False)
    run = autopilot.set_run_mode("always")
    assert run["mode"] == "always" and run["enabled"] is True
    assert "until you stop it" in run["summary"]

    plan = autopilot._plan_next(guard.settings())
    assert plan["scan"] is True, "24/7 means it keeps watching overnight"
    assert plan["sleep"] >= 15 * 60 and "more slowly" in plan["resting"]

    # And it really scans, instead of the old "US market is closed." skip.
    guard.save_settings({"watchlist": ["AAPL"]})
    monkeypatch.setattr("trading.signals.signal_for", lambda symbol, record=True: {
        "symbol": symbol, "signal": "hold", "confidence": 0.5, "score": 0.0, "reasons": [], "indicators": {"price": 200.0}})
    summary = autopilot.run_once()
    assert summary["skipped"] is None and summary["actions"][0]["symbol"] == "AAPL"


def test_until_mode_stops_itself_when_the_time_passes():
    autopilot.set_run_mode("until", time.time() + 3600)
    assert guard.settings()["ai"]["run_mode"] == "until"
    assert autopilot._plan_next(guard.settings())["scan"] is True

    guard.save_settings({"ai": {"run_until": time.time() - 1}})
    plan = autopilot._plan_next(guard.settings())
    assert plan.get("finished") is True

    autopilot.stop("time passed")
    assert guard.settings()["ai"]["enabled"] is False
    assert autopilot.run_status()["summary"] == "time passed"


def test_a_run_mode_needs_a_real_choice_and_a_future_time():
    with pytest.raises(BrokerError):
        autopilot.set_run_mode("whenever")
    with pytest.raises(BrokerError):
        autopilot.set_run_mode("until", time.time() - 60)


def test_the_mode_survives_a_restart(monkeypatch):
    autopilot.set_run_mode("always")
    autopilot._THREAD = None  # as if the engine had just started again
    open_market(monkeypatch, False)
    assert autopilot.ensure_running() is True
    assert autopilot.run_mode() == "always"


# --- practice money -----------------------------------------------------------------


def test_practice_and_real_money_are_never_ambiguous():
    paper = brokers.get("paper")
    assert paper.money() == "practice" and "no real money" in paper.label.lower()
    assert paper.account()["money"] == "practice"
    assert brokers.get("snaptrade").money() == "real"  # an aggregator reaches the owner's own account


def test_fills_cross_the_spread_and_pay_the_commission(monkeypatch):
    open_market(monkeypatch, True)
    brokers.save_paper_settings({"realistic_fills": True, "spread_bps": 4, "slippage_bps": 3, "commission": 1})
    paper = brokers.get("paper")

    buy = paper.place(OrderRequest(symbol="AAPL", side="buy", qty=10))
    assert buy["status"] == "filled"
    assert buy["filled_price"] > 200.0, "a market buy pays a little more than the quote"
    assert buy["fee"] == 1 and buy["slippage"] > 0
    sell = paper.place(OrderRequest(symbol="AAPL", side="sell", qty=10))
    assert sell["filled_price"] < 200.0, "a market sell receives a little less"
    # The round trip costs the spread and both commissions instead of being free.
    assert sell["realized_pl"] < 0
    assert paper.account()["equity"] < 100_000


def test_an_order_given_while_the_market_is_shut_waits_for_the_opening_bell(monkeypatch):
    open_market(monkeypatch, False)
    paper = brokers.get("paper")
    order = paper.place(OrderRequest(symbol="AAPL", side="buy", qty=5))
    assert order["status"] == "queued" and "opening bell" in order["note"]
    assert paper.positions() == [], "nothing may fill on an overnight price"

    open_market(monkeypatch, True)
    assert paper.orders()[0]["status"] == "filled"
    assert paper.positions()[0]["symbol"] == "AAPL"


def test_queueing_can_be_switched_off_for_practice(monkeypatch):
    open_market(monkeypatch, False)
    brokers.save_paper_settings({"queue_when_closed": False})
    assert brokers.get("paper").place(OrderRequest(symbol="AAPL", side="buy", qty=1))["status"] == "filled"


def test_the_practice_record_is_kept_honestly(monkeypatch):
    open_market(monkeypatch, True)
    monkeypatch.setattr(market, "history", lambda symbol, range_="6mo": [{"date": "2020-01-01", "close": 100.0, "volume": 1},
                                                                         {"date": "2030-01-01", "close": 110.0, "volume": 1}])
    paper = brokers.get("paper")
    paper.reset(50)  # the owner may want to practise with a small, real-feeling amount
    assert paper.account()["equity"] == 50
    assert brokers.paper_settings()["starting_cash"] == 50

    paper.place(OrderRequest(symbol="AAPL", side="buy", notional=20))
    paper.place(OrderRequest(symbol="AAPL", side="sell", qty=0.05))
    stats = paper.stats()
    assert stats["start_equity"] == 50 and stats["trades"] == 2 and stats["closed"] == 1
    assert stats["win_rate"] is not None and stats["history"]
    assert stats["benchmark"]["symbol"] == "SPY" and stats["benchmark"]["change_pct"] == 10.0


# --- only a real engine resumes the owner's trader -----------------------------------------


def test_importing_the_routes_never_starts_the_owners_trader(monkeypatch):
    import importlib

    import routes_trading

    started = []
    monkeypatch.setattr(autopilot, "ensure_running", lambda: started.append(1) or True)
    importlib.reload(routes_trading)
    assert started == [], "importing the server must not resume the real AI trader"

    monkeypatch.setenv("NYX_NO_BACKGROUND", "1")
    routes_trading._start_schedule()
    assert started == [], "a look-only engine leaves the trader alone"

    monkeypatch.delenv("NYX_NO_BACKGROUND")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    routes_trading._start_schedule()
    assert started == [1], "a real engine start resumes it"


def test_the_engine_resumes_the_trader_at_startup():
    import server

    names = {getattr(h, "__module__", "") + "." + getattr(h, "__name__", "") for h in server.app.router.on_startup}
    assert "routes_trading._start_schedule" in names
