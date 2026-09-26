"""An office actually doing a job (Project Null N8): plan → staff → brief → work → review → wrap.

The model is faked — deterministically, and shaped like the real thing: JSON for the manager calls, a tool call
followed by a report for the workers. What is under test is everything around it: sections and desks appearing,
tasks handed out and finished, files landing in the office's work folder, the answer reaching the main chat,
what the office remembers afterwards, hiring, halting, and focus mode letting go by itself.
"""

import json
import re
import sys
import time
import types

import pytest

from office import casting, focus, gatekeeper, library, memory, settings as settings_module, talk
from office import roles as role_module
from office.engine import ENGINE, OfficeError
from office.state import AGENT_IDLE, TASK_DONE

PLAN = {
    "reply": "Two sections on it: one writing the page, one finding examples.",
    "title": "Landing page", "scale": "small",
    "sections": [
        {"name": "Frontend", "purpose": "The page itself", "existing": False,
         "team": [{"role": "coder", "count": 2}],
         "tasks": [{"title": "Write the page", "detail": "One HTML file with a hero and the copy.",
                    "role": "coder", "after": []},
                   {"title": "Check the page", "detail": "Read it and say what is missing.",
                    "role": "reviewer", "after": ["Write the page"]}]},
        {"name": "Research", "purpose": "Find examples worth copying", "existing": False,
         "team": [{"role": "researcher", "count": 1}],
         "tasks": [{"title": "Find three examples", "detail": "Three landing pages that do this well.",
                    "role": "researcher", "after": []}]},
    ],
}


class FakeRouter:
    """Answers like a well-behaved model: JSON where JSON was asked for, a tool call then a report otherwise."""

    def __init__(self) -> None:
        self.providers = {"fake": object()}
        self.prompts = []

    def unavailable_reason(self, name, explicit=False):
        return None if name == "fake" else "not configured"

    def stream(self, messages, on_event=None, **kwargs):
        last = next((m for m in reversed(messages) if m.get("role") == "user"), {})
        text = str(last.get("content", ""))
        self.prompts.append(text)
        return self._answer(text, messages), "fake"

    def _answer(self, text: str, messages) -> str:
        if "Plan the work" in text:
            return "Here you go:\n```json\n" + json.dumps(PLAN) + "\n```"
        if "Give every task to exactly one agent" in text:
            names = re.findall(r"^- (.+?) \(", text, re.MULTILINE)
            titles = re.findall(r"^- (.+?): ", text, re.MULTILINE)
            titles = [t for t in titles if t not in names]
            assignments = [{"task": title, "agent": names[index % len(names)] if names else ""}
                           for index, title in enumerate(titles)]
            return json.dumps({"assignments": assignments, "note": "Split by hand."})
        if "Check it against the tasks" in text:
            return json.dumps({"verdict": "ok", "fixes": [], "report": "The section produced page.html.",
                               "note": "Dark theme only."})
        if "Write the answer for the owner" in text:
            return json.dumps({"reply": "# Done\nThe page is in work/page.html.",
                               "summary": "Built the landing page and found three examples.",
                               "decisions": ["Dark theme only"], "facts": ["The palette is black and purple"],
                               "open": []})
        if "sent this to you" in text:
            return "On it — I will switch to tabs.\nTASK: Switch to tabs — reformat page.html with tabs."
        if "Task from" in text:
            if any("Tool results:" in str(m.get("content", "")) for m in messages):
                return "Done — wrote work/page.html with the hero and the copy."
            return ('<thinking>write the file</thinking>\n<tool_call>\nname: write_file\n'
                    'arguments: {"path": "page.html", "content": "<h1>Hello</h1>"}\n</tool_call>')
        return "Noted."


@pytest.fixture
def engine(tmp_path, monkeypatch):
    library.use_root(tmp_path / "offices")
    router = FakeRouter()
    casting.set_router(router)
    casting.forget_members()
    monkeypatch.setattr(casting, "members", lambda domain="", **kwargs: [
        {"member": "fake:m1", "provider": "fake", "model": "m1", "score": 0.9, "local": True, "free": True},
        {"member": "fake:m2", "provider": "fake", "model": "m2", "score": 0.6, "local": False, "free": True}])
    monkeypatch.setattr(casting, "capacity",
                        lambda **kwargs: casting.Capacity(agents=40, concurrency=4, members=2, reason="test"))
    # Never write into the owner's real sub-agent roster from a test.
    monkeypatch.setattr(role_module, "add_to_subagents", lambda role, office_name: "(roster untouched in tests)")
    ENGINE.reset_for_tests()
    focus.reset_for_tests()
    talk.GATES.resize(4)
    yield ENGINE, router
    ENGINE.reset_for_tests()
    focus.reset_for_tests()
    casting.set_router(None)
    casting.forget_members()
    library.use_root(None)
    role_module.forget_invented()


