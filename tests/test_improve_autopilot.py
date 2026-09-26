"""Improvement autopilot: schedules from words, auto-approve windows, controls — no real models or threads."""

from __future__ import annotations

import json

import pytest

import improve_autopilot as ap
from change_review import ChangeLog, ChangeOrigin, ChangeStatus


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class StubEngine:
    """Files one proposal per session straight into the change log, then reports done."""

    def __init__(self, log, titles=("Retry Gemini timeouts",)):
        self.log, self.titles, self.sessions, self.goals = log, list(titles), {}, []

    def start(self, goal, time_budget_seconds=0, max_power=False):
        self.goals.append((goal, time_budget_seconds, max_power))
        ids = []
        for title in self.titles:
            ids.append(self.log.propose(title=title, description="Add a retry.", author="Nyx", target="router.py",
                                        origin=ChangeOrigin.AGENT).change_id)
        session = {"session_id": f"s{len(self.sessions)}", "status": "done", "change_ids": ids, "error": ""}
        self.sessions[session["session_id"]] = session
        return session

    def get(self, session_id):
        return self.sessions.get(session_id)

    def stop(self, session_id):
        return self.sessions.get(session_id)


class Patch:
    def __init__(self, ok=True, error=""):
        self.ok, self.error, self.diff, self.file, self.summary, self.seconds = ok, error, "--- a\n+++ b\n", "router.py", "added retry", 1.0
        self.tests, self.already_failing = "1 passed", []


APPROVE = json.dumps({"verdict": "approve", "confidence": 0.8, "already_done": False, "risk": "low", "reasons": "router.py has no retry."})
DENY = json.dumps({"verdict": "deny", "confidence": 0.9, "already_done": False, "risk": "high", "reasons": "Weakens security."})


@pytest.fixture()
def world(tmp_path):
    clock = Clock()
    log = ChangeLog(tmp_path / "changes.json")
    engine = StubEngine(log)
    patched, committed, prompts = [], [], []
    replies = {"critic": "OK\nLooks safe.", "idea": APPROVE, "study": json.dumps({"lessons": [
        {"topic": "Slow first reply", "insight": "Gemini smart model stalls", "improvement": "Cool down faster",
         "module": "router.py", "evidence": "125 s turn", "research_query": ""}]})}

    def model_fn(prompt, system="", max_tokens=0):
        prompts.append(prompt)
        if "reviewing a proposed change" in prompt:
            return replies["critic"]
        if "deciding whether an AI assistant should make" in prompt:
            return replies["idea"]
        return replies["study"]

    def preparer(change, test_depth="quick", max_changed_lines=150, feedback=""):
        patched.append((change["id"], test_depth, max_changed_lines))
        return world_patch["result"]

    def committer(result):
        committed.append(result)
        return result

    world_patch = {"result": Patch()}
    manager = ap.AutopilotManager(model_fn=model_fn, engine=engine, preparer=preparer, committer=committer, change_log=log,
                                  clock=clock, sleep=clock.sleep, store_dir=tmp_path / "autopilot", threaded=False,
                                  idle_fn=lambda: 10 ** 9, hour_fn=lambda: 12, web_fn=lambda q: "")
    return {"m": manager, "clock": clock, "log": log, "engine": engine, "patched": patched, "patch": world_patch,
            "replies": replies, "tmp": tmp_path, "committed": committed, "prompts": prompts}


@pytest.mark.parametrize("text, phases, loop, hours, auto", [
    ("improve and auto approve all improvements for 22 hours", [("improve", 1320)], False, 22, True),
    ("Study for 1 hour and improve for 1 hour and loop this until I stop", [("study", 60), ("improve", 60)], True, None, False),
    ("take a detox hour", [("detox", 60)], False, 1, False),
    ("study 30 min, improve 2h, rest 10 min, repeat for 3 days, auto-approve", [("study", 30), ("improve", 120), ("rest", 10)], True, 72, True),
    ("for the next 22 hours improve and auto approve everything", [("improve", 1320)], False, 22, True),
    ("Self check and apply all improvements for 1 hour", [("improve", 60)], False, 1, True),
])
def test_owner_sentences_become_plans(text, phases, loop, hours, auto):
    plan = ap.parse_instruction(text)
    assert [(p["kind"], p["minutes"]) for p in plan["phases"]] == phases
    assert plan["loop"] is loop and plan["hours"] == hours and plan["auto_approve"] is auto


