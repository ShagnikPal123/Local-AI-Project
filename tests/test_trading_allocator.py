"""Diversification/sizing (allocator.py) and reliability-ranked scanning (signals.rank_watchlist).

Covers the owner's ask directly: a $50 account must not go all-in on the first buy signal, a
symbol the AI has been wrong about before should get sized down, and a position should be able to
sell on a stop-loss or take-profit even when the raw indicator hasn't flipped to "sell".
"""

from __future__ import annotations

import pytest

from trading import allocator, market, signals, store


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "folder", lambda: tmp_path)


def base_ai(**overrides):
    ai = {"max_per_trade": 500.0, "max_invested": 50.0, "max_position_pct": 0.3, "target_positions": 5,
          "min_confidence": 0.6, "stop_loss_pct": 8.0, "take_profit_pct": 20.0}
    ai.update(overrides)
    return ai


def signal(symbol, score=0.6, confidence=0.75, kind="buy", multiplier=1.0, graded=0, hit_rate=None):
    return {"symbol": symbol, "signal": kind, "score": score, "confidence": confidence, "reasons": ["Uptrend."],
            "reliability": {"symbol": symbol, "graded": graded, "hit_rate": hit_rate, "multiplier": multiplier},
            "expected_value": round(score * confidence * multiplier, 4)}


def test_position_cap_is_the_tighter_of_flat_limit_and_budget_share():
    ai = base_ai(max_per_trade=500.0, max_invested=50.0, max_position_pct=0.3)
    assert allocator.position_cap(ai) == 15.0  # 30% of $50, well under the $500 flat limit


def test_a_50_dollar_account_spreads_across_several_picks_not_one():
    ai = base_ai(max_invested=50.0, target_positions=5)
    ranked = [signal("AAA", score=0.9, confidence=0.9), signal("BBB", score=0.7, confidence=0.8),
              signal("CCC", score=0.6, confidence=0.7), signal("DDD", score=0.5, confidence=0.65)]
    plans = allocator.plan_buys(ai, ranked, owned={}, room=50.0)
    funded = [p for p in plans if p["notional"] > 0]
    assert len(funded) >= 3, "a small account should open several small positions, not one big one"
    assert all(p["notional"] <= allocator.position_cap(ai) + 0.01 for p in funded)
    assert sum(p["notional"] for p in funded) <= 50.0 + 0.01
    # the best-ranked pick should still get sized first / largest, not just first-in-list
    assert funded[0]["symbol"] == "AAA"


def test_diversification_target_stops_new_buys_once_reached():
    ai = base_ai(target_positions=2)
    ranked = [signal("CCC", score=0.8, confidence=0.8)]
    plans = allocator.plan_buys(ai, ranked, owned={"AAA": 1.0, "BBB": 1.0}, room=1000.0)
    assert plans[0]["notional"] == 0.0
    assert "diversification" in plans[0]["why"].lower()


def test_unreliable_symbol_gets_sized_down():
    ai = base_ai(max_invested=1000.0, target_positions=2)
    reliable = signal("GOOD", score=0.8, confidence=0.8, multiplier=1.3, graded=8, hit_rate=0.9)
    unreliable = signal("BAD", score=0.8, confidence=0.8, multiplier=0.4, graded=8, hit_rate=0.1)
    plans_good = allocator.plan_buys(ai, [reliable], owned={}, room=1000.0)
    plans_bad = allocator.plan_buys(ai, [unreliable], owned={}, room=1000.0)
    assert plans_bad[0]["notional"] < plans_good[0]["notional"]


def test_low_confidence_is_skipped_entirely():
    ai = base_ai(min_confidence=0.7)
    plans = allocator.plan_buys(ai, [signal("WEAK", confidence=0.5)], owned={}, room=100.0)
    assert plans == []


def test_stop_loss_fires_even_without_a_sell_signal():
    ai = base_ai()
    position = {"symbol": "AAA", "qty": 2.0, "pl_pct": -9.0}
    decision = allocator.review_position(ai, position, signal=None)
    assert decision and "stop loss" in decision["why"].lower()


def test_take_profit_fires_even_without_a_sell_signal():
    ai = base_ai()
    position = {"symbol": "AAA", "qty": 2.0, "pl_pct": 25.0}
    decision = allocator.review_position(ai, position, signal=None)
    assert decision and "take profit" in decision["why"].lower()


def test_holding_within_bounds_with_no_sell_signal_is_left_alone():
    ai = base_ai()
    position = {"symbol": "AAA", "qty": 2.0, "pl_pct": 3.0}
    assert allocator.review_position(ai, position, signal=signal("AAA", kind="hold")) is None


def test_should_rotate_needs_a_clear_edge():
    held = signal("OLD", score=0.1, confidence=0.6)  # expected_value 0.06
    barely_better = signal("NEW", score=0.15, confidence=0.6)  # 0.09, not a clear edge
    much_better = signal("NEW", score=0.9, confidence=0.9)  # 0.81
    assert allocator.should_rotate(held, barely_better) is False
    assert allocator.should_rotate(held, much_better) is True


def test_symbol_reliability_is_neutral_with_no_history():
    assert signals.symbol_reliability("AAPL") == {"symbol": "AAPL", "graded": 0, "hit_rate": None, "multiplier": 1.0}


def test_symbol_reliability_drops_after_a_string_of_wrong_calls():
    store.write("predictions", {"predictions": [
        {"symbol": "AAPL", "signal": "buy", "confidence": 0.7, "price": 100.0, "at": i, "horizon_days": 5,
         "outcome": {"return_pct": -1.0, "right": False, "graded_at": i}} for i in range(6)
    ]})
    reliability = signals.symbol_reliability("AAPL")
    assert reliability["graded"] == 6
    assert reliability["multiplier"] < 1.0


def test_rank_watchlist_sorts_by_expected_value_and_skips_errors(monkeypatch):
    fake = {"AAA": {"symbol": "AAA", "signal": "buy", "score": 0.3, "confidence": 0.6, "reasons": []},
            "BBB": {"symbol": "BBB", "signal": "buy", "score": 0.9, "confidence": 0.9, "reasons": []}}

    def fake_signal_for(symbol, record=False):
        if symbol == "CCC":
            raise market.MarketDataError("no data")
        return dict(fake[symbol])

    monkeypatch.setattr(signals, "signal_for", fake_signal_for)
    ranked = signals.rank_watchlist(["AAA", "BBB", "CCC"])
    assert [r["symbol"] for r in ranked if "error" not in r] == ["BBB", "AAA"]
    assert any(r.get("symbol") == "CCC" and "error" in r for r in ranked)
