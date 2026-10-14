"""The bot team: the skeptic, the traders, the manager, the strategist and the tuning dials."""

from __future__ import annotations

import pytest

from ichos_trader import config, settings, store
from ichos_trader.markets import SimulatedFeed
from ichos_trader.markets.hub import MarketHub
from ichos_trader.models import Order
from ichos_trader.team import Team, manager, skeptic, strategist, traders

NOW = 1_800_000_000.0


def row(symbol="BTC-USD", **over):
    base = {"symbol": symbol, "name": symbol, "asset_class": "crypto", "price": 100.0, "change_pct": 1.0,
            "score": 0.7, "signal": "buy", "confidence": 0.7, "opportunity": 0.6, "tradability": 0.8,
            "liquidity": 0.9, "dollar_volume": 5e8, "spread_bps": 2.0, "flow": 0.2, "open": True, "reasons": []}
    base.update(over)
    return base


def buy(symbol="BTC-USD"):
    return Order(symbol, "buy", 1.0, "crypto", "Vega")


# --- the mild skeptic -----------------------------------------------------------------------

def test_the_skeptic_never_blocks_a_sale():
    assert skeptic.review(Order("BTC-USD", "sell", 1, "crypto"), None, None, 1.0) == (1.0, "info", "")


def test_the_skeptic_stops_pumps_ghost_markets_and_stale_prices():
    assert skeptic.review(buy(), row(change_pct=45.0), None, 0.5, NOW, NOW)[1] == "veto"
    assert skeptic.review(buy(), row(liquidity=0.05), None, 0.5, NOW, NOW)[1] == "veto"
    assert skeptic.review(buy(), row(), None, 0.5, NOW - 900, NOW)[1] == "veto"
    assert skeptic.review(buy(), None, None, 0.5)[1] == "veto"


def test_the_skeptic_shrinks_doubtful_buys_and_strictness_moves_the_line():
    size, level, why = skeptic.review(buy(), row(spread_bps=40.0, flow=-0.6), None, 0.5, NOW, NOW)
    assert level == "warn" and size == pytest.approx(0.3) and "spread" in why and "sellers" in why
    assert skeptic.review(buy(), row(spread_bps=20.0), None, 0.0, NOW, NOW)[0] == 1.0  # easy-going
    assert skeptic.review(buy(), row(spread_bps=20.0), None, 1.0, NOW, NOW)[0] == 0.5  # strict


# --- traders ------------------------------------------------------------------------------

def test_a_trader_takes_its_stop_loss_and_buys_only_its_own_markets():
    team = Team()
    vega = next(t for t in team.traders() if t["name"] == "Vega")
    held = [{"symbol": "ETH-USD", "asset_class": "crypto", "qty": 2.0, "value": 180.0, "pl_pct": -6.0, "bot": "Vega"}]
    rows = {"ETH-USD": row("ETH-USD"), "SOL-USD": row("SOL-USD"), "AAPL": row("AAPL", asset_class="stock"),
            "THIN-USD": row("THIN-USD", tradability=0.1)}
    orders = traders.decide(vega, rows, {}, held, {"equity": 10_000.0}, config.default_settings(), {"ETH-USD"}, team)
    sells = [o for o in orders if o.side == "sell"]
    buys = [o.symbol for o in orders if o.side == "buy"]
    assert [o.symbol for o in sells] == ["ETH-USD"] and "stop-loss" in sells[0].reason
    assert buys == ["SOL-USD"]


def test_the_rotator_swaps_its_weakest_coin_for_a_clearly_better_one():
    team = Team()
    orion = next(t for t in team.traders() if t["style"] == "rotate")
    held = [{"symbol": s, "asset_class": "crypto", "qty": 1.0, "value": 100.0, "pl_pct": 1.0, "bot": "Orion"}
            for s in ("ETH-USD", "LTC-USD")]
    rows = {"ETH-USD": row("ETH-USD", score=0.7, signal="hold"), "LTC-USD": row("LTC-USD", score=0.4, signal="hold"),
            "SOL-USD": row("SOL-USD", score=0.9)}
    orders = traders.decide(orion, rows, {}, held, {"equity": 10_000.0}, config.default_settings(),
                            {"ETH-USD", "LTC-USD"}, team)
    assert [(o.side, o.symbol) for o in orders] == [("sell", "LTC-USD"), ("buy", "SOL-USD")]


# --- the manager --------------------------------------------------------------------------

def _fills(bot, results):
    return [{"bot": bot, "realized": r} for r in results]


