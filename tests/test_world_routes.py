"""The World tab's HTTP surface (U34–U40): the owner's own machine only. Running a world end to end is covered in
``test_world_engine``; these are the routes around it."""

import types

import pytest
from fastapi.testclient import TestClient

import server
from office import casting, focus, library
from office import roles as role_module
from office.engine import ENGINE as OFFICE
from world import store
from world.engine import ENGINE


@pytest.fixture
def client(tmp_path, monkeypatch):
    library.use_root(tmp_path / "offices")
    store.use_root(tmp_path / "worlds")
    monkeypatch.setattr(casting, "members", lambda domain="", **kwargs: [
        {"member": "fake:m1", "provider": "fake", "model": "m1", "score": 0.9, "local": True, "free": True}])
    monkeypatch.setattr(casting, "capacity",
                        lambda **kwargs: casting.Capacity(agents=30, concurrency=3, members=1, reason="test"))
    monkeypatch.setattr(casting, "_device", lambda: types.SimpleNamespace(max_workers=4, ram_gb=16))
    monkeypatch.setattr(role_module, "add_to_subagents", lambda role, office_name: "(roster untouched in tests)")
    OFFICE.reset_for_tests()
    ENGINE.reset_for_tests()
    focus.reset_for_tests()
    yield TestClient(server.app, client=("127.0.0.1", 50502))
    ENGINE.reset_for_tests()
    OFFICE.reset_for_tests()
    focus.reset_for_tests()
    library.use_root(None)
    store.use_root(None)


def test_the_tab_opens_on_an_empty_lobby_with_this_machines_limits(client):
    body = client.get("/api/world").json()

    assert body["worlds"] == [] and body["running"] == ""
    assert body["limits"]["machine"] == "medium" and body["limits"]["max_speed"] == "fast"
    assert [s["allowed"] for s in body["limits"]["speeds"]] == [True, True, True, False]


def test_a_world_is_made_read_changed_and_put_in_the_trash(client):
    made = client.post("/api/world/worlds", json={"name": "Atlas", "goal": "Map the market",
                                                  "duration": "2 days", "speed": "rush"}).json()
    world_id = made["world"]["id"]

    assert made["world"]["speed"] == "fast", "clamped to what this machine can run"
    assert made["world"]["duration"] == 2 * 86400
    assert client.get(f"/api/world/worlds/{world_id}").json()["world"]["name"] == "Atlas"

    changed = client.patch(f"/api/world/worlds/{world_id}", json={"name": "Atlas Two", "duration": "until done"}).json()
    assert changed["world"]["name"] == "Atlas Two" and changed["world"]["duration"] == 0
    bad = client.patch(f"/api/world/worlds/{world_id}", json={"duration": "soonish"})
    assert bad.status_code == 409

    law = client.post(f"/api/world/worlds/{world_id}/laws", json={"text": "Every report names its sources."}).json()
    assert law["status"] == "testing"
    enforced = client.post(f"/api/world/worlds/{world_id}/laws/{law['lid']}", json={"action": "enforce"}).json()
    assert enforced["status"] == "enforced"
    refused = client.post(f"/api/world/worlds/{world_id}/laws", json={"text": "Publish everything now."}).json()
    assert refused["status"] == "rejected"
    assert client.post(f"/api/world/worlds/{world_id}/laws/{refused['lid']}",
                       json={"action": "enforce"}).status_code == 409

    speed = client.post(f"/api/world/worlds/{world_id}/speed", json={"speed": "deliberate"}).json()
    assert speed["world"]["speed"] == "deliberate"

    gone = client.delete(f"/api/world/worlds/{world_id}").json()
    assert ".trash" in gone["trashed"] and client.get("/api/world").json()["worlds"] == []
    assert client.get(f"/api/world/worlds/{world_id}").status_code == 409
    assert any(o["id"] == made["world"]["office_id"] for o in library.tree()["offices"]), "its office stays"


def test_upscale_lists_offices_and_marks_the_one_that_has_a_world(client):
    office = client.post("/api/office/offices", json={"name": "Client site"}).json()["office"]

    body = client.post("/api/world/upscale", json={"office_id": office["id"], "goal": "Rebuild it"}).json()

    assert body["world"]["office_id"] == office["id"]
    row = next(o for o in client.get("/api/world").json()["offices"] if o["id"] == office["id"])
    assert row["has_world"] is True


def test_asking_for_things_that_are_not_there_is_a_readable_409(client):
    made = client.post("/api/world/worlds", json={"name": "Quiet"}).json()
    world_id = made["world"]["id"]

    start = client.post(f"/api/world/worlds/{world_id}/control", json={"action": "start"})
    assert start.status_code == 409 and "goal" in start.json()["detail"]
    assert client.post(f"/api/world/worlds/{world_id}/wars/war-nope/hearing").status_code == 409
    assert client.post(f"/api/world/worlds/{world_id}/startups/su-nope", json={"action": "approve"}).status_code == 409
    assert client.post(f"/api/world/worlds/{world_id}/graves/9/rejoin").status_code == 409
    assert client.post(f"/api/world/worlds/{world_id}/mood", json={"agent_id": "agt-nope"}).status_code == 409
