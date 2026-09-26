"""Tests for learning.py (OVERHAUL_CONTRACTS.md round 2, Coder B).

Every ``Learner`` here is constructed with explicit ``tmp_path`` files rather
than the module singleton, so the real data directory is never touched (the
class is lazy-loading specifically so this pattern works — see
``Learner.__init__``'s docstring).
"""

from __future__ import annotations

import hashlib
import random
import time

import pytest

from learning import (
    FeatureHasher,
    Learner,
    OnlineSoftmax,
    TurnSummary,
    _MIN_OBSERVATIONS,
    _MIN_ROUTE_UPDATES,
)


def make_learner(tmp_path) -> Learner:
    return Learner(
        turns_path=tmp_path / "turns.jsonl",
        models_path=tmp_path / "models.json",
        feedback_path=tmp_path / "feedback.jsonl",
    )


def make_summary(**overrides) -> TurnSummary:
    defaults = dict(
        turn_id="t0", chat_id="c0", message="hello there", mode="fast", escalated=False,
        provider="gemini", model="gemini-2.5-flash", agents=[], skills=[], tools=[],
        latency_ms=120.0, ok=True, reply_chars=40, ts=time.time(),
    )
    defaults.update(overrides)
    return TurnSummary(**defaults)


# --- FeatureHasher -----------------------------------------------------------------------


