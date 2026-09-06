"""Tests for Serious Mode and specialist personality profiles."""

import pytest
from personalities import (
    PERSONALITY_PRESETS,
    get_personality,
    list_personalities,
    resolve_personality,
)


def test_serious_mode_preset():
    """Verify that 'serious' mode is registered and contains strict analytical guidance."""
    preset = get_personality("serious")
    assert preset["display_name"] == "Serious Mode"
    assert "analytical" in preset["system_guidance"].lower()
    assert "filler" in preset["system_guidance"].lower()


def test_specialist_presets_exist():
    """Verify that coding_mentor, research_assistant, systems_architect, debugger, homework_helper exist."""
    required = [
        "serious",
        "coding_mentor",
        "research_assistant",
        "systems_architect",
        "debugger",
        "homework_helper",
    ]
    for key in required:
        assert key in PERSONALITY_PRESETS
        p = get_personality(key)
        assert p["id"] == key
        assert len(p["system_guidance"]) > 20


def test_resolve_personality_serious():
    """Test resolution of serious mode via resolve_personality."""
    resolved = resolve_personality(personality_id="serious")
    assert resolved is not None
    assert resolved["id"] == "serious"
