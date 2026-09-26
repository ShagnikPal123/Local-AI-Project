"""Front-end design sense: no default design (Project Null N88).

The owner's complaint is that assistants produce the same interface whatever you
ask for. So what is tested here is that a brief is built from *this* request and
*this* owner — their past words, what they undid, the tabs they already have —
and that it always carries the "do not do the generic version" list, even with no
model and no internet.
"""

from __future__ import annotations

import json

import pytest

import design_sense


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(design_sense, "_decisions_path", lambda: tmp_path / "decisions.jsonl")
    # No web, no model, unless a test asks for one.
    monkeypatch.setattr(design_sense, "_research", lambda request, limit=4: [])
    monkeypatch.setattr(design_sense, "apple_guidance", lambda request, limit=3: [])


def test_a_brief_works_with_no_model_and_no_internet():
    brief = design_sense.build_brief("a page for tracking my runs", research=False, use_model=False)
    assert brief["request"].startswith("a page")
    assert brief["avoid"], "the whole point is knowing what not to reach for"
    assert "centred hero" in " ".join(brief["avoid"])
    assert "Decide it yourself" in brief["text"], "with no model it hands over the method, not half a brief"
    assert brief["reading"] and brief["principles"]["apple"]


def test_what_the_owner_undid_is_remembered_and_carried_into_the_next_brief():
    design_sense.record_decision("tab", "Glass cards over the memory field", verdict="undone")
    design_sense.record_decision("tab", "Tabular numbers in the trading table", verdict="applied")

    taste = design_sense.taste()
    assert "Glass cards over the memory field" in taste["undone"]
    assert "Tabular numbers in the trading table" in taste["kept"]

    brief = design_sense.build_brief("restyle the trading tab", research=False, use_model=False)
    assert "Glass cards" in brief["text"], "a brief has to say what they already rejected"


def test_a_decision_is_kept_as_a_line_of_json_and_the_file_does_not_grow_forever(tmp_path):
    for index in range(design_sense.MAX_DECISIONS + 20):
        design_sense.record_decision("ui", f"change {index}")
    lines = design_sense._decisions_path().read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == design_sense.MAX_DECISIONS
    assert json.loads(lines[-1])["summary"] == f"change {design_sense.MAX_DECISIONS + 19}"


def test_the_brief_reads_the_owners_own_words_about_looks():
    lines = design_sense.past_requests()
    assert lines, "the goals file is where every request is kept verbatim"
    assert any(design_sense._UI_WORDS.search(line) for line in lines)
    assert all(25 <= len(line) <= 260 for line in lines)


def test_the_app_tokens_come_from_the_real_stylesheet():
    tokens = design_sense.app_tokens()
    assert tokens.get("color-bg") == "#000000", "the owner asked for black; a brief must know that"
    assert any(name.startswith("color-accent") for name in tokens)


def test_the_model_decides_the_design_and_the_avoid_list_survives_it(monkeypatch):
    decided = {
        "intent": "See this week's runs at a glance",
        "audience": "one runner, most mornings",
        "mood": ["quiet", "quick", "physical"],
        "directions": [{"name": "Ledger", "idea": "a dense list", "why_not": "less celebratory"},
                       {"name": "Track", "idea": "a lap-shaped chart", "why_not": "harder to read numbers"}],
        "chosen": {"name": "Ledger", "because": "they check numbers, not trophies"},
        "tokens": {"palette": [{"role": "accent", "value": "#7BD88F"}], "type": "system, 1.25 scale",
                   "spacing": "8px base", "radius": "10px", "motion": "150ms state only", "surface": "flat"},
        "layout": "this week first, then the list",
        "components": ["this week", "the list", "one run"],
        "states": {"empty": "one line and a button", "loading": "skeleton rows"},
        "accessibility": ["4.5:1 body text", "visible focus ring"],
        "avoid": ["a podium graphic"],
        "model": "test-model",
    }
    monkeypatch.setattr(design_sense, "_model_brief", lambda request, context: decided)
    brief = design_sense.build_brief("a page for tracking my runs", research=False)

    assert brief["chosen"]["name"] == "Ledger" and brief["model"] == "test-model"
    assert "a podium graphic" in brief["avoid"], "what the model decided to avoid is kept"
    assert "centred hero" in " ".join(brief["avoid"]), "…on top of the standing list, not instead of it"
    assert "It should feel: quiet, quick, physical" in brief["text"]
    assert "accent #7BD88F" in brief["text"]


def test_a_broken_model_never_costs_the_brief(monkeypatch):
    def explode(request, context):
        raise RuntimeError("no key")

    monkeypatch.setattr(design_sense, "_model_brief", explode)
    brief = design_sense.build_brief("a settings page", research=False)
    assert "no key" in brief.get("model_error", "")
    assert brief["text"] and brief["avoid"]

    # And the one-line form used inside other prompts never raises at all.
    assert design_sense.brief_for_prompt("anything").startswith("[Design brief")


def test_tab_creation_asks_for_the_brief_first():
    """The one-line insertions that make tab creation stop reaching for a default."""
    from pathlib import Path

    import landscape_tools
    import server

    for module in (landscape_tools, server):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "design_sense.brief_for_prompt" in source, f"{module.__name__} should design on purpose"
