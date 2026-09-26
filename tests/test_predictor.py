"""Predictions (next tab, usual hours) and quiet work while the owner is away — all with stubs."""

from __future__ import annotations

import time

import pytest

import predictor


class Clock:
    def __init__(self, hour=14):
        base = time.mktime((2026, 9, 14, hour, 0, 0, 0, 0, -1))
        self.now = base

    def __call__(self):
        return self.now


@pytest.fixture()
def world(tmp_path):
    clock = Clock()
    p = predictor.Predictor(tmp_path / "predictions.json", clock=clock)
    return p, clock


def test_next_tab_learns_the_owners_habits(world):
    p, clock = world
    for _ in range(3):
        for tab in ("nyx", "learn", "improve"):
            p.observe_tab(tab)
            clock.now += 60
    p.observe_tab("nyx")
    guess = p.next_tab()
    assert guess["tab"] == "learn" and guess["evidence"] >= 2
    assert p.next_tab("learn")["tab"] == "improve"


def test_no_guess_without_evidence(world):
    p, _ = world
    p.observe_tab("nyx")
    p.observe_tab("keys")
    assert p.next_tab("nyx") is None  # one visit is not a habit


def test_usual_hours_and_quiet_time(world):
    p, clock = world
    for _ in range(60):
        p.observe_activity()  # all at 14:00
    info = p.usual_hours()
    assert info["busiest_hour"] == 14 and 3 in info["quiet_hours"] and 14 not in info["quiet_hours"]
    assert not p.is_quiet_now()
    clock.now += 13 * 3600  # 03:00
    assert p.is_quiet_now()


def test_settings_are_validated(world):
    p, _ = world
    s = p.update_settings(idle_tabs=True, auto_updates="explode", idle_minutes=1, unknown=5)
    assert s["idle_tabs"] is True and s["auto_updates"] == "check" and s["idle_minutes"] == 5
    assert p.update_settings(auto_updates="install")["auto_updates"] == "install"


def test_idle_scheduler_makes_one_tab_a_day_only_when_away(world, monkeypatch):
    p, clock = world
    p.update_settings(idle_tabs=True, auto_updates="off", idle_minutes=10)
    made = []
    idle = {"s": 30}
    scheduler = predictor.IdleScheduler(p, idle_fn=lambda: idle["s"], tab_maker=lambda topic, why: made.append((topic, why)) or "ok")
    monkeypatch.setattr(scheduler, "_needed_tab", lambda: ("Gpu Prices", "you came back to gpu prices in 4 recent requests"))
    assert scheduler.tick() == []  # owner is here
    idle["s"] = 3600
    assert scheduler.tick() == ["tab"] and made[0][0] == "Gpu Prices"
    assert scheduler.tick() == []  # once a day
    assert "while you were away" in p.snapshot()["idle_log"][-1]["text"]


def test_idle_scheduler_detox_in_quiet_hours(world):
    p, clock = world
    p.update_settings(detox_daily=True, detox_auto_approve=True, auto_updates="off", idle_minutes=10)
    started = []
    scheduler = predictor.IdleScheduler(p, idle_fn=lambda: 7200, detox_starter=lambda auto: started.append(auto) or "run r1")
    assert scheduler.tick() == []  # 14:00 is not quiet
    clock.now += 13 * 3600
    assert scheduler.tick() == ["detox"] and started == [True]
    assert scheduler.tick() == []


def test_update_checks_report_and_install_restarts(world):
    p, _ = world
    p.update_settings(auto_updates="install")
    restarted = []
    scheduler = predictor.IdleScheduler(p, idle_fn=lambda: 0,
                                        updater=lambda mode: {"ok": True, "behind": 2, "installed": mode == "install", "detail": "Installed 2 update(s)"},
                                        restart=lambda: restarted.append(True))
    assert "update" in scheduler.tick()
    assert restarted == [True] and p.snapshot()["update"]["behind"] == 2


def test_needed_tab_picks_a_repeated_topic(world, tmp_path, monkeypatch):
    p, _ = world
    import json

    turns = tmp_path / "learning" / "turns.jsonl"
    turns.parent.mkdir(parents=True)
    turns.write_text("\n".join(json.dumps({"message": m}) for m in [
        "check gpu prices on newegg", "are gpu prices dropping", "compare gpu prices for rtx cards",
        "what's the weather", "gpu prices in canada", "hello"]))
    monkeypatch.setattr(predictor, "data_path", lambda rel: tmp_path / rel)
    topic, why = predictor.IdleScheduler(p)._needed_tab()
    assert "gpu" in topic.lower() and "recent requests" in why


def test_routes(monkeypatch, tmp_path):
    import server
    from fastapi.testclient import TestClient

    local = TestClient(server.app, client=("127.0.0.1", 50091))
    for tab in ("nyx", "learn", "nyx", "learn", "nyx"):
        local.post("/api/presence", json={"tab": tab})
    assert local.get("/api/predict").json()["next_tab"]["tab"] == "learn"
    assert local.put("/api/predict/settings", json={"idle_tabs": True}).json()["idle_tabs"] is True
    remote = TestClient(server.app, client=("203.0.113.4", 50092))
    assert remote.put("/api/predict/settings", json={"idle_tabs": False}).status_code == 403
    assert remote.post("/api/updates/install").status_code == 403
