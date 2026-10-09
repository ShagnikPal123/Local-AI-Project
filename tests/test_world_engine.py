"""A world actually running (U34–U40, U44): its government's projects done by its office, laws tried and enforced,
contests heard and settled, start-ups founded, a child born from two trades, the dead remembered, and the machine
handed back when it is over.

The model is faked, shaped like the real thing — the office's own fake answers plus the world government's JSON.
"""

import json
import re
import time
import types

import pytest

import world as world_package
from office import casting, focus, library, talk
from office import roles as role_module
from office.engine import ENGINE as OFFICE
from world import engine as engine_module, genome, sim, store
from world.engine import ENGINE, WorldError

OFFICE_PLAN = {
    "reply": "Two sections: one builds the page, one finds examples.",
    "title": "Landing page", "scale": "small",
    "sections": [
        {"name": "Frontend", "purpose": "Write the page code", "existing": False,
         "team": [{"role": "coder", "count": 1}],
         "tasks": [{"title": "Write the page", "detail": "One HTML file.", "role": "coder", "after": []}]},
        {"name": "Research", "purpose": "Research examples", "existing": False,
         "team": [{"role": "researcher", "count": 1}],
         "tasks": [{"title": "Find three examples", "detail": "Three good pages.", "role": "researcher", "after": []}]},
    ],
}


class FakeRouter:
    def __init__(self) -> None:
        self.providers = {"fake": object()}
        self.plans = 0
        self.prompts = []
        self.plan_answers = [
            {"project": "Build the landing page and find examples to learn from.", "title": "First page",
             "why": "The goal needs a page first.", "done": False,
             "laws": [{"scope": "world", "sector": "", "text": "Every report names its sources."}],
             "startup": None, "rivals": None},
            {"project": "Improve the page using what Research found.", "title": "Second pass",
             "why": "Make it better.", "done": False, "laws": [],
             "rivals": {"sector_a": "Frontend", "approach_a": "Hand-written HTML and CSS",
                        "sector_b": "Research", "approach_b": "Start from a template", "reason": "How to build the page"}},
            {"project": "Nothing left.", "title": "Done", "why": "The goal is met.", "done": True},
        ]

    def unavailable_reason(self, name, explicit=False):
        return None if name == "fake" else "not configured"

    def stream(self, messages, on_event=None, **kwargs):
        last = next((m for m in reversed(messages) if m.get("role") == "user"), {})
        text = str(last.get("content", ""))
        self.prompts.append(text)
        return self._answer(text, messages), "fake"

    def _answer(self, text, messages):
        if "Plan the next project" in text:
            answer = self.plan_answers[min(self.plans, len(self.plan_answers) - 1)]
            self.plans += 1
            return "```json\n" + json.dumps(answer) + "\n```"
        if "pick the better idea" in text:
            return json.dumps({"winner": "a", "why": "Hand-written is lighter."})
        if "name the new technology" in text:
            return json.dumps({"tech": "Glass and light", "about": "Bright towers.", "style": "spire",
                               "palette": ["#112233", "#445566", "#778899"]})
        if "opened a resolution" in text:
            return "Our option is better because it is simpler, and the goal values speed."
        if "asks how you are" in text:
            return "Busy, and enjoying the page work."
        if "Plan the work" in text:
            return "```json\n" + json.dumps(OFFICE_PLAN) + "\n```"
        if "Give every task to exactly one agent" in text:
            names = re.findall(r"^- (.+?) \(", text, re.MULTILINE)
            titles = [t for t in re.findall(r"^- (.+?): ", text, re.MULTILINE) if t not in names]
            return json.dumps({"assignments": [{"task": t, "agent": names[i % len(names)] if names else ""}
                                               for i, t in enumerate(titles)], "note": "Split."})
        if "Check it against the tasks" in text:
            return json.dumps({"verdict": "ok", "fixes": [], "report": "Done well.", "note": ""})
        if "Write the answer for the owner" in text:
            return json.dumps({"reply": "# Done\nThe page is in work/page.html.", "summary": "Built the page.",
                               "decisions": [], "facts": [], "open": []})
        if "Task from" in text:
            if any("Tool results:" in str(m.get("content", "")) for m in messages):
                return "Done — wrote work/page.html."
            return ('<tool_call>\nname: write_file\narguments: {"path": "page.html", "content": "<h1>Hi</h1>"}\n'
                    '</tool_call>')
        return "Noted."


