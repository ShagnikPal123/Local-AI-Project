"""The court: sides are framed, every round is argued, judges vote, the owner can overrule, and it never crashes."""

import json

import pytest


@pytest.fixture()
def court(tmp_path, monkeypatch):
    import court as module

    monkeypatch.setattr(module, "_path", lambda: tmp_path / "court_cases.json")
    monkeypatch.setattr(module, "_cases", {})
    monkeypatch.setattr(module, "_loaded", True)
    monkeypatch.setattr(module, "_publish", lambda case: None)
    return module


def scripted(votes=("s1", "s1", "s2")):
    calls = []
    remaining = list(votes)

    def ask(messages, max_tokens):
        prompt = messages[0]["content"]
        calls.append(prompt)
        if "clerk" in prompt:
            return json.dumps({"sides": [{"name": "Tabs", "stance": "Use tabs"}, {"name": "Spaces", "stance": "Use spaces"}]})
        if "impartial judge" in prompt:
            return json.dumps({"side": remaining.pop(0), "reason": "Better evidence."})
        return "My argument."
    return ask, calls


def test_a_case_runs_every_round_and_the_majority_wins(court):
    ask, calls = scripted()
    case = court.start("Tabs or spaces?", ask=ask, background=False)
    assert [s["name"] for s in case["sides"]] == ["Tabs", "Spaces"]
    counsel = [t for t in case["transcript"] if t["role"] == "counsel"]
    assert [t["round"] for t in counsel] == ["opening", "opening", "rebuttal", "rebuttal", "closing", "closing"]
    assert case["status"] == "verdict" and case["verdict"]["winner"] == "s1"
    assert len(calls) == 1 + 6 + 3                     # the budget cap: 1 + 3 rounds × 2 sides + 3 judges


def test_a_split_bench_names_no_winner(court):
    ask, _ = scripted(votes=("s1", "s2", "nonsense"))
    case = court.start("Tabs or spaces?", ask=ask, background=False)
    assert case["verdict"]["split"] is True and case["verdict"]["winner"] == ""


def test_bad_framing_falls_back_to_for_and_against(court):
    case = court.start("Should we ship?", ask=lambda m, n: "not json", background=False)
    assert [s["name"] for s in case["sides"]] == ["For", "Against"]


def test_a_failing_model_ends_the_case_with_a_reason(court):
    def boom(messages, max_tokens):
        raise RuntimeError("no key")
    case = court.start("Anything?", ask=boom, background=False)
    assert case["status"] == "failed" and "no key" in case["note"]


def test_the_owner_can_pick_the_winner(court):
    ask, _ = scripted()
    case = court.start("Tabs or spaces?", ask=ask, background=False)
    picked = court.pick(case["id"], "s2")
    assert picked["owner_pick"] == "s2"
    with pytest.raises(ValueError):
        court.pick(case["id"], "s9")


def test_several_questions_and_an_empty_one(court):
    ask, _ = scripted()
    case = court.start(["Is A better?", "Is B cheaper?"], ask=ask, background=False)
    assert case["questions"] == ["Is A better?", "Is B cheaper?"]
    with pytest.raises(ValueError):
        court.start("   ", ask=ask, background=False)


def test_tools_register_and_open_windows(court, monkeypatch):
    sent = []
    import agent_events

    monkeypatch.setattr(agent_events, "publish_ui", lambda type, **p: sent.append((type, p)))
    assert "game window" in court.tool_open_window("Game Studio")
    assert sent[-1] == ("ui.open_window", {"kind": "game", "title": ""})
    assert court.tool_open_window("fridge").startswith("Error")
