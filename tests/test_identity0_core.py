"""Identity 0 (Big Kahuna) as the main brain: it leads, it falls back, it never loops, it learns."""

import json
import threading
import time
from unittest.mock import patch

import pytest

from providers.base import Provider, ProviderError


class Fake(Provider):
    """A provider that streams fixed chunks, optionally failing partway."""

    def __init__(self, name, chunks=("hello ", "world"), fail_at=None, vision=False):
        self.name = name
        self.chunks = list(chunks)
        self.fail_at = fail_at
        self.supports_vision = vision
        self.calls = []

    def is_available(self):
        return True

    def list_models(self):
        return ["fake-local"]

    def chat(self, messages):
        return "".join(self.chunks)

    def stream_events(self, messages, *, model=None, thinking=False):
        self.calls.append(model)
        for index, chunk in enumerate(self.chunks):
            if self.fail_at is not None and index == self.fail_at:
                raise ProviderError(f"{self.name} broke")
            yield {"type": "text", "text": chunk}
        if self.fail_at is not None and self.fail_at >= len(self.chunks):
            raise ProviderError(f"{self.name} broke")


@pytest.fixture
def kahuna(monkeypatch):
    """A real Router whose providers are fakes, with Big Kahuna switched on."""
    from device_profile import Tier
    from identity0 import members, state

    monkeypatch.setattr("router.is_online", lambda: True)
    monkeypatch.setattr("router.get_device_profile", lambda: None)
    monkeypatch.setattr("router.select_tier", lambda _p: Tier(name="large", model_tag="x"))
    monkeypatch.setattr(members, "_ollama_info", lambda _m: {})
    import router as router_module

    # Fakes that fail on purpose would otherwise stay "recently failed" for 5 minutes and reorder later tests.
    monkeypatch.setattr(router_module, "_RECENT_FAILURE", {})
    monkeypatch.setattr(router_module, "_SMART_COOLDOWN", {})

    r = router_module.Router()
    local, nvidia, gemini = Fake("ollama", ("local ", "answer")), Fake("nvidia", ("nv ", "answer")), Fake("gemini", ("gem ", "answer"))
    r.ollama = local
    r.providers = {"identity0": r.providers["identity0"], "ollama": local, "nvidia": nvidia, "gemini": gemini}
    r.custom = {}
    state.update_settings(enabled=True, shadow_rate=0.0, panel_on_hard=False)
    members.forget_cache()
    return r, local, nvidia, gemini


def _stream(r, text="Tell me about rivers"):
    events = []
    reply, used = r.stream([{"role": "user", "content": text}], events.append)
    return reply, used, events


def _records():
    from identity0 import state

    path = state.path("experiences.jsonl")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_big_kahuna_leads_the_chain_only_when_enabled(kahuna):
    from identity0 import members, state

    r, *_ = kahuna
    assert r._candidate_chain()[0].name == "identity0"
    state.update_settings(enabled=False)
    members.forget_cache()
    assert all(p.name != "identity0" for p in r._candidate_chain())


def test_answer_comes_from_the_best_member_and_is_recorded(kahuna):
    r, local, *_ = kahuna
    reply, used, events = _stream(r)
    assert used == "identity0"
    assert reply == "local answer"  # local, free, private: the prior favours it with no history
    labels = [e.get("model") for e in events if e["type"] == "provider"]
    assert "ollama:fake-local" in labels
    record = _records()[-1]
    assert record["lead"]["member"] == "ollama:fake-local" and record["lead"]["ok"]
    assert record["trainable"]["lead"] is False  # "fake-local" is no known open-license family


def test_a_lead_that_fails_before_text_hands_over_inside_kahuna(kahuna):
    r, local, nvidia, gemini = kahuna
    local.fail_at = 0
    reply, used, _ = _stream(r)
    assert used == "identity0"
    assert reply in ("nv answer", "gem answer")
    assert _records()[-1]["lead"]["member"].split(":")[0] in ("nvidia", "gemini")


def test_a_lead_that_fails_mid_answer_is_reset_not_mixed(kahuna):
    r, local, *_ = kahuna
    local.fail_at = 1  # "local " arrives, then it breaks
    reply, _, events = _stream(r)
    assert "local" not in reply
    assert any(e["type"] == "reset" for e in events)


def test_a_bug_in_kahuna_falls_through_to_the_old_chain(kahuna, monkeypatch):
    from identity0 import provider

    r, *_ = kahuna
    monkeypatch.setattr(provider, "make_plan", lambda *_a, **_k: 1 / 0)
    reply, used, _ = _stream(r)
    assert used != "identity0" and reply.endswith("answer")


