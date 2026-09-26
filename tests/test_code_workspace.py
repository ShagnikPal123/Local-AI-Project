"""Code tab: edits are proposals until accepted, conflicts are caught, undo is safe (Request G7)."""

from __future__ import annotations

import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import code_workspace


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(code_workspace, "_state_path", lambda: tmp_path / "code_workspaces.json")
    import paths

    real = paths.data_path
    monkeypatch.setattr(code_workspace, "data_path", lambda name: tmp_path / name if name == "code_backups" else real(name))


def _fake_model(monkeypatch, text):
    import model_roles

    monkeypatch.setattr(model_roles.MODEL_ROLES, "run", lambda role, prompt, **kw: types.SimpleNamespace(text=text, label="Code · test"))


def test_files_outside_an_opened_folder_are_refused(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "app.py").write_text("print('hi')\n", encoding="utf-8")
    with pytest.raises(code_workspace.CodeError):
        code_workspace.read(str(project / "app.py"))
    code_workspace.open_workspace(str(project / "app.py"))
    assert code_workspace.read(str(project / "app.py"))["total_lines"] == 2
    with pytest.raises(code_workspace.CodeError):
        code_workspace.read(str(tmp_path / "secret.txt"))


def test_a_proposal_writes_nothing_until_applied_then_undo_restores(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    source = project / "calc.py"
    source.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    code_workspace.open_workspace(str(project))
    _fake_model(monkeypatch, '{"explanation": "Validate inputs.", "edits": [{"find": "    return a + b", '
                '"replace": "    if a is None or b is None:\n        raise ValueError(\\"missing\\")\n    return a + b"}]}')
    proposal = code_workspace.propose(str(source), "validate inputs")
    assert "+    if a is None" in proposal["diff"] and proposal["added"] == 2
    assert "raise" not in source.read_text(encoding="utf-8")

    applied = code_workspace.apply(proposal["id"])
    assert applied["status"] == "applied" and "raise ValueError" in source.read_text(encoding="utf-8")
    code_workspace.undo(proposal["id"])
    assert source.read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"


def test_stale_files_and_ambiguous_edits_are_refused(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    source = project / "x.py"
    source.write_text("a = 1\na = 1\nb = 2\n", encoding="utf-8")
    code_workspace.open_workspace(str(project))
    _fake_model(monkeypatch, '{"edits": [{"find": "a = 1", "replace": "a = 3"}]}')
    with pytest.raises(code_workspace.CodeError, match="more than one place"):
        code_workspace.propose(str(source), "change a")

    _fake_model(monkeypatch, '{"edits": [{"find": "b = 2", "replace": "b = 5"}]}')
    proposal = code_workspace.propose(str(source), "change b")
    source.write_text("a = 1\na = 1\nb = 2\nc = 9\n", encoding="utf-8")
    with pytest.raises(code_workspace.CodeError, match="changed since"):
        code_workspace.apply(proposal["id"])


def test_routes_are_owner_only_once_claimed(monkeypatch):
    import server

    client = TestClient(server.app, client=("127.0.0.1", 50004))
    assert client.get("/api/code/workspaces").status_code == 200
    remote = TestClient(server.app, client=("203.0.113.9", 50005))
    assert remote.get("/api/code/workspaces").status_code in (401, 403)



def test_new_files_folders_and_starting_from_scratch_stay_inside_what_the_owner_chose(tmp_path, monkeypatch):
    """Request H12: new file / new folder / start from a template, and nothing outside opened folders."""
    import code_workspace as cw

    monkeypatch.setattr(cw, "_state_path", lambda: tmp_path / "state.json")
    parent = tmp_path / "projects"
    parent.mkdir()
    workspace = cw.start_project(str(parent), "Weather App", "website")
    root = Path(workspace["path"])
    assert (root / "index.html").read_text(encoding="utf-8").count("Weather App") >= 2

    made = cw.create_file(str(root / "src" / "app.js"), "export {};\n")
    assert Path(made["path"]).read_text(encoding="utf-8") == "export {};\n"
    cw.create_folder(str(root / "assets"))
    assert (root / "assets").is_dir()
    with pytest.raises(cw.CodeError):
        cw.create_file(str(root / "index.html"))
    with pytest.raises(cw.CodeError):
        cw.create_file(str(tmp_path / "outside.txt"))
    with pytest.raises(cw.CodeError):
        cw.create_folder(str(root / "bad|name"))
    with pytest.raises(cw.CodeError):
        cw.start_project(str(parent), "Weather App", "empty")


def test_building_in_an_empty_folder_is_a_reviewable_proposal_with_undo(tmp_path, monkeypatch):
    import code_workspace as cw
    import model_roles

    monkeypatch.setattr(cw, "_state_path", lambda: tmp_path / "state.json")
    root = tmp_path / "blank"
    root.mkdir()
    cw.open_workspace(str(root))
    reply = ('{"explanation": "A tiny page.", "files": [{"path": "index.html", "content": "<h1>Hi</h1>\\n"},'
             '{"path": "js/app.js", "content": "console.log(1)\\n"}, {"path": "../escape.txt", "content": "x"}]}')
    monkeypatch.setattr(model_roles.MODEL_ROLES, "run", lambda *a, **k: type("R", (), {"text": reply, "label": "test-model"})())

    proposal = cw.propose_files(str(root), "a hello page")
    assert [f["relative"] for f in proposal["files"]] == ["index.html", "js/app.js"]
    assert proposal["skipped"] == ["../escape.txt"] and not (root / "index.html").exists()
    assert "content" not in proposal["files"][0]

    cw.apply(proposal["id"])
    assert (root / "js" / "app.js").read_text(encoding="utf-8") == "console.log(1)\n"
    assert not (tmp_path / "escape.txt").exists()
    cw.undo(proposal["id"])
    assert not (root / "index.html").exists() and not (root / "js").exists()


def test_intent_md_is_understood_starters_get_it_and_proposals_read_it(tmp_path, monkeypatch):
    """Request H14: Anthropic's intent.md — a skill, a /command, a starter file, and context for code proposals."""
    import code_workspace as cw
    import commands
    import intent_md
    import model_roles
    from skills import SkillStore

    store = SkillStore(path=tmp_path / "skills.json")
    assert "Capture intent" in [s.name for s in store.select_for("please write an intent.md for my idea")]
    assert any(c["name"] == "intent" for c in commands.all_commands())
    assert all(f"## {section}" in intent_md.template("X") for section in intent_md.SECTIONS)

    monkeypatch.setattr(cw, "_state_path", lambda: tmp_path / "state.json")
    workspace = cw.start_project(str(tmp_path), "Garden Log", "python")
    root = Path(workspace["path"])
    assert (root / "intent.md").read_text(encoding="utf-8").startswith("# Intent: Garden Log")

    seen = {}

    def fake_run(role, prompt, **kwargs):
        seen["prompt"] = prompt
        return type("R", (), {"text": '{"files": [{"path": "notes.txt", "content": "hi"}]}', "label": "test"})()

    monkeypatch.setattr(model_roles.MODEL_ROLES, "run", fake_run)
    cw.propose_files(str(root), "add a notes file")
    assert "intent.md" in seen["prompt"] and "# Intent: Garden Log" in seen["prompt"]
