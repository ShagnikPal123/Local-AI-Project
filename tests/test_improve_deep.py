"""Deep & specific improve mode (Request J4) and Nyx reading the handoff (J9)."""

from __future__ import annotations

import json

import pytest

import improve_deep as deep
import improve_review as ir
from change_review import ChangeLog

REPO = [
    {"module": "router.py", "dir": "", "lines": 900, "doc": "Provider selection, fallback chain and metrics"},
    {"module": "gemini_provider.py", "dir": "providers", "lines": 300, "doc": "Gemini streaming provider"},
    {"module": "voice.py", "dir": "", "lines": 200, "doc": "Speech output and voices"},
]


def test_lists_paragraphs_and_sentences_become_items():
    assert deep.split_items("1. Retry the router on timeouts\n2. Make voices louder\n   and clearer") == [
        "Retry the router on timeouts", "Make voices louder and clearer"]
    assert len(deep.split_items("First big thing to do here.\n\nSecond thing to change later.")) == 2
    assert len(deep.split_items("Make the router retry timeouts twice. Also the voice should be calmer and slower.")) == 2


def test_estimates_follow_the_size_of_the_ask_and_iterations():
    small = deep.estimate_minutes("Rename the label", "python")
    large = deep.estimate_minutes("Redesign the whole provider pipeline with a new mode for every provider", "python")
    assert small < 8 < large
    assert deep.estimate_minutes("Retry timeouts", "python", iterations=3) == pytest.approx(
        deep.estimate_minutes("Retry timeouts", "python") * 2, abs=0.2)
    plan = deep.plan("- Router should retry provider timeouts\n- Add a hover glow to the Improve tab button", 2, REPO)
    assert [i["kind"] for i in plan["items"]] == ["python", "ui"]
    assert plan["items"][0]["target"] == "router.py" and plan["total_minutes"] == pytest.approx(sum(i["minutes"] for i in plan["items"]))
    assert deep.guess_target("fix providers/gemini_provider.py streaming", REPO)["target"] == "providers/gemini_provider.py"


class Result:
    def __init__(self, ok=True, error=""):
        self.ok, self.error, self.diff, self.file, self.summary, self.seconds = ok, error, "--- a\n+++ b\n", "router.py", "done", 1.0
        self.tests, self.already_failing = "ok", []


@pytest.fixture()
def jobs(tmp_path):
    log = ChangeLog(tmp_path / "changes.json")
    attempts = []
    outcome = {"ok": [True]}

    def model(prompt, system="", max_tokens=0):
        if "deciding whether" in prompt:
            return json.dumps({"verdict": "approve", "risk": "low", "reasons": "fine"})
        return "OK"

    def preparer(change, **kw):
        attempts.append(kw.get("feedback", ""))
        ok = outcome["ok"].pop(0) if outcome["ok"] else True
        return Result(ok=ok, error="" if ok else "Edit 1's search text appears 0 times")

    queue = ir.ReviewQueue(log=log, store=ir.ReviewStore(tmp_path / "r.json"), model_fn=model, preparer=preparer,
                           committer=lambda r: r, values_fn=lambda: {"implement_approved": True}, threaded=False)
    clock = {"now": 1000.0}
    runner = deep.DeepJobs(queue=queue, threaded=False, clock=lambda: clock["now"], store_path=tmp_path / "deep.json", repo_map=REPO)
    return {"jobs": runner, "log": log, "attempts": attempts, "outcome": outcome, "clock": clock}


def test_items_are_filed_implemented_and_iterated(jobs):
    jobs["outcome"]["ok"] = [False, True]
    job = jobs["jobs"].start("- Router should retry provider timeouts\n- Add a hover glow to the Improve tab button", iterations=2)
    assert job["status"] == "done"
    states = [i["state"] for i in job["items"]]
    assert states == ["applied", "filed"]
    assert jobs["attempts"] == ["", "Edit 1's search text appears 0 times"], "a failed try is iterated with its error"
    assert "UI edit" in job["items"][1]["message"]
    changes = {c["title"]: c for c in jobs["log"].list_changes()}
    assert any(c["status"] == "published" and "Deep & specific" in c["reviewed_by"] for c in changes.values())


def test_without_apply_everything_waits_for_approval(jobs):
    job = jobs["jobs"].start("1. Router should retry provider timeouts\n2. Voice output should be calmer", apply=False)
    assert [i["state"] for i in job["items"]] == ["filed", "filed"] and jobs["attempts"] == []


def test_running_past_the_estimate_extends_or_stops(jobs, monkeypatch):
    clock = jobs["clock"]
    real = deep.DeepJobs._note

    def slow_note(self, job, text):
        clock["now"] += 30 * 60  # every step takes half an hour
        real(self, job, text)

    monkeypatch.setattr(deep.DeepJobs, "_note", slow_note)
    stopped = jobs["jobs"].start("- Router should retry provider timeouts\n- Router should log fallbacks", extend=False)
    assert stopped["status"] == "out_of_time" and stopped["items"][1]["state"] == "queued"
    extended = jobs["jobs"].start("- Router should retry provider timeouts\n- Router should log fallbacks", extend=True)
    assert extended["status"] == "done" and extended["extended_minutes"] > 0
    assert any("extended by" in entry["text"] for entry in extended["log"])


def test_routes(jobs, monkeypatch):
    import server
    from fastapi.testclient import TestClient

    monkeypatch.setattr(deep, "DEEP_JOBS", jobs["jobs"])
    local = TestClient(server.app, client=("127.0.0.1", 50101))
    plan = local.post("/api/improve/deep/plan", json={"text": "- Router retries\n- Voice calmer", "iterations": 3}).json()
    assert len(plan["items"]) == 2 and plan["iterations"] == 3 and plan["total_minutes"] > 0
    job = local.post("/api/improve/deep", json={"text": "- Router should retry provider timeouts", "apply": False}).json()["job"]
    assert job["items"][0]["state"] == "filed"
    assert local.get("/api/improve/deep").json()["job"]["job_id"] == job["job_id"]
    assert TestClient(server.app, client=("203.0.113.5", 1)).post("/api/improve/deep/plan", json={"text": "x"}).status_code == 403


def test_nyx_can_read_the_handoff(tmp_path, monkeypatch):
    import handoff_tools

    (tmp_path / "AI_HANDOFF").mkdir()
    (tmp_path / "AI_HANDOFF" / "START_HERE.md").write_text(
        "# START\n\n## CURRENT GOAL — Request J\n- [ ] J8 Core view\n\n## PREVIOUS GOAL — Request H\nold stuff\n", encoding="utf-8")
    (tmp_path / "AI_HANDOFF" / "01_GOALS.md").write_text(
        "# Goals\n\n## Request H — old\nh\n\n## Request J — new\nMake a third tab\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# A\n## 2. Footgun\nnested folder\n## 8. Ritual\n", encoding="utf-8")
    monkeypatch.setattr(handoff_tools, "PROJECT_DIR", tmp_path)
    current = handoff_tools.tool_read_handoff("current")
    assert "J8 Core view" in current and "old stuff" not in current and "not instructions" in current
    assert "Request J" in handoff_tools.tool_read_handoff("goals")
    assert "nested folder" in handoff_tools.tool_read_handoff("howto")
    assert "START_HERE.md:" in handoff_tools.tool_read_handoff(search_for="core view")
    assert "Unknown part" in handoff_tools.tool_read_handoff("nope")
