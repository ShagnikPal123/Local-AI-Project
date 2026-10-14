"""voice_bench: each stage is timed on its own, nothing real is called here, and cloud models are never timed unasked."""

from __future__ import annotations

import voice_bench


def test_voice_tests_time_a_fresh_sample_and_the_cached_one():
    calls = []
    rows = voice_bench.time_voice_tests(["en-US-AriaNeural"], synth=lambda text, voice_id: calls.append((text, voice_id)))
    assert rows[0]["voice"] == "en-US-AriaNeural" and "first_ms" in rows[0] and "cached_ms" in rows[0]
    assert calls[0] == calls[1], "the second call must be the same line, so it shows the cached time"


def test_a_broken_voice_is_reported_and_the_rest_still_run():
    def synth(text, voice_id):
        if voice_id == "bad":
            raise RuntimeError("no such voice")
    rows = voice_bench.time_voice_tests(["bad", "good"], synth=synth)
    assert "no such voice" in rows[0]["error"] and "first_ms" in rows[1]


def test_first_sound_reports_first_and_last_chunk():
    result = voice_bench.time_first_sound("en-US-AriaNeural", stream=lambda text, voice: [180.0, 420.0, 900.0])
    assert result == {"voice": "en-US-AriaNeural", "first_chunk_ms": 180.0, "whole_clip_ms": 900.0, "chunks": 3}


def test_voice_to_action_is_a_dry_run():
    seen = []
    result = voice_bench.time_voice_to_action(lambda text, dry_run: seen.append(dry_run) or {"handled": True, "reply": "Opening Chrome."}, runs=3)
    assert seen == [True, True, True] and result["handled"] and result["reply"] == "Opening Chrome."


def test_a_cloud_voice_model_is_not_timed_unless_asked():
    called = []
    skipped = voice_bench.time_spoken_answer(run=lambda q: called.append(q), provider="groq")
    assert "skipped" in skipped and called == []
    timed = voice_bench.time_spoken_answer(run=lambda q: "Pasta with garlic. Quick and easy.", provider="ollama")
    assert timed["provider"] == "ollama" and timed["words"] == 6 and "answer_ms" in timed
