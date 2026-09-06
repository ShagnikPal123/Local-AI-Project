"""Resource governor (ROADMAP EE1-EE9).

Two properties matter more than the rest: the safety floor cannot be overridden
by a setting, and the ceiling is actually enforced rather than merely displayed.
"""

from unittest.mock import MagicMock, patch

import pytest

from resource_governor import PowerMode, ResourceGovernor


@pytest.fixture
def governor():
    return ResourceGovernor()


def _profile(max_workers=8, power_mode="balanced"):
    profile = MagicMock()
    profile.max_workers = max_workers
    profile.recommended_power_mode = power_mode
    return profile


# --- modes scale the machine -------------------------------------------------------

@pytest.mark.parametrize("mode,expected", [
    (PowerMode.LOW, 2),
    (PowerMode.MEDIUM, 4),
    (PowerMode.HIGH, 6),
    (PowerMode.MAX, 8),
])
def test_modes_claim_increasing_shares(governor, mode, expected):
    with patch("device_profile.get_device_profile", return_value=_profile(8)):
        assert governor.set_mode(mode).max_workers == expected


def test_low_still_leaves_a_usable_system(governor):
    """Never zero: the product must still function at the lowest setting."""
    with patch("device_profile.get_device_profile", return_value=_profile(1)):
        assert governor.set_mode(PowerMode.LOW).max_workers >= 1


# --- the safety floor wins ----------------------------------------------------------

def test_throttling_overrides_the_selected_mode(governor):
    """A setting must not be able to push a struggling machine harder."""
    with patch("device_profile.get_device_profile", return_value=_profile(8)):
        governor.set_mode(PowerMode.MAX)
        with patch("hardware_safety.SAFETY_MONITOR.get_hardware_status") as status:
            status.return_value = MagicMock(throttle_recommended=True)
            ceiling = governor.ceiling()
    assert ceiling.max_workers < 8
    assert "throttl" in ceiling.capped_reason.lower()


def test_a_capped_ceiling_explains_itself(governor):
    """The user must be told why they did not get what they selected."""
    with patch("device_profile.get_device_profile", return_value=_profile(8)):
        governor.set_mode(PowerMode.MAX)
        with patch("hardware_safety.SAFETY_MONITOR.get_hardware_status") as status:
            status.return_value = MagicMock(throttle_recommended=True)
            assert governor.ceiling().capped_reason.strip()


def test_max_is_refused_as_unsustainable_on_a_weak_machine(governor):
    with patch("device_profile.get_device_profile", return_value=_profile(2)):
        sustainable, note = governor.can_sustain(PowerMode.MAX)
    assert sustainable is False
    assert note.strip()


def test_local_models_are_disabled_on_a_tiny_device(governor):
    with patch("device_profile.get_device_profile", return_value=_profile(1)), \
         patch("device_profile.select_tier", return_value=MagicMock(name_="tiny")) as tier:
        tier.return_value.name = "tiny"
        ceiling = governor.set_mode(PowerMode.HIGH)
    assert ceiling.allow_local_models is False
    assert "local models" in ceiling.capped_reason.lower()


# --- automatic modes -----------------------------------------------------------------

def test_auto_picks_high_on_a_capable_machine(governor):
    with patch("device_profile.get_device_profile", return_value=_profile(12)):
        assert governor.set_mode(PowerMode.AUTO).mode is PowerMode.HIGH


def test_auto_picks_low_on_a_weak_machine(governor):
    with patch("device_profile.get_device_profile", return_value=_profile(2)):
        assert governor.set_mode(PowerMode.AUTO).mode is PowerMode.LOW


def test_auto_task_spends_less_on_a_simple_turn(governor):
    with patch("device_profile.get_device_profile", return_value=_profile(12)):
        governor.set_mode(PowerMode.AUTO_TASK)
        simple = governor.ceiling("simple")
        complex_ = governor.ceiling("complex")
    assert simple.max_workers < complex_.max_workers


# --- never crash the caller -----------------------------------------------------------

def test_an_unreadable_machine_is_treated_as_weak(governor):
    """Unknown hardware must fail conservative, not optimistic."""
    with patch("device_profile.get_device_profile", side_effect=RuntimeError("no probe")):
        ceiling = governor.set_mode(PowerMode.MAX)
    assert ceiling.max_workers == 1


def test_a_broken_safety_monitor_does_not_raise(governor):
    with patch("hardware_safety.SAFETY_MONITOR.get_hardware_status",
               side_effect=RuntimeError("sensor gone")):
        assert governor.ceiling().max_workers >= 1


def test_describe_modes_lists_every_mode(governor):
    ids = {m["id"] for m in governor.describe_modes()["modes"]}
    assert ids == {"low", "medium", "high", "max", "auto", "auto_task"}


def test_auto_is_marked_recommended(governor):
    modes = governor.describe_modes()["modes"]
    recommended = [m["id"] for m in modes if m["recommended"]]
    assert recommended == ["auto"]


# --- enforcement, not decoration -------------------------------------------------------

def test_the_pool_respects_the_governor_ceiling():
    """Choosing Low must actually stop the agent pool from growing."""
    from agent_pool import AgentPool

    with patch("agent_pool.ChatService"):
        pool = AgentPool(initial_size=1, max_agents=10)

    with patch("resource_governor.GOVERNOR.ceiling") as ceiling:
        ceiling.return_value = MagicMock(max_agents=2)
        assert pool._effective_max_agents() == 2


def test_the_pool_keeps_working_if_the_governor_is_unavailable():
    """A governor that breaks the product by being absent is worse than none.

    Falls back to the pool's own limit, which the constructor has already clamped
    to what the hardware can take — so the safety floor still applies.
    """
    from agent_pool import AgentPool

    with patch("agent_pool.ChatService"):
        pool = AgentPool(initial_size=1, max_agents=10)

    with patch("resource_governor.GOVERNOR.ceiling", side_effect=RuntimeError("gone")):
        assert pool._effective_max_agents() == pool.max_agents