def test_the_manager_moves_money_to_the_winner():
    team = Team()
    before = {t["name"]: t["share"] for t in team.traders()}
    fills = _fills("Vega", [300.0, 200.0]) + _fills("Nova", [-150.0])
    manager.review(team, fills, [], {"equity": 10_000.0, "peak": 10_000.0}, {}, config.default_settings())
    after = {t["name"]: t["share"] for t in team.traders()}
    assert after["Vega"] == pytest.approx(before["Vega"] + 0.05)
    assert after["Nova"] == pytest.approx(before["Nova"] - 0.05)
    assert "Moved 5%" in team.notes.latest(1)[0]["text"]


def test_the_manager_retires_a_loser_and_sells_what_it_held():
    team = Team()
    fills = _fills("Nova", [-10.0] * 6) + _fills("Vega", [5.0])
    held = [{"symbol": "AAPL", "asset_class": "stock", "qty": 3.0, "pl": -2.0, "bot": "Nova"}]
    orders, _ = manager.review(team, fills, held, {"equity": 10_000.0, "peak": 10_000.0}, {}, config.default_settings())
    assert "Nova" not in [t["name"] for t in team.traders()]
    assert [(o.side, o.symbol, o.qty) for o in orders] == [("sell", "AAPL", 3.0)]
    assert sum(t["share"] for t in team.traders()) == pytest.approx(1.0, abs=0.001)


def test_the_manager_hires_for_a_market_nobody_covers():
    team = Team()
    cfg = {**config.default_settings(), "markets": {"crypto": True, "stocks": True, "fx": True}}
    rows = {f"EURUSD{i}": row(f"EURUSD{i}", asset_class="fx", score=0.7) for i in range(3)}
    manager.review(team, [], [], {"equity": 10_000.0, "peak": 10_000.0}, rows, cfg)
    hired = [t for t in team.traders() if t["classes"] == ["fx"]]
    assert len(hired) == 1 and team.roster["hires"][-1]["name"] == hired[0]["name"]


def test_auto_mode_leans_careful_after_a_drawdown_unless_risk_is_pinned():
    cfg = config.default_settings()
    chosen = manager.choose_settings({"equity": 9_000.0, "peak": 10_000.0}, {}, cfg)
    assert chosen["risk"]["value"] < 0.5 and chosen["risk"]["why"].startswith("Leaning careful")
    assert manager.choose_settings({"equity": 9_000.0, "peak": 10_000.0}, {}, {**cfg, "pins": {"risk": 0.7}}) == {}


# --- learn first --------------------------------------------------------------------------

def test_the_strategist_learns_a_few_markets_a_cycle_until_the_playbook_is_full():
    hub = MarketHub(feeds={"crypto": SimulatedFeed(lambda: NOW)}, clock=lambda: NOW)
    snaps = hub.snapshots(hub.instruments(["crypto"])[:30], with_book=False)
    team = Team()
    cycles = 0
    while not strategist.learning_status()["done"]:
        assert strategist.study(snaps, team, NOW) == strategist.PER_CYCLE
        cycles += 1
    assert cycles == strategist.LEARN_TARGET // strategist.PER_CYCLE
    status = strategist.learning_status()
    assert status["studied"] == strategist.LEARN_TARGET and status["best"]
    assert strategist.study(snaps, team, NOW + 60) == strategist.PER_CYCLE  # the 6 not yet studied
    assert strategist.study(snaps, team, NOW + 120) == 0  # all fresh now


# --- the tuning dials ---------------------------------------------------------------------

def test_a_dial_set_by_hand_is_pinned_until_handed_back_to_auto():
    store.write("chosen", {"risk": {"value": 0.3, "why": "test"}})
    assert settings.effective()["risk"] == 0.3
    settings.save({"risk": 0.9})
    assert settings.effective()["risk"] == 0.9 and settings.load()["pins"] == {"risk": 0.9}
    settings.save({}, unpin=["risk"])
    assert settings.effective()["risk"] == 0.3


def test_dials_are_clamped_and_junk_is_ignored():
    saved = settings.save({"stop_loss_pct": 900, "max_positions": 3.6, "theme": {"accent": "red;"}, "broker": "live",
                           "markets": {"fx": 1, "moon": True}, "shutdown": {"slow_cycles": 0}})
    assert saved["stop_loss_pct"] == 50.0 and saved["max_positions"] == 4
    assert saved["theme"]["accent"] == "#7c6cff" and saved["broker"] == "sim"
    assert saved["markets"]["fx"] is True and "moon" not in saved["markets"]
    assert saved["shutdown"]["slow_cycles"] == 1
    with pytest.raises(ValueError):
        settings.save({"risk": "lots"})
