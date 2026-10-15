"""The turn loop keeps the owner's request alive, and says who really answered.

Request G (2026-09-15): a download request came back "I did not get a usable
answer back" twice (the model's tool call had raw Windows paths and could not be
parsed), and the next message — "switch to nvidia" — carried out the failed
request as well. Separately, the model dropdown never reached the turn.
"""

from __future__ import annotations

import types

import pytest

import turn_runner
from turn_runner import FAILED_TURN_NOTE, TurnRunner


class _Store:
    def __init__(self) -> None:
        self.rows = []

    def append(self, role, content, chat_id=None):
        self.rows.append((role, content))


class _Service:
    chat_id = "chat-g"
    enable_tools = True
    auto_web_search = False
    speed_mode = None
    _PERSONALITY_PREFIX = "[Personality"

    def __init__(self, router) -> None:
        self.router = router
        self.chat_store = _Store()
        self.conversation_history = [{"role": "system", "content": "standing instructions"}]
        self.speed_policy = types.SimpleNamespace(decide=lambda text, mode: types.SimpleNamespace(fast=False))

    def _attach_skills(self, text):
        return []

    def _apply_directives(self, directives):
        pass

    def add_message(self, role, content):
        self.conversation_history.append({"role": role, "content": content})

    def _append_assistant_response(self, reply):
        self.conversation_history.append({"role": "assistant", "content": reply})

    def _has_search_intent(self, text):
        return False


class _ScriptedRouter:
    """Returns scripted (text, provider) pairs and records what each call asked for."""

    def __init__(self, script, before=None) -> None:
        self.script = list(script)
        self.calls = []
        self.before = before or (lambda on_event, kw: None)

    def stream(self, history, on_event, **kw):
        self.calls.append(kw)
        self.before(on_event, kw)
        text, provider = self.script.pop(0) if self.script else ("", "fake")
        if text:
            on_event({"type": "text", "text": text})
        return text, provider


@pytest.fixture(autouse=True)
def quiet_learning(monkeypatch):
    monkeypatch.setattr(TurnRunner, "_learning_before", lambda self, *a, **k: {})
    monkeypatch.setattr(TurnRunner, "_learning_after", lambda self, *a, **k: None)
    monkeypatch.setattr(TurnRunner, "_optimize_prompt", lambda self, text, *a, **k: text)


def _run(router, message="make a download for my friends", **kw):
    events = []
    service = _Service(router)
    result = TurnRunner(service, message, sink=events.append, **kw).run()
    return result, events, service


def test_an_unreadable_tool_call_is_asked_for_again_instead_of_dropping_the_request():
    router = _ScriptedRouter([
        ("<tool_call>\nname: list_files\narguments: {not json at all", "gemini"),
        ("Here is the download.", "gemini"),
    ])
    result, events, service = _run(router)

    assert result["reply"] == "Here is the download."
    assert any("could not be read" in str(m.get("content")) for m in service.conversation_history)
    assert FAILED_TURN_NOTE not in [m.get("content") for m in service.conversation_history]


def test_an_empty_reply_is_retried_on_another_provider():
    router = _ScriptedRouter([("", "gemini"), ("Done.", "nvidia")])
    result, events, _ = _run(router)

    assert result["reply"] == "Done."
    assert router.calls[1]["exclude"] == ["gemini"]
    assert any(e["type"] == "status" and "empty reply" in e["text"] for e in events)


def test_a_turn_that_did_nothing_says_so_and_is_marked_not_pending():
    router = _ScriptedRouter([("", "gemini"), ("", "nvidia"), ("", "groq")])
    result, _, service = _run(router)

    assert result["reply"].startswith("Nothing was done for this request")
    assert service.conversation_history[-1]["content"] == FAILED_TURN_NOTE


def test_the_dropdown_provider_goes_to_the_router_and_a_fallback_is_announced():
    def unavailable(on_event, kw):
        on_event({"type": "provider.unavailable", "name": "nvidia", "reason": "no API key is set for nvidia"})

    router = _ScriptedRouter([("Hello.", "gemini")], before=unavailable)
    result, events, _ = _run(router, "hi", provider="NVIDIA")

    assert router.calls[0]["prefer"] == "nvidia"
    fallback = [e for e in events if e["type"] == "provider.fallback"]
    assert fallback == [{"type": "provider.fallback", "wanted": "nvidia", "used": "gemini",
                         "reason": "no API key is set for nvidia", "turn_id": fallback[0]["turn_id"]}]


def test_auto_means_the_router_decides():
    router = _ScriptedRouter([("Hello.", "gemini")])
    _run(router, "hi", provider="auto")
    assert router.calls[0]["prefer"] is None