def test_it_can_never_call_itself(kahuna):
    r, local, nvidia, gemini = kahuna
    for fake in (local, nvidia, gemini):
        fake.fail_at = 0
    kahuna_provider = r.providers["identity0"]
    calls = []
    original = kahuna_provider.stream_events

    def counting(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    kahuna_provider.stream_events = counting
    with pytest.raises(ProviderError):
        _stream(r)
    assert len(calls) == 1


def test_paid_providers_join_only_when_they_are_the_owners_pick(kahuna):
    import model_choice
    from identity0 import members

    r, *_ = kahuna
    r.providers["deepseek"] = Fake("deepseek")
    members.forget_cache()
    with patch("router.SETTINGS.free_only", False):
        assert not any(m.provider == "deepseek" for m in members.available(r, refresh=True))
        model_choice.remember("deepseek")
        assert any(m.provider == "deepseek" for m in members.available(r, refresh=True))


def test_competence_prefers_the_member_that_wins():
    from identity0 import competence
    from identity0.members import Member

    a = Member("nvidia:x", "nvidia", "x", False, True, False, "a")
    b = Member("gemini:y", "gemini", "y", False, True, False, "b")
    for _ in range(8):
        competence.record_verdict("code", b.id, a.id)
    assert competence.rank("code", [a, b])[0].id == b.id


def test_own_model_graduates_then_is_demoted():
    from identity0 import competence

    changes = [competence.record_verdict("chat", "self:nano-v1", "ollama:q") for _ in range(40)]
    assert "graduated" in changes and competence.graduated("chat")
    changes = [competence.record_verdict("chat", "ollama:q", "self:nano-v1") for _ in range(40)]
    assert "demoted" in changes and not competence.graduated("chat")
    assert competence.stage("chat", True) == "twin" and competence.stage("chat", False) == "collaborate"


def test_judge_counts_a_winner_only_when_both_readings_agree(monkeypatch):
    from identity0 import collab, judge

    def reply(winner):
        return {"ok": True, "text": json.dumps({"winner": winner, "confidence": 0.9, "reason": "r"}), "ms": 1}

    # A judge that always prefers whatever it reads first: position bias → a tie.
    monkeypatch.setattr(collab, "complete", lambda *a, **k: reply("A"))
    assert judge.compare("q {x}", "a {json}", "b }", judge="ollama:j")["winner"] == "tie"

    # A judge that recognises answer "good" in either position → a real winner.
    def fair(member, messages, **kwargs):
        prompt = messages[0]["content"]
        first = prompt.split("Answer A:\n", 1)[1].split("\n\nAnswer B:", 1)[0]
        return reply("A" if first == "good" else "B")

    monkeypatch.setattr(collab, "complete", fair)
    assert judge.compare("q", "bad", "good", judge="ollama:j")["winner"] == "b"


def test_a_shadow_that_wins_is_learned(kahuna, monkeypatch):
    from identity0 import competence, judge, provider, state

    r, local, nvidia, gemini = kahuna
    nvidia.chunks = gemini.chunks = ["Tides come from the Moon's gravity pulling the oceans ", "into two bulges."]
    state.update_settings(shadow_rate=1.0)
    monkeypatch.setattr(judge, "compare", lambda *a, **k: {"ok": True, "winner": "b", "confidence": 0.8,
                                                            "by": "gemini:j", "reason": "b is right"})
    provider.set_current_turn("turn-1")
    try:
        _stream(r, "Explain how tides work in detail please")
    finally:
        provider.set_current_turn("")
    deadline = time.time() + 5
    while time.time() < deadline and not any(rec.get("verdict") for rec in _records()):
        time.sleep(0.05)
    record = next(rec for rec in _records() if rec.get("verdict"))
    assert record["verdict"]["winner"] == "shadow" and record["learned"]
    shadow = record["shadow"]["member"]
    assert competence.table()["domains"][record["domain"]][shadow]["wins"] == 1


def test_internal_calls_never_spend_on_shadows(kahuna):
    from identity0 import state

    r, *_ = kahuna
    state.update_settings(shadow_rate=1.0)
    _stream(r)
    time.sleep(0.2)
    assert all(rec["shadow"] is None for rec in _records())


def test_feedback_moves_the_leads_rating(kahuna):
    from identity0 import competence, experience, provider

    r, *_ = kahuna
    provider.set_current_turn("turn-9")
    try:
        _stream(r)
    finally:
        provider.set_current_turn("")
    assert experience.on_feedback("turn-9", 1)
    domain = _records()[-1]["domain"]
    assert competence.table()["domains"][domain]["ollama:fake-local"]["rating"] == 1


def test_experience_file_is_capped(monkeypatch):
    from identity0 import experience, state

    state.update_settings(experience_cap_mb=1)
    big = "x" * 7000
    for i in range(200):
        experience.write({"id": f"e{i}", "ts": i, "prompt": big, "protocol": "solo"})
    assert state.path(experience.FILE).stat().st_size <= 1024 * 1024 + 20000
    assert experience.recent(1)[0]["id"] == "e199"


def test_settings_are_validated():
    from identity0 import state

    with pytest.raises(state.SettingsError):
        state.update_settings(shadow_rate=3)
    with pytest.raises(state.SettingsError):
        state.update_settings(layered_mode="always")
    with pytest.raises(state.SettingsError):
        state.update_settings(nonsense=1)
    assert state.update_settings(layered_mode="auto")["layered_mode"] == "auto"


def test_ollama_streams_the_named_model_with_thinking_and_a_real_context(monkeypatch):
    from providers import ollama_provider

    sent = {}

    class Response:
        status_code = 200
        encoding = None

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def iter_lines(self, decode_unicode=True):
            yield json.dumps({"message": {"thinking": "hmm"}})
            yield json.dumps({"message": {"content": "hi"}})

    def post(url, json=None, **kwargs):
        sent.update(json)
        return Response()

    monkeypatch.setattr(ollama_provider.requests, "post", post)
    provider = ollama_provider.OllamaProvider()
    events = list(provider.stream_events([{"role": "user", "content": "x", "images": [{"data": "QUJD"}]}],
                                         model="qwen3.5:9b", thinking=True))
    assert events == [{"type": "thought", "text": "hmm"}, {"type": "text", "text": "hi"}]
    assert sent["model"] == "qwen3.5:9b" and sent["think"] is True
    assert sent["options"]["num_ctx"] >= 8192 and sent["messages"][0]["images"] == ["QUJD"]
