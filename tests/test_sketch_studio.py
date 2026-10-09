"""The Create tab's drawing studio (U2): Nyx draws as checked data, scans to improve, and the owner's drawings."""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest

import sketch_studio as sk

PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()


class FakeRoles:
    def __init__(self, text):
        self.text, self.calls = text, []

    def run(self, role, prompt, **kwargs):
        self.calls.append((role, prompt, kwargs))
        return SimpleNamespace(text=self.text, label="fake model")


def test_shapes_are_checked_and_clamped_and_anything_else_is_dropped():
    shapes = sk.clean_shapes([
        {"kind": "rect", "x": -999, "y": 10, "w": 99999, "h": 20, "fill": "red", "stroke": "javascript:alert(1)"},
        {"kind": "circle", "cx": 500, "cy": 300, "r": 40, "fill": "#ABCDEF"},
        {"kind": "path", "points": [[0, 0]] * 500, "stroke": "#000"},
        {"kind": "script", "code": "alert(1)"},
        {"kind": "text", "x": 10, "y": 10, "text": "<b>hi</b>" * 30},
        {"kind": "polygon", "points": [[1, 1], [2, 2]]},
    ])
    kinds = [s["kind"] for s in shapes]
    assert kinds == ["rect", "ellipse", "path", "text"]
    rect, ellipse, path, text = shapes
    assert rect["x"] == -50 and rect["w"] <= sk.WIDTH + 100 and rect["fill"] == "#e5484d" and rect["stroke"] == "#111111"
    assert ellipse["rx"] == ellipse["ry"] == 40 and ellipse["fill"] == "#abcdef"
    assert len(path["points"]) == sk.MAX_POINTS
    assert len(text["text"]) <= 80


def test_nyx_draws_from_a_fenced_or_bare_json_answer(monkeypatch):
    answer = "Sure!\n```json\n" + json.dumps({"say": "A sun.", "shapes": [
        {"kind": "ellipse", "cx": 800, "cy": 120, "rx": 60, "ry": 60, "fill": "yellow"}]}) + "\n```"
    roles = FakeRoles(answer)
    monkeypatch.setattr(sk, "_roles", lambda: roles)
    out = sk.draw("a sun in the corner")
    assert out["shapes"][0]["fill"] == "#ffd60a" and out["say"] == "A sun."
    assert roles.calls[0][0] == "code_generation"
    roles.text = "I cannot draw."
    with pytest.raises(sk.SketchError):
        sk.draw("a sun")
    with pytest.raises(sk.SketchError):
        sk.draw("   ")


def test_scan_sends_the_drawing_to_the_vision_role_and_returns_improvements(monkeypatch):
    roles = FakeRoles(json.dumps({"sees": "A house.", "suggestions": ["Add a door", "Add a sky"],
                                  "shapes": [{"kind": "rect", "x": 450, "y": 400, "w": 60, "h": 100, "fill": "brown"}]}))
    monkeypatch.setattr(sk, "_roles", lambda: roles)
    out = sk.scan(PNG, "make it cosy")
    role, prompt, kwargs = roles.calls[0]
    assert role == "image_check" and kwargs["images"][0][1] == "image/png" and "cosy" in prompt
    assert out["sees"] == "A house." and len(out["suggestions"]) == 2 and out["shapes"][0]["fill"] == "#8d5b3a"
    with pytest.raises(sk.SketchError):
        sk.scan("not a picture")


def test_drawings_are_saved_listed_and_loaded(tmp_path, monkeypatch):
    monkeypatch.setattr(sk, "data_path", lambda name: tmp_path / name)
    saved = sk.save(PNG, "My House")
    listed = sk.sketches()
    assert listed[0]["id"] == saved["id"] and listed[0]["name"] == "my house"
    assert sk.load(saved["id"]) == PNG
    with pytest.raises(sk.SketchError):
        sk.load("../../secrets")


def test_sketch_routes_are_the_owner_s():
    from fastapi.testclient import TestClient

    import server

    remote = TestClient(server.app, client=("203.0.113.9", 50061))
    for method, path, body in (("post", "/api/sketch/draw", {"request": "a cat"}), ("post", "/api/sketch/scan", {"image": PNG}),
                               ("post", "/api/sketch/render", {"request": "x"}), ("get", "/api/sketch/saved", None),
                               ("post", "/api/sketch/saved", {"image": PNG}), ("get", "/api/sketch/saved/abc", None)):
        call = getattr(remote, method)
        response = call(path, json=body) if body is not None else call(path)
        assert response.status_code in (401, 403), path
