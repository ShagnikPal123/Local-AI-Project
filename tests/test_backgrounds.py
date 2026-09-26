"""Custom backgrounds: an upload or a generated picture, with motion that fits (Request G8)."""

from __future__ import annotations

import types

import pytest

import backgrounds


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(backgrounds, "_path", lambda: tmp_path / "backgrounds.json")
    monkeypatch.setattr(backgrounds, "_announce", lambda: None)
    uploads_seen = {"gif1": {"mime": "image/gif", "name": "loop.gif"}, "img1": {"mime": "image/png", "name": "p.png"},
                    "doc1": {"mime": "application/pdf", "name": "x.pdf"}}
    import uploads

    monkeypatch.setattr(uploads, "get_upload", lambda upload_id: uploads_seen.get(upload_id))


def test_motion_is_picked_from_the_words():
    assert backgrounds.pick_animation("Loki, god of time, in the TVA") == "time"
    assert backgrounds.pick_animation("a phoenix rising from embers") == "embers"
    assert backgrounds.pick_animation("a quiet library") == "drift"


def test_a_gif_moves_by_itself_and_a_document_is_refused():
    gif = backgrounds.add("gif1")
    assert gif["kind"] == "gif" and gif["animation"] == "still" and gif["url"] == "/api/uploads/gif1"
    assert backgrounds.state()["active"]["id"] == gif["id"]
    with pytest.raises(ValueError):
        backgrounds.add("doc1")


def test_generated_background_uses_the_image_model_and_can_be_tuned_and_cleared(monkeypatch):
    import image_gen

    calls = []
    monkeypatch.setattr(image_gen, "generate_image", lambda prompt, size="": calls.append((prompt, size)) or types.SimpleNamespace(
        ok=True, image_id="img1", label="NVIDIA FLUX", error="", url="/api/uploads/img1"))
    made = backgrounds.generate("Loki god of time")
    assert made["animation"] == "time" and "wallpaper" in calls[0][0] and calls[0][1] == "1792x1024"
    tuned = backgrounds.update(made["id"], dim=2, animation="breathe")
    assert tuned["dim"] == 0.9 and tuned["animation"] == "breathe"
    assert backgrounds.activate(None)["active"] is None
    assert "cleared" in backgrounds.tool_set_background(clear=True)
