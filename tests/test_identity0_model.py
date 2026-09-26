"""Identity 0's own model: the transformer, its tokenizer, training, layer-by-layer mode, serving, jobs."""

import json
import threading
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from identity0.model.config import PRESETS, ModelConfig  # noqa: E402
from identity0.model.runtime import KahunaLM, generate  # noqa: E402

TEXT = ("The Moon orbits the Earth. The Earth orbits the Sun. Plants make food from light in photosynthesis. "
        "Water boils at one hundred degrees Celsius at sea level. Rivers flow to the sea. ") * 40


def _tiny(seed: int = 0) -> KahunaLM:
    torch.manual_seed(seed)
    return KahunaLM(PRESETS["tiny"]).eval()


def test_parameter_count_matches_the_config():
    for name in ("tiny", "nano"):
        cfg = PRESETS[name]
        assert KahunaLM(cfg).parameter_count() == cfg.parameters()


def test_kv_cache_decoding_matches_a_full_recompute():
    model = _tiny()
    ids = torch.randint(0, 512, (1, 24))
    full = model(ids)[0]
    caches = model.new_caches(1, 32, "cpu", torch.float32)
    parts = [model(ids[:, :10], caches, start=0)[0]]
    parts += [model(ids[:, i:i + 1], caches, start=i)[0] for i in range(10, 24)]
    assert torch.allclose(torch.cat(parts), full, atol=1e-5)


def test_save_and_load_round_trip(tmp_path):
    model = _tiny()
    model.save(tmp_path)
    again = KahunaLM.load(tmp_path)
    ids = torch.randint(0, 512, (1, 8))
    assert torch.allclose(model(ids), again(ids), atol=1e-6)
    assert not (json.loads((tmp_path / "config.json").read_text())["tie_embeddings"] is False)


