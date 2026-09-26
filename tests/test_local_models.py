"""Local models on this PC and the free-model finder (Request R12–R13)."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import local_models
import model_finder


class FakeResponse:
    def __init__(self, status=200, payload=None, lines=()):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self._lines = lines
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def iter_lines(self):
        for line in self._lines:
            yield line.encode() if isinstance(line, str) else line

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_a_model_fits_the_graphics_card_the_ram_or_neither():
    room = {"vram_gb": 16.0, "ram_gb": 32.0}
    assert local_models.fits(5.2, room) == "gpu"
    assert local_models.fits(20.0, room) == "ram"
    assert local_models.fits(80.0, room) == "no"


def test_status_says_what_is_installed_and_which_models_fit(monkeypatch):
    monkeypatch.setattr(local_models, "ollama_exe", lambda: r"C:\ollama.exe")
    monkeypatch.setattr(local_models, "running", lambda: True)
    monkeypatch.setattr(local_models, "memory", lambda: {"vram_gb": 16.0, "ram_gb": 32.0})
    monkeypatch.setattr(local_models, "_get", lambda path, timeout=2.0: {"models": [
        {"name": "qwen3:8b", "size": 5_200_000_000, "details": {"family": "qwen3", "parameter_size": "8B", "quantization_level": "Q4_K_M"}}]})
    status = local_models.status()
    assert status["installed"] and status["running"] and status["models"][0]["name"] == "qwen3:8b"
    assert status["total_bytes"] == 5_200_000_000
    fitting = {item["name"]: item["fits"] for item in status["suggested"]}
    assert fitting["qwen3:8b"] == "gpu" and fitting["qwen3:32b"] in ("ram", "no")
    assert any(item["installed"] for item in status["suggested"] if item["name"] == "qwen3:8b")


def test_scan_finds_downloaded_gguf_files_and_says_if_they_fit(tmp_path, monkeypatch):
    big = tmp_path / "Downloads" / "Qwen3-8B-Q4_K_M.gguf"
    big.parent.mkdir(parents=True)
    big.write_bytes(b"0" * (60 * 1024 * 1024))
    (big.parent / "notes.txt").write_text("not a model")
    monkeypatch.setattr(local_models, "_search_dirs", lambda: [tmp_path / "Downloads"])
    monkeypatch.setattr(local_models, "memory", lambda: {"vram_gb": 16.0, "ram_gb": 32.0})
    result = local_models.scan()
    assert [f["name"] for f in result["files"]] == ["Qwen3-8B-Q4_K_M.gguf"]
    entry = result["files"][0]
    assert entry["quantization"] == "Q4_K_M" and entry["ready"] and entry["fits"] == "gpu"


def test_pulling_and_adding_need_ollama_and_a_real_file(tmp_path, monkeypatch):
    monkeypatch.setattr(local_models, "running", lambda: False)
    with pytest.raises(local_models.LocalModelError):
        local_models.pull("qwen3:8b")
    monkeypatch.setattr(local_models, "running", lambda: True)
    with pytest.raises(local_models.LocalModelError):
        local_models.pull("not a model name!!")
    monkeypatch.setattr(local_models, "ollama_exe", lambda: "")
    with pytest.raises(local_models.LocalModelError):
        local_models.add_file(str(tmp_path / "missing.gguf"))
    weights = tmp_path / "model.safetensors"
    weights.write_bytes(b"0" * 1024)
    with pytest.raises(local_models.LocalModelError):
        local_models.add_file(str(weights))


def test_a_pull_reports_progress_from_ollamas_stream(monkeypatch):
    lines = [json.dumps({"status": "pulling manifest"}),
             json.dumps({"status": "downloading", "total": 5_000_000_000, "completed": 2_500_000_000}),
             json.dumps({"status": "success"})]
    monkeypatch.setattr(local_models, "running", lambda: True)
    monkeypatch.setattr(local_models.requests, "post", lambda *a, **k: FakeResponse(200, {}, lines))
    job = local_models.pull("qwen3:8b", threaded=False)
    assert job["status"] == "done" and job["percent"] == 100.0
    assert any("2.5 of 5.0 GB" in entry["text"] for entry in job["log"])


def test_use_sets_the_offline_model_and_can_take_a_job(monkeypatch):
    from config import SETTINGS

    monkeypatch.setattr(SETTINGS, "ollama_model", "old")
    monkeypatch.setattr("model_choice.remember", lambda *a, **k: None)
    assigned = {}
    monkeypatch.setattr("model_roles.MODEL_ROLES.assign_role",
                        lambda role, provider, **kw: assigned.setdefault(role, {"title": "Data absorption", **kw}) or {"title": "Data absorption"})
    result = local_models.use("qwen3:8b", role="data_absorption")
    assert SETTINGS.ollama_model == "qwen3:8b" and result["role"] == "Data absorption"
    assert assigned["data_absorption"]["model"] == "qwen3:8b"


def test_install_only_runs_when_ollama_is_missing(monkeypatch):
    monkeypatch.setattr(local_models, "ollama_exe", lambda: "C:/ollama.exe")
    with pytest.raises(local_models.LocalModelError):
        local_models.install_ollama()


# --- model finder --------------------------------------------------------------------------------


def test_the_catalog_marks_what_is_already_set_up(monkeypatch):
    monkeypatch.setattr(model_finder, "configured", lambda: {"nvidia": True, "groq": False})
    results = model_finder.from_catalog()
    by_provider = {r["provider"]: r for r in results}
    assert by_provider["nvidia"]["note"] == "Already set up here."
    assert by_provider["groq"]["score"] > by_provider["nvidia"]["score"]     # what you do not have comes first
    assert all(r["signup"].startswith("http") for r in results)
    images = [r["provider"] for r in model_finder.from_catalog("images")]
    assert set(images) == {"nvidia", "pollinations"}      # both really do make pictures for free
    assert model_finder.from_catalog("quantum knitting") == []


def test_openrouter_free_models_are_the_ones_priced_at_zero():
    payload = {"data": [
        {"id": "meta-llama/llama-3.3-70b-instruct:free", "name": "Llama 3.3 70B (free)", "context_length": 131072,
         "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "openai/gpt-4o", "name": "GPT-4o", "context_length": 128000, "pricing": {"prompt": "0.0000025", "completion": "0.00001"}}]}
    free = model_finder.openrouter_free(get=lambda url, **kw: FakeResponse(200, payload))
    assert [f["model"] for f in free] == ["meta-llama/llama-3.3-70b-instruct:free"]
    assert free[0]["signup"] == "https://openrouter.ai/keys" and "131,072" in free[0]["free"]


def test_a_deep_search_reads_pages_and_keeps_only_the_free_ones(monkeypatch):
    monkeypatch.setattr(model_finder, "openrouter_free", lambda **kw: [])
    monkeypatch.setattr(model_finder, "configured", lambda: {})
    pages = {"https://free.example/api": "Our inference API has a free tier: 1M tokens a month, no credit card.",
             "https://paid.example/api": "Enterprise pricing starts at $2,000 a month."}

    def model_fn(prompt, *, system="", max_tokens=300):
        free = "free tier" in prompt
        return json.dumps({"free": free, "provider": "Example AI", "what_you_get": "1M free tokens a month",
                           "signup": "https://free.example/keys"})

    job = model_finder.search("vision", deep=True, threaded=False, model_fn=model_fn,
                              searcher=lambda q: [{"url": u, "title": u} for u in pages],
                              fetcher=lambda url: pages[url])
    assert job["status"] == "done"
    web = [r for r in job["results"] if r["kind"] == "web"]
    assert len(web) == 1 and web[0]["signup"] == "https://free.example/keys"
    assert job["searched"], "it should say what it searched for"
    assert model_finder.prefill(web[0])["company"] == "Example AI"


def test_the_finder_still_answers_without_a_model(monkeypatch):
    monkeypatch.setattr(model_finder, "openrouter_free", lambda **kw: [])
    monkeypatch.setattr(model_finder, "configured", lambda: {})

    def broken(*args, **kwargs):
        raise RuntimeError("no model")

    job = model_finder.search("", deep=True, threaded=False, model_fn=broken,
                              searcher=lambda q: [{"url": "https://x.example/free", "title": "Free LLM API"}],
                              fetcher=lambda url: "A free tier API for LLM models, no credit card needed.")
    assert job["status"] == "done"
    assert any(r["kind"] == "web" for r in job["results"])


# --- HTTP ----------------------------------------------------------------------------------------


@pytest.fixture()
def client():
    import server

    return TestClient(server.app, client=("127.0.0.1", 50041))


def test_routes_are_owner_only_and_report_the_machine(client, monkeypatch):
    import server

    monkeypatch.setattr(local_models, "ollama_exe", lambda: "")
    monkeypatch.setattr(local_models, "running", lambda: False)
    monkeypatch.setattr(local_models, "probe_servers", lambda *a, **k: [])
    body = client.get("/api/local-models").json()
    assert body["status"]["installed"] is False and body["status"]["suggested"]
    remote = TestClient(server.app, client=("203.0.113.7", 50042))
    assert remote.get("/api/local-models").status_code == 403
    assert remote.post("/api/local-models/pull", json={"name": "qwen3:8b"}).status_code == 403
    assert client.post("/api/local-models/pull", json={"name": "qwen3:8b"}).status_code == 409  # Ollama not running
    assert client.get("/api/model-finder").json()["catalog"]
