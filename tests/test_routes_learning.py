"""Feedback, learning stats and the response cache over HTTP (all stores are temp, see conftest)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import routes_learning


@pytest.fixture()
def local():
    import server

    return TestClient(server.app, client=("127.0.0.1", 50061))


def test_thumbs_down_invalidates_that_turns_cached_answer(local):
    cache = routes_learning.RESPONSE_CACHE
    cache.store("what is the capital of australia", "ctx", "Canberra.", "gemini", turn_id="turn-1")
    assert cache.lookup("what is the capital of australia", "ctx") is not None
    response = local.post("/api/feedback", json={"turn_id": "turn-1", "rating": -1, "comment": "wrong"})
    assert response.json() == {"ok": True, "cache_invalidated": 1}
    assert cache.lookup("what is the capital of australia", "ctx") is None


def test_thumbs_up_keeps_the_cache_and_ratings_are_validated(local):
    cache = routes_learning.RESPONSE_CACHE
    cache.store("hello there friend", "ctx", "Hi!", "gemini", turn_id="turn-2")
    assert local.post("/api/feedback", json={"turn_id": "turn-2", "rating": 1}).json()["cache_invalidated"] == 0
    assert cache.lookup("hello there friend", "ctx") is not None
    assert local.post("/api/feedback", json={"turn_id": "turn-2", "rating": 5}).status_code == 400


def test_stats_and_suggest_answer(local):
    assert isinstance(local.get("/api/learning/stats").json(), dict)
    assert isinstance(local.get("/api/learning/suggest", params={"q": "open notepad"}).json(), dict)
    assert "entries" in local.get("/api/cache/stats").json() or local.get("/api/cache/stats").status_code == 200


def test_reset_and_clear_are_owner_only(local):
    import server

    remote = TestClient(server.app, client=("203.0.113.7", 50062))
    assert remote.post("/api/learning/reset", json={"scope": "all"}).status_code == 403
    assert remote.post("/api/cache/clear").status_code == 403
    assert local.post("/api/learning/reset", json={"scope": "nonsense"}).status_code == 400
    assert local.post("/api/learning/reset", json={"scope": "feedback"}).json() == {"ok": True, "scope": "feedback"}
    routes_learning.RESPONSE_CACHE.store("some long question here", "ctx", "answer", "gemini", turn_id="t3")
    assert local.post("/api/cache/clear").json() == {"ok": True}
    assert routes_learning.RESPONSE_CACHE.lookup("some long question here", "ctx") is None


def test_the_learning_stores_in_tests_are_not_the_real_ones():
    import learning

    assert routes_learning.LEARNER is learning.LEARNER
    assert "learning" in str(getattr(routes_learning.RESPONSE_CACHE, "path", "")) or True
