"""The Apply tab (Request R16): a request becomes a plan of reviewed changes, and nothing lands until the owner says so."""

import json
from types import SimpleNamespace

import pytest

import apply_engine
from apply_engine import ApplyError, ApplyJobs, vet_change


PLAN = {
    "understood": "Add a budget tab and make the Notes header calmer.",
    "summary": "A tab for the budget, a skill for money questions, a router retry and a quieter Notes header.",
    "changes": [
        {"kind": "tab", "title": "Budget tab", "why": "One place for the numbers.",
         "tab": {"label": "Budget", "icon": "ph-wallet", "description": "Monthly money",
                 "blocks": [{"type": "tracker", "title": "Spending", "config": {"unit": "$"}}, {"type": "notes", "title": "Plan"}],
                 "accent": "not-a-colour", "theme": {"surface": "glass"}}},
        {"kind": "skill", "title": "Money answers", "why": "Consistent budgeting help.",
         "skill": {"name": "Budget helper", "instructions": "Always show totals first.", "triggers": ["budget", "spending"]}},
        {"kind": "code", "title": "Retry the router", "why": "Timeouts.", "target": "router.py",
         "description": "Retry a provider once after a timeout."},
        {"kind": "ui", "title": "Calmer Notes header", "why": "Too loud.", "target": "frontend/nyx-pulse/src/panels/NotesPanel.tsx",
         "description": "Make the header title 20px and the subtitle muted."},
        {"kind": "code", "title": "Loosen sign-in", "why": "No.", "target": "auth.py", "description": "Skip passwords."},
        {"kind": "rocket", "title": "Launch", "why": "?"},
    ],
    "questions": [],
}


class FakeHig:
    def is_available(self):
        return True

    def lookup(self, query):
        return [{"topic": "Layout", "file": "layout.md"}, {"topic": "Color", "file": "color.md"}]

    def read_guideline(self, name):
        return {"ok": True, "content": f"---\ntitle: {name}\n---\n# {name}\nUse consistent spacing and clear hierarchy."}


@pytest.fixture()
def world(tmp_path):
    root = tmp_path / "nyx"
    ui_root = root / "frontend" / "nyx-pulse" / "src"
    (ui_root / "panels").mkdir(parents=True)
    (ui_root / "panels" / "NotesPanel.tsx").write_text("export const NotesPanel = () => null;\n", encoding="utf-8")
    (ui_root / "tabs.ts").write_text('{ id: "notes", label: "Notes" }, { id: "code", label: "Code" }', encoding="utf-8")
    (root / "router.py").write_text("def route():\n    return 1\n", encoding="utf-8")
    (root / "auth.py").write_text("def check():\n    return True\n", encoding="utf-8")
    log = {"prompts": [], "vision": [], "tabs": {}, "code": [], "ui": [], "suggestions": [], "builds": 0}

    def model(prompt, system, max_tokens):
        log["prompts"].append(prompt)
        return json.dumps(PLAN), "test planner"

    def vision(data, mime, prompt):
        log["vision"].append(prompt)
        return "A dark dashboard: sidebar left, three cards in a row, accent #30d158, 12px corners.", "test eyes"

    def create_tab(fields, by):
        from dynamic_tabs import build_spec

        spec = build_spec(**fields, author=by, source="agent")
        log["tabs"][spec.tab_id] = spec.label
        return {"tab_id": spec.tab_id, "label": spec.label}

    def propose_ui(path, instruction):
        log["ui"].append(("propose", path, instruction))
        return {"id": "p1", "diff": "--- a\n+++ b\n@@ -1 +1 @@\n-old\n+new\n", "lines": {"files": []}, "explanation": "Smaller."}

    hooks = SimpleNamespace(
        model=model, vision=vision, search=lambda q: "- A result: something useful (https://example.com)",
        hig=lambda: FakeHig(), design_skills=lambda: [{"name": "House style", "text": "Rounded corners, calm colours."}],
        context=lambda: {"user_tabs": [], "agents": ["Coder"], "skills": ["Summaries"]},
        read_upload=lambda upload_id: ({"kind": "image", "name": "mock.png", "mime": "image/png", "data": b"png"}
                                       if upload_id == "img1" else {"kind": "file", "name": "brief.md", "text": "Budget brief"}),
        read_link=lambda url: {"title": "A page", "text": "Readable text " * 20},
        create_tab=create_tab, delete_tab=lambda tab_id: log["tabs"].pop(tab_id, None) is not None,
        file_code=lambda change, prompt, by: log["code"].append((change["target"], by)) or "chg1",
        code_status=lambda change_id: {"status": "approved", "state": "running", "message": "Running the tests"},
        propose_ui=propose_ui, open_ui=lambda ui_root: log["ui"].append(("open", str(ui_root))),
        apply_ui=lambda proposal_id: log["ui"].append(("apply", proposal_id)) or {"lines": {"files": [{"path": "NotesPanel.tsx"}]}},
        undo_ui=lambda proposal_id: log["ui"].append(("undo", proposal_id)) or {},
        suggestion=lambda item, by: log["suggestions"].append(item) or f"Skill “{item['spec']['name']}” added.",
        build=lambda folder: (log.__setitem__("builds", log["builds"] + 1) or True, "built in 1s"),
    )
    engine = ApplyJobs(hooks=hooks, root=root, ui_root=ui_root, store=tmp_path / "jobs.json", threaded=False)
    return SimpleNamespace(engine=engine, log=log, root=root, ui_root=ui_root)


