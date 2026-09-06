"""Tests for the speech pattern learning module."""

from speech_patterns import SpeechPatternStore, analyze_speech_patterns, format_patterns_for_prompt


def test_analyze_speech_patterns_detects_slang_and_emoji():
    messages = [
        "yo that's fire fr no cap 🔥",
        "lowkey wanna go out tbh 😂",
        "bet, let's do it 🎉",
    ]
    patterns = analyze_speech_patterns(messages)
    assert patterns["slang_usage"] == "frequent"
    assert patterns["emoji_usage"] == "frequent"


def test_analyze_speech_patterns_empty_input():
    assert analyze_speech_patterns([]) == {}
    assert analyze_speech_patterns(["", "  "]) == {}


def test_analyze_speech_patterns_short_style():
    patterns = analyze_speech_patterns(["ok", "sure", "yes"])
    assert patterns["message_style"] == "short"


def test_patterns_for_prompt_empty():
    assert format_patterns_for_prompt({}) == ""


def test_format_patterns_for_prompt_renders_guidance():
    patterns = {"slang_usage": "frequent", "message_style": "short"}
    text = format_patterns_for_prompt(patterns)
    assert "slang" in text.lower()
    assert "short" in text


def test_store_learn_and_clear(tmp_path):
    store = SpeechPatternStore(path=tmp_path / "patterns.json")
    assert store.get_patterns() == {}

    store.learn(["yo that's fire fr", "no cap, that's lit"])
    patterns = store.get_patterns()
    assert patterns["slang_usage"] == "frequent"

    assert store.clear() >= 1
    assert store.get_patterns() == {}


def test_store_persists_across_instances(tmp_path):
    path = tmp_path / "patterns.json"
    SpeechPatternStore(path=path).learn(["bet, let's go"])
    reloaded = SpeechPatternStore(path=path)
    assert reloaded.get_patterns()["slang_usage"] == "frequent"


def test_build_context_prompt_empty_when_no_patterns(tmp_path):
    store = SpeechPatternStore(path=tmp_path / "patterns.json")
    assert store.build_context_prompt() == ""