def test_auto_approve_window_reviews_approves_and_applies(world):
    m, log = world["m"], world["log"]
    run = m.start("improve and auto approve everything for 22 hours")
    assert run["auto_approve"] and run["remaining_seconds"] == 22 * 3600
    m.step(run["run_id"])
    change = log.list_changes()[0]
    assert change["status"] == "published" and change["published_by"] == "Autopilot"
    assert "authorised by the owner" in change["reviewed_by"]
    assert change["ai_review"].startswith("OK") and change["content"].startswith("--- a")
    assert world["patched"] == [(change["id"], "quick", 150)]
    state = m.active()
    assert state["stats"]["applied"] == 1 and m.restart_pending


def test_research_says_no_before_any_code_is_written(world):
    m, log = world["m"], world["log"]
    world["engine"].titles = ["Delete the permission checks"]
    world["replies"]["idea"] = DENY
    run = m.start("improve, auto approve, for 2 hours")
    m.step(run["run_id"])
    change = log.list_changes()[0]
    assert change["status"] == "rejected" and world["patched"] == []
    assert "Weakens security" in change["ai_review"]
    idea_prompt = next(p for p in world["prompts"] if "deciding whether" in p)
    assert "Outline:" in idea_prompt and "def " in idea_prompt, "the target file was read before deciding"


def test_critic_reads_the_real_diff_and_can_still_block(world):
    m, log = world["m"], world["log"]
    world["engine"].titles = ["Faster cache lookups"]
    world["replies"]["critic"] = "BLOCK\nThe diff drops the lock."
    run = m.start("improve, auto approve, for 2 hours")
    m.step(run["run_id"])
    change = log.list_changes()[0]
    assert change["status"] == "rejected" and world["committed"] == []
    critic_prompt = next(p for p in world["prompts"] if "reviewing a proposed change" in p)
    assert "--- a" in critic_prompt, "the critic saw the diff, not an empty content block"


def test_failed_tests_retry_once_then_reject(world):
    m, log = world["m"], world["log"]
    world["engine"].titles = ["Faster cache"]
    world["patch"]["result"] = Patch(ok=False, error="Tests failed with the edit")
    run = m.start("improve, auto approve, for 2 hours")
    m.step(run["run_id"])
    newest = log.list_changes()[0]
    assert newest["status"] == "rejected" and "Tests failed" in newest["ai_review"]
    assert len(world["patched"]) == 2, "one retry with the error as feedback"
    assert m.active()["stats"]["failed"] == 1


def test_the_same_idea_again_is_closed_as_a_duplicate(world):
    m, log = world["m"], world["log"]
    world["engine"].titles = ["Retry Gemini timeouts", "Retry Gemini timeouts again"]
    run = m.start("improve, auto approve, for 2 hours")
    m.step(run["run_id"])
    statuses = sorted(c["status"] for c in log.list_changes())
    assert statuses == ["published", "rejected"]
    assert m.active()["stats"]["duplicates"] == 1 and len(world["patched"]) == 1


def test_implement_off_approves_only_and_says_so(world):
    m, log = world["m"], world["log"]
    m.set_control("implement_approved", False)
    run = m.start("improve, auto approve, for 2 hours")
    m.step(run["run_id"])
    change = log.list_changes()[0]
    assert change["status"] == "approved" and world["patched"] == []
    assert m.active()["stats"]["approved_only"] == 1
    assert any("Implement approved changes" in entry["text"] for entry in m.active()["log"])


def test_without_auto_approve_findings_wait_for_the_owner(world):
    m, log = world["m"], world["log"]
    run = m.start("improve the router for 1 hour")
    m.step(run["run_id"])
    assert log.list_changes()[0]["status"] == ChangeStatus.IN_REVIEW.value
    assert world["patched"] == [] and m.active()["stats"]["waiting_for_owner"] == 1


def test_hourly_limit_holds_extra_changes(world):
    m = world["m"]
    m.set_control("max_changes_per_hour", 1)
    world["engine"].titles = ["One", "Two", "Three"]
    run = m.start("improve, auto-approve, 3 hours")
    m.step(run["run_id"])
    stats = m.active()["stats"]
    assert stats["applied"] == 1 and stats["waiting_for_owner"] == 2


def test_study_improve_loop_cycles_phases(world):
    m, clock = world["m"], world["clock"]
    run = m.start("study for 1 hour and improve for 1 hour, loop until I stop")
    rid = run["run_id"]
    m.step(rid)  # study: writes a lesson, waits one cycle
    lessons = m.lessons()
    assert lessons and lessons[0]["topic"] == "Slow first reply"
    clock.now += 3600
    m.step(rid)
    assert m.active()["phase"]["kind"] == "improve"
    assert "Cool down faster" in world["engine"].goals[-1][0]  # lessons steer the improve goal
    clock.now += 3600
    m.step(rid)
    state = m.active()
    assert state["phase"]["kind"] == "study" and state["cycles"] == 1 and state["status"] == "active"
    assert m.stop()["status"] == "stopped" and m.active() is None


