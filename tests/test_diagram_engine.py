"""Diagrams and pictures for the chat overlay (Request R14)."""

import json

import pytest
from fastapi.testclient import TestClient

import diagram_engine


def test_a_messy_model_reply_becomes_a_drawable_spec():
    spec = diagram_engine.clean_spec({
        "title": "  How a request flows  ", "kind": "nonsense",
        "nodes": ["You", {"id": "Turn Runner", "label": "Turn runner", "sub": "plans and calls tools", "group": "Engine", "shape": "round"},
                  {"label": ""}, {"id": "tools", "label": "Tools", "shape": "wobbly"}],
        "edges": [{"from": "You", "to": "Turn runner", "label": "asks"}, {"from": "turn-runner", "to": "tools"},
                  {"from": "tools", "to": "tools"}, {"from": "nowhere", "to": "tools"}, {"bad": "row"}],
        "notes": ["one", "two"],
    }, request="how a request flows")
    assert spec["kind"] == "flow" and spec["title"] == "How a request flows"
    assert [n["label"] for n in spec["nodes"]] == ["You", "Turn runner", "Tools"]
    assert spec["nodes"][1]["shape"] == "round" and spec["nodes"][2]["shape"] == "box"   # unknown shape falls back
    assert len(spec["edges"]) == 2                                                        # self-links and unknown ids dropped
    assert spec["edges"][0]["from"] == "you" and spec["edges"][0]["to"] == "turn-runner"
    assert [g["label"] for g in spec["groups"]] == ["Engine"]                             # a group named on a node is kept
    with pytest.raises(diagram_engine.DiagramError):
        diagram_engine.clean_spec({"nodes": []})
    with pytest.raises(diagram_engine.DiagramError):
        diagram_engine.clean_spec("not a diagram at all")


def test_asking_about_nyx_draws_this_install_not_a_guess():
    assert diagram_engine.is_self_request("show me a diagram of how you, the ai works")
    assert diagram_engine.is_self_request("diagram your agents and tools")
    assert not diagram_engine.is_self_request("draw how photosynthesis works")
    spec = diagram_engine.self_portrait()
    labels = {n["label"] for n in spec["nodes"]}
    assert {"You", "Turn runner"} <= labels
    assert spec["source"] == "itself" and spec["caption"]
    assert any(n["group"] == "Knowledge" for n in spec["nodes"])
    assert all(any(n["id"] == edge["from"] for n in spec["nodes"]) for edge in spec["edges"])


def test_a_simple_request_takes_one_call_and_a_complex_one_takes_two():
    calls = []

    def model(prompt, *, system="", max_tokens=1200, role=""):
        calls.append(prompt[:30])
        if prompt.startswith("Here is a diagram"):
            return json.dumps({"title": "Checked", "kind": "flow", "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"},
                                                                             {"id": "c", "label": "C"}],
                               "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}]})
        return json.dumps({"title": "First", "kind": "flow", "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                           "edges": [{"from": "a", "to": "b"}]})

    simple = diagram_engine.make("a login flow", model_fn=model)
    assert simple["helpers"] == 1 and len(calls) == 1 and simple["title"] == "First"
    calls.clear()
    complex_one = diagram_engine.make("compare the full end to end architecture of both systems and their pipelines", model_fn=model)
    assert complex_one["helpers"] == 2 and len(calls) == 2 and complex_one["title"] == "Checked"


def test_without_a_model_it_still_opens_with_something_real():
    def broken(*args, **kwargs):
        raise RuntimeError("no model")

    spec = diagram_engine.make("how options pricing works with volatility", model_fn=broken)
    assert spec["source"] == "offline" and len(spec["nodes"]) >= 2
    assert "No model was reachable" in spec["caption"]


def test_pictures_come_with_a_licence_and_a_source():
    class Response:
        def __init__(self, payload):
            self.status_code = 200
            self._payload = payload

        def json(self):
            return self._payload

    payload = {"results": [{"url": "https://img.example/a.jpg", "thumbnail": "https://img.example/a-t.jpg", "title": "A cat",
                            "foreign_landing_url": "https://openverse.org/image/1", "license": "cc-by", "creator": "Someone"}]}
    images = diagram_engine.find_image("cat", limit=1, get=lambda url, **kw: Response(payload))
    assert images[0]["licence"] == "CC-BY" and images[0]["where"] == "Openverse" and images[0]["source"].startswith("https://")


def test_saving_drawing_and_reopening(tmp_path, monkeypatch):
    monkeypatch.setattr(diagram_engine, "_dir", lambda: tmp_path)
    spec = diagram_engine.save(diagram_engine.self_portrait())
    again = diagram_engine.load(spec["id"])
    assert again["title"] == spec["title"]
    drawn = diagram_engine.update(spec["id"], {"strokes": [{"color": "#fff", "size": 3, "points": [[1, 2], [3, 4]]}], "title": "My copy"})
    assert drawn["title"] == "My copy" and drawn["strokes"][0]["points"] == [[1, 2], [3, 4]]
    assert diagram_engine.load(spec["id"])["strokes"]
    assert diagram_engine.recent()[0]["id"] == spec["id"]
    with pytest.raises(diagram_engine.DiagramError):
        diagram_engine.load("nothing")


def test_the_tool_opens_the_overlay_and_says_what_it_drew(tmp_path, monkeypatch):
    monkeypatch.setattr(diagram_engine, "_dir", lambda: tmp_path)
    published = []
    monkeypatch.setattr("agent_events.publish_ui", lambda kind, **payload: published.append((kind, payload)))
    reply = diagram_engine.tool_show_diagram("show me a diagram of how you work")
    assert "Opened a diagram" in reply and "[diagram:" in reply
    assert published and published[0][0] == "diagram.open"


@pytest.fixture()
def client():
    import server

    return TestClient(server.app, client=("127.0.0.1", 50051))


def test_routes_make_and_update_a_diagram(client, tmp_path, monkeypatch):
    monkeypatch.setattr(diagram_engine, "_dir", lambda: tmp_path)
    monkeypatch.setattr(diagram_engine, "make", lambda request, **kw: diagram_engine.clean_spec(
        {"title": "Made", "nodes": [{"id": "a", "label": "A"}], "edges": []}, request=request))
    made = client.post("/api/diagram", json={"request": "anything"})
    assert made.status_code == 200, made.text
    diagram_id = made.json()["diagram"]["id"]
    assert client.get(f"/api/diagram/{diagram_id}").json()["diagram"]["title"] == "Made"
    updated = client.put(f"/api/diagram/{diagram_id}", json={"title": "Renamed", "strokes": [{"color": "#fff", "size": 2, "points": [[0, 0]]}]})
    assert updated.json()["diagram"]["title"] == "Renamed"
    assert client.get("/api/diagram").json()["recent"][0]["id"] == diagram_id
    assert client.get("/api/diagram/missing").status_code == 409
