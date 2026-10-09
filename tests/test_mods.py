"""Mods: one named, validated, live bundle per lasting change the owner asks for (mods.py)."""

from __future__ import annotations

import pytest

import mods


@pytest.fixture(autouse=True)
def known_tools(monkeypatch):
    monkeypatch.setattr(mods, "_known_tools", lambda: ["research", "search_web", "open_link", "send_email", "mod_save"])


def store() -> mods.ModStore:
    return mods.MOD_STORE


def test_every_problem_is_named_at_once_with_the_fix():
    with pytest.raises(mods.ModError) as caught:
        store().save("Bad", [
            {"kind": "remindr", "text": "x"},
            {"kind": "block_tools", "tools": ["websearch"]},
            {"kind": "reminder", "text": "Stretch", "every_minutes": 1},
        ])
    text = str(caught.value)
    assert "did you mean 'reminder'" in text
    assert "did you mean 'search_web'" in text
    assert "every_minutes" in text
    assert store().list() == []


def test_a_mod_cannot_block_the_tools_that_undo_it():
    with pytest.raises(mods.ModError, match="cannot be blocked"):
        store().save("Lock in", [{"kind": "block_tools", "tools": ["mod_save"]}])


def test_block_tools_refuses_the_call_until_switched_off():
    store().save("No web", [{"kind": "block_tools", "tools": ["search_web"], "reason": "offline week"}])
    assert "No web" in store().blocked("search_web") and "offline week" in store().blocked("search_web")
    assert store().blocked("open_link") is None
    store().set_enabled("no web", False)
    assert store().blocked("search_web") is None


def test_the_tool_registry_enforces_the_block():
    from tools import ToolParam, ToolRegistry

    registry = ToolRegistry()
    registry.register("search_web", "Search", [ToolParam("query", "string", "q")], lambda query: "results")
    store().save("No web", [{"kind": "block_tools", "tools": ["search_web"]}])
    assert registry.call_tool("search_web", query="x").startswith("Blocked: the owner's mod 'No web'")


def test_turn_context_lists_mods_and_only_the_instructions_that_apply():
    store().save("Short", [{"kind": "instructions", "text": "Keep answers under 4 sentences."}])
    store().save("Code style", [{"kind": "instructions", "text": "Use TypeScript examples.", "when": ["code"]}])
    store().save("Paused", [{"kind": "instructions", "text": "Speak like a pirate."}], enabled=False)
    note = store().turn_context("what's the weather")
    assert note.startswith(mods.CONTEXT_PREFIX)
    assert "id short" in note and "id code-style" in note and "(id paused, off)" in note
    assert "Keep answers under 4 sentences" in note
    assert "TypeScript" not in note and "pirate" not in note
    assert "TypeScript" in store().turn_context("help me write code")


def test_saving_with_mod_id_replaces_instead_of_duplicating():
    made = store().save("Stretch", [{"kind": "reminder", "text": "Stretch", "every_minutes": 45}])
    with pytest.raises(mods.ModError, match="already a mod called"):
        store().save("Stretch", [{"kind": "reminder", "text": "Stretch", "every_minutes": 30}])
    store().save("Stretch", [{"kind": "reminder", "text": "Stretch", "every_minutes": 30}], mod_id=made["id"])
    assert len(store().list()) == 1
    assert store().view()["reminders"][0]["every_minutes"] == 30


def test_mod_commands_join_the_menu_and_cannot_clash(monkeypatch, tmp_path):
    import commands

    monkeypatch.setattr(commands, "_store_path", lambda: tmp_path / "commands.json")
    monkeypatch.setattr(commands, "skill_commands", lambda: [])
    monkeypatch.setattr(commands, "agent_commands", lambda: [])
    store().save("Standup", [{"kind": "command", "name": "standup", "template": "Run my standup"}])
    listed = {c["name"]: c for c in commands.all_commands()}
    assert listed["standup"]["origin"] == "mod" and listed["standup"]["template"].endswith("{args}")
    assert "Run my standup" in commands.brief_for("/standup today")["context"]
    with pytest.raises(mods.ModError, match="already belongs"):
        store().save("Other", [{"kind": "command", "name": "standup", "template": "x"}])
    with pytest.raises(mods.ModError, match="built-in"):
        store().save("Clash", [{"kind": "command", "name": "quiz", "template": "x"}])


def test_theme_is_applied_and_switching_off_puts_back_only_what_it_still_owns():
    import ui_state

    look = ui_state.UI_STATE
    store().save("Teal", [{"kind": "theme", "tokens": {"accent": "teal", "radius": 16}}])
    assert look.snapshot()["theme"]["accent"] == ui_state.NAMED_COLORS["teal"]
    look.update_theme({"radius": 4})  # the owner changed this by hand since
    store().set_enabled("teal", False)
    theme = look.snapshot()["theme"]
    assert theme["accent"] == ui_state.DEFAULT_THEME["accent"]
    assert theme["radius"] == 4


def test_bad_theme_values_are_refused_with_the_reason():
    with pytest.raises(mods.ModError, match=r"parts\[0\] \(theme\)"):
        store().save("Ugly", [{"kind": "theme", "tokens": {"accent": "url(javascript:x)"}}])


def test_view_carries_what_the_app_draws():
    store().save("Focus", [{"kind": "banner", "text": "Exam on Friday", "tone": "warn"},
                           {"kind": "status", "text": "Focus mode"},
                           {"kind": "start_tab", "tab": "Notes"}])
    view = store().view()
    assert view["banners"][0]["text"] == "Exam on Friday" and view["banners"][0]["tone"] == "warn"
    assert view["statuses"][0]["text"] == "Focus mode"
    assert view["start_tab"] == "Notes"
    store().delete("focus")
    assert store().view() == {"banners": [], "statuses": [], "reminders": [], "start_tab": ""}


def test_tools_report_errors_the_model_can_act_on():
    reply = mods.tool_mod_save("Oops", '[{"kind": "status"}]')
    assert reply.startswith("Error:") and "`text` is required" in reply and "mod_help" in reply
    reply = mods.tool_mod_save("Short", [{"kind": "instructions", "text": "Be brief."}], request="keep it short")
    assert "switched on" in reply
    assert "keep it short" in mods.tool_mod_list()
    assert "is now off" in mods.tool_mod_toggle("short", False)
    assert "Deleted" in mods.tool_mod_delete("Short")


def test_catalog_names_every_part_and_maps_asks_to_parts():
    text = mods.catalog_text()
    for kind in mods.PARTS:
        assert f"**{kind}**" in text
    assert "remind me to stretch" in text


@pytest.mark.parametrize("text,expected", [
    ("from now on answer in French", True),
    ("remind me to drink water every hour", True),
    ("stop using the web", True),
    ("what is 2+2", False),
])
def test_setup_requests_take_the_full_pipeline(text, expected):
    assert mods.wants_setup_change(text) is expected


def test_mod_instructions_reach_the_model_on_the_quick_path_too():
    """Most turns are short; a mod that only held on long ones would look broken (as personalities once did)."""
    from unittest.mock import MagicMock, patch

    from chat_service import ChatService

    store().save("French", [{"kind": "instructions", "text": "Always answer in French."}])
    with patch("chat_service.Router") as router_class:
        router = MagicMock()
        router.chat.return_value = ("Bonjour !", "test_provider")
        router_class.return_value = router
        ChatService(enable_tools=True).chat("hi")
    sent = router.chat.call_args[0][0]
    assert any(m["role"] == "system" and "Always answer in French." in m["content"] for m in sent)
