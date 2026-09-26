"""Data Absorption: reading, topics, safe fetching, runs, reports and approvals (Request R1–R8)."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import absorb_engine
import absorb_sources
import absorb_text


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

DOC = """# Efficient inference

Flash attention reduces the memory needed for long context windows in transformer models. Quantization to 4 bits lets
a 14B model run on a 16 GB GPU with little loss in accuracy. [Home](https://example.com) [Docs](https://example.com/docs)

See https://example.com | https://example.org | https://example.net

Ollama serves GGUF models locally and exposes an HTTP API on port 11434. Researchers at Stanford University measured a
2.4x throughput gain when the KV cache was paged instead of allocated per request.
"""


def test_lines_keep_order_and_skip_link_lists():
    lines = absorb_text.split_lines(DOC, limit=10)
    assert lines[0].startswith("Flash attention reduces")
    assert not any("example.org" in line for line in lines)
    assert any(line.startswith("Ollama serves GGUF") for line in lines)
    assert absorb_text.split_lines(DOC, limit=2) == [l for l in lines if l in absorb_text.split_lines(DOC, limit=2)]


def test_topics_highlight_longest_terms_and_names_without_a_topic():
    model = absorb_text.TopicModel(absorb_text.DEFAULT_TOPICS)
    line = "Flash attention and quantization let Ollama run models on an NVIDIA GPU at Stanford University."
    spans = model.match(line)
    terms = {(s["term"], s["topic"]) for s in spans}
    assert ("flash attention", "models") in terms          # not just "attention"
    assert ("quantization", "models") in terms
    assert any(s["term"] == "Stanford University" and s["topic"] is None for s in spans)
    for a, b in zip(spans, spans[1:]):
        assert a["e"] <= b["s"]                              # no overlapping highlights
        assert line[a["s"]:a["e"]]
    vote = model.vote(spans)
    assert abs(sum(vote.values()) - 1) < 0.01 and max(vote, key=vote.get) == "models"


def test_a_topic_learns_words_seen_next_to_its_terms():
    model = absorb_text.TopicModel([{"id": "models", "code": "MODEL", "name": "Models", "terms": ["quantization", "gguf", "inference"]}])
    line = "Quantization and GGUF inference make speculative decoding practical."
    added = []
    for _ in range(2):
        added += model.learn(line, model.match(line))
    assert ("models", "speculative decoding practical") in added or any("speculative" in term for _, term in added)
    assert any("speculative" in s["term"] for s in model.match("Speculative decoding practical at scale"))


def test_derived_and_planned_topics_have_unique_codes():
    topics = absorb_text.derive_topics([DOC, "Balance sheet debt and cash flow. Cash flow drives valuation of the balance sheet."])
    codes = [t["code"] for t in topics]
    assert len(codes) == len(set(codes)) and all(t["terms"] for t in topics)
    planned = absorb_text.topics_from_plan("options pricing", [
        {"name": "Black–Scholes", "code": "BS", "terms": ["volatility", "strike"], "queries": ["black scholes"]},
        {"name": "Greeks", "code": "BS", "terms": ["delta", "gamma"]}])
    assert [t["code"] for t in planned][0] == "BS" and planned[1]["code"] != "BS"
    fallback = absorb_text.topics_from_plan("options pricing volatility smile")
    assert fallback and fallback[0]["terms"]


# ---------------------------------------------------------------------------
# Fetching safely
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status=200, body=b"", headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}

    def iter_content(self, size):
        for i in range(0, len(self._body), size):
            yield self._body[i:i + size]

    def json(self):
        return json.loads(self._body)


def test_private_addresses_are_refused_even_after_a_redirect(monkeypatch):
    with pytest.raises(absorb_sources.SourceError):
        absorb_sources.check_url("http://127.0.0.1:8000/api/chats")
    with pytest.raises(absorb_sources.SourceError):
        absorb_sources.check_url("file:///C:/Windows/win.ini")
    monkeypatch.setattr(absorb_sources, "_public_host", lambda host: host == "public.example")
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse(302, headers={"location": "http://localhost:8000/api/chats"})

    with pytest.raises(absorb_sources.SourceError):
        absorb_sources.fetch("https://public.example/page", get=fake_get)
    assert calls == ["https://public.example/page"]


def test_downloads_are_capped_and_pages_turned_into_text(monkeypatch):
    monkeypatch.setattr(absorb_sources, "_public_host", lambda host: True)
    page = (b"<html><title>A page</title><nav>menu menu</nav><script>alert(1)</script><p>" + b"Real words here. " * 200 + b"</p></html>")
    body, kind, final = absorb_sources.fetch("https://x.example/a", get=lambda url, **k: FakeResponse(200, page, {"content-type": "text/html"}),
                                             max_bytes=1000)
    assert len(body) == 1000 and kind == "text/html" and final == "https://x.example/a"
    title, text = absorb_sources.html_to_text(page.decode())
    assert title == "A page" and "menu" not in text and "alert" not in text and "Real words here." in text


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


class FakeBrain(absorb_engine.BrainPort):
    def __init__(self):
        self.remembered = []
        self.distilled = []
        self.forgotten = []
        self.memories = []

    def remember(self, text, ref, topic=""):
        self.remembered.append((text, ref, topic))

    def known(self, terms):
        return {"memory", "models"}

    def recall(self, query, limit=6):
        return self.memories

    def forget(self, prefix):
        self.forgotten.append(prefix)
        return len([r for r in self.remembered if r[1].startswith(prefix)])

    def related(self, words, limit=12):
        return ["volatility", "hedging"]

    def distill(self, question, answer, ref):
        self.distilled.append((question, answer, ref))


def fake_model(prompt, *, system="", max_tokens=900):
    if "Name each group" in prompt:
        return json.dumps({"topics": [{"name": "Local inference", "code": "INFER"}, {"name": "Money", "code": "CASH"}]})
    if "Write down what an AI assistant should remember" in prompt:
        return "```json\n" + json.dumps({"summary": "It is about inference.", "facts": [
            {"text": "Quantization to 4 bits lets a 14B model run on a 16 GB GPU.", "topic": "INFER"},
            {"text": "Ollama exposes an HTTP API on port 11434 for local models.", "topic": "INFER"}],
            "qa": [{"q": "Which port does Ollama use?", "a": "11434"}]}) + "\n```"
    if "Write the report" in prompt:
        return json.dumps({"headline": "Nyx learned how local inference fits in 16 GB.", "learned": [{"code": "INFER", "points": ["4-bit fits"]}],
                           "suggestions": [
                               {"kind": "skill", "title": "Local model sizing", "why": "Several documents covered it",
                                "spec": {"name": "Local model sizing", "description": "Pick a model that fits",
                                         "instructions": "Check VRAM before picking a model.", "triggers": ["vram", "model size"]}},
                               {"kind": "speedup", "title": "Cache model lists", "why": "Faster", "spec": {"description": "Cache /api/tags", "target": ""}},
                               {"kind": "nonsense", "title": "x"}],
                           "next": ["Study speculative decoding"]})
    return ""


def make_engine(tmp_path, brain, **kw):
    docs = {
        "https://a.example/one": DOC,
        "https://a.example/two": "Cash flow and debt shape the balance sheet. Revenue grew 12% while margins fell to 31% in the quarter. " * 3,
    }

    def reader(candidate):
        return {**candidate, "title": candidate["url"].rsplit("/", 1)[-1].title(), "text": docs[candidate["url"]]}

    return absorb_engine.AbsorbEngine(store_dir=tmp_path / "absorb", model_fn=fake_model, brain=brain, reader=reader,
                                      upload_reader=lambda uid: {"kind": "upload", "title": "notes.txt", "text": DOC},
                                      threaded=False, line_seconds=0, sleep=lambda s: None, **kw)


def test_a_given_run_reads_everything_indexes_facts_and_writes_a_report(tmp_path):
    brain = FakeBrain()
    engine = make_engine(tmp_path, brain)
    live = engine.start("given", links=["https://a.example/one", "https://a.example/two"])
    run = engine.get(live["id"])
    assert run.status == "done", run.error
    assert [t["code"] for t in run.topics.topics][:2] == ["INFER", "CASH"]
    assert all(d["state"] == "indexed" for d in run.docs)
    assert run.counts["facts"] >= 2 and run.counts["examples"] >= 1
    assert all(ref.startswith(f"absorb:{run.id}:") for _, ref, _ in brain.remembered)
    assert brain.distilled and brain.distilled[0][1] == "11434"
    assert not any(d.get("text") for d in run.docs)           # documents themselves are not kept
    view = engine.live(run.id)
    assert view["stages"]["index"] == 2 and view["counts"]["rows"] == len(run.dataset)
    assert view["chart"] and {"t", "v", "topic"} <= set(view["chart"][0])
    assert view["reader"]["doc"]["lines"][0]["spans"] is not None
    report = run.report
    assert report["headline"].startswith("Nyx learned") and report["written_by"] == "model"
    kinds = [s["kind"] for s in run.suggestions]
    assert "skill" in kinds and "speedup" in kinds and "nonsense" not in kinds
    assert all(s["state"] == "pending" for s in run.suggestions)  # nothing is applied on its own
    saved = json.loads((tmp_path / "absorb" / "runs" / f"{run.id}.json").read_text(encoding="utf-8"))
    assert saved["status"] == "done"


def test_approving_a_skill_adds_it_and_dismissing_changes_nothing(tmp_path, monkeypatch):
    import skills

    store = skills.SkillStore(tmp_path / "skills.json", tmp_path / "library.json")
    monkeypatch.setattr(skills, "SKILL_STORE", store)
    engine = make_engine(tmp_path, FakeBrain())
    run = engine.get(engine.start("given", links=["https://a.example/one"])["id"])
    skill = next(s for s in run.suggestions if s["kind"] == "skill")
    speed = next(s for s in run.suggestions if s["kind"] == "speedup")
    result = engine.decide(run.id, skill["id"], "approve")
    assert result["state"] == "applied" and any(s["name"] == "Local model sizing" for s in store.list_skills())
    assert engine.decide(run.id, speed["id"], "dismiss")["state"] == "dismissed"
    with pytest.raises(absorb_engine.AbsorbError):
        engine.decide(run.id, skill["id"], "approve")


def test_forget_takes_the_runs_memories_back_out(tmp_path):
    brain = FakeBrain()
    engine = make_engine(tmp_path, brain)
    run_id = engine.start("given", links=["https://a.example/one"])["id"]
    assert engine.forget(run_id)["removed"] >= 1
    assert brain.forgotten == [f"absorb:{run_id}:"] and engine.get(run_id).forgotten


def test_a_prompt_run_plans_topics_searches_and_stops_on_time(tmp_path):
    clock = {"t": 1000.0}

    def tick():
        clock["t"] += 3
        return clock["t"]

    def papers(query, limit):
        return [{"kind": "paper", "title": f"Paper about {query}", "url": f"https://papers.example/{abs(hash(query)) % 997}",
                 "source": "OpenAlex", "text": DOC}]

    brain = FakeBrain()
    engine = make_engine(tmp_path, brain, finders={"papers": papers}, clock=tick)
    engine._reader = lambda c: {**c, "text": c.get("text") or DOC}
    live = engine.start("prompt", prompt="local model inference", settings={"minutes": 2, "sources": {"papers": True, "github": False, "wiki": False, "web": False}})
    run = engine.get(live["id"])
    assert run.status == "done" and run.topics.topics
    assert run.counts["indexed"] >= 1
    assert any("Searched" in entry["text"] for entry in run.log)


def test_starting_needs_the_right_inputs_and_one_run_at_a_time(tmp_path):
    engine = make_engine(tmp_path, FakeBrain())
    with pytest.raises(absorb_engine.AbsorbError):
        engine.start("given")
    with pytest.raises(absorb_engine.AbsorbError):
        engine.start("prompt", prompt="x")
    with pytest.raises(absorb_engine.AbsorbError):
        engine.start("given", links=["ftp://nope"])
    with pytest.raises(absorb_engine.AbsorbError):
        engine.start("teleport")
    assert absorb_engine.clean_settings({"speed": 99, "depth": 1, "parallel": "3"})["speed"] == 4.0
    assert absorb_engine.clean_settings({"depth": 1})["depth"] == 6


def test_chats_get_study_facts_only_when_they_fit(tmp_path, monkeypatch):
    brain = FakeBrain()
    engine = make_engine(tmp_path, brain)
    monkeypatch.setattr(absorb_engine, "settings", lambda: {"use_in_chats": True})
    brain.memories = [{"text": "Ollama listens on port 11434.", "ref": "absorb:abc:1", "score": 4.2, "source": "knowledge"},
                      {"text": "Unrelated chat line", "ref": "", "score": 9.0, "source": "chat"},
                      {"text": "Weak match", "ref": "absorb:abc:2", "score": 0.5, "source": "knowledge"}]
    notes = engine.knowledge_notes("which port does my local ollama server use?")
    assert "11434" in notes and "Unrelated" not in notes and "Weak match" not in notes
    assert engine.knowledge_notes("hi") == ""


def test_prune_trims_old_lines_before_removing_runs(tmp_path):
    engine = make_engine(tmp_path, FakeBrain())
    run_id = engine.start("given", links=["https://a.example/one"])["id"]
    result = engine.prune(cap_mb=0.000001)
    assert result["trimmed_docs"] >= 1 or result["removed_runs"] >= 1


def test_latex_never_becomes_a_topic():
    wiki = ("The attention weight is {\\displaystyle a_{ij}} for every token pair, and {\\displaystyle W_Q} is the query matrix. "
            "Transformers replace recurrence with attention in sequence models.")
    assert "displaystyle" not in " ".join(absorb_text.split_lines(wiki, limit=5)).lower()
    assert not any("displaystyle" in phrase for phrase in absorb_text.keyphrases(wiki, 8))
    assert any("attention" in phrase or "transformer" in phrase for phrase in absorb_text.keyphrases(wiki, 8))


def test_only_facts_that_are_really_in_the_document_are_kept(tmp_path):
    """A model that echoes the instructions, or adds something of its own, must not reach Nyx's memory."""
    def echoing_model(prompt, *, system="", max_tokens=900):
        if "Name each group" in prompt:
            return json.dumps({"topics": [{"name": "Local inference", "code": "INFER"}]})
        if "Write down what an AI assistant should remember" in prompt:
            return json.dumps({"summary": "two sentences", "facts": [
                {"text": "one self-contained fact, under 240 characters, with its numbers and names", "topic": "INFER"},
                {"text": "The Eiffel Tower was completed in 1889 in Paris and is made of iron.", "topic": "INFER"},
                {"text": "Quantization to 4 bits lets a 14B model run on a 16 GB GPU with little loss in accuracy.", "topic": "INFER"}],
                "qa": [{"q": "What does quantization allow?", "a": "A 14B model to run on a 16 GB GPU."}]})
        return ""

    brain = FakeBrain()
    engine = make_engine(tmp_path, brain)
    engine._model_fn = echoing_model
    run = engine.get(engine.start("given", links=["https://a.example/one"])["id"])
    kept = [text for text, _ref, _topic in brain.remembered]
    assert any("Quantization to 4 bits" in k for k in kept)
    assert not any("Eiffel" in k for k in kept)
    assert not any("self-contained fact" in k for k in kept)
    assert run.docs[0]["summary"] != "two sentences"
    assert run.counts["model_facts"] == 1


def test_json_salvages_a_reply_that_ran_out_of_tokens():
    cut = '{"summary": "It is about inference.", "facts": [{"text": "Ollama listens on 11434.", "topic": "INFER"}, {"text": "Quant'
    salvaged = absorb_engine.json_from(cut)
    assert salvaged["facts"][0]["text"] == "Ollama listens on 11434."


def test_json_from_survives_chatter_and_thinking():
    assert absorb_engine.json_from('<think>{"no": 1}</think> Sure! {"a": {"b": "}"}} trailing') == {"a": {"b": "}"}}
    assert absorb_engine.json_from("no json here") is None


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def test_routes_start_watch_and_refuse_other_machines(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import server

    engine = make_engine(tmp_path, FakeBrain())
    monkeypatch.setattr(absorb_engine, "ENGINE", engine)
    local = TestClient(server.app, client=("127.0.0.1", 50031))
    remote = TestClient(server.app, client=("203.0.113.9", 50032))
    assert remote.post("/api/absorb/start", json={"mode": "given", "links": ["https://a.example/one"]}).status_code == 403
    started = local.post("/api/absorb/start", json={"mode": "given", "links": ["https://a.example/one"]})
    assert started.status_code == 200, started.text
    run_id = started.json()["id"]
    assert local.get(f"/api/absorb/{run_id}/live").json()["status"] == "done"
    overview = local.get("/api/absorb").json()
    assert overview["runs"][0]["id"] == run_id and overview["defaults"]["depth"] == 14
    doc_id = engine.get(run_id).docs[0]["id"]
    assert local.get(f"/api/absorb/{run_id}/doc/{doc_id}").json()["doc"]["lines"]
    assert local.post(f"/api/absorb/{run_id}/explode").status_code == 404
    assert local.post("/api/absorb/start", json={"mode": "given"}).status_code == 409
    suggestion = engine.get(run_id).suggestions[0]
    assert remote.post(f"/api/absorb/{run_id}/suggestions/{suggestion['id']}/approve").status_code == 403