@pytest.fixture
def worlds(tmp_path, monkeypatch):
    library.use_root(tmp_path / "offices")
    store.use_root(tmp_path / "worlds")
    router = FakeRouter()
    casting.set_router(router)
    casting.forget_members()
    monkeypatch.setattr(casting, "members", lambda domain="", **kwargs: [
        {"member": "fake:m1", "provider": "fake", "model": "m1", "score": 0.9, "local": True, "free": True},
        {"member": "fake:m2", "provider": "fake", "model": "m2", "score": 0.6, "local": False, "free": True}])
    monkeypatch.setattr(casting, "capacity",
                        lambda **kwargs: casting.Capacity(agents=40, concurrency=4, members=2, reason="test"))
    monkeypatch.setattr(casting, "_device", lambda: types.SimpleNamespace(max_workers=8, ram_gb=32))
    monkeypatch.setattr(role_module, "add_to_subagents", lambda role, office_name: "(roster untouched in tests)")
    monkeypatch.setattr(engine_module, "TICK_SECONDS", 0.02)
    monkeypatch.setattr(engine_module, "CENSUS_STEP_SECONDS", 0.0)
    monkeypatch.setitem(world_package.SPEEDS["rush"], "rest", 0.05)
    OFFICE.reset_for_tests()
    ENGINE.reset_for_tests()
    focus.reset_for_tests()
    talk.GATES.resize(4)
    yield ENGINE, router
    ENGINE.reset_for_tests()
    OFFICE.reset_for_tests()
    focus.reset_for_tests()
    casting.set_router(None)
    casting.forget_members()
    library.use_root(None)
    store.use_root(None)
    role_module.forget_invented()


