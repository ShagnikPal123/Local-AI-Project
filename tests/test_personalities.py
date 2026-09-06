"""Tests for the personalities module."""

import pytest

from personalities import (
    PersonalityNotFoundError,
    clear_custom_personality,
    get_custom_personality,
    get_personality,
    list_personalities,
    resolve_personality,
    save_custom_personality,
)


def test_list_personalities_includes_gen_z_and_close_friend():
    ids = {preset["id"] for preset in list_personalities()}
    assert {"gen_z", "close_friend", "professional", "concise"} <= ids


def test_get_personality_returns_guidance():
    preset = get_personality("gen_z")
    assert preset["id"] == "gen_z"
    assert "slang" in preset["system_guidance"].lower()


def test_get_personality_is_case_insensitive():
    assert get_personality("CLOSE_FRIEND")["id"] == "close_friend"


def test_get_personality_unknown_raises():
    with pytest.raises(PersonalityNotFoundError):
        get_personality("does_not_exist")


def test_save_and_load_custom_personality(tmp_path, monkeypatch):
    import personalities

    monkeypatch.setattr(personalities, "_CUSTOM_PERSONALITY_FILE", tmp_path / "custom.json")
    record = save_custom_personality("Talk like a pirate, arr.")
    assert record["id"] == "custom"
    loaded = get_custom_personality()
    assert loaded["system_guidance"] == "Talk like a pirate, arr."


def test_clear_custom_personality(tmp_path, monkeypatch):
    import personalities

    monkeypatch.setattr(personalities, "_CUSTOM_PERSONALITY_FILE", tmp_path / "custom.json")
    save_custom_personality("Some style")
    assert clear_custom_personality() is True
    assert get_custom_personality() is None


def test_save_custom_personality_rejects_empty():
    with pytest.raises(ValueError):
        save_custom_personality("   ")


def test_resolve_personality_priority():
    # Explicit custom text wins over preset ID.
    resolved = resolve_personality("gen_z", "Talk formally.")
    assert resolved["id"] == "custom"
    assert resolved["system_guidance"] == "Talk formally."

    # Preset ID resolves when no custom text given.
    assert resolve_personality("concise")["id"] == "concise"

    # Nothing configured -> None.
    assert resolve_personality() is None
