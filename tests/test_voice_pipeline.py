"""The listening pipeline: when a sentence is finished, and when a draft may answer it.

No model is called here. `think_ahead` is off in every test that would otherwise
start the active-listening or drafting threads, so these are the rules only.
"""

from __future__ import annotations

import time

import pytest

import voice_pipeline


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Keep the owner's own voice settings out of the tests."""
    monkeypatch.setattr(voice_pipeline, "_settings_path", lambda: tmp_path / "voice_pipeline.json")
    monkeypatch.setattr(voice_pipeline, "_settings_cache", None, raising=False)
    voice_pipeline.update_settings(think_ahead=False)
    yield
    monkeypatch.setattr(voice_pipeline, "_settings_cache", None, raising=False)
    voice_pipeline._sessions.clear()


def test_a_trailing_and_is_not_the_end_of_a_sentence():
    assert voice_pipeline.completeness("open notes and") < 0.2
    assert voice_pipeline.completeness("what I want is to") < 0.2


def test_a_finished_question_scores_high_and_waits_less():
    score = voice_pipeline.completeness("what is the capital of France?")
    assert score > 0.8
    assert voice_pipeline.wait_for(score) < voice_pipeline.wait_for(0.1)


def test_the_pause_is_longest_when_the_sentence_is_still_open():
    config = voice_pipeline.settings()
    assert voice_pipeline.wait_for(0.05) == config["wait_open"]
    assert voice_pipeline.wait_for(0.6) == config["wait_unsure"]
    assert voice_pipeline.wait_for(0.95) == config["wait_done"]


def test_an_instruction_is_a_command_and_never_drafted():
    assert voice_pipeline.kind_of("open my downloads folder") == "command"
    assert voice_pipeline.draftable("open my downloads folder") is False
    # Anything that would act is out, even phrased as a question.
    assert voice_pipeline.draftable("could you send Ana an email about Friday") is False


def test_a_question_may_be_drafted():
    assert voice_pipeline.kind_of("how far away is the moon") == "question"
    assert voice_pipeline.draftable("how far away is the moon") is True


def test_think_reports_the_wait_and_never_needs_a_model():
    reply = voice_pipeline.think("s1", "what is the capital of France?", chat_id="c1")
    assert reply["complete"] > 0.8
    assert reply["wait_ms"] == voice_pipeline.settings()["wait_done"]
    assert reply["utterance_id"]
    assert reply["draft_ready"] is False


def test_the_draft_answers_the_words_it_was_written_for():
    state = voice_pipeline.session("s2")
    state.draft = "Paris is the capital of France."
    state.draft_for = "what is the capital of france"
    state.draft_at = time.time()
    state.draft_provider, state.draft_model = "ollama", "qwen3.5:9b"

    # Punctuation and case do not matter; the words do.
    taken = voice_pipeline.take_draft("s2", "What is the capital of France?")
    assert taken is not None
    assert taken["text"].startswith("Paris")
    # It is used once, so a second turn cannot answer from a stale draft.
    assert voice_pipeline.take_draft("s2", "What is the capital of France?") is None


def test_a_draft_is_refused_for_different_words():
    state = voice_pipeline.session("s3")
    state.draft = "Paris."
    state.draft_for = "what is the capital of france"
    state.draft_at = time.time()
    assert voice_pipeline.take_draft("s3", "what is the capital of Japan") is None


def test_a_draft_is_refused_once_it_is_stale():
    state = voice_pipeline.session("s4")
    state.draft = "Paris."
    state.draft_for = "what is the capital of france"
    state.draft_at = time.time() - voice_pipeline.DRAFT_TTL_SECONDS - 1
    assert voice_pipeline.take_draft("s4", "what is the capital of france") is None


def test_a_draft_is_never_used_for_an_instruction():
    state = voice_pipeline.session("s5")
    state.draft = "Sent."
    state.draft_for = "send ana an email"
    state.draft_at = time.time()
    assert voice_pipeline.take_draft("s5", "send ana an email") is None


def test_settings_survive_a_round_trip():
    voice_pipeline.update_settings(wait_done=300, smaller_panel=False)
    assert voice_pipeline.settings()["wait_done"] == 300
    assert voice_pipeline.settings()["smaller_panel"] is False
    voice_pipeline._settings_cache = None            # re-read from the file
    assert voice_pipeline.settings()["wait_done"] == 300


def test_an_idle_session_is_forgotten():
    state = voice_pipeline.session("s6")
    state.touched = time.time() - voice_pipeline.SESSION_TTL_SECONDS - 5
    voice_pipeline.session("s7")                     # any call sweeps the old ones
    assert "s6" not in voice_pipeline._sessions
