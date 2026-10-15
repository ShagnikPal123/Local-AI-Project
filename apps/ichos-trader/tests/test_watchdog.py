"""The watchdog stops a trader that is slow or losing, and pauses one whose prices are old."""

from __future__ import annotations

from ichos_trader import config, watchdog

RULES = config.default_settings()["shutdown"]


def _check(**over):
    args = dict(recent_cycle_ms=[800.0] * 10, equity=10_000.0, peak=10_000.0, run_start_equity=10_000.0,
                run_hours=1.0, rules=RULES)
    args.update(over)
    return watchdog.check(**args)


def test_a_healthy_run_carries_on():
    assert _check() == ""


def test_five_slow_cycles_in_a_row_shut_it_down_but_four_do_not():
    assert "cycles each took over 5 s" in _check(recent_cycle_ms=[900.0] + [6_000.0] * 5)
    assert _check(recent_cycle_ms=[6_000.0] * 4 + [900.0]) == ""


def test_falling_past_the_drawdown_limit_shuts_it_down():
    assert "fell 12.0%" in _check(equity=8_800.0, peak=10_000.0)
    assert _check(equity=9_200.0, peak=10_000.0, run_start_equity=9_000.0) == ""


def test_a_full_day_below_the_start_means_it_is_not_making_money():
    assert "not making money" in _check(equity=9_950.0, run_hours=25.0)
    assert _check(equity=9_950.0, run_hours=3.0) == ""


def test_old_prices_pause_rather_than_stop():
    assert watchdog.stale([400.0, 900.0], RULES).startswith("Paused")
    assert watchdog.stale([5.0, 900.0], RULES) == ""
    assert watchdog.stale([], RULES) == ""
