"""Skills library and automatic attachment (ROADMAP U1-U5)."""

import json

import pytest

from skills import (
    BUILTIN_SKILLS,
    SkillError,
    SkillStore,
    build_skill_prompt,
    parse_skill_reply,
)


@pytest.fixture
def store(tmp_path):
    return SkillStore(tmp_path / "skills.json")


# --- the library ----------------------------------------------------------------------

def test_builtin_skills_ship_with_the_app(store):
    names = {s["name"] for s in store.list_skills()}
    assert {"Debugging", "Research", "Maths"} <= names


def test_every_builtin_has_instructions_and_triggers(store):
    import auto_team

    for skill in store.list_skills():
        assert skill["instructions"].strip()
        # Auto (Update 1, U21) is the one skill that runs only when called by name — /auto or @auto — because a
        # trigger word like "/auto" would also fire inside "/automation".
        assert skill["triggers"] or skill["name"] == auto_team.SKILL_NAME


def test_builtins_sort_before_user_skills(store):
    store.add("Zebra", "d", "instructions here", ["zebra"])
    assert store.list_skills()[0]["source"] == "builtin"


# --- automatic attachment (U3) ----------------------------------------------------------

def test_a_matching_turn_attaches_the_right_skill(store):
    selected = store.select_for("I have a bug with this traceback")
    assert "Debugging" in [s.name for s in selected]


def test_a_time_sensitive_turn_attaches_research(store):
    selected = store.select_for("what is the latest news on this")
    assert "Research" in [s.name for s in selected]


def test_an_unrelated_turn_attaches_nothing(store):
    """An unhelpful skill steers the answer wrong — worse than no skill."""
    assert store.select_for("mmm") == []


def test_attachment_is_capped(store):
    """Five sets of instructions cancel each other out."""
    busy = "bug error explain write solve latest review draft calculate"
    assert len(store.select_for(busy)) <= 3


def test_the_best_match_comes_first(store):
    selected = store.select_for("bug error traceback exception crash explain")
    assert selected[0].name == "Debugging"


def test_a_disabled_skill_is_never_attached(store):
    debugging = next(s for s in store.list_skills() if s["name"] == "Debugging")
    store.set_enabled(debugging["id"], False)
    assert "Debugging" not in [s.name for s in store.select_for("I have a bug")]


def test_the_context_carries_the_instructions(store):
    context = store.build_context("I have a bug in my code")
    assert "Skills active" in context
    assert "Reproduce the problem" in context


def test_no_match_produces_no_context(store):
    """A turn that needs nothing must pay nothing."""
    assert store.build_context("mmm") == ""


def test_usage_is_counted(store):
    store.build_context("I have a bug")
    debugging = next(s for s in store.list_skills() if s["name"] == "Debugging")
    assert debugging["uses"] >= 1


# --- adding skills (U2) -------------------------------------------------------------------

def test_a_skill_can_be_added_and_is_then_attachable(store):
    store.add("Kubernetes", "help with k8s", "Check the pod events first.", ["kubectl", "k8s"])
    assert "Kubernetes" in [s.name for s in store.select_for("my k8s pod is failing")]


def test_a_skill_needs_a_name(store):
    with pytest.raises(SkillError):
        store.add("  ", "d", "instructions")


def test_a_skill_needs_instructions(store):
    with pytest.raises(SkillError):
        store.add("Name", "d", "   ")


def test_triggers_are_derived_when_not_supplied(store):
    skill = store.add("Sourdough", "baking sourdough bread at home", "Watch the hydration.")
    assert skill.triggers
    assert "sourdough" in skill.triggers


def test_a_skill_with_no_usable_triggers_is_refused(store):
    with pytest.raises(SkillError):
        store.add("Ab", "the and for", "instructions")


# --- built-ins are protected ---------------------------------------------------------------

def test_a_builtin_cannot_be_deleted(store):
    """Deleting one would stop an app update ever improving it."""
    debugging = next(s for s in store.list_skills() if s["name"] == "Debugging")
    with pytest.raises(SkillError):
        store.remove(debugging["id"])


def test_a_builtin_can_be_disabled(store):
    debugging = next(s for s in store.list_skills() if s["name"] == "Debugging")
    assert store.set_enabled(debugging["id"], False).enabled is False


def test_a_user_skill_can_be_deleted(store):
    skill = store.add("Temporary", "d", "instructions here", ["temp"])
    assert store.remove(skill.skill_id) is True


def test_removing_an_unknown_skill_reports_failure(store):
    assert store.remove("nope") is False


# --- persistence ------------------------------------------------------------------------------

def test_user_skills_survive_a_restart(tmp_path):
    path = tmp_path / "skills.json"
    SkillStore(path).add("Persisted", "d", "instructions here", ["persist"])
    assert "Persisted" in [s["name"] for s in SkillStore(path).list_skills()]


def test_a_disabled_builtin_stays_disabled_across_restarts(tmp_path):
    path = tmp_path / "skills.json"
    first = SkillStore(path)
    debugging = next(s for s in first.list_skills() if s["name"] == "Debugging")
    first.set_enabled(debugging["id"], False)

    second = SkillStore(path)
    reloaded = next(s for s in second.list_skills() if s["name"] == "Debugging")
    assert reloaded["enabled"] is False


def test_shipped_builtin_text_wins_over_a_stored_copy(tmp_path):
    """So an app update can improve a built-in the user already has."""
    path = tmp_path / "skills.json"
    path.write_text(json.dumps({"skills": [{
        "id": "builtin-debugging", "name": "Debugging", "source": "builtin",
        "instructions": "stale text from an old version", "triggers": ["bug"],
        "enabled": True,
    }]}), encoding="utf-8")

    store = SkillStore(path)
    debugging = next(s for s in store.list_skills() if s["name"] == "Debugging")
    assert "stale text" not in debugging["instructions"]


def test_a_corrupt_library_still_leaves_the_builtins(tmp_path):
    path = tmp_path / "skills.json"
    path.write_text("{ not json", encoding="utf-8")
    assert len(SkillStore(path).list_skills()) == len(BUILTIN_SKILLS)


# --- writing a skill from a description (U2) -----------------------------------------------

def test_the_skill_prompt_asks_for_guidance_not_code():
    prompt = build_skill_prompt("help me with sourdough")
    assert "not code" in prompt.lower()
    assert "TRIGGERS" in prompt


def test_a_well_formed_reply_parses():
    parsed = parse_skill_reply(
        "NAME: Sourdough Baking\n"
        "TRIGGERS: sourdough, starter, hydration\n"
        "INSTRUCTIONS: Check the starter is active before blaming the recipe."
    )
    assert parsed["name"] == "Sourdough Baking"
    assert "starter" in parsed["triggers"]
    assert parsed["instructions"].startswith("Check the starter")


def test_a_multiline_instruction_block_parses():
    parsed = parse_skill_reply(
        "NAME: Thing\nTRIGGERS: a, b\nINSTRUCTIONS: first line\nsecond line"
    )
    assert "second line" in parsed["instructions"]


@pytest.mark.parametrize("reply", [
    "",
    "I would be happy to help you with that!",
    "NAME: Only a name",
    "INSTRUCTIONS: only instructions",
])
def test_a_malformed_reply_is_refused(reply):
    """A half-formed skill would be attached to real turns."""
    with pytest.raises(SkillError):
        parse_skill_reply(reply)