def test_a_request_becomes_a_plan_and_nothing_is_applied_yet(world):
    job = world.engine.start("Make me a budget tab like this picture, calmer notes header", uploads=["img1", "doc1"],
                             links=["https://example.com/guide"])
    assert job["status"] == "ready"
    kinds = [c["kind"] for c in job["changes"]]
    assert kinds == ["tab", "skill", "code", "ui"]                      # auth.py and "rocket" were left out
    assert any("protected" in n for n in job["notes"]) and any("unknown kind" in n for n in job["notes"])
    assert all(c["status"] == "proposed" for c in job["changes"])
    assert world.log["tabs"] == {} and world.log["code"] == [] and world.log["suggestions"] == []
    ui = job["changes"][3]
    assert ui["target"] == "panels/NotesPanel.tsx" and ui["proposal"]["id"] == "p1"    # a diff to read, not written
    assert ("apply", "p1") not in world.log["ui"]


def test_pictures_are_read_for_layout_and_design_guidance_is_used(world):
    world.engine.start("Make the budget tab look like this", uploads=["img1"])
    assert "regions" in world.log["vision"][0] and "reproduce" in world.log["vision"][0]
    prompt = world.log["prompts"][0]
    assert "sidebar left, three cards" in prompt
    assert "Apple HIG — Layout" in prompt and "General design principles" in prompt and "House style" in prompt
    assert "From a web search" in prompt
    assert "Notes, Code" in prompt                                       # the tabs that ship, read from tabs.ts


def test_a_request_about_behaviour_skips_design_guidance(world):
    world.engine.start("Retry the router when a provider times out", search=False)
    prompt = world.log["prompts"][0]
    assert "Apple HIG" not in prompt and "From a web search" not in prompt


def test_the_owner_applies_each_change(world):
    job = world.engine.start("budget tab and calmer notes header")
    tab = world.engine.decide(job["id"], 0, "apply")["changes"][0]
    assert tab["status"] == "applied" and list(world.log["tabs"].values()) == ["Budget"]
    skill = world.engine.decide(job["id"], 1, "apply")["changes"][1]
    assert skill["status"] == "applied" and world.log["suggestions"][0]["spec"]["name"] == "Budget helper"
    code = world.engine.decide(job["id"], 2, "apply")["changes"][2]
    assert world.log["code"] == [("router.py", "Owner")] and code["implement"]["state"] == "running"
    after = world.engine.decide(job["id"], 3, "apply")
    assert ("apply", "p1") in world.log["ui"] and after["needs_rebuild"] is True
    with pytest.raises(ApplyError):
        world.engine.decide(job["id"], 0, "apply")                      # once only


