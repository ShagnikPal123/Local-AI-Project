"""Super brain and Nyx Core: memories, recall, binary buffers, a network that grows without forgetting."""

from __future__ import annotations

import struct

import numpy as np
import pytest
from fastapi.testclient import TestClient

import nyx_core
import super_brain


@pytest.fixture()
def brain(tmp_path):
    return super_brain.SuperBrain(tmp_path / "brain.db", background=False)


def test_chunks_skip_link_lists_and_keep_sentences():
    text = ("Use high contrast for text so everyone can read it. [Dark Mode](dark-mode.md)\n\n"
            "- [Accessibility](accessibility.md)\n\nButtons need a clear label that says what happens.")
    pieces = super_brain.chunks(text)
    assert any("high contrast" in p for p in pieces) and any("clear label" in p for p in pieces)
    assert not any(p.strip().startswith("- [Accessibility]") for p in pieces)


def test_ingest_builds_memories_concepts_links_and_is_idempotent(brain):
    brain.ingest("Gemini flash lite answers quickly. Nemotron Ultra reasons deeply but is slower.", source="models")
    first = brain.counts()
    assert first["memories"] >= 1 and first["concepts"] >= 3 and first["edges"] >= 4 and first["hubs"] == 1
    brain.ingest("Gemini flash lite answers quickly. Nemotron Ultra reasons deeply but is slower.", source="models")
    assert brain.counts()["memories"] == first["memories"]  # known text is not stored twice


def test_recall_finds_the_substantive_memory(brain):
    brain.ingest("The owner prefers short answers with bullet points when asking about code.", source="chat")
    brain.ingest("Buttons in dark mode should use vibrant system colors with enough contrast against the background.", source="design")
    brain.ingest("Pizza dough needs to rest for an hour before baking.", source="web")
    hits = brain.recall("what colors should dark mode buttons use")
    assert hits and "dark mode" in hits[0]["text"].lower() and hits[0]["source"] == "design"


def test_points_and_edges_buffers_are_consistent(brain):
    brain.ingest("Circuits need a ground plane. A voltage regulator keeps the rail stable at 3.3 volts.", source="design")
    count, data = brain.points_buffer()
    assert len(data) == count * 24
    x, y, z, cluster, kind, weight = struct.unpack_from("<6f", data, 0)
    assert int(cluster) == super_brain.cluster_for("design") and int(kind) in (0, 1, 2)
    pairs, edge_data = brain.edges_buffer()
    indices = struct.unpack(f"<{pairs * 2}I", edge_data)
    assert pairs > 0 and max(indices) < count


def test_positions_cluster_by_source(brain):
    brain.ingest("Email from the professor about the lab report deadline next Friday.", source="email")
    brain.ingest("Search results about the fastest laptops for machine learning this year.", source="web")
    count, data = brain.points_buffer()
    rows = [struct.unpack_from("<6f", data, i * 24) for i in range(count)]
    centres = {c: np.mean([r[:3] for r in rows if int(r[3]) == c], axis=0) for c in {int(r[3]) for r in rows}}
    email, web = centres[super_brain.cluster_for("email")], centres[super_brain.cluster_for("web")]
    assert np.linalg.norm(email - web) > 60


def test_seed_folder_respects_protected_paths(brain, tmp_path, monkeypatch):
    folder = tmp_path / "notes"
    folder.mkdir()
    (folder / "ideas.md").write_text("Build a containment enclosure with an air gap and a physical kill switch.")
    (folder / ".env.local").write_text("SECRET=1")
    (folder / "secret.txt").write_text("the password is hunter2 for the vault")
    import permissions

    monkeypatch.setattr(permissions, "is_protected_path", lambda p: p.endswith("secret.txt"))
    brain.seed(["folder"], folder=str(folder), background=False)
    assert brain.recall("containment kill switch")
    assert not brain.recall("hunter2 password vault")
    assert brain.seeding["done"] == ["folder"] and not brain.seeding["running"]


def test_growing_net_widens_without_changing_its_answers():
    net = nyx_core.GrowingNet()
    idx, vals = nyx_core.features("search the web for gpu prices")
    for _ in range(30):
        net.learn(idx, vals, 1, 1, [0])
    _, before = net.forward(idx, vals)
    params = net.parameters()
    net.widen(0)
    _, after = net.forward(idx, vals)
    assert net.widths() == [24] and net.parameters() > params
    for head in before:
        assert np.allclose(before[head], after[head], atol=1e-2)
    for _ in range(200):
        net.learn(idx, vals, 1, 1, [0])
    net.deepen()
    _, deeper = net.forward(idx, vals)
    assert len(net.layers) == 2 and deeper["domain"].argmax() == 1


def test_core_learns_grows_predicts_and_completes(tmp_path):
    core = nyx_core.NyxCore(tmp_path / "core")
    samples = [("search the web for the latest gpu prices", "full", ["web_search"]),
               ("hi how are you today", "fast", []),
               ("send an email to my professor", "full", ["email_send"])]
    for i in range(160):
        text, mode, tools = samples[i % 3]
        core.observe_turn(turn_id=str(i), message=text, reply="done", mode=mode, escalated=False, provider="gemini",
                          model="flash", tools=tools, ok=True, latency_ms=800)
    snap = core.snapshot()
    assert snap["widths"][0] > 12 and any("grew" in g["event"] for g in snap["growth_log"])
    assert snap["domain_accuracy"] >= 0.9 and snap["level"] >= 1 and snap["parameters"] > 0
    assert core.predict("search the web for the latest gpu prices")["domain"] == "web"
    assert core.complete("send an ") == ["email"]
    assert core.recommend_model("search the web for the latest gpu prices")["provider"] == "gemini"
    view = core.network_view(text="send an email")
    assert view["layers"][0]["size"] == nyx_core.INPUT_DIM and view["links"]
    core._save(force=True)
    again = nyx_core.NyxCore(tmp_path / "core")
    assert again.snapshot()["widths"] == snap["widths"]


def test_levels_climb_with_parameters():
    assert nyx_core.NyxCore.level_for(10)["name"] == "Seed"
    assert nyx_core.NyxCore.level_for(600_000)["name"] == "Spark"
    top = nyx_core.NyxCore.level_for(9_000_000_000)
    assert top["name"] == "Frontier" and top["progress"] == 1.0 and top["next_at"] is None


def test_routes_serve_brain_and_core():
    import server

    super_brain.BRAIN.ingest("Nyx Core grows a neural network from every conversation it has.", source="chat")
    client = TestClient(server.app, client=("127.0.0.1", 50081))
    summary = client.get("/api/brain/summary").json()
    assert summary["nodes"] > 0 and len(summary["clusters"]) == len(super_brain.CLUSTERS)
    points = client.get("/api/brain/points")
    assert int(points.headers["x-count"]) * 24 == len(points.content)
    assert client.get("/api/brain/search", params={"q": "neural network"}).json()["memories"]
    assert "level" in client.get("/api/core").json()
    preview = client.post("/api/optimizer/preview", json={"text": "make this all"}).json()
    assert preview["mode"] == "expand" and preview["changed"]
    remote = TestClient(server.app, client=("203.0.113.9", 50082))
    assert remote.post("/api/brain/seed", json={"folder": "C:/"}).status_code == 403
    assert remote.put("/api/optimizer/settings", json={"enabled": True}).status_code == 403
