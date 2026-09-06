"""Tests for the background thought loop (stay-in-thought continuation)."""

import time
from unittest.mock import MagicMock

from thought_loop import (
    BackgroundThinker,
    cleanup_thoughts,
    get_thought,
    list_thoughts,
    start_background_thought,
)


def _fake_service(interim_messages=("Searching the web...", "Verifying facts...")):
    service = MagicMock()

    def fake_chat(task, attribute_id=None, interim_callback=None):
        for message in interim_messages:
            if interim_callback:
                interim_callback(message)
        time.sleep(0.05)
        return ("final researched answer", "ollama")

    service.chat.side_effect = fake_chat
    return service


def test_background_thinker_completes_with_milestones():
    service = _fake_service()
    thinker = BackgroundThinker(service, "research this")
    thinker.start()
    status = thinker.wait(timeout=10)
    assert status["status"] == "complete"
    assert status["result"] == "final researched answer"
    assert "Searching the web..." in status["milestones"]
    assert status["provider"] == "ollama"


def test_background_thinker_isolates_state_between_thoughts():
    service = _fake_service()
    first = BackgroundThinker(service, "task one").start()
    second = BackgroundThinker(service, "task two").start()
    assert first.thought.thought_id != second.thought.thought_id
    first.wait(timeout=10)
    second.wait(timeout=10)
    assert first.status()["result"] == "final researched answer"
    assert second.status()["result"] == "final researched answer"


def test_background_thinker_records_error():
    service = MagicMock()
    service.chat.side_effect = RuntimeError("provider blew up")
    thinker = BackgroundThinker(service, "doomed task").start()
    status = thinker.wait(timeout=10)
    assert status["status"] == "error"
    assert "provider blew up" in status["error"]


def test_registry_start_and_poll():
    service = _fake_service()
    thinker = start_background_thought(service, "poll me")
    assert get_thought(thinker.thought.thought_id) is thinker
    assert any(t["thought_id"] == thinker.thought.thought_id for t in list_thoughts())
    status = thinker.wait(timeout=10)
    assert status["status"] == "complete"


def test_cleanup_removes_only_finished_old_thoughts():
    service = _fake_service()
    thinker = start_background_thought(service, "old task")
    thinker.wait(timeout=10)
    count = cleanup_thoughts(max_age_seconds=0.0)
    assert get_thought(thinker.thought.thought_id) is None
    assert count >= 1
