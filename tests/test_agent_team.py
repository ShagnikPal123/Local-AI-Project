"""Named agent team with master/worker hierarchy (ROADMAP B1-B6, Z3)."""

from unittest.mock import patch

import pytest

from agent_team import AgentRole, AgentStatus, AgentTeam


@pytest.fixture
def team():
    return AgentTeam()


# --- the hierarchy invariant ------------------------------------------------------

def test_a_team_defaults_to_having_a_master(team):
    """A manager should exist without the user having to ask for one."""
    master = team.ensure_master()
    assert master.role is AgentRole.MASTER
    assert team.snapshot()["total"] == 1


def test_ensure_master_is_idempotent(team):
    first = team.ensure_master()
    second = team.ensure_master()
    assert first.agent_id == second.agent_id


def test_only_one_master_exists_at_a_time(team):
    team.spawn("first", "lead the work", role=AgentRole.MASTER)
    team.spawn("second", "lead instead", role=AgentRole.MASTER)
    masters = [a for a in team.snapshot()["agents"] if a["role"] == "master"]
    assert len(masters) == 1
    assert masters[0]["name"] == "second"


def test_a_real_master_replaces_an_auto_created_placeholder(team):
    """The placeholder must not linger as a confusing extra worker."""
    team.ensure_master()
    team.spawn("lead", "manage the others", role=AgentRole.MASTER)
    snapshot = team.snapshot()
    assert snapshot["total"] == 1
    assert snapshot["agents"][0]["name"] == "lead"


def test_a_user_created_master_is_demoted_not_deleted(team):
    """Deleting a user's agent would silently discard their work."""
    team.spawn("original", "manage things", role=AgentRole.MASTER)
    team.spawn("replacement", "manage things better", role=AgentRole.MASTER)
    names = {a["name"] for a in team.snapshot()["agents"]}
    assert names == {"original", "replacement"}


def test_the_master_cannot_be_dismissed_while_workers_remain(team):
    master = team.ensure_master()
    team.spawn("worker", "do the thing")
    assert team.dismiss(master.agent_id) is False


def test_the_master_can_be_dismissed_once_alone(team):
    master = team.ensure_master()
    assert team.dismiss(master.agent_id) is True


def test_dismissing_an_unknown_agent_reports_failure(team):
    assert team.dismiss("nope") is False


# --- the exact request: three agents, one managing ---------------------------------

def test_three_agents_two_goals_one_manager(team):
    team.spawn("research", "find current sources")
    team.spawn("builder", "implement and test the change")
    team.spawn("lead", "manage the other two", role=AgentRole.MASTER)

    snapshot = team.snapshot()
    assert snapshot["total"] == 3
    assert snapshot["agents"][0]["role"] == "master"   # master sorts first
    assert snapshot["agents"][0]["name"] == "lead"


def test_agents_can_carry_individual_personalities(team):
    agent = team.spawn("gremlin", "be casual", personality_id="gen_z")
    assert agent.snapshot()["personality_id"] == "gen_z"


# --- progress reporting ------------------------------------------------------------

def test_progress_moves_through_the_lifecycle(team):
    agent = team.spawn("worker", "do the thing")
    assert agent.status is AgentStatus.IDLE

    team.begin(agent.agent_id, "reading files")
    assert team.get(agent.agent_id).status is AgentStatus.WORKING
    assert team.get(agent.agent_id).current_step == "reading files"

    team.finish_step(agent.agent_id)
    done = team.get(agent.agent_id)
    assert done.status is AgentStatus.IDLE
    assert done.steps_completed == 1


def test_a_blocked_agent_says_why(team):
    agent = team.spawn("worker", "do the thing")
    team.block(agent.agent_id, "waiting on the researcher")
    snapshot = team.get(agent.agent_id).snapshot()
    assert snapshot["status"] == "blocked"
    assert "researcher" in snapshot["current_step"]


def test_a_failed_agent_keeps_its_error(team):
    agent = team.spawn("worker", "do the thing")
    team.fail(agent.agent_id, "provider unavailable")
    snapshot = team.get(agent.agent_id).snapshot()
    assert snapshot["status"] == "error"
    assert snapshot["last_error"] == "provider unavailable"


def test_progress_calls_on_unknown_agents_do_not_raise(team):
    """Worker threads report against ids that may already be dismissed."""
    team.begin("gone", "x")
    team.finish_step("gone")
    team.block("gone", "x")
    team.fail("gone", "x")


# --- the two diagnoses the panel exists for ----------------------------------------

def test_a_vague_goal_is_flagged(team):
    """A stalled team must be distinguishable from an idle one."""
    team.spawn("worker", "stuff")
    assert "worker" in team.snapshot()["vague_goals"]


def test_a_real_goal_is_not_flagged(team):
    team.spawn("worker", "implement the recency ranking fix")
    assert team.snapshot()["vague_goals"] == []


def test_the_master_is_not_judged_for_a_short_goal(team):
    team.ensure_master()
    assert team.snapshot()["vague_goals"] == []


def test_resource_pressure_is_reported(team):
    pressure = team.snapshot()["resource_pressure"]
    assert "throttled" in pressure
    assert "telemetry_available" in pressure


def test_resource_pressure_survives_a_broken_monitor(team):
    """A diagnostic that crashes the panel is worse than no diagnostic."""
    with patch("hardware_safety.SAFETY_MONITOR.get_hardware_status",
               side_effect=RuntimeError("sensor exploded")):
        pressure = team.snapshot()["resource_pressure"]
    assert pressure["throttled"] is False
    assert pressure["telemetry_available"] is False


def test_counts_reflect_agent_states(team):
    a = team.spawn("a", "do a real thing here")
    b = team.spawn("b", "do another real thing")
    team.begin(a.agent_id, "working")
    team.fail(b.agent_id, "broke")
    snapshot = team.snapshot()
    assert snapshot["working"] == 1
    assert snapshot["errored"] == 1
