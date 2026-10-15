"""Routes for the Memories screen: add, edit (keep mark and reason), delete by id."""

from types import SimpleNamespace

import pytest

from memory import MemoryStore


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import server

    store = MemoryStore(path=tmp_path / "memory.json")
    fake = SimpleNamespace(memory=store, rag=SimpleNamespace(mark_dirty=lambda: None))
    monkeypatch.setattr(server, "_get_service", lambda chat_id=None: fake)
    monkeypatch.setattr(server, "_get_rag", lambda: SimpleNamespace(mark_dirty=lambda: None))
    return TestClient(server.app, client=("127.0.0.1", 50123))


def test_add_edit_and_delete_by_id(client):
    added = client.post("/api/memory/important", json={"topic": "pet", "content": "A cat", "keep": True, "keep_reason": "family"})
    assert added.status_code == 200
    memory = added.json()["memory"]
    assert memory["id"].startswith("mem_") and memory["keep"] is True

    edited = client.patch(f"/api/memory/important/{memory['id']}", json={"content": "Two cats", "keep": False})
    assert edited.status_code == 200 and edited.json()["memory"]["content"] == "Two cats"
    assert edited.json()["memory"]["keep"] is False

    listed = client.get("/api/memory").json()["important"]
    assert [item["id"] for item in listed] == [memory["id"]]

    assert client.delete(f"/api/memory/important/{memory['id']}").json() == {"removed": True}
    assert client.get("/api/memory").json()["important"] == []


def test_bad_edits_are_refused(client):
    assert client.patch("/api/memory/important/mem_nope", json={"content": "x"}).status_code == 404
    assert client.post("/api/memory/important", json={"topic": " ", "content": "x"}).status_code == 400

