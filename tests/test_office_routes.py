"""The Office Space HTTP surface (Project Null N8): the owner's own machine only, and nothing else.

Job-running is covered in ``test_office_engine``; these are the routes around it — the lobby (office files and
folders, drag and drop, link work flows, open in File Explorer), the snapshot the tab renders, the live
"who would get this" preview, focus mode and the settings.
"""

import pytest
from fastapi.testclient import TestClient

import server
from office import casting, focus, library
from office.engine import ENGINE


@pytest.fixture
def client(tmp_path, monkeypatch):
    library.use_root(tmp_path / "offices")
    monkeypatch.setattr(casting, "members", lambda domain="", **kwargs: [
        {"member": "fake:m1", "provider": "fake", "model": "m1", "score": 0.9, "local": True, "free": True}])
    monkeypatch.setattr(casting, "capacity",
                        lambda **kwargs: casting.Capacity(agents=30, concurrency=3, members=1, reason="test"))
    ENGINE.reset_for_tests()
    focus.reset_for_tests()
    yield TestClient(server.app, client=("127.0.0.1", 50501))
    ENGINE.reset_for_tests()
    focus.reset_for_tests()
    library.use_root(None)


def test_the_tab_opens_on_an_empty_library_and_says_so(client):
    body = client.get("/api/office").json()

    assert body["first_run"] is True, "the very first open makes an office and opens the chat instead of a lobby"
    assert body["library"]["offices"] == [] and body["library"]["folders"] == []
    assert body["settings"]["focus_mode"] == "ask"
    assert body["capacity"]["agents"] >= 10


def test_making_an_office_answers_with_the_whole_snapshot(client):
    body = client.post("/api/office/offices", json={"name": "New idea"}).json()

    assert body["office"]["name"] == "New idea"
    assert [s["name"] for s in body["sections"]] == ["Head Office"]
    assert body["agents"][0]["role"] == "top-manager"
    assert client.get("/api/office").json()["first_run"] is False


def test_folders_nest_and_offices_drag_into_them(client):
    folder = client.post("/api/office/folders", json={"name": "Client work"}).json()["folder"]
    inner = client.post("/api/office/folders", json={"name": "Acme", "parent": folder["id"]}).json()["folder"]
    office = client.post("/api/office/offices", json={"name": "Loose"}).json()["office"]

    moved = client.patch(f"/api/office/items/{office['id']}", json={"parent": inner["id"]}).json()["item"]

    assert moved["parent"] == inner["id"]
    tree = client.get("/api/office/library").json()
    assert {f["name"] for f in tree["folders"]} == {"Client work", "Acme"}
    assert tree["offices"][0]["parent"] == inner["id"]


def test_link_work_flows_is_a_folder_switch(client):
    folder = client.post("/api/office/folders", json={"name": "One flow"}).json()["folder"]
    client.post("/api/office/offices", json={"name": "A", "parent": folder["id"]})
    second = client.post("/api/office/offices", json={"name": "B", "parent": folder["id"]}).json()["office"]

    client.patch(f"/api/office/items/{folder['id']}", json={"linked": True})

    snapshot = client.get(f"/api/office/offices/{second['id']}").json()
    assert [o["name"] for o in snapshot["office"]["linked_offices"]] == ["A"]
    assert snapshot["office"]["folder"]["linked"] is True


def test_deleting_an_office_keeps_it_in_the_trash(client):
    office = client.post("/api/office/offices", json={"name": "Throwaway"}).json()["office"]

    result = client.delete(f"/api/office/items/{office['id']}").json()

    assert "trashed" in result
    assert client.get("/api/office/library").json()["offices"] == []
    assert client.get(f"/api/office/offices/{office['id']}").status_code == 409


def test_the_targeted_preview_never_needs_a_model(client):
    office = client.post("/api/office/offices", json={"name": "Aim"}).json()["office"]

    body = client.post(f"/api/office/offices/{office['id']}/resolve",
                       json={"text": "top manager: how is it going?"}).json()

    assert body["count"] == 1 and body["label"].startswith("Top Manager")
    assert body["message"] == "how is it going?"

    nobody = client.post(f"/api/office/offices/{office['id']}/say", json={"text": "hey marketing"})
    assert nobody.status_code == 409, "a message with no recipients is refused, not silently dropped"


