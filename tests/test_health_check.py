"""Post-change health verification (ROADMAP F3, F5).

This is the half of self-revival that was missing: something has to notice the
app is broken before restoring a checkpoint is any use.
"""

from unittest.mock import patch

import pytest

from health_check import DEFAULT_CHECKS, run_health_check


def _ok() -> str:
    return "fine"


def _boom() -> str:
    raise RuntimeError("everything is on fire")


class _UnusualError(Exception):
    """A check can raise anything; the runner must survive all of it."""


def _explodes_with_a_weird_error() -> str:
    raise _UnusualError("something nobody anticipated")


def _returns_nonsense() -> str:
    return None  # type: ignore[return-value]


# --- the basics ---------------------------------------------------------------------

def test_a_healthy_system_reports_healthy():
    result = run_health_check([("a", _ok), ("b", _ok)])
    assert result["healthy"] is True
    assert result["failed"] == []


def test_one_failing_check_makes_the_system_unhealthy():
    result = run_health_check([("a", _ok), ("b", _boom)])
    assert result["healthy"] is False
    assert result["failed"] == ["b"]


def test_a_failure_keeps_the_reason():
    result = run_health_check([("b", _boom)])
    detail = result["results"][0]["detail"]
    assert "RuntimeError" in detail
    assert "on fire" in detail


def test_every_check_runs_even_after_one_fails():
    """Stopping at the first failure would hide the rest of the damage."""
    result = run_health_check([("a", _boom), ("b", _boom), ("c", _ok)])
    assert len(result["results"]) == 3
    assert result["failed"] == ["a", "b"]


# --- a check that raises must not become the bug -------------------------------------

def test_the_checker_survives_an_unanticipated_exception():
    """Learned from the safety monitor: a check that raises has become the hazard."""
    result = run_health_check([("weird", _explodes_with_a_weird_error)])
    assert result["healthy"] is False
    assert "_UnusualError" in result["results"][0]["detail"]


def test_an_interrupt_is_deliberately_not_swallowed():
    """KeyboardInterrupt and SystemExit must still stop the process.

    The runner catches `Exception`, not `BaseException`, on purpose — swallowing
    a Ctrl-C so a health check could finish would itself be a bug.
    """
    def interrupt() -> str:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_health_check([("interrupt", interrupt)])


def test_a_check_returning_nothing_still_counts_as_passing():
    """Checks signal failure by raising; a quiet return is success."""
    assert run_health_check([("quiet", _returns_nonsense)])["healthy"] is True


def test_timings_are_reported():
    result = run_health_check([("a", _ok)])
    assert result["results"][0]["duration_ms"] >= 0
    assert "total_ms" in result


# --- the real checks ------------------------------------------------------------------

def test_the_real_system_is_healthy():
    result = run_health_check()
    assert result["healthy"] is True, result["failed"]


def test_the_real_check_is_fast_enough_for_the_request_path():
    """Anything slow here gets removed, and then there is no verification at all."""
    result = run_health_check()
    assert result["total_ms"] < 2000


def test_a_broken_overlay_is_detected():
    with patch("overlay.OVERLAY.list_entries", side_effect=RuntimeError("disk gone")):
        result = run_health_check()
    assert result["healthy"] is False
    assert "overlay" in result["failed"]


def test_a_broken_auth_store_is_detected():
    """Auth breaking locks everyone out — it must fail the check."""
    with patch("server_auth.AUTH_STORE.resolve_session", side_effect=RuntimeError("gone")):
        result = run_health_check()
    assert result["healthy"] is False
    assert "auth" in result["failed"]


def test_a_broken_safety_monitor_is_detected():
    with patch("hardware_safety.SAFETY_MONITOR.get_hardware_status",
               side_effect=RuntimeError("sensor dead")):
        result = run_health_check()
    assert result["healthy"] is False
    assert "hardware_safety" in result["failed"]


def test_every_default_check_has_a_name_and_is_callable():
    assert DEFAULT_CHECKS
    for name, check in DEFAULT_CHECKS:
        assert name and callable(check)