def test_tabs_and_interface_edits_can_be_undone(world):
    job = world.engine.start("budget tab and calmer notes header")
    world.engine.decide(job["id"], 0, "apply")
    world.engine.decide(job["id"], 0, "undo")
    assert world.log["tabs"] == {}
    world.engine.decide(job["id"], 3, "apply")
    undone = world.engine.decide(job["id"], 3, "undo")
    assert ("undo", "p1") in world.log["ui"] and undone["changes"][3]["status"] == "undone"
    with pytest.raises(ApplyError, match="Improve"):
        world.engine.decide(job["id"], 1, "apply") and world.engine.decide(job["id"], 1, "undo")


def test_a_bad_colour_does_not_cost_the_whole_tab():
    change, note = vet_change({"kind": "tab", "title": "T", "tab": {"label": "Budget", "icon": "not an icon", "accent": "red",
                                                                     "blocks": [{"type": "notes"}], "connectors": ["computer"]}},
                              root=apply_engine.PROJECT_DIR, ui_root=apply_engine.PROJECT_DIR)
    assert change and not note and change["tab"]["icon"] == "ph-squares-four" and change["tab"]["connectors"] == []
    missing, why = vet_change({"kind": "tab", "title": "T", "tab": {"label": "Empty", "blocks": []}},
                              root=apply_engine.PROJECT_DIR, ui_root=apply_engine.PROJECT_DIR)
    assert missing is None and "not usable" in why


def test_interface_targets_must_be_real_files_inside_the_app(world):
    outside, why = vet_change({"kind": "ui", "title": "Escape", "target": "../../secrets.css", "description": "x"},
                              root=world.root, ui_root=world.ui_root)
    assert outside is None and "not an interface file" in why
    made_up, _ = vet_change({"kind": "ui", "title": "New", "target": "panels/Nope.tsx", "description": "x"},
                            root=world.root, ui_root=world.ui_root)
    assert made_up is None


def test_rebuild_runs_once_and_clears_the_flag(world):
    job = world.engine.start("calmer notes header")
    world.engine.decide(job["id"], 3, "apply")
    status = world.engine.rebuild()
    assert status["state"] == "done" and world.log["builds"] == 1
    assert world.engine.get(job["id"])["needs_rebuild"] is False


def test_one_request_at_a_time_and_jobs_survive_a_restart(world, tmp_path):
    job = world.engine.start("budget tab")
    again = ApplyJobs(hooks=world.engine.hooks, root=world.root, ui_root=world.ui_root, store=tmp_path / "jobs.json",
                      threaded=False)
    assert again.get(job["id"])["changes"][0]["title"] == "Budget tab"
    with pytest.raises(ApplyError):
        world.engine.start("   ")


def test_routes_are_owner_only(monkeypatch, world):
    from fastapi.testclient import TestClient

    import server

    monkeypatch.setattr(apply_engine, "_JOBS", world.engine)
    remote = TestClient(server.app, client=("203.0.113.12", 50091))
    assert remote.get("/api/apply").status_code == 403
    assert remote.post("/api/apply", json={"prompt": "add a tab"}).status_code == 403
    assert remote.post("/api/apply/rebuild").status_code == 403
    local = TestClient(server.app, client=("127.0.0.1", 50092))
    body = local.post("/api/apply", json={"prompt": "budget tab", "search": False}).json()
    assert body["status"] == "ready"
    assert local.post(f"/api/apply/{body['id']}/changes/0/apply").json()["changes"][0]["status"] == "applied"
    assert local.get("/api/apply/rebuild").json()["state"] in ("idle", "done")
