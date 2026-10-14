"""Commander's pick: rules that read the words, a nearest-neighbour vote that learns from earlier assignments, and the
owner's own corrections counting most. No model calls and no network: the model catalog is faked."""

import pytest

import commander_pick as cp


@pytest.fixture()
def picker(tmp_path):
    return cp.Picker(path=tmp_path / "picks.json", clock=lambda: 1000.0)


@pytest.mark.parametrize("text, tier, sector", [
    ("Fix the crash in the login function and add a test for it", "zencode", "Fixes"),
    ("Refactor the trading API routes into a module", "zencode", "Updates"),
    ("Research the best vector databases and compare their pros and cons", "crescendo", "Research"),
    ("What time is it in Tokyo?", "pico", "Questions"),
    ("Write a friendly birthday message for my mum", "monolith", "Updates"),
])
def test_rules_read_the_kind_of_work(text, tier, sector):
    pick = cp.rule_pick(text)
    assert pick["tier"] == tier and pick["sector"] == sector
    assert pick["source"] == "rules" and pick["why"]


def test_more_work_gets_more_effort():
    small = cp.rule_pick("Rename the button")
    big = cp.rule_pick("- build the login page\n- add the API route\n- write tests for both\n- update the README")
    assert cp.EFFORTS.index(big["effort"]) > cp.EFFORTS.index(small["effort"])
    assert cp.rule_pick("What is 2 + 2?")["effort"] == "low"


def test_research_never_runs_on_low_effort():
    assert cp.rule_pick("Research GPUs")["effort"] in ("high", "super")


def test_with_no_history_the_rules_decide(picker):
    pick = picker.suggest("Fix the crash in the parser")
    assert pick["source"] == "rules" and pick["tier"] == "zencode"


def test_it_learns_from_earlier_assignments(picker):
    # The rules would call a newsletter "monolith" work; the owner keeps giving newsletters to the heavy models.
    for title in ("Weekly newsletter draft", "Newsletter for the club", "Write the newsletter intro"):
        picker.learn(f"{title} with the members update", "crescendo", "high", "Updates", title=title)
    assert cp.rule_pick("Draft the newsletter for the members")["tier"] == "monolith"
    pick = picker.suggest("Draft the newsletter for the members")
    assert pick["tier"] == "crescendo" and pick["effort"] == "high"
    assert pick["source"] == "learned" and "tier" in pick["learned"]
    assert "newsletter" in pick["why"].lower()


def test_one_unlike_example_does_not_override_the_rules(picker):
    picker.learn("Plan the garden layout for spring", "crescendo", "super", "Research")
    pick = picker.suggest("Fix the crash in the login function")
    assert pick["tier"] == "zencode" and pick["source"] == "rules"


def test_an_owner_correction_counts_on_its_own(picker):
    picker.learn("Summarise the meeting notes from today", "pico", "low", "Questions", by_owner=True, title="Meeting notes")
    pick = picker.suggest("Summarise the meeting notes from Monday")
    assert pick["tier"] == "pico" and pick["source"] == "learned"


def test_the_owner_outvotes_older_automatic_picks(picker):
    for _ in range(2):
        picker.learn("Clean up the photo folder by date", "monolith", "normal", "Updates")
    picker.learn("Clean up the photo folder by date", "zencode", "high", "Updates", by_owner=True)
    assert picker.suggest("Clean up the photo folder by date please")["tier"] == "zencode"


def test_examples_persist_and_are_capped(tmp_path, monkeypatch):
    path = tmp_path / "picks.json"
    monkeypatch.setattr(cp, "MAX_EXAMPLES", 3)
    first = cp.Picker(path=path)
    for i in range(5):
        first.learn(f"task number {i} about rockets", "monolith", "normal", "Updates")
    again = cp.Picker(path=path)
    assert again.count() == 3


def test_nonsense_is_not_learned(picker):
    picker.learn("do the thing", "gigantic", "normal", "Updates")
    picker.learn("", "zencode", "normal", "Updates")
    assert picker.count() == 0


def test_model_for_reuses_auto_assign_and_never_starts_a_bill(monkeypatch):
    import model_autoassign

    pool = [
        {"provider": "ollama", "model": "qwen-coder", "facts": {"quality": 0.6, "zencode": 0.9, "speed": 0.7},
         "local": True, "paid": False, "label": "Ollama · qwen-coder"},
        {"provider": "groq", "model": "llama-fast", "facts": {"quality": 0.6, "zencode": 0.5, "speed": 0.95},
         "local": False, "paid": False, "label": "Groq · llama-fast"},
    ]
    monkeypatch.setattr(model_autoassign, "candidates", lambda configured=None: pool)
    monkeypatch.setattr(model_autoassign, "_bench_state", lambda p, m: "ok")
    assert cp.model_for("zencode", table={})["model"] == "qwen-coder"
    assert cp.model_for("pico", table={})["model"] == "llama-fast"


def test_model_for_falls_back_to_the_router(monkeypatch):
    import model_autoassign

    monkeypatch.setattr(model_autoassign, "candidates", lambda configured=None: [])
    pick = cp.model_for("monolith", table={})
    assert pick["provider"] == "" and "router" in pick["label"].lower()


def test_pick_gives_everything_a_thread_needs(picker, monkeypatch):
    monkeypatch.setattr(cp, "model_for", lambda tier, **_: {"provider": "ollama", "model": "m", "label": "Ollama · m",
                                                            "local": True, "why": "fits"})
    pick = cp.pick("Fix the bug in the parser", picker=picker)
    assert pick["tier"] == "zencode" and pick["tier_label"] == cp.TIER_LABELS["zencode"]
    assert pick["provider"] == "ollama" and pick["local"] is True


def test_kinds_and_efforts_are_the_model_lineups():
    import model_lineup

    assert cp.TIER_LABELS == {"pico": "Pico", "monolith": "Monolith", "crescendo": "Crescendo", "zencode": "Zencode"}
    assert list(cp.EFFORTS) == [e.id for e in model_lineup.EFFORTS]
    assert all(model_lineup.family(tier) is not None for tier in cp.TIERS)


def test_the_rules_never_pick_aleph():
    huge = "\n".join(f"- part {i} of a very long job with many steps" for i in range(30))
    assert cp.rule_pick(huge)["effort"] == "super"