def test_a_switch_made_by_a_tool_redirects_the_rest_of_the_turn():
    router = _ScriptedRouter([
        ('<tool_call>\nname: fake_switch\narguments: {}\n</tool_call>', "gemini"),
        ("Switched to nvidia.", "nvidia"),
    ])

    def fake_switch() -> str:
        from tool_context import emit

        emit("model.switched", provider="nvidia", model="")
        return "Switched."

    turn_runner.TOOL_REGISTRY.register("fake_switch", "test", [], fake_switch)
    try:
        result, events, _ = _run(router, "switch to nvidia", provider="gemini")
    finally:
        turn_runner.TOOL_REGISTRY.tools.pop("fake_switch", None)

    assert result["reply"] == "Switched to nvidia."
    assert router.calls[1]["prefer"] == "nvidia"
    assert not [e for e in events if e["type"] == "provider.fallback"]
    assert any(e["type"] == "model.switched" for e in events)


def test_an_answer_written_before_a_tool_call_is_not_lost_when_the_last_step_says_little():
    """Request H9: the model wrote the answer, then called a tool; the reset hid it and the turn ended on "Saved."."""
    from turn_runner import TurnRunner

    long_answer = "Here is the full plan. " * 30
    replies = iter([long_answer + '<tool_call>\nname: get_time\narguments: {}\n</tool_call>', "Saved."])

    class _Router:
        def stream(self, history, on_event, **kwargs):
            text = next(replies)
            on_event({"type": "provider", "name": "nvidia", "model": ""})
            on_event({"type": "text", "text": text})
            return text, "nvidia"

    class _Service:
        chat_id = "t"
        enable_tools = True
        auto_web_search = False
        conversation_history = [{"role": "user", "content": "plan it"}]
        router = _Router()

        def _append_assistant_response(self, reply):
            self.saved = reply

    service = _Service()
    events = []
    runner = TurnRunner(service, "plan it", sink=events.append)
    reply = runner._tool_loop(max_steps=4)
    assert reply.startswith("Here is the full plan.") and reply.endswith("Saved.")
    assert service.saved == reply


def test_a_swarm_turn_that_answers_alone_is_asked_once_to_use_its_swarm(monkeypatch):
    """Update 1, U5: in Swarm mode a model answered three planets from memory, and the mode looked like Normal."""
    import swarm

    monkeypatch.setattr(swarm, "limit", lambda: 6)
    router = _ScriptedRouter([("Mars is red. Venus is hot. Jupiter is big.", "ollama"),
                              ("Mars is red. Venus is hot. Jupiter is big.", "ollama")])
    result, events, service = _run(router, message="one fact about each of Mars, Venus and Jupiter", mode="swarm")

    nudges = [m for m in service.conversation_history if str(m.get("content", "")).startswith("You are in Swarm mode")]
    assert len(nudges) == 1, "asked once, never in a loop"
    assert result["reply"].startswith("Mars is red"), "a model that still answers alone is accepted the second time"
    assert any(e["type"] == "answer.reset" for e in events), "the first, swarm-less answer was taken off the screen"

    plain = _run(_ScriptedRouter([("Hi!", "ollama")]), message="hi there", mode="normal")[2]
    assert not any(str(m.get("content", "")).startswith("You are in Swarm mode") for m in plain.conversation_history)


# --- Integrity (Fixer Upper S26): act instead of refusing -------------------------------------------------------


def _nudges(service):
    return [m for m in service.conversation_history if str(m.get("content", "")).startswith("You stopped without doing")]


def test_a_turn_that_refuses_the_keyboard_is_asked_once_to_do_it():
    """The Google Docs transcript (2026-10-13): qwen3.5:9b said it could not type, with keyboard_type one step away."""
    router = _ScriptedRouter([
        ("I can't control your mouse or keyboard to type for you.", "ollama"),
        ("I can't control your mouse or keyboard to type for you.", "ollama"),
    ])
    result, events, service = _run(router, message="open google docs and type hi in a fresh document")

    assert len(_nudges(service)) == 1, "asked once, never in a loop"
    assert any(e["type"] == "status" and "Not giving up" in e["text"] for e in events)
    assert result["reply"].startswith("I can't"), "a model that still refuses is accepted the second time"


def test_a_typing_request_answered_without_the_keyboard_is_nudged_even_without_refusal_words():
    router = _ScriptedRouter([("The doc is open. Click in it and type hi.", "ollama"), ("Typed hi.", "ollama")])
    result, _, service = _run(router, message="type hi in a fresh google doc")

    assert len(_nudges(service)) == 1
    assert result["reply"] == "Typed hi."


