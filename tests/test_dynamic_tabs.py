"""User-defined tabs (ROADMAP CC1-CC12).

The governing rule: a tab is a declarative spec the client renders, never
generated code. Most of these tests try to get something executable, or a
capability the tab should not have, through the validator.
"""

import json

import pytest

from dynamic_tabs import (
    ALLOWED_CONNECTORS,
    BlockType,
    TabSpecError,
    TabStore,
    build_spec,
    build_tab_prompt,
    parse_tab_reply,
)

SIMPLE_BLOCKS = [{"type": "notes", "title": "Scratch"}]


@pytest.fixture
def store(tmp_path):
    return TabStore(tmp_path / "tabs.json")


def _spec(label="Notes", blocks=None, **kwargs):
    return build_spec(label=label, blocks=blocks or SIMPLE_BLOCKS, **kwargs)


# --- validation: only known blocks -----------------------------------------------------

def test_a_valid_spec_is_accepted():
    spec = _spec()
    assert spec.label == "Notes"
    assert spec.blocks[0].type is BlockType.NOTES


def test_an_unknown_block_type_is_refused():
    """The client can only render blocks it knows; anything else renders nothing."""
    with pytest.raises(TabSpecError):
        _spec(blocks=[{"type": "arbitrary_html"}])


def test_a_tab_needs_a_name():
    with pytest.raises(TabSpecError):
        _spec(label="   ")


def test_a_tab_needs_at_least_one_block():
    # Calls build_spec directly: the _spec helper substitutes a default for an
    # empty list, which would hide exactly the case under test.
    with pytest.raises(TabSpecError):
        build_spec(label="Empty", blocks=[])


def test_too_many_blocks_are_refused():
    with pytest.raises(TabSpecError):
        _spec(blocks=[{"type": "text"}] * 41)   # the cap is 40 since U4


def test_an_absurdly_long_label_is_refused():
    with pytest.raises(TabSpecError):
        _spec(label="x" * 100)


# --- validation: nothing executable can get through --------------------------------------

@pytest.mark.parametrize("icon", [
    "<script>alert(1)</script>",
    "javascript:alert(1)",
    "ph-note; drop table",
    "../../etc/passwd",
    "PH-NOTE",
])
def test_a_dangerous_icon_is_refused(icon):
    with pytest.raises(TabSpecError):
        _spec(icon=icon)


@pytest.mark.parametrize("accent", [
    "expression(alert(1))",
    "url(javascript:alert(1))",
    "red; background: url(evil)",
    "#12",
])
def test_a_dangerous_accent_is_refused(accent):
    """Accent is a colour, never arbitrary CSS."""
    with pytest.raises(TabSpecError):
        _spec(accent=accent)


def test_a_hex_accent_is_accepted():
    assert _spec(accent="#9184d9").accent == "#9184d9"


def test_a_design_token_accent_is_accepted():
    assert _spec(accent="var(--color-accent)").accent == "var(--color-accent)"


# --- validation: a generated tab cannot grant itself capability ---------------------------

def test_a_generated_tab_cannot_reference_machine_control():
    """A tab written for a user must not reach system control by asking."""
    with pytest.raises(TabSpecError):
        _spec(connectors=["system_control"])


def test_a_generated_tab_cannot_reference_the_app_launcher():
    with pytest.raises(TabSpecError):
        _spec(connectors=["app_launcher"])


def test_an_allowed_connector_is_accepted():
    spec = _spec(connectors=["web_search"])
    assert spec.connectors == ["web_search"]


def test_duplicate_connectors_are_collapsed():
    assert _spec(connectors=["web_search", "web_search"]).connectors == ["web_search"]


def test_the_allowed_list_excludes_everything_dangerous():
    assert not ({"system_control", "app_launcher", "mcp", "dynamic_modularity"}
                & ALLOWED_CONNECTORS)


# --- fuzzy search (CC2, CC6) ---------------------------------------------------------------

def test_a_tab_is_found_by_its_own_name(store):
    store.create(_spec(label="Notes"))
    assert [r["label"] for r in store.find("notes")] == ["Notes"]


def test_a_tab_is_found_by_words_in_its_description(store):
    """The user types what they call it, not what it is called."""
    store.create(_spec(label="Inbox", description="my email and messages"))
    assert [r["label"] for r in store.find("email")] == ["Inbox"]