def test_control_pause_and_resume_on_an_idle_office(client):
    office = client.post("/api/office/offices", json={"name": "Controls"}).json()["office"]
    agent_id = client.get(f"/api/office/offices/{office['id']}").json()["agents"][0]["id"]

    paused = client.post(f"/api/office/offices/{office['id']}/control",
                         json={"action": "pause", "scope": "agent", "id": agent_id}).json()
    assert [a["status"] for a in paused["agents"]] == ["paused"]

    resumed = client.post(f"/api/office/offices/{office['id']}/control",
                          json={"action": "resume", "scope": "office"}).json()
    assert [a["status"] for a in resumed["agents"]] == ["idle"]

    assert client.post(f"/api/office/offices/{office['id']}/control", json={"action": "sit down"}).status_code == 409


def test_deliver_now_and_auto_decisions(client):
    """Update 1: the Output box's Deliver now (U41) and the Auto decisions switch (U42)."""
    office = client.post("/api/office/offices", json={"name": "Outputs"}).json()["office"]
    early = client.post(f"/api/office/offices/{office['id']}/deliver")
    assert early.status_code == 409 and "give the office a job" in early.json()["detail"]

    on = client.post(f"/api/office/offices/{office['id']}/options", json={"auto_decisions": True}).json()
    assert on["office"]["settings"]["auto_decisions"] is True
    assert on["outputs"] == [] and on["staffing"] == []
    off = client.post(f"/api/office/offices/{office['id']}/options", json={"auto_decisions": False}).json()
    assert off["office"]["settings"]["auto_decisions"] is False


def test_files_and_memory_are_readable_and_forgettable(client):
    from office import memory

    office = client.post("/api/office/offices", json={"name": "Files"}).json()["office"]
    (library.work_dir(office["id"]) / "notes.md").write_text("# hello", encoding="utf-8")
    entry = memory.add(office["id"], "The owner prefers dark mode.", kind="decision")

    files = client.get(f"/api/office/offices/{office['id']}/files").json()
    assert [f["path"] for f in files["files"]] == ["notes.md"]
    assert client.get(f"/api/office/offices/{office['id']}/file", params={"path": "notes.md"}).json()["text"] == "# hello"
    assert client.get(f"/api/office/offices/{office['id']}/file", params={"path": "../../secrets"}).status_code == 404

    assert len(client.get(f"/api/office/offices/{office['id']}/memory").json()["entries"]) == 1
    assert client.delete(f"/api/office/offices/{office['id']}/memory/{entry['id']}").json()["entries"] == []


def test_focus_mode_can_be_answered_once_and_remembered(client):
    body = client.post("/api/office/focus", json={"action": "enter", "remember": "always"}).json()

    assert body["held"] is True
    assert client.get("/api/office/settings").json()["settings"]["focus_mode"] == "always"

    left = client.post("/api/office/focus", json={"action": "leave"}).json()
    assert left["held"] is False
    client.put("/api/office/settings", json={"changes": {"focus_mode": "ask"}})


def test_none_of_it_is_reachable_from_another_computer(tmp_path):
    library.use_root(tmp_path / "offices")
    try:
        remote = TestClient(server.app, client=("203.0.113.44", 50502))
        for method, path, body in (("get", "/api/office", None),
                                   ("get", "/api/office/library", None),
                                   ("post", "/api/office/offices", {"name": "theirs"}),
                                   ("post", "/api/office/focus", {"action": "enter"})):
            call = getattr(remote, method)
            response = call(path, json=body) if body is not None else call(path)
            assert response.status_code == 403, f"{path} answered a remote caller"
    finally:
        library.use_root(None)


def test_office_routes_do_not_exist_on_a_hosted_build():
    import deploy_mode

    assert "/api/office" in deploy_mode.HOSTED_BLOCKED_PREFIXES