def test_a_refusal_the_owner_caused_is_left_alone(monkeypatch):
    """When the owner's screen is set to "never", saying so is honest, not lazy."""
    monkeypatch.setattr(turn_runner.TOOL_REGISTRY, "call_tool",
                        lambda name, **kw: "Not on the owner's screen: The owner's screen is off-limits (keyboard type).")
    router = _ScriptedRouter([
        ("<tool_call>\nname: keyboard_type\narguments: {\"text\": \"hi\"}\n</tool_call>", "ollama"),
        ("I can't type on your screen: it is set to off-limits in the Computer tab.", "ollama"),
    ])
    result, _, service = _run(router, message="type hi in the open document")

    assert not _nudges(service)
    assert "off-limits" in result["reply"]


def test_plain_questions_and_plan_turns_are_never_nudged():
    plain = _run(_ScriptedRouter([("Use the menu: File, then New.", "ollama")]), message="how do I type a new doc?")[2]
    assert not _nudges(plain)
    chat = _run(_ScriptedRouter([("Hi! What can I do?", "ollama")]), message="hi there")[2]
    assert not _nudges(chat)


def _fold_service(replies, on_step=None):
    class _Router:
        step = 0

        def stream(self, history, on_event, **kwargs):
            _Router.step += 1
            if on_step:
                on_step(_Router.step)
            text = next(replies)
            on_event({"type": "text", "text": text})
            return text, "nvidia"

    class _Service:
        chat_id = "t"
        enable_tools = True
        auto_web_search = False
        conversation_history = [{"role": "user", "content": "build the page"}]
        router = _Router()

        def _append_assistant_response(self, reply):
            self.saved = reply

    return _Service()


def test_a_note_added_while_tools_run_is_folded_into_the_same_task(monkeypatch):
    """Active speech: "also make it blue" sent mid-task becomes part of the task, not a second turn."""
    import turn_registry

    turns = turn_registry.TurnRegistry()
    monkeypatch.setattr(turn_registry, "TURNS", turns)
    turns.start("fold-1", "t", "build the page")
    replies = iter(['<tool_call>\nname: get_time\narguments: {}\n</tool_call>', "Built it, and it is blue."])
    service = _fold_service(replies, on_step=lambda step: step == 1 and turns.add_note("fold-1", "also make it blue"))
    events = []
    reply = TurnRunner(service, "build the page", sink=events.append, turn_id="fold-1")._tool_loop(max_steps=4)

    assert reply == "Built it, and it is blue."
    tool_results = [m for m in service.conversation_history if m.get("_tool_results")]
    assert "also make it blue" in tool_results[-1]["content"]
    assert any(e["type"] == "speech" and e.get("source") == "fold" for e in events)
    assert not turns.listening("fold-1")          # closed before the last answer went out


def test_a_note_that_arrives_while_the_answer_is_written_gets_one_more_pass(monkeypatch):
    import turn_registry

    turns = turn_registry.TurnRegistry()
    monkeypatch.setattr(turn_registry, "TURNS", turns)
    turns.start("fold-2", "t", "write a haiku")
    replies = iter(["A haiku about rain.", "A haiku about rain, and one about snow."])
    service = _fold_service(replies, on_step=lambda step: step == 1 and turns.add_note("fold-2", "and one about snow"))
    events = []
    reply = TurnRunner(service, "write a haiku", sink=events.append, turn_id="fold-2")._tool_loop(max_steps=4)

    assert reply == "A haiku about rain, and one about snow."
    assert any("and one about snow" in str(m.get("content")) for m in service.conversation_history)
    assert [e["type"] for e in events].count("answer.reset") >= 1


def test_a_lineup_pick_becomes_the_turns_plan(monkeypatch, tmp_path):
    """Doc step 2: the new model names do something. "carbon" answers through Big Kahuna with Monolith's plan."""
    import model_lineup

    monkeypatch.setattr(model_lineup, "data_path", lambda name: tmp_path / name)
    runner = TurnRunner(_Service(_ScriptedRouter([])), "hello", sink=lambda e: None, provider="carbon")
    assert runner.lineup_plan is not None and runner.lineup_plan.family_id == "monolith"
    assert runner.prefer_provider == "identity0"


def test_a_provider_picked_by_hand_keeps_answering_when_effort_is_set(monkeypatch, tmp_path):
    import model_lineup

    monkeypatch.setattr(model_lineup, "data_path", lambda name: tmp_path / name)
    model_lineup.save_effort("high")
    runner = TurnRunner(_Service(_ScriptedRouter([])), "hello", sink=lambda e: None, provider="gemini")
    assert runner.lineup_plan is not None and runner.lineup_plan.effort == "high"
    assert runner.prefer_provider == "gemini"


def test_no_pick_and_auto_effort_leave_the_turn_as_it_was(monkeypatch, tmp_path):
    import model_lineup

    monkeypatch.setattr(model_lineup, "data_path", lambda name: tmp_path / name)
    runner = TurnRunner(_Service(_ScriptedRouter([])), "hello", sink=lambda e: None)
    assert runner.lineup_plan is None and runner.prefer_provider is None
