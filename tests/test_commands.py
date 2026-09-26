"""Slash commands: the menu finds what you mean, guesses when it can't, and can make one (Request G5)."""

from __future__ import annotations

import pytest

import commands


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(commands, "_store_path", lambda: tmp_path / "commands.json")
    monkeypatch.setattr(commands, "skill_commands", lambda: [])


def test_typing_letters_ranks_the_command_you_mean_first():
    assert commands.rank("qu")[0]["name"] == "quiz"
    assert commands.rank("dup")[0]["name"] == "duplicate"
    assert commands.rank("picture")[0]["name"] == "image"
    assert commands.rank("copy")[0]["name"] == "duplicate"


def test_an_unknown_command_is_guessed_offline_and_offers_one_to_make():
    result = commands.guess("/studyplan biology", use_model=False)
    assert result["suggestion"]["name"] == "studyplan"
    assert "{args}" in result["suggestion"]["template"]
    assert result["source"] in ("offline", "fuzzy")


def test_the_mini_model_can_point_at_an_existing_command(monkeypatch):
    monkeypatch.setattr(commands, "_ask_model", lambda text, cmds, budget: {"match": "flashcards", "confidence": 0.8, "new": None})
    result = commands.guess("/memorise-terms photosynthesis")
    assert result["source"] == "model"
    assert result["matches"][0]["name"] == "flashcards"


def test_owner_commands_are_saved_as_templates_and_listed():
    made = commands.add_command("/Study Plan", "Study plan", "Weekly plan", "Make a weekly study plan for")
    assert made["name"] == "study-plan" and made["template"].endswith("{args}")
    assert any(c["name"] == "study-plan" for c in commands.all_commands())
    with pytest.raises(ValueError):
        commands.add_command("quiz", "", "", "x")
    assert commands.remove_command("study-plan")


def test_several_commands_anywhere_in_a_message_are_found_and_briefed_first():
    """Request H13: /commands in the middle or at the end, several at once; paths and unknown words are not commands."""
    import commands

    catalog = [
        {"name": "quiz", "title": "Practice quiz", "kind": "prompt", "template": "Make a 5-question practice quiz about {args}."},
        {"name": "summarize", "title": "Summarize", "kind": "prompt", "template": "Summarize clearly: {args}"},
        {"name": "new", "title": "New chat", "kind": "client", "action": "chat.new"},
    ]
    text = "Read C:/Users/me/notes.txt and /summarize it, then /quiz me on it. See https://x.com/quiz too /nope /quiz"
    found = commands.find_inline(text, catalog)
    assert [c["name"] for c in found] == ["summarize", "quiz"]

    brief = commands.brief_for("start /new then /quiz cells", catalog)
    assert brief["found"] == ["new", "quiz"]
    assert brief["context"].startswith(commands.PREFIX)
    assert "app action" in brief["context"] and "practice quiz" in brief["context"]
    assert commands.brief_for("no commands here", catalog)["context"] == ""