def test_run_ends_when_the_window_closes(world):
    m, clock = world["m"], world["clock"]
    run = m.start("improve for 2 hours")
    clock.now += 2 * 3600 + 1
    assert m.step(run["run_id"]) is False
    assert m.runs()[0]["status"] == "done"


def test_working_hours_and_away_only_gate_the_work(world):
    m = world["m"]
    m.set_control("active_from_hour", 22)
    m.set_control("active_to_hour", 6)
    run = m.start("improve for 5 hours")
    m.step(run["run_id"])
    assert m.active()["status"] == "waiting" and "working hours" in m.active()["work"]
    assert world["engine"].goals == []
    m._hour_fn = lambda: 23
    m.set_control("only_when_idle", True)
    m._idle_fn = lambda: 30
    m.step(run["run_id"])
    assert "away" in m.active()["work"]
    m._idle_fn = lambda: 3600
    m.step(run["run_id"])
    assert world["engine"].goals, "works once the owner is away inside the hours"


def test_pause_shifts_the_schedule(world):
    m, clock = world["m"], world["clock"]
    run = m.start("improve for 2 hours")
    m.pause()
    clock.now += 5000
    resumed = m.resume()
    assert resumed["remaining_seconds"] == pytest.approx(2 * 3600)


def test_controls_can_be_added_by_nyx_and_steer_prompts(world):
    m = world["m"]
    control = m.add_control({"label": "Research depth", "kind": "slider", "min": 0, "max": 10, "value": 7,
                             "affects": "How many sources to read before proposing a change"})
    assert control["key"] == "research_depth" and control["added_by"] == "nyx" and control["value"] == 7
    assert m.set_control("research_depth", 42)["value"] == 10  # clamped
    run = m.start("improve for 1 hour")
    m.step(run["run_id"])
    assert "Research depth: 10 — How many sources to read" in world["engine"].goals[-1][0]
    with pytest.raises(ap.AutopilotError):
        m.remove_control("aggressiveness")
    m.remove_control("research_depth")
    reloaded = ap.AutopilotManager(store_dir=world["tmp"] / "autopilot", threaded=False)
    assert "research_depth" not in [c["key"] for c in reloaded.controls()]
    assert reloaded.control_values()["max_changes_per_hour"] == 4


def test_bad_plans_are_explained(world):
    m = world["m"]
    with pytest.raises(ap.AutopilotError):
        m.start("", phases=[{"kind": "dance", "minutes": 10}])
    with pytest.raises(ap.AutopilotError):
        m.start("", phases=[{"kind": "study", "minutes": 0}])


def test_tools_and_routes(world, monkeypatch):
    import improve_tools
    import server
    from fastapi.testclient import TestClient

    monkeypatch.setattr(ap, "AUTOPILOT", world["m"])
    reply = improve_tools.tool_improve_schedule("Study 1 hour then improve 1 hour, loop until I stop")
    assert "study 60 min → improve 60 min (looping)" in reply and "until the owner stops it" in reply
    assert "Added the slider" in improve_tools.tool_improve_add_control("Web searches", affects="searches per cycle", maximum=5)
    local = TestClient(server.app, client=("127.0.0.1", 50071))
    state = local.get("/api/improve/autopilot").json()
    assert state["active"]["loop"] is True and any(c["key"] == "web_searches" for c in state["controls"])
    assert local.put("/api/improve/controls/aggressiveness", json={"value": 5}).json()["value"] == 5
    assert local.post("/api/improve/autopilot/stop").json()["status"] == "stopped"
    remote = TestClient(server.app, client=("203.0.113.8", 50072))
    assert remote.post("/api/improve/autopilot", json={"instruction": "improve"}).status_code == 403


def test_a_cut_off_study_reply_still_yields_its_whole_lessons():
    """2026-09-16: replies cut at 1500 tokens made every study cycle say "Nothing new to learn"."""
    cut = ('{"lessons": [{"topic": "Quota", "insight": "429 {x} errors", "improvement": "backoff"},'
           ' {"topic": "Overload", "insight": "503 \\"quoted\\" } seen", "improvement": "circuit breaker"},'
           ' {"topic": "Cut", "insight": "this one is cut off')
    assert [lesson["topic"] for lesson in ap.parse_lessons(cut)] == ["Quota", "Overload"]
