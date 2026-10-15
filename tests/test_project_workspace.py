"""A project's working file (project_workspace.py): its folder and drives open read-only and never outside themselves,
text files and notes go into its knowledge, Google Drive waits on sign-in, helpers are put on it, the load balance
picks the emptiest free thread, and a Library item opens in one chat."""

import pytest


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    import project_knowledge
    import project_workspace
    import projects

    monkeypatch.setattr(projects, "_path", lambda: tmp_path / "projects.json")
    monkeypatch.setattr(project_knowledge, "_path", lambda: tmp_path / "knowledge.json")
    folder = tmp_path / "Moon base"
    (folder / "plans").mkdir(parents=True)
    (folder / "notes.md").write_text("# Notes\nThe dome needs air.", encoding="utf-8")
    (folder / "photo.png").write_bytes(b"\x89PNG")
    (folder / ".secret").write_text("hidden", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("not yours", encoding="utf-8")
    project = projects.create("Moon base")
    projects.update(project["id"], {"folder": str(folder), "drives": ["drive:Shared plans", " ", "drive:Shared plans"]})
    return project_workspace, projects, project["id"], folder, tmp_path


def test_drives_are_kept_once_each(ws):
    _w, projects, pid, _folder, _tmp = ws
    assert projects.get(pid)["drives"] == ["drive:Shared plans"]


def test_the_folder_lists_folders_first_and_hides_dot_files(ws):
    w, _p, pid, _folder, _tmp = ws
    listing = w.browse(pid)
    names = [e["name"] for e in listing["entries"]]
    assert names == ["plans", "notes.md", "photo.png"]
    assert listing["up"] == ""
    assert [e["name"] for e in w.browse(pid, match="note")["entries"]] == ["notes.md"]


def test_nothing_outside_the_folder_and_drives_opens(ws):
    w, _p, pid, _folder, tmp = ws
    with pytest.raises(w.WorkspaceError, match="outside"):
        w.browse(pid, str(tmp))
    with pytest.raises(w.WorkspaceError, match="outside"):
        w.add_file(pid, "../outside.txt")


def test_google_drive_waits_on_sign_in(ws):
    w, _p, pid, _folder, _tmp = ws
    with pytest.raises(w.WorkspaceError, match="Google sign-in"):
        w.browse(pid, "drive:Shared plans")


def test_a_text_file_goes_into_the_knowledge_and_a_picture_does_not(ws):
    import project_knowledge

    w, _p, pid, _folder, _tmp = ws
    assert w.add_file(pid, "notes.md")["title"] == "notes.md"
    assert [d["title"] for d in project_knowledge.list_docs(pid)] == ["notes.md"]
    with pytest.raises(w.WorkspaceError, match="text files"):
        w.add_file(pid, "photo.png")
    found = w.find(pid, "notes dome")
    assert any(f["path"].endswith("notes.md") for f in found["files"])


def test_a_helper_is_put_on_the_project(ws):
    w, projects, pid, _folder, _tmp = ws
    assert w.add_helper(pid, "Researcher")["made"] is False
    assert projects.get(pid)["members"]["agents"] == ["Researcher"]


def test_the_balance_skips_busy_and_full_threads():
    import project_workspace as w

    rows = [
        {"title": "Busy", "status": "working", "job": "build", "tokens": {"share": 0.1}},
        {"title": "Full", "status": "idle", "job": "build", "tokens": {"share": 0.9}},
        {"title": "Roomy", "status": "idle", "job": "build", "tokens": {"share": 0.3}},
        {"title": "Emptiest", "status": "idle", "job": "build", "tokens": {"share": 0.05}},
        {"title": "Researcher", "status": "idle", "job": "research", "tokens": {"share": 0.0}},
        {"title": "Old", "status": "resolved", "job": "build", "tokens": {"share": 0.0}},
    ]
    found = w.balance(rows, "build")
    assert found["pick"] == "Emptiest"
    assert found["counts"] == {"free": 3, "busy": 1, "waiting": 0, "full": 1}
    assert w.balance(rows[:2])["pick"] == "" and "new thread" in w.balance(rows[:2])["advice"]


def test_a_library_item_opens_in_one_chat(ws):
    from types import SimpleNamespace

    w, projects, pid, _folder, _tmp = ws

    class Store:
        def __init__(self):
            self.chats = {}

        def create(self, title=None, activate=True):
            chat_id = f"c{len(self.chats) + 1}"
            self.chats[chat_id] = []
            return chat_id

        def exists(self, chat_id):
            return chat_id in self.chats

        def append(self, role, content, chat_id=None, extra=None):
            self.chats[chat_id].append(SimpleNamespace(role=role, content=content))

    store = Store()
    item = projects.add_artifact("Dome plan", "plan", "Three layers of glass.", pid)
    first = w.artifact_chat(item["id"], store)
    assert w.artifact_chat(item["id"], store) == first
    assert "Three layers of glass." in store.chats[first][0].content
