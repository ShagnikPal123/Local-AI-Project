"""Active speech: Nyx confirms what it understood, talks while it works, and answers a message sent mid-task.

The owner (2026-10-14): respond "in the beginning, middle and end … so it shows confirmation that the AI knows
what you are asking … if a new item is added to the queue it reads it, responds, and can split or … answer each one."
"""

from __future__ import annotations

import threading
import time

import pytest

import active_speech
from active_speech import Narrator, acknowledge, busy_ack, understand
from turn_registry import TurnRegistry


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _narrator(message="Can you rename my photos by date?", **options):
    events = []
    clock = _Clock()
    opts = {"enabled": True, "model_ack": False, "end_note": True, **options}
    return Narrator(message, events.append, options=opts, clock=clock), events, clock


def _speech(events, phase=None):
    return [e["text"] for e in events if e["type"] == "speech" and (phase is None or e["phase"] == phase)]


# --- understanding a message ---------------------------------------------------------------------------


def test_a_request_is_said_back_in_nyx_words():
    assert acknowledge("Can you rename my photos by date?") == "Got it — I'll rename your photos by date."
    assert acknowledge("Nyx, open my calendar") == "Got it — I'll open your calendar."
    assert acknowledge("I want a summary of my emails") == "Got it — you want a summary of your emails. On it."
    assert acknowledge("could you tell me what you know about rust") == "Got it — I'll tell you what I know about rust."


def test_questions_and_statements_are_quoted_back_and_small_talk_needs_no_receipt():
    assert acknowledge("what's the weather in Tokyo tomorrow?").startswith("Good question")
    assert "active speech" in acknowledge("One thing to add to the AI is active speech.")
    assert acknowledge("thanks!") == "" and acknowledge("hi") == ""
    assert understand("[fresh] what is 2+2?")[0] == "ask"


def test_a_model_line_is_used_when_it_is_short_and_clean():
    assert active_speech.model_acknowledge("x", ask=lambda p, b: "Sure, renaming your photos by date now") == \
        "Sure, renaming your photos by date now."
    assert active_speech.model_acknowledge("x", ask=lambda p, b: None) == ""
    assert active_speech.model_acknowledge("x", ask=lambda p, b: "<tool_call>bad") == ""

    def broken(prompt, budget):
        raise RuntimeError("offline")

    assert active_speech.model_acknowledge("x", ask=broken) == ""


# --- beginning, middle, end ----------------------------------------------------------------------------


def test_the_first_line_comes_from_the_rules_when_the_model_is_off():
    narrator, events, _clock = _narrator()
    narrator.start()
    assert _speech(events, "start") == ["Got it — I'll rename your photos by date."]
    assert events[0]["source"] == "rules"


def test_the_model_line_goes_first_when_it_answers_in_time():
    events = []
    narrator = Narrator("rename my photos", events.append, options={"enabled": True, "model_ack": True, "end_note": True},
                        ask=lambda p, b: "Got it, renaming your photos by date.")
    narrator.start(wait=True)
    assert _speech(events, "start") == ["Got it, renaming your photos by date."]
    assert events[0]["source"] == "model" and not events[0].get("replace")


def test_a_slow_model_line_replaces_the_rule_line(monkeypatch):
    monkeypatch.setattr(active_speech, "RULE_WAIT_SECONDS", 0.01)
    events = []
    release = threading.Event()

    def slow(prompt, budget):
        release.wait(2)
        return "Renaming your photos by date, starting with the newest."

    narrator = Narrator("rename my photos", events.append, options={"enabled": True, "model_ack": True, "end_note": True},
                        ask=slow)
    narrator.start()
    deadline = time.time() + 2
    while time.time() < deadline and not events:
        time.sleep(0.01)
    assert events and events[0]["source"] == "rules"
    release.set()
    while time.time() < deadline and len(events) < 2:
        time.sleep(0.01)
    assert events[1]["source"] == "model" and events[1]["replace"] is True