def test_hasher_bucket_is_stable_and_matches_the_documented_algorithm():
    """blake2b with a fixed digest_size and no key is deterministic across
    processes and runs — unlike Python's salted builtin hash(). Recomputing
    the expected bucket independently pins the exact algorithm, not just
    "some value or other"."""
    hasher = FeatureHasher()
    digest = hashlib.blake2b(b"w:hello", digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    expected_bucket = value % FeatureHasher.NUM_BUCKETS
    expected_sign = 1.0 if (value // FeatureHasher.NUM_BUCKETS) % 2 == 0 else -1.0

    bucket, sign = hasher.token_bucket("w:hello")
    assert bucket == expected_bucket
    assert sign == expected_sign

    # And stability across separate instances / "processes" in spirit.
    other = FeatureHasher()
    assert other.token_bucket("w:hello") == (bucket, sign)


def test_hasher_buckets_stay_within_range():
    hasher = FeatureHasher()
    features = hasher.featurize("Does this code have a bug? ```def f(): pass``` see https://x.com")
    assert features
    assert all(0 <= bucket < FeatureHasher.NUM_BUCKETS for bucket in features)


def test_hasher_meta_features_reflect_the_text():
    hasher = FeatureHasher()
    with_code = hasher.featurize("```python\ndef f(): pass\n```")
    without_code = hasher.featurize("just a plain sentence")
    # Not guaranteed to be literally disjoint (hash collisions exist), but the
    # code sample must add at least the has_code meta bucket that the plain
    # sentence does not have.
    assert set(with_code) - set(without_code)


# --- OnlineSoftmax -------------------------------------------------------------------------


def test_softmax_learns_a_separable_toy_problem():
    hasher = FeatureHasher()
    model = OnlineSoftmax()
    random.seed(0)

    def features_for(label: str):
        text = "alpha bravo charlie delta" if label == "a" else "wombat yonder zephyr quokka"
        return hasher.featurize(text)

    data = [(features_for("a"), "a") for _ in range(150)] + [(features_for("b"), "b") for _ in range(150)]
    random.shuffle(data)
    for features, label in data:
        model.learn(features, label)

    correct = 0
    for features, label in data:
        probs = model.predict_proba(features)
        predicted = max(probs, key=probs.get)
        correct += int(predicted == label)
    assert correct / len(data) > 0.9


def test_softmax_predict_proba_is_empty_before_any_label():
    model = OnlineSoftmax()
    assert model.predict_proba({1: 1.0}) == {}


def test_softmax_persistence_round_trip():
    hasher = FeatureHasher()
    model = OnlineSoftmax()
    for _ in range(20):
        model.learn(hasher.featurize("the quick brown fox"), "fox")
        model.learn(hasher.featurize("a slow green turtle"), "turtle")

    restored = OnlineSoftmax.from_dict(model.to_dict())
    probe = hasher.featurize("the quick brown fox jumps")
    original_probs = model.predict_proba(probe)
    restored_probs = restored.predict_proba(probe)
    assert set(original_probs) == set(restored_probs)
    for label in original_probs:
        assert original_probs[label] == pytest.approx(restored_probs[label], abs=1e-9)


# --- Learner: route model -------------------------------------------------------------------


def test_route_model_flips_to_full_after_repeated_escalations(tmp_path):
    learner = make_learner(tmp_path)
    message = "please help me plan this out"
    for i in range(_MIN_OBSERVATIONS + 10):
        learner.observe_turn(make_summary(turn_id=f"t{i}", message=message, mode="fast", escalated=True))

    assert learner.route_model.updates >= _MIN_ROUTE_UPDATES
    suggestion = learner.suggest(message)
    assert suggestion["route"] is not None
    assert suggestion["route"]["label"] == "full"


def test_a_full_turn_with_no_tools_and_thumbs_up_teaches_fast(tmp_path):
    learner = make_learner(tmp_path)
    message = "what is the capital of a hypothetical country called zorbaland"
    for i in range(_MIN_OBSERVATIONS + 5):
        turn_id = f"t{i}"
        learner.observe_turn(make_summary(turn_id=turn_id, message=message, mode="full", escalated=False, tools=[]))
        learner.feedback(turn_id, 1)

    suggestion = learner.suggest(message)
    assert suggestion["route"] is not None
    assert suggestion["route"]["label"] == "fast"


def test_a_fast_turn_with_thumbs_down_teaches_full_via_feedback(tmp_path):
    learner = make_learner(tmp_path)
    message = "summarize this for me in detail please"
    for i in range(_MIN_OBSERVATIONS + 5):
        turn_id = f"t{i}"
        learner.observe_turn(make_summary(turn_id=turn_id, message=message, mode="fast", escalated=False))
        learner.feedback(turn_id, -1)

    suggestion = learner.suggest(message)
    assert suggestion["route"] is not None
    assert suggestion["route"]["label"] == "full"


# --- Learner: cold start / suggest shape -----------------------------------------------------


def test_cold_start_returns_empty_lists_and_explains_why(tmp_path):
    learner = make_learner(tmp_path)
    suggestion = learner.suggest("anything at all")
    assert suggestion["route"] is None
    assert suggestion["agents"] == []
    assert suggestion["skills"] == []
    assert suggestion["provider_ranking"] == []
    assert suggestion["confidence"] == 0.0
    assert "cold start" in suggestion["explain"].lower()


def test_agent_suggestions_appear_after_enough_successful_turns(tmp_path):
    learner = make_learner(tmp_path)
    message = "refactor this python module for me"
    for i in range(_MIN_OBSERVATIONS + 5):
        learner.observe_turn(make_summary(turn_id=f"t{i}", message=message, mode="full", agents=["coder"], ok=True))

    suggestion = learner.suggest(message)
    names = [a["name"] for a in suggestion["agents"]]
    assert "coder" in names


def test_skill_suggestions_appear_from_use_skill_signal(tmp_path):
    learner = make_learner(tmp_path)
    message = "write me a haiku about autumn leaves"
    for i in range(_MIN_OBSERVATIONS + 5):
        learner.observe_turn(make_summary(
            turn_id=f"t{i}", message=message, mode="full", skills=["haiku-writer"], tools=["use_skill"],
        ))

    suggestion = learner.suggest(message)
    ids = [s["id"] for s in suggestion["skills"]]
    assert "haiku-writer" in ids


def test_provider_ranking_prefers_the_more_successful_provider(tmp_path):
    learner = make_learner(tmp_path)
    for i in range(15):
        learner.observe_turn(make_summary(turn_id=f"good{i}", provider="gemini", model="flash", ok=True, latency_ms=50))
    for i in range(15):
        learner.observe_turn(make_summary(turn_id=f"bad{i}", provider="groq", model="llama", ok=False, latency_ms=50))

    suggestion = learner.suggest("anything, this just needs enough total turns")
    ranking = {entry["provider"]: entry["score"] for entry in suggestion["provider_ranking"]}
    assert ranking["gemini/flash"] > ranking["groq/llama"]


# --- feedback changes suggestions (skill one-vs-rest) ------------------------------------------


def test_feedback_changes_skill_suggestions(tmp_path):
    learner = make_learner(tmp_path)
    message = "translate this sentence into french"
    # Seed enough total observations for suggest() to leave cold start, using
    # unrelated turns so they do not themselves teach the skill in question.
    for i in range(_MIN_OBSERVATIONS):
        learner.observe_turn(make_summary(turn_id=f"filler{i}", message="totally unrelated filler text"))

    for i in range(15):
        turn_id = f"skill{i}"
        learner.observe_turn(make_summary(turn_id=turn_id, message=message, mode="full", skills=["translator"]))
        learner.feedback(turn_id, 1)

    suggestion = learner.suggest(message)
    ids = {s["id"]: s["p"] for s in suggestion["skills"]}
    assert "translator" in ids
    assert ids["translator"] >= 0.6


# --- style hints -------------------------------------------------------------------------------


def test_style_hints_empty_without_enough_evidence(tmp_path):
    learner = make_learner(tmp_path)
    assert learner.style_hints() == ""


def test_style_hints_prefer_short_replies_once_the_evidence_is_in(tmp_path):
    learner = make_learner(tmp_path)
    for i in range(10):
        turn_id = f"short{i}"
        learner.observe_turn(make_summary(turn_id=turn_id, reply_chars=50))
        learner.feedback(turn_id, 1)
    for i in range(10):
        turn_id = f"long{i}"
        learner.observe_turn(make_summary(turn_id=turn_id, reply_chars=2000))
        learner.feedback(turn_id, -1)

    hints = learner.style_hints()
    assert "short" in hints.lower()


# --- persistence & reset --------------------------------------------------------------------


def test_persistence_round_trip_across_instances(tmp_path):
    turns_path = tmp_path / "turns.jsonl"
    models_path = tmp_path / "models.json"
    feedback_path = tmp_path / "feedback.jsonl"

    first = Learner(turns_path=turns_path, models_path=models_path, feedback_path=feedback_path)
    message = "does this survive a restart"
    for i in range(_MIN_OBSERVATIONS + 5):
        first.observe_turn(make_summary(turn_id=f"t{i}", message=message, mode="fast", escalated=True))
    first.flush()

    second = Learner(turns_path=turns_path, models_path=models_path, feedback_path=feedback_path)
    suggestion = second.suggest(message)
    assert suggestion["route"] is not None
    assert suggestion["route"]["label"] == "full"
    assert second.total_turns == first.total_turns


def test_reset_all_clears_everything(tmp_path):
    learner = make_learner(tmp_path)
    for i in range(_MIN_OBSERVATIONS + 5):
        learner.observe_turn(make_summary(turn_id=f"t{i}", mode="fast", escalated=True))
    learner.feedback("t0", 1)
    assert learner.total_turns > 0

    learner.reset("all")
    assert learner.total_turns == 0
    assert learner.feedback_counts == {}
    assert learner.suggest("anything")["explain"].lower().startswith("cold start")


def test_reset_feedback_only_keeps_models(tmp_path):
    learner = make_learner(tmp_path)
    message = "keep the models but drop feedback"
    for i in range(_MIN_OBSERVATIONS + 5):
        learner.observe_turn(make_summary(turn_id=f"t{i}", message=message, mode="fast", escalated=True))
    learner.feedback("t0", 1)

    learner.reset("feedback")
    assert learner.feedback_counts == {}
    # Route model weights (built purely from observe_turn/escalation, not feedback) survive.
    suggestion = learner.suggest(message)
    assert suggestion["route"]["label"] == "full"


def test_reset_rejects_an_unknown_scope(tmp_path):
    learner = make_learner(tmp_path)
    with pytest.raises(ValueError):
        learner.reset("bogus")


# --- stats -----------------------------------------------------------------------------------


def test_stats_reports_observations_and_feedback(tmp_path):
    learner = make_learner(tmp_path)
    learner.observe_turn(make_summary(turn_id="t0"))
    learner.feedback("t0", 1)
    stats = learner.stats()
    assert stats["observations"] == 1
    assert stats["feedback"]["positive"] == 1
    assert "route" in stats["models"]