def test_shipped_tabs_are_searchable_too(store):
    shipped = [{"id": "models", "label": "Models"}]
    assert [r["id"] for r in store.find("models", shipped=shipped)] == ["models"]


def test_search_reports_why_something_matched(store):
    store.create(_spec(label="Inbox", description="my email and messages"))
    assert "email" in store.find("email")[0]["matched"]


def test_a_better_match_ranks_higher(store):
    store.create(_spec(label="Email Inbox", description="email messages"))
    store.create(_spec(label="Notes", description="email mentioned once"))
    assert store.find("email inbox")[0]["label"] == "Email Inbox"


def test_searching_for_nothing_finds_nothing(store):
    store.create(_spec(label="Notes"))
    assert store.find("") == []


def test_an_unmatched_search_returns_nothing_to_offer_creation(store):
    store.create(_spec(label="Notes"))
    assert store.find("submarine") == []


# --- editing (CC9, CC10) --------------------------------------------------------------------

def test_a_tab_can_be_renamed(store):
    spec = store.create(_spec(label="Notes"))
    assert store.update(spec.tab_id, label="Scratchpad").label == "Scratchpad"


def test_a_tab_can_be_recoloured(store):
    spec = store.create(_spec(label="Notes"))
    assert store.update(spec.tab_id, accent="#5ac08a").accent == "#5ac08a"


def test_an_edit_is_revalidated(store):
    """Editing must not be a way around the rules that applied at creation."""
    spec = store.create(_spec(label="Notes"))
    with pytest.raises(TabSpecError):
        store.update(spec.tab_id, accent="expression(alert(1))")
    with pytest.raises(TabSpecError):
        store.update(spec.tab_id, connectors=["system_control"])


def test_editing_an_unknown_tab_fails(store):
    with pytest.raises(TabSpecError):
        store.update("nope", label="x")


def test_an_unchanged_field_is_preserved(store):
    spec = store.create(_spec(label="Notes", description="keep me"))
    assert store.update(spec.tab_id, label="Renamed").description == "keep me"


# --- combining (CC11) -------------------------------------------------------------------------

def test_two_tabs_can_be_combined(store):
    first = store.create(_spec(label="Notes", blocks=[{"type": "notes", "title": "A"}]))
    second = store.create(_spec(label="Tasks", blocks=[{"type": "checklist", "title": "B"}]))
    combined = store.combine(first.tab_id, second.tab_id)
    assert len(combined.blocks) == 2
    assert combined.source == "derived"


def test_combining_leaves_the_originals_alone(store):
    first = store.create(_spec(label="Notes"))
    second = store.create(_spec(label="Tasks"))
    store.combine(first.tab_id, second.tab_id)
    assert store.get(first.tab_id) is not None
    assert store.get(second.tab_id) is not None


def test_combining_over_the_block_limit_is_refused(store):
    blocks = [{"type": "text", "title": f"b{i}"} for i in range(21)]
    first = store.create(_spec(label="A", blocks=blocks))
    second = store.create(_spec(label="B", blocks=blocks))
    with pytest.raises(TabSpecError):
        store.combine(first.tab_id, second.tab_id)


def test_combining_a_missing_tab_fails(store):
    first = store.create(_spec(label="Notes"))
    with pytest.raises(TabSpecError):
        store.combine(first.tab_id, "nope")


# --- persistence (CC7) --------------------------------------------------------------------------

def test_tabs_survive_a_restart(tmp_path):
    """A base-app update must never wipe someone's own tabs."""
    path = tmp_path / "tabs.json"
    TabStore(path).create(_spec(label="Persisted"))
    assert [t["label"] for t in TabStore(path).list_tabs()] == ["Persisted"]


def test_a_corrupt_tab_file_does_not_break_the_nav(tmp_path):
    path = tmp_path / "tabs.json"
    path.write_text("{ not json", encoding="utf-8")
    assert TabStore(path).list_tabs() == []


def test_an_invalid_stored_tab_is_skipped_not_fatal(tmp_path):
    """A spec valid under older rules must disappear, not break the app."""
    path = tmp_path / "tabs.json"
    path.write_text(json.dumps({"tabs": [
        {"id": "good", "label": "Good", "blocks": [{"type": "notes"}]},
        {"id": "bad", "label": "Bad", "blocks": [{"type": "arbitrary_html"}]},
    ]}), encoding="utf-8")
    assert [t["label"] for t in TabStore(path).list_tabs()] == ["Good"]