def test_middle_lines_are_spaced_out_capped_and_stop_once_the_answer_is_written():
    narrator, events, clock = _narrator()
    narrator.start()
    clock.now += 1
    narrator.observe({"type": "tool.start", "name": "search_web", "label": "Searching the web"})
    assert _speech(events, "middle") == []           # too soon after the first line
    clock.now += 7
    narrator.observe({"type": "tool.start", "name": "search_web", "label": "Searching the web"})
    assert _speech(events, "middle") == ["Searching the web now."]
    clock.now += 7
    narrator.observe({"type": "tool.start", "name": "search_web"})
    assert _speech(events, "middle") == ["Searching the web now."]   # never the same line twice
    clock.now += 7
    narrator.observe({"type": "answer.delta", "text": "Here"})
    narrator.observe({"type": "tool.start", "name": "read_file"})
    assert len(_speech(events, "middle")) == 1
    narrator.observe({"type": "answer.reset"})
    for name in ("read_file", "list_files", "run_python", "remember", "send_email"):
        clock.now += 7
        narrator.observe({"type": "tool.start", "name": name})
    assert len(_speech(events, "middle")) == active_speech.MAX_MIDDLE


def test_agents_and_long_waits_are_mentioned():
    narrator, events, clock = _narrator()
    clock.now += 7
    narrator.observe({"type": "agent.update", "name": "Coder", "status": "working"})
    clock.now += 30
    narrator.observe({"type": "thought.delta", "text": "hmm"})
    assert _speech(events, "middle") == ["Coder is helping with this now.",
                                         "Still on it — this one is taking a little longer."]


def test_the_end_line_comes_only_for_longer_turns():
    quick, events, clock = _narrator()
    clock.now += 2
    quick.observe({"type": "done"})
    assert _speech(events, "end") == []

    slow, events, clock = _narrator()
    clock.now += 7
    slow.observe({"type": "tool.start", "name": "search_web"})
    clock.now += 7
    slow.observe({"type": "done"})
    assert _speech(events, "end") == ["Done — 14 seconds, 1 step."]
    slow.observe({"type": "tool.start", "name": "read_file"})
    assert _speech(events, "middle") == ["Searching the web now."]   # nothing after the end


def test_stops_and_errors_say_so_and_off_means_silent():
    narrator, events, _clock = _narrator()
    narrator.observe({"type": "stopped"})
    assert _speech(events, "end") == ["Stopped — what I had so far is kept."]
    narrator, events, _clock = _narrator(enabled=False)
    narrator.start()
    narrator.observe({"type": "error", "message": "boom"})
    assert events == []


def test_settings_are_saved_and_unknown_keys_ignored():
    assert active_speech.settings() == active_speech.DEFAULTS
    assert active_speech.save_settings(end_note=False, bogus=True)["end_note"] is False
    assert active_speech.settings()["end_note"] is False and "bogus" not in active_speech.settings()


# --- a message that arrives mid-task ---------------------------------------------------------------------


@pytest.mark.parametrize("mode,words", [
    ("queue", "right after this"), ("interrupt", "stopping this"), ("parallel", "alongside"),
    ("branch", "branch"), ("fold", "adding"),
])
def test_every_mid_task_message_gets_an_answer_that_says_what_happens_to_it(mode, words):
    assert words in busy_ack("write a poem about the sea", mode)


def test_the_inbox_takes_notes_only_while_the_turn_listens():
    turns = TurnRegistry()
    turns.start("t1", "c1", "build the page")
    assert turns.add_note("t1", "also make it blue") is False      # not in its tool loop yet
    turns.open_inbox("t1")
    assert turns.listening("t1") and turns.add_note("t1", "also make it blue")
    assert turns.take_notes("t1") == ["also make it blue"] and turns.take_notes("t1") == []
    turns.add_note("t1", "and a footer")
    assert turns.take_notes("t1", close=True) == ["and a footer"]
    assert turns.add_note("t1", "too late") is False
    turns.open_inbox("t1")
    turns.finish("t1")
    assert not turns.listening("t1") and turns.add_note("t1", "after the end") is False
