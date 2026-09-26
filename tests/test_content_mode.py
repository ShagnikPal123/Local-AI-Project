"""Adult mode is the owner's setting; the four hard limits are not (owner request, 2026-09-15)."""

from __future__ import annotations

import content_mode


def test_the_setting_turns_the_prompt_line_on_and_off(tmp_path, monkeypatch):
    monkeypatch.setattr(content_mode, "_path", lambda: tmp_path / "content_mode.json")
    assert content_mode.enabled() is False and content_mode.system_prompt() == ""
    content_mode.set_enabled(True)
    assert content_mode.enabled() is True and content_mode.system_prompt().startswith("[Adult mode is on]")
    content_mode.set_enabled(False)
    assert content_mode.enabled() is False


def test_minors_real_people_and_force_stay_refused_in_every_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(content_mode, "_path", lambda: tmp_path / "content_mode.json")
    content_mode.set_enabled(True)
    for prompt in ("nude 16 year old", "explicit art of a teen", "naked photo of my classmate",
                   "nsfw picture of a celebrity", "erotic scene where she is drugged and unconscious"):
        assert content_mode.check_image_prompt(prompt), prompt
    for allowed in ("an explicit scene between two adults", "a painting of a stormy sea",
                    "a documentary poster about child poverty", "a brutal sword fight"):
        assert content_mode.check_image_prompt(allowed) == "", allowed


def test_image_generation_refuses_before_calling_a_model(tmp_path, monkeypatch):
    import image_gen

    monkeypatch.setattr(content_mode, "_path", lambda: tmp_path / "content_mode.json")
    content_mode.set_enabled(True)

    def explode(*args, **kwargs):
        raise AssertionError("a refused prompt reached the image model")

    monkeypatch.setattr("model_roles.MODEL_ROLES.generate", explode)
    result = image_gen.generate_image("nude 15 year old girl")
    assert result.ok is False and "minors" in result.error
