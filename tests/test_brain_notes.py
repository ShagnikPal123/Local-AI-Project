"""Shared Obsidian brain: one note format, saved under Brain/<kind>/, found again by search (brain_notes.py)."""

import pytest

import brain_notes
from connectors.obsidian_connector import ObsidianConnector


def test_note_has_front_matter_body_and_wikilinks():
    text = brain_notes.build_note("Pick TTS voice", "We chose VoxCPM.", kind="decision", author="claude-ws13",
                                  links=["Voice plan"], tags=["#voice"], today="2026-10-13")
    assert text.startswith("---\ntitle: Pick TTS voice\nkind: decision\nauthor: claude-ws13\ncreated: 2026-10-13\n")
    assert "tags: [brain, decision, voice]" in text
    assert "We chose VoxCPM." in text and "- [[Voice plan]]" in text


def test_unknown_kind_is_refused():
    with pytest.raises(ValueError):
        brain_notes.build_note("x", "y", kind="gossip")


def test_save_then_recall_through_the_vault_folder(tmp_path):
    conn = ObsidianConnector(api_key="", vault_path=str(tmp_path))
    out = brain_notes.save_note(conn, "Skills first!", "Install claude-mem skills.", kind="handoff", today="2026-10-13")
    assert out["success"] and out["path"] == "Brain/handoff/2026-10-13-skills-first.md"
    (tmp_path / "Other.md").write_text("claude-mem is mentioned here too", encoding="utf-8")
    hits = brain_notes.recall(conn, "claude-mem")
    assert [h["filename"] for h in hits] == ["Brain/handoff/2026-10-13-skills-first.md"]
