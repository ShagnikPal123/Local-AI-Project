"""The super brain calls Data Absorption relies on: what is already known, related concepts, forgetting a run."""

import pytest

import super_brain


@pytest.fixture()
def brain(tmp_path):
    return super_brain.SuperBrain(tmp_path / "brain.db", background=False)


def test_known_concepts_are_found_case_insensitively(brain):
    brain.ingest("Quantization lets large language models run on small graphics cards.", source="knowledge")
    known = brain.known_concepts(["Quantization", "graphics", "unheardofword"])
    assert "quantization" in known and "unheardofword" not in known


def test_related_concepts_follow_the_links(brain):
    for _ in range(2):
        brain.ingest("Options pricing depends on volatility and the strike price of the contract.", source="knowledge")
    related = brain.related_concepts(["volatility"])
    assert related and "volatility" not in related


def test_forget_ref_removes_only_that_runs_memories_and_recall_stops_finding_them(brain):
    brain.ingest("Ollama listens on port 11434 for local model requests.", source="knowledge", kind="absorbed", ref="absorb:run1:doc1")
    brain.ingest("Pizza dough needs to rest for an hour before baking.", source="web", ref="other")
    assert brain.recall("which port does ollama listen on")
    before = brain.counts()["memories"]
    assert brain.forget_ref("absorb:run1:") == 1
    assert brain.counts()["memories"] == before - 1
    assert not [m for m in brain.recall("which port does ollama listen on") if "11434" in m["text"]]
    assert brain.recall("pizza dough rest")
    assert brain.forget_ref("ab") == 0  # too short to be a real prefix