def _wait(condition, seconds=60.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return False


def test_a_new_world_starts_from_a_camp_with_its_own_office_in_office_space(worlds):
    engine, _router = worlds

    data = engine.create(name="Moon base", goal="Build a landing page", duration="for 5 days", speed="rush")

    world = data["world"]
    assert world["name"] == "Moon base" and world["duration"] == 5 * 86400 and world["speed"] == "rush"
    assert world["era_name"] == "First Light" and world["status"] == "idle"
    assert [s["name"] for s in data["sectors"]] == ["Head Office"] and data["sectors"][0]["important"]
    assert any(b["kind"] == "capitol" and b["state"] == "standing" for b in data["buildings"]), "the camp stands"
    assert data["bots"][0]["role"] == "Top Manager" and genome.decode(data["bots"][0]["code"])
    folder = next(f for f in library.tree()["folders"] if f["name"] == "Worlds")
    office = next(o for o in library.tree()["offices"] if o["id"] == world["office_id"])
    assert office["parent"] == folder["id"], "its office is visible under Office Space → Worlds"
    settings = OFFICE.open(world["office_id"]).settings
    assert (settings["review_rounds"], settings["worker_steps"]) == (0, 3), "Rush is low effort per task"
    assert store.worlds()[0]["id"] == world["id"]


def test_upscaling_an_office_makes_its_team_the_first_citizens_once(worlds):
    engine, _router = worlds
    office, _ = library.create_office("Site rebuild")
    OFFICE.open(office.id)
    OFFICE.add_section(office.id, "Backend", "Write the API code")

    first = engine.upscale(office.id, goal="Rebuild the site")
    again = engine.upscale(office.id)

    assert first["world"]["id"] == again["world"]["id"], "one office, one world"
    assert first["world"]["name"] == "Site rebuild World" and first["world"]["office_id"] == office.id
    assert {s["name"] for s in first["sectors"]} == {"Head Office", "Backend"}
    assert next(s for s in first["sectors"] if s["name"] == "Backend")["kind"] == "data_center"
    assert len(first["bots"]) == 2


def test_a_world_runs_its_governments_projects_through_the_office_until_the_goal_is_met(worlds):
    engine, router = worlds
    data = engine.create(name="Pageland", goal="Build a landing page for the product", speed="rush")
    world_id, office_id = data["world"]["id"], data["world"]["office_id"]

    engine.control(world_id, "start")
    assert focus.status()["held"] and focus.pinned() == world_id, "everything else stops while it runs"
    assert _wait(lambda: engine.snapshot(world_id)["world"]["status"] == "complete", 120), \
        engine.snapshot(world_id)["world"]

    snap = engine.snapshot(world_id)
    projects = snap["projects"]
    assert [p["status"] for p in projects] == ["done", "done"], projects
    assert projects[0]["title"] == "First page"
    office = OFFICE.open(office_id)
    first_job = office.job(projects[0]["job_id"])
    assert first_job.request.startswith("Project 1: First page\n[Pageland · Year 1"), \
        "the project's name first (the office titles its Output card from it), then the world's header"
    assert "Every report names its sources. — on trial in this project" in first_job.request
    assert office.chat[0].by_name == "World Government", "the government signs its projects"
    assert office.outputs and office.outputs[-1].status == "done", "the result is in the Output box"

    law = snap["laws"][0]
    assert law["status"] == "enforced" and law["trial_job"] == projects[0]["job_id"]

    # Project 2's plan started a contest between Frontend and Research.
    war = snap["wars"][0]
    assert {snap_sector["name"] for snap_sector in snap["sectors"] if snap_sector["sid"] in (war["a"], war["b"])} == \
        {"Frontend", "Research"}
    assert war["reason"] == "How to build the page"

    births = [b for b in snap["bots"] if b["parents"]]
    assert births, "two trades made a child after a project"
    child = births[0]
    assert child["role"] == "Research Coder" and child["generation"] == 1
    assert set(child["skills"]) >= {"research", "code"}
    assert snap["world"]["births"] >= 1
    kinds = {e["kind"] for e in snap["timeline"]}
    assert {"founded", "census", "project", "done", "law", "war", "birth"} <= kinds, kinds
    assert snap["world"]["tech_points"] > 0 and snap["world"]["game_days"] > 0

    assert not focus.status()["held"] and not focus.pinned(), "the machine is handed back"
    assert engine.running_world() == ""
    raw = store.read_file(store.path_of(world_id))
    assert raw["st"] == "complete" and len(raw["P"]) == 2


def test_a_contest_is_heard_and_the_owner_decides_and_the_loser_may_found_a_startup(worlds):
    engine, _router = worlds
    data = engine.create(name="Debate", goal="Ship an app")
    world_id, office_id = data["world"]["id"], data["world"]["office_id"]
    OFFICE.add_section(office_id, "Frontend", "Write the UI code")
    OFFICE.add_section(office_id, "Research", "Research what users want")
    world = engine.open(world_id)
    view = engine._view(world)
    sim.sync_sectors(world, view)
    sim.sync_bots(world, view)
    front = world.sector_by_name("Frontend")
    research = world.sector_by_name("Research")
    war = engine._declare_war(world, {"a": front.sid, "b": research.sid, "a_stance": "Native app",
                                      "b_stance": "Web app first", "reason": "Which platform first"})

    engine.war_hearing(world_id, war.wid)
    assert _wait(lambda: engine.open(world_id).war(war.wid).status == "awaiting")
    heard = engine.open(world_id).war(war.wid)
    assert "Our option is better" in heard.cases["a"] and "Our option is better" in heard.cases["b"]

    engine.war_decide(world_id, war.wid, choice="b")

    settled = engine.open(world_id).war(war.wid)
    assert settled.status == "resolved" and settled.winner == "b" and settled.by == "owner"
    assert settled.decision == "Web app first"
    assert research.influence == 2 and front.influence == -1
    startup = engine.open(world_id).startups[0]
    assert startup.name == "Frontend Ventures" and startup.idea == "Native app" and startup.status == "proposed"

    engine.startup_action(world_id, startup.suid, "approve")

    founded = engine.open(world_id).startup(startup.suid)
    assert founded.status == "founded" and founded.sector
    assert OFFICE.open(office_id).section(founded.sector).name == "Frontend Ventures"
    assert engine.open(world_id).sectors[founded.sector].startup is True
    with pytest.raises(WorldError):
        engine.war_decide(world_id, war.wid, choice="a")


def test_the_owner_can_settle_a_contest_their_own_way(worlds):
    engine, _router = worlds
    data = engine.create(name="Own way", goal="Ship it")
    world = engine.open(data["world"]["id"])
    OFFICE.add_section(world.office_id, "Alpha", "Write code")
    view = engine._view(world)
    sim.sync_sectors(world, view)
    capital, alpha = world.capital(), world.sector_by_name("Alpha")
    war = engine._declare_war(world, {"a": capital.sid, "b": alpha.sid, "a_stance": "X", "b_stance": "Y",
                                      "reason": "Which way"})

    with pytest.raises(WorldError):
        engine.war_decide(world.id, war.wid, choice="own", text="")
    engine.war_decide(world.id, war.wid, choice="own", text="Do both, X for now and Y next month.")

    assert war.winner == "owner" and war.decision.startswith("Do both") and not world.startups


def test_mood_is_asked_live_and_never_written_down(worlds):
    engine, _router = worlds
    data = engine.create(name="Moods", goal="Anything")
    top = data["bots"][0]["aid"]

    answer = engine.mood(data["world"]["id"], top)

    assert answer["live"] and answer["mood"] == "Busy, and enjoying the page work."
    raw = json.dumps(store.read_file(store.path_of(data["world"]["id"])))
    assert "enjoying" not in raw


def test_a_world_will_not_take_the_machine_from_a_working_office_unless_told(worlds, monkeypatch):
    engine, _router = worlds
    data = engine.create(name="Patient", goal="Anything")
    other, _ = library.create_office("Busy office")
    OFFICE.open(other.id)
    monkeypatch.setattr(OFFICE, "running_office", lambda: other.id)
    halted = []
    monkeypatch.setattr(OFFICE, "control", lambda office_id, action, **kw: halted.append((office_id, action)) or {})

    with pytest.raises(WorldError, match="halt that office first"):
        engine.control(data["world"]["id"], "start")
    assert not halted

    monkeypatch.setattr(engine, "_loop", lambda run: None)
    engine.control(data["world"]["id"], "start", halt_office=True)
    assert halted == [(other.id, "halt")]


def test_a_world_needs_a_goal_and_pausing_hands_the_machine_back(worlds, monkeypatch):
    engine, _router = worlds
    empty = engine.create(name="Blank")
    with pytest.raises(WorldError, match="goal"):
        engine.control(empty["world"]["id"], "start")

    data = engine.create(name="Pauser", goal="Write a guide")
    world_id = data["world"]["id"]
    monkeypatch.setattr(engine, "_ask_plan", lambda world: (time.sleep(5), {})[1])
    engine.control(world_id, "start")
    assert focus.pinned() == world_id

    engine.control(world_id, "pause")
    assert engine.open(world_id).status == "paused" and not focus.status()["held"] and not focus.pinned()

    engine.control(world_id, "resume")
    assert engine.open(world_id).status == "running" and focus.pinned() == world_id
    engine.control(world_id, "stop")
    assert engine.open(world_id).status == "stopped" and not focus.status()["held"]


def test_speed_is_effort_and_a_small_machine_cannot_rush(worlds, monkeypatch):
    engine, _router = worlds
    data = engine.create(name="Speedy", goal="Anything")
    world_id, office_id = data["world"]["id"], data["world"]["office_id"]

    engine.set_speed(world_id, "deliberate")
    settings = OFFICE.open(office_id).settings
    assert (settings["review_rounds"], settings["worker_steps"]) == (2, 6)

    monkeypatch.setattr(casting, "_device", lambda: types.SimpleNamespace(max_workers=2, ram_gb=8))
    snap = engine.set_speed(world_id, "rush")
    assert snap["world"]["speed"] == "steady", "a small machine runs the world, just slower"
    assert snap["limits"]["population"] == 24 and snap["limits"]["machine"] == "small"


def test_the_let_go_are_buried_and_can_be_brought_back(worlds):
    engine, _router = worlds
    data = engine.create(name="Graves", goal="Anything")
    world_id, office_id = data["world"]["id"], data["world"]["office_id"]
    section = OFFICE.add_section(office_id, "Writers", "Write the docs")
    agent = OFFICE.add_agent(office_id, section["id"], "writer")
    world = engine.open(world_id)
    sim.sync_sectors(world, engine._view(world))
    sim.sync_bots(world, engine._view(world))
    code = world.bots[agent["id"]].code

    office = OFFICE.open(office_id)
    office.agents.pop(agent["id"])
    from office.state import StaffChange
    office.add_staff_change(StaffChange(id="chg-1", agent_id=agent["id"], agent_name=agent["name"], change="let_go",
                                        why="Not needed for three jobs."))
    sim.sync_bots(world, engine._view(world))

    grave = world.graves[-1]
    assert grave.name == agent["name"] and grave.epitaph == "Not needed for three jobs." and grave.code == code

    back = engine.rejoin(world_id, grave.gid)

    assert back["agent"]["origin"] == "rejoined" and back["grave"]["rejoined"]
    assert world.bots[back["agent"]["id"]].code == code, "it comes back with the same genetic code"
    with pytest.raises(WorldError, match="already rejoined"):
        engine.rejoin(world_id, grave.gid)


def test_the_owners_word_starts_a_world_and_later_commands_wait_for_the_next_project(worlds, monkeypatch):
    engine, _router = worlds
    data = engine.create(name="Commanded")
    world_id = data["world"]["id"]
    monkeypatch.setattr(engine, "_loop", lambda run: None)

    result = engine.say(world_id, "Make a recipe site, work on it for 3 hours")

    world = engine.open(world_id)
    assert world.goal.startswith("Make a recipe site") and world.duration == 3 * 3600
    assert world.status == "running" and result["queued"]
    engine.say(world_id, "Use green as the main colour")
    assert world.commands == ["Use green as the main colour"]
