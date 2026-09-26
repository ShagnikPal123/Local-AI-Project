"""Tests for response_cache.py (OVERHAUL_CONTRACTS.md round 2, Coder B).

Every ``ResponseCache`` here is constructed with an explicit ``path`` so the
real data directory is never touched.
"""

from __future__ import annotations

import pytest

from response_cache import ResponseCache


class FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_cache(tmp_path, **kwargs) -> ResponseCache:
    return ResponseCache(path=tmp_path / "cache.json", **kwargs)


CTX = "personality:default|provider:gemini"


# --- exact + near-duplicate hits --------------------------------------------------------------


def test_exact_hit_after_store(tmp_path):
    cache = make_cache(tmp_path)
    stored = cache.store("What is the capital of France?", CTX, "Paris.", "gemini", "turn1")
    assert stored is True

    hit = cache.lookup("What is the capital of France?", CTX)
    assert hit is not None
    assert hit.reply == "Paris."
    assert hit.similarity == 1.0


def test_exact_match_is_normalisation_insensitive(tmp_path):
    cache = make_cache(tmp_path)
    cache.store("What is the capital of France?", CTX, "Paris.", "gemini", "turn1")

    hit = cache.lookup("  what IS the... capital of France  ", CTX)
    assert hit is not None
    assert hit.reply == "Paris."


def test_different_context_key_does_not_match(tmp_path):
    cache = make_cache(tmp_path)
    cache.store("What is the capital of France?", CTX, "Paris.", "gemini", "turn1")

    hit = cache.lookup("What is the capital of France?", "personality:pirate|provider:openai")
    assert hit is None


def test_near_duplicate_hit(tmp_path):
    cache = make_cache(tmp_path)
    cache.store(
        "Can you explain what photosynthesis is in simple terms",
        CTX, "Photosynthesis turns light into energy.", "gemini", "turn1",
    )

    hit = cache.lookup("Can you explain what photosynthesis is in simple terms please", CTX)
    assert hit is not None
    assert hit.reply == "Photosynthesis turns light into energy."
    assert hit.similarity >= 0.85


def test_dissimilar_message_is_a_miss(tmp_path):
    cache = make_cache(tmp_path)
    cache.store("Can you explain what photosynthesis is", CTX, "It turns light into energy.", "gemini", "turn1")

    hit = cache.lookup("Write me a poem about the ocean at midnight", CTX)
    assert hit is None


# --- refusal rules -----------------------------------------------------------------------------


@pytest.mark.parametrize("message", [
    "What is the weather today?",
    "What's the latest news on this?",
    "What time is it right now?",
    "What's the current stock price?",
])
def test_time_sensitive_messages_are_never_cached(tmp_path, message):
    cache = make_cache(tmp_path)
    assert cache.store(message, CTX, "some answer", "gemini", "turn1") is False
    assert cache.stats()["refusals"].get("time_sensitive", 0) >= 1


@pytest.mark.parametrize("message", [
    "Please remember that I like coffee",
    "My name is Alex",
    "I am a teacher",
    "Forget what I said earlier",
])
def test_personal_or_stateful_messages_are_never_cached(tmp_path, message):
    cache = make_cache(tmp_path)
    assert cache.store(message, CTX, "ok noted", "gemini", "turn1") is False
    assert cache.stats()["refusals"].get("personal", 0) >= 1


def test_word_anchoring_does_not_false_positive_on_substrings(tmp_path):
    """"update" contains "date" and "know" is close to "now" - must not trip the filter."""
    cache = make_cache(tmp_path)
    assert cache.store("Please update the documentation for this function", CTX, "Sure thing.", "gemini", "turn1") is True


def test_attachments_are_never_cached(tmp_path):
    cache = make_cache(tmp_path)
    stored = cache.store("Summarize this document", CTX, "It says...", "gemini", "turn1", attachments=["upload1"])
    assert stored is False
    assert cache.stats()["refusals"].get("attachments", 0) >= 1