def test_a_tab_can_be_deleted(store):
    spec = store.create(_spec(label="Temp"))
    assert store.delete(spec.tab_id) is True
    assert store.get(spec.tab_id) is None


# --- designing from a description (CC4, CC5) ------------------------------------------------------

def test_the_design_prompt_lists_only_allowed_blocks_and_connectors():
    prompt = build_tab_prompt("a notes tab")
    assert "notes" in prompt
    assert "system_control" not in prompt


def test_a_plain_json_reply_parses():
    data = parse_tab_reply('{"label": "Notes", "blocks": [{"type": "notes"}]}')
    assert data["label"] == "Notes"


def test_a_fenced_json_reply_parses():
    """Models routinely wrap JSON in a code fence."""
    data = parse_tab_reply('```json\n{"label": "Notes", "blocks": [{"type": "notes"}]}\n```')
    assert data["label"] == "Notes"


def test_json_with_surrounding_prose_parses():
    data = parse_tab_reply('Sure!\n{"label": "Notes", "blocks": [{"type": "notes"}]}\nHope that helps')
    assert data["label"] == "Notes"


@pytest.mark.parametrize("reply", [
    "",
    "I would love to help with that!",
    '{"label": "Notes"}',
    '{"blocks": [{"type": "notes"}]}',
    "{ not json at all",
])
def test_a_malformed_design_is_refused(reply):
    """A malformed tab would render broken in front of the user."""
    with pytest.raises(TabSpecError):
        parse_tab_reply(reply)



# --- U4 "super free create": more to build with, all of it data ----------------------------------------------


def test_the_new_blocks_are_cleaned_to_what_the_page_can_draw():
    spec = _spec(blocks=[
        {"type": "form", "config": {"fields": [{"label": "Mood", "kind": "select", "options": ["good", "bad"]},
                                                {"label": "Notes", "kind": "<script>"}, {"nope": 1}],
                                     "ai_prompt": "Tell me if my week is getting better.", "layout": {"span": 2, "variant": "hero"}}},
        {"type": "table", "config": {"columns": ["Item", "Qty"], "rows": [["Eggs", "12", "extra"], ["Milk"]]}},
        {"type": "board", "config": {"cards": {"To do": ["Plan trip"]}}},
        {"type": "image", "config": {"src": "https://example.com/a.png", "caption": "Hi"}},
        {"type": "gallery", "config": {"images": ["https://example.com/b.png", "javascript:alert(1)", {"src": "/api/uploads/abcd1234"}]}},
        {"type": "actions", "config": {"buttons": [{"label": "Brief me", "do": "ask", "value": "Morning brief"},
                                                    {"label": "Bad", "do": "link", "value": "javascript:alert(1)"},
                                                    {"label": "Notes", "do": "open_tab", "value": "notes"}]}},
        {"type": "counter", "config": {"label": "Glasses of water", "goal": 8, "layout": {"accent": "#30a46c", "span": 9}}},
    ], theme={"columns": 3})
    form, table, board, image, gallery, actions, counter = (b.config for b in spec.blocks)
    assert [f["kind"] for f in form["fields"]] == ["select", "text"] and form["layout"] == {"span": 2, "variant": "hero"}
    assert table["rows"] == [["Eggs", "12"], ["Milk", ""]]
    assert board["columns"] == ["To do", "Doing", "Done"] and board["cards"]["To do"] == ["Plan trip"]
    assert image["src"].startswith("https://")
    assert [g["src"] for g in gallery["images"]] == ["https://example.com/b.png", "/api/uploads/abcd1234"]
    assert [b["label"] for b in actions["buttons"]] == ["Brief me", "Notes"]
    assert counter["goal"] == 8 and counter["layout"] == {"span": 4, "accent": "#30a46c"}
    assert spec.theme["columns"] == 3


def test_a_picture_block_without_a_safe_picture_is_refused():
    with pytest.raises(TabSpecError):
        _spec(blocks=[{"type": "image", "config": {"src": "file:///C:/secrets.png"}}])


def test_the_model_is_told_the_whole_vocabulary():
    from dynamic_tabs import build_tab_prompt

    prompt = build_tab_prompt("a habit tracker")
    for word in ("form", "board", "actions", "counter", "layout", "columns"):
        assert word in prompt