def test_tokenizer_round_trips_and_masks_only_the_assistant(tmp_path):
    from identity0.model.tokenizer import KahunaTokenizer

    tok = KahunaTokenizer.train([TEXT, "Hello, 世界! def f(x): return x"], 400, tmp_path)
    assert tok.decode(tok.encode("Hello, 世界!")) == "Hello, 世界!"
    ids, mask = tok.chat([{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello there"}],
                         add_generation_prompt=False)
    learned = tok.decode([t for t, m in zip(ids, mask) if m])
    assert "hello there" in learned and "hi" not in learned.replace("hello there", "")


def test_a_short_training_run_learns_and_writes_everything(tmp_path):
    from identity0.model import train

    rows = [{"messages": [{"role": "user", "content": "Who are you?"}, {"role": "assistant", "content": "I am Identity 0."}]}]
    metrics = train.run({"out": str(tmp_path), "texts": [TEXT] * 30, "preset": "tiny", "minutes": 0.25, "seq_len": 64,
                         "batch": 8, "cpu": True, "sft_rows": rows, "warmup": 5, "lr": 3e-3})
    assert metrics["steps"] > 5 and metrics["held_out_perplexity"] < 400  # random guessing over 512 tokens is 512
    for name in ("config.json", "tokenizer.json", "model.safetensors", "metrics.json"):
        assert (tmp_path / name).exists()
    assert not (tmp_path / "tokens_train.bin").exists()  # rebuilt on demand: kept small
    assert KahunaLM.load(tmp_path).cfg.vocab_size <= 512


@pytest.mark.parametrize("compression,tolerance", [(None, 1e-5), ("int8", 5e-2), ("nf4", 0.35)])
def test_layered_mode_matches_the_full_model(tmp_path, compression, tolerance):
    from identity0.model.layered import LayeredModel, shard

    model = _tiny(1)
    model.save(tmp_path / "full")
    info = shard(tmp_path / "full", tmp_path / "layers", compression=compression)
    assert info["files"] == PRESETS["tiny"].n_layers + 2
    layered = LayeredModel(tmp_path / "layers", device="cpu", dtype=torch.float32)
    ids = torch.randint(0, 512, (1, 12))
    diff = (layered.forward(ids) - model(ids)).abs().max().item()
    assert diff < tolerance, diff
    assert layered.loads == PRESETS["tiny"].n_layers  # one block reused, one load per layer


def test_layered_generation_uses_the_cache_and_matches_greedy(tmp_path):
    from identity0.model.layered import LayeredModel, shard

    model = _tiny(2)
    model.save(tmp_path / "full")
    shard(tmp_path / "full", tmp_path / "layers")
    layered = LayeredModel(tmp_path / "layers", device="cpu", dtype=torch.float32)
    prompt = [5, 6, 7, 8]
    assert list(layered.generate(prompt, max_new_tokens=6)) == list(generate(model, prompt, max_new_tokens=6, temperature=0))


def test_sharding_resumes_after_an_interruption(tmp_path):
    from identity0.model.layered import shard

    model = _tiny()
    model.save(tmp_path / "full")
    shard(tmp_path / "full", tmp_path / "layers")
    (tmp_path / "layers" / "head.safetensors").unlink()
    manifest = json.loads((tmp_path / "layers" / "manifest.json").read_text())
    manifest["files"].pop("head")
    (tmp_path / "layers" / "manifest.json").write_text(json.dumps(manifest))
    before = (tmp_path / "layers" / "layer_000.safetensors").stat().st_mtime_ns
    shard(tmp_path / "full", tmp_path / "layers")
    assert (tmp_path / "layers" / "head.safetensors").exists()
    assert (tmp_path / "layers" / "layer_000.safetensors").stat().st_mtime_ns == before


def test_layered_mode_is_off_unless_the_owner_and_max_power_allow_it(monkeypatch):
    from identity0 import state
    from identity0.model import layered

    assert not layered.allowed()["allowed"]
    state.update_settings(layered_mode="auto")
    import resource_governor

    monkeypatch.setattr(resource_governor.GOVERNOR, "_mode", resource_governor.PowerMode.MAX)
    assert layered.allowed()["allowed"]
    assert layered.needs_layered(20 * 2**30, 16 * 2**30, 32 * 2**30)


def test_serve_speaks_openai_and_the_client_streams(tmp_path, monkeypatch):
    from identity0.model import client, serve
    from identity0.model.tokenizer import KahunaTokenizer
    from http.server import ThreadingHTTPServer

    KahunaTokenizer.train([TEXT], 512, tmp_path)
    _tiny().save(tmp_path)
    engine = serve.Engine(tmp_path, "nano-test")
    server = ThreadingHTTPServer(("127.0.0.1", 0), serve.make_handler(engine))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(client, "URL", f"http://127.0.0.1:{server.server_address[1]}")
        client.forget()
        assert client.is_ready()
        pieces = list(client.stream_chat([{"role": "user", "content": "hello"}], max_tokens=8))
        assert isinstance("".join(pieces), str)
    finally:
        server.shutdown()


def test_registry_promotes_and_rolls_back(tmp_path):
    from identity0.model import registry

    registry.register("nano-v1", tmp_path / "a", kind="nano", metrics={"held_out_perplexity": 50.0})
    registry.register("nano-v2", tmp_path / "b", kind="nano", metrics={"held_out_perplexity": 40.0})
    registry.promote("nano-v1")
    registry.promote("nano-v2")
    assert registry.current()["version"] == "nano-v2"
    registry.rollback()
    assert registry.current()["version"] == "nano-v1"
    with pytest.raises(registry.RegistryError):
        registry.promote("nope")


def test_jobs_record_progress_and_honour_cancel():
    from identity0 import jobs

    job = jobs.start("serve", {}, spawn=False)
    assert jobs.get(job["id"])["state"] == "queued"
    jobs.cancel(job["id"])
    assert jobs.run(job["id"]) in (0, 1)
    assert jobs.get(job["id"])["state"] in ("cancelled", "done", "failed")
    with pytest.raises(jobs.JobError):
        jobs.start("rm -rf", {})


def test_the_app_side_never_imports_torch():
    import subprocess
    import sys

    code = ("import sys; import identity0.provider, identity0.jobs, identity0.model.client, identity0.model.registry, "
            "identity0.corpus.store, identity0.corpus.dataset, routes_identity0; print('torch' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(Path(__file__).parent.parent))
    assert out.stdout.strip().endswith("False"), out.stdout + out.stderr


def test_an_interrupted_training_run_is_picked_back_up(tmp_path, monkeypatch):
    """A sleep or a restart must not end a run that takes hours (server startup calls jobs.recover)."""
    from identity0 import jobs

    started = jobs.start("train_nano", {"minutes": 1}, spawn=False)
    started.update(state="running", pid=999999, version="nano-v9", progress=0.4)
    jobs._write(started)
    monkeypatch.setattr(jobs, "_alive", lambda pid: False)
    monkeypatch.setattr(jobs, "_spawn", lambda job_id: 4242)

    assert jobs.get(started["id"])["state"] == "interrupted"
    resumed = jobs.recover()
    assert resumed is not None and resumed["params"]["resume"] is True
    assert resumed["params"]["version"] == "nano-v9" and resumed["id"] != started["id"]
    assert jobs.recover() is None, "a run it already picked up must not be picked up again"