def test_delegated_to_agents_is_never_cached(tmp_path):
    cache = make_cache(tmp_path)
    stored = cache.store("Build me a landing page", CTX, "Done.", "gemini", "turn1", agents=["designer"])
    assert stored is False
    assert cache.stats()["refusals"].get("delegated", 0) >= 1


def test_a_non_knowledge_tool_call_is_never_cached(tmp_path):
    cache = make_cache(tmp_path)
    stored = cache.store("Open my downloads folder", CTX, "Opened.", "gemini", "turn1", tools=["open_path"])
    assert stored is False
    assert cache.stats()["refusals"].get("tool_used", 0) >= 1


def test_pure_knowledge_tools_are_still_cacheable(tmp_path):
    cache = make_cache(tmp_path)
    stored = cache.store("What is the square root of 5764801", CTX, "2401.", "gemini", "turn1", tools=["solve_math"])
    assert stored is True


# --- TTL expiry with a fake clock ---------------------------------------------------------------


def test_ttl_expiry(tmp_path):
    clock = FakeClock()
    cache = make_cache(tmp_path, ttl_seconds=60.0, clock=clock)
    cache.store("What is the capital of France?", CTX, "Paris.", "gemini", "turn1")

    clock.advance(30)
    assert cache.lookup("What is the capital of France?", CTX) is not None

    clock.advance(31)  # total 61s, past the 60s TTL
    assert cache.lookup("What is the capital of France?", CTX) is None


# --- 👎 invalidation -----------------------------------------------------------------------------


def test_disliked_turn_is_invalidated(tmp_path):
    cache = make_cache(tmp_path)
    cache.store("What is the capital of France?", CTX, "Paris.", "gemini", "turn1")
    assert cache.lookup("What is the capital of France?", CTX) is not None

    removed = cache.invalidate_turn("turn1")
    assert removed == 1
    assert cache.lookup("What is the capital of France?", CTX) is None


def test_a_refused_dislike_reason_blocks_storing_when_rating_is_checked_directly():
    """_refusal_reason itself refuses a negative rating; store()'s own public
    contract is "already-disliked answers are never (re)cached", exercised via
    invalidate_turn above since store() has no rating parameter of its own."""
    reason = ResponseCache._refusal_reason("anything", rating=-1)
    assert reason == "disliked"


# --- LRU cap --------------------------------------------------------------------------------------


def test_lru_cap_evicts_the_least_recently_used_entry(tmp_path):
    cache = make_cache(tmp_path, max_entries=3)
    for i in range(3):
        cache.store(f"unique question number {i} about topic", CTX, f"answer {i}", "gemini", f"turn{i}")

    # Touch entry 0 so it becomes the most recently used, leaving 1 as the LRU victim.
    assert cache.lookup("unique question number 0 about topic", CTX) is not None

    cache.store("unique question number 3 about topic", CTX, "answer 3", "gemini", "turn3")

    assert cache.stats()["entries"] == 3
    assert cache.lookup("unique question number 0 about topic", CTX) is not None
    assert cache.lookup("unique question number 3 about topic", CTX) is not None
    assert cache.lookup("unique question number 1 about topic", CTX) is None


# --- stats -----------------------------------------------------------------------------------------


def test_stats_tracks_hits_misses_and_hit_rate(tmp_path):
    cache = make_cache(tmp_path)
    cache.store("What is the capital of France?", CTX, "Paris.", "gemini", "turn1")
    cache.lookup("What is the capital of France?", CTX)
    cache.lookup("Something completely unrelated to anything cached", CTX)

    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["hit_rate"] == pytest.approx(0.5)


# --- persistence -----------------------------------------------------------------------------------


def test_persistence_round_trip(tmp_path):
    path = tmp_path / "cache.json"
    first = ResponseCache(path=path)
    first.store("What is the capital of France?", CTX, "Paris.", "gemini", "turn1")

    second = ResponseCache(path=path)
    hit = second.lookup("What is the capital of France?", CTX)
    assert hit is not None
    assert hit.reply == "Paris."
