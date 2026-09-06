"""Conversational tab editing (ROADMAP CC9).

Common edits are read locally so they are instant and work offline. Everything
else goes to the model, whose reply is a *proposal* — validated exactly like a
hand-written edit.
"""

import pytest

from dynamic_tabs import TabSpecError, build_spec
from tab_editor import (
    build_edit_prompt,
    interpret_locally,
    parse_edit_reply,
)


@pytest.fixture
def spec():
    return build_spec(
        label="Notes",
        blocks=[{"type": "notes", "title": "Scratch"}, {"type": "text", "title": "About"}],
    )


# --- the local fast path ---------------------------------------------------------------

@pytest.mark.parametrize("instruction,expected", [
    ("make it green", "#5ac08a"),
    ("turn it blue", "#5a9ce0"),
    ("make this tab purple please", "#9184d9"),
    ("set the colour to red", "#e07a7a"),
])
def test_colour_words_are_read_without_a_model(spec, instruction, expected):
    """A round trip to turn 'make it green' into a hex code is waste."""
    assert interpret_locally(spec, instruction)["accent"] == expected


def test_an_explicit_hex_wins(spec):
    assert interpret_locally(spec, "make it #123456")["accent"] == "#123456"


@pytest.mark.parametrize("instruction,expected", [
    ("rename it to Scratchpad", "Scratchpad"),
    ("call it Daily Log", "Daily Log"),
    ('name it "Inbox"', "Inbox"),
])
def test_renames_are_read_without_a_model(spec, instruction, expected):
    assert interpret_locally(spec, instruction)["label"] == expected


def test_two_changes_in_one_instruction(spec):
    changes = interpret_locally(spec, "call it Journal and make it green")
    assert changes["label"] == "Journal"
    assert changes["accent"] == "#5ac08a"


def test_adding_a_block(spec):
    changes = interpret_locally(spec, "add a checklist")
    types = [b["type"] for b in changes["blocks"]]
    assert types == ["notes", "text", "checklist"]


def test_removing_a_block(spec):
    changes = interpret_locally(spec, "remove the text block")
    assert [b["type"] for b in changes["blocks"]] == ["notes"]


def test_removing_the_last_block_is_refused(spec):
    """A tab with no blocks shows nothing."""
    single = build_spec(label="One", blocks=[{"type": "notes", "title": "S"}])
    assert interpret_locally(single, "remove the notes") is None


def test_removing_a_block_that_is_not_there_changes_nothing(spec):
    assert interpret_locally(spec, "remove the checklist") is None


# --- knowing when to defer to the model ---------------------------------------------------

@pytest.mark.parametrize("instruction", [
    "make it feel more like a workspace",
    "reorganise this so the important bits are first",
    "something is off about the layout",
    "",
    "   ",
])
def test_an_ambiguous_instruction_defers_to_the_model(spec, instruction):
    """None means 'ask the model'. Guessing would be worse than the round trip."""
    assert interpret_locally(spec, instruction) is None


def test_an_unknown_colour_defers_rather_than_guessing(spec):
    """A wrong guess gives a colour the user did not ask for."""
    assert interpret_locally(spec, "make it chartreuse") is None


# --- the model path is a proposal, not a spec -----------------------------------------------

def test_a_plain_json_edit_parses():
    assert parse_edit_reply('{"accent": "#5ac08a"}') == {"accent": "#5ac08a"}


def test_a_fenced_edit_parses():
    assert parse_edit_reply('```json\n{"label": "New"}\n```') == {"label": "New"}


def test_unknown_keys_are_dropped():
    """A model must not be able to set fields the edit surface does not expose."""
    changes = parse_edit_reply('{"label": "New", "tab_id": "hacked", "author": "someone"}')
    assert changes == {"label": "New"}


def test_a_model_refusal_is_surfaced():
    with pytest.raises(TabSpecError) as excinfo:
        parse_edit_reply('{"error": "that is not a change to this tab"}')
    assert "not a change" in str(excinfo.value)


@pytest.mark.parametrize("reply", [
    "",
    "Sure, I can help with that!",
    "{ not json",
    '{"nothing": "useful"}',
    '["a", "list"]',
])
def test_a_malformed_edit_is_refused(reply):
    with pytest.raises(TabSpecError):
        parse_edit_reply(reply)


# --- the prompt --------------------------------------------------------------------------------

def test_the_edit_prompt_constrains_the_model(spec):
    prompt = build_edit_prompt(spec, "make it green")
    assert "#rrggbb" in prompt
    assert "system_control" not in prompt
    assert "Notes" in prompt  # it can see the current tab


def test_the_edit_prompt_offers_a_way_to_refuse(spec):
    assert '"error"' in build_edit_prompt(spec, "delete my hard drive")


@pytest.mark.parametrize("instruction,expected", [
    ("call it Journal and make it green", "Journal"),
    ("rename it to Daily Log, then add a checklist", "Daily Log"),
    ("name it Inbox also make it blue", "Inbox"),
    ("call it Work Notes but keep the colour", "Work Notes"),
])
def test_a_name_stops_at_the_next_clause(spec, instruction, expected):
    """Otherwise 'call it Journal and make it green' names the tab all of that."""
    assert interpret_locally(spec, instruction)["label"] == expected