def _wait(condition, seconds=60.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return False


def test_a_new_office_opens_with_a_head_office_and_a_top_manager(engine):
    office_engine, _router = engine
    office, _ = library.create_office("First office")

    opened = office_engine.open(office.id)

    assert [s.name for s in opened.sections.values()] == ["Head Office"]
    top = opened.top_manager()
    assert top is not None and top.member, "the top manager sits down with a model already chosen"
    assert office_engine.snapshot(office.id)["office"]["counts"]["agents"] == 1


def test_a_job_runs_end_to_end_and_the_office_remembers_it(engine):
    office_engine, _router = engine
    office, directory = library.create_office("Landing page")
    office_engine.open(office.id)

    office_engine.say(office.id, "Build me a landing page for the new product.")
    assert _wait(lambda: not office_engine.running_office()), "the job finished"

    state = office_engine.open(office.id)
    names = {s.name for s in state.sections.values()}
    assert {"Head Office", "Frontend", "Research"} <= names, "the sections from the plan were built"
    assert len(state.agents) >= 5, "managers and workers were hired for them"
    assert all(a.status == AGENT_IDLE for a in state.agents.values()), "everyone sat back down afterwards"

    tasks = list(state.tasks.values())
    assert tasks and all(t.status == TASK_DONE for t in tasks), [t.status for t in tasks]
    assert (directory / "work" / "page.html").read_text(encoding="utf-8") == "<h1>Hello</h1>"
    assert list((directory / "work" / "_reports").glob("*.md")), "every finished task leaves its full report"

    chat = [m.text for m in state.chat]
    assert any("Two sections on it" in text for text in chat), "the top manager said what it was doing"
    assert any(text.startswith("# Done") for text in chat), "and delivered the answer"

    job = state.jobs[-1]
    assert job.status == "done" and job.title == "Landing page"
    assert "landing page" in memory.brief(state.id, "landing page").lower()
    assert any(e["kind"] == "decision" for e in memory.load(state.id)["entries"])

    # Reopening is the real test of "it fully remembers things from previous sessions".
    office_engine.close(office.id)
    ENGINE.reset_for_tests()
    reopened = office_engine.open(office.id)
    assert {s.name for s in reopened.sections.values()} == names
    assert len(reopened.agents) >= 5


def test_a_second_office_cannot_start_while_one_is_working(engine):
    office_engine, _router = engine
    first, _ = library.create_office("Busy")
    second, _ = library.create_office("Waiting")
    office_engine.open(first.id)
    office_engine.open(second.id)

    office_engine.say(first.id, "Build me a landing page.")
    try:
        with pytest.raises(OfficeError, match="One office runs at a time"):
            office_engine.say(second.id, "And one for me too.")
    finally:
        _wait(lambda: not office_engine.running_office())


def test_halting_stops_everything_and_leaves_the_work_that_was_saved(engine):
    office_engine, _router = engine
    office, directory = library.create_office("Halt me")
    office_engine.open(office.id)
    office_engine.say(office.id, "Build me a landing page.")
    _wait(lambda: office_engine.open(office.id).phase in ("staff", "brief", "work"), seconds=20)

    office_engine.control(office.id, "halt")
    _wait(lambda: not office_engine.running_office())

    state = office_engine.open(office.id)
    assert state.jobs[-1].status == "stopped"
    assert all(a.status in (AGENT_IDLE, "paused") for a in state.agents.values())
    assert not any(t.status in ("working", "queued") for t in state.tasks.values())
    assert any("Halted" in m.text for m in state.chat)


def test_the_targeted_chat_reaches_the_agents_it_names_and_they_answer(engine):
    office_engine, _router = engine
    office, _ = library.create_office("Talk to them")
    office_engine.open(office.id)
    office_engine.say(office.id, "Build me a landing page.")
    assert _wait(lambda: not office_engine.running_office())

    preview = office_engine.resolve(office.id, "coders in every group: use tabs")
    assert preview["count"] >= 1 and "Coder" in preview["label"]

    result = office_engine.target(office.id, "coders in every group: use tabs")
    assert result["replying"] >= 1
    assert _wait(lambda: any(m.kind == "thread" and m.by != "owner"
                             for m in office_engine.open(office.id).thread), seconds=30)

    state = office_engine.open(office.id)
    replies = [m for m in state.thread if m.by != "owner"]
    assert replies and "tabs" in replies[0].text.lower()
    assert any(t.title == "Switch to tabs" for t in state.tasks.values()), \
        "a TASK line in a reply becomes real work"


def test_an_agent_asking_for_a_teammate_is_answered_on_the_spot_before_the_board_exists(engine):
    office_engine, _router = engine
    office, _ = library.create_office("Hiring")
    state = office_engine.open(office.id)
    section = next(iter(state.sections.values()))
    asker = state.top_manager()

    answer = office_engine.agent_hire(state, asker, role="illustrator",
                                      why="The page needs original artwork and nobody here can draw.",
                                      long_term="Every page we build from now on needs its own artwork.",
                                      count=1, section_id=section.id)

    assert "Approved" in answer, answer
    assert any(a.role == "illustrator" for a in state.agents.values())
    assert any(r["id"] == "illustrator" for r in state.invented_roles), "a new kind is recorded on the office"
    assert state.hires[-1].status == "approved" and state.hires[-1].decided_by == "the section manager"


def test_the_hiring_board_wakes_after_ten_new_kinds_and_then_decides(engine):
    office_engine, _router = engine
    office, _ = library.create_office("Too many kinds")
    state = office_engine.open(office.id)
    state.invented_roles = [{"id": f"kind-{i}", "title": f"Kind {i}", "glyph": "●", "color": "#fff",
                             "domain": "chat", "kind": "worker", "goal": ""} for i in range(10)]

    office_engine._maybe_wake_gatekeeper(state)

    board = state.agent(state.gatekeeper_id)
    assert board is not None and board.role == gatekeeper.HIRING_BOARD
    assert any("Hiring Board" in m.text for m in state.chat)

    answer = office_engine.agent_hire(state, state.top_manager(), role="another coder",
                                      why="More hands.", long_term="", count=1)
    assert "Hiring Board" in answer, "requests now go to the board instead of being approved on the spot"
    assert _wait(lambda: state.hires[-1].status != "pending", seconds=30)
    assert state.hires[-1].decided_by == board.name


def test_focus_mode_is_held_for_the_job_and_let_go_afterwards(engine, monkeypatch):
    office_engine, _router = engine
    paused, resumed = [], []
    fake = types.ModuleType("background_jobs")
    fake.pause_all = lambda reason, by="": paused.append((reason, by)) or "token-1"
    fake.resume = lambda token: resumed.append(token) or {"resumed": True}
    fake.status = lambda: {"paused": ["improve autopilot"], "not_paused": ["identity0 training"]}
    monkeypatch.setitem(sys.modules, "background_jobs", fake)
    settings_module.save({"focus_mode": "always"})

    office, _ = library.create_office("Focused")
    office_engine.open(office.id)
    office_engine.say(office.id, "Build me a landing page.")

    assert _wait(lambda: focus.status()["held"], seconds=20), "the office pauses the rest of Nyx while it works"
    assert paused and paused[0][1] == "office"
    assert _wait(lambda: not office_engine.running_office())
    assert resumed == ["token-1"], "everything else resumes by itself when the office finishes"
    assert focus.status()["held"] is False
    settings_module.save({"focus_mode": "ask"})


def test_the_snapshot_is_everything_the_tab_draws(engine):
    office_engine, _router = engine
    office, _ = library.create_office("Snapshot")
    office_engine.open(office.id)

    snapshot = office_engine.snapshot(office.id)

    assert set(snapshot) >= {"office", "sections", "agents", "tasks", "chat", "thread", "feed", "hires", "roles",
                             "focus"}
    assert snapshot["office"]["capacity_detail"]["concurrency"] == 4
    assert any(r["id"] == "coder" for r in snapshot["roles"]), "the role colours and glyphs travel with it"
    assert snapshot["office"]["path"].endswith("Snapshot")
