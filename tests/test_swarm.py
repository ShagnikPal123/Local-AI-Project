"""Swarm (Update 1, U5): many agents on one job, never more than the PC can carry.

The slider's promise is the thing to test: whatever the owner asks for, the swarm is clamped to the machine's
ceiling, at most the Power budget work at once, and a swarm-sized dispatch really can hold more boxes than an
ordinary one — while an ordinary dispatch keeps its old limits.
"""

from __future__ import annotations

import threading
import time
import types

import pytest

import agent_dispatch as ad
import swarm


def _machine(monkeypatch, workers: int, ram: float = 32, vram: float = 16):
    import device_profile

    profile = types.SimpleNamespace(max_workers=workers, ram_gb=ram, vram_gb=vram)
    monkeypatch.setattr(device_profile, "get_device_profile", lambda force_refresh=False: profile)


def test_the_ceiling_follows_the_hardware_and_never_passes_the_hard_max(monkeypatch):
    _machine(monkeypatch, workers=1, ram=8, vram=0)
    small, why = swarm.ceiling()
    assert small == swarm.MIN_SIZE * 2 and "8 GB RAM" in why
    _machine(monkeypatch, workers=8)
    assert swarm.ceiling()[0] == 32
    _machine(monkeypatch, workers=50)
    assert swarm.ceiling()[0] == swarm.HARD_MAX


def test_the_slider_is_remembered_and_clamped_to_the_machine(monkeypatch):
    _machine(monkeypatch, workers=4)          # ceiling 16
    assert swarm.settings()["size"] == 8, "the default is a sensible eight"
    assert swarm.save(12)["size"] == 12
    assert swarm.limit() == 12
    assert swarm.save(500)["size"] == 16, "the slider cannot promise more than the PC can carry"
    assert swarm.save(0)["size"] == swarm.MIN_SIZE
    with pytest.raises(ValueError):
        swarm.save("lots")
    swarm.save(16)
    _machine(monkeypatch, workers=1, ram=8, vram=0)   # the same file read on a smaller machine
    assert swarm.limit() == 4


def test_how_many_work_at_once_is_the_power_budget_never_more_than_the_swarm(monkeypatch):
    import resource_governor

    budget = types.SimpleNamespace(max_agents=6)
    monkeypatch.setattr(resource_governor.GOVERNOR, "ceiling", lambda task_complexity=None: budget)
    assert swarm.parallel(20) == 6
    assert swarm.parallel(3) == 3
    view = swarm.describe()
    assert view["parallel"] <= view["size"] <= view["ceiling"]
    assert "at a time" in view["summary"] or "all at once" in view["summary"]


# --- the dispatch a swarm uses -------------------------------------------------------------


ROSTER = [{"name": "Manager", "role": "master"}, {"name": "Coder", "emoji": "", "role": "worker"}]


@pytest.fixture
def roster(monkeypatch):
    import agent_runtime

    by_name = {a["name"].lower(): a for a in ROSTER}
    monkeypatch.setattr(agent_runtime, "load_roster", lambda: [dict(a) for a in ROSTER])
    monkeypatch.setattr(agent_runtime, "roster_entry_exact", lambda n: by_name.get((n or "").strip().lower()))
    monkeypatch.setattr(agent_runtime, "roster_entry", lambda n: by_name.get((n or "").strip().lower()))


def test_an_ordinary_dispatch_keeps_its_limits_and_a_swarm_holds_more(roster):
    registry = ad.DispatchRegistry(runner=lambda agent, task, context: f"did {task}", threaded=False,
                                   poster=lambda chat, text: None)
    twenty = [{"agent": "Coder", "task": f"fix bug {n}"} for n in range(20)]
    with pytest.raises(ad.DispatchError):
        registry.start(twenty)
    with pytest.raises(ad.DispatchError):
        registry.start(twenty[:9])  # nine copies of one agent is still too many outside a swarm

    view = registry.start(twenty, max_instances=20, parallel=4)
    assert view["swarm"] is True and view["parallel"] == 4
    assert view["counts"]["done"] == 20
    assert view["instances"][19]["label"] == "Coder #20"

    # The slider is a limit both ways: a swarm of 4 holds 4, even though an ordinary dispatch could hold 12.
    with pytest.raises(ad.DispatchError):
        registry.start(twenty[:5], max_instances=4)


def test_a_swarm_runs_no_more_than_its_parallel_budget_at_once(roster):
    lock = threading.Lock()
    running = {"now": 0, "most": 0}

    def runner(agent, task, context):
        with lock:
            running["now"] += 1
            running["most"] = max(running["most"], running["now"])
        time.sleep(0.05)
        with lock:
            running["now"] -= 1
        return "ok"

    registry = ad.DispatchRegistry(runner=runner, poster=lambda chat, text: None)
    registry.start([{"agent": "Coder", "task": f"part {n}"} for n in range(10)], max_instances=10, parallel=3,
                   wait=True)
    assert running["most"] <= 3


def test_the_dispatch_tool_uses_the_swarm_size_only_in_a_swarm_turn(roster, monkeypatch):
    from tool_context import ToolContext, use_context

    monkeypatch.setattr(swarm, "parallel", lambda size=0: 2)
    seen = {}

    def fake_start(items, **kwargs):
        seen["items"], seen["kwargs"] = items, kwargs
        return {"dispatch_id": "x", "instances": []}

    monkeypatch.setattr(ad.DISPATCHES, "start", fake_start)
    monkeypatch.setattr(ad.DISPATCHES, "get", lambda _id: {"instances": []})

    with use_context(ToolContext(swarm=16)):
        ad.tool_dispatch_agents(agent="Coder", count=14, task="fix one small error each")
    assert len(seen["items"]) == 14 and seen["kwargs"]["max_instances"] == 16 and seen["kwargs"]["parallel"] == 2

    with use_context(ToolContext()):
        ad.tool_dispatch_agents(agent="Coder", count=14, task="fix one small error each")
    assert len(seen["items"]) == ad.MAX_PER_AGENT and "max_instances" not in seen["kwargs"]


def test_a_16_gb_laptop_that_reports_15_8_gb_gets_the_16_gb_worker_count():
    """The owner's laptop: 32 GB installed, 15.79 GB visible to Windows (the integrated GPU keeps the rest)."""
    from device_profile import DeviceProfile, select_tier

    laptop = DeviceProfile("Windows", "Ryzen AI 9", 24, ram_gb=15.79, gpu_name="RTX 5080 Laptop", vram_gb=15.92)
    assert laptop.max_workers == 4
    assert select_tier(laptop).name == "medium", "the model tier stays strict: the next one up is a 35B model"
    assert DeviceProfile("Windows", "x", 8, ram_gb=14.0, gpu_name=None, vram_gb=0).max_workers == 2
