"""Tests for the lightweight local memory store."""

from memory import MemoryStore


def test_memory_store_remembers_and_builds_context(tmp_path):
    """Memory should persist facts and include them in prompt context."""
    store = MemoryStore(path=tmp_path / "memory.json")

    store.remember("preferred_tone", "concise and practical")
    store.remember("favorite_tool", "Ollama when available")

    assert store.data["preferences"]["preferred_tone"] == "concise and practical"
    prompt = store.build_context_prompt()
    assert "concise" in prompt.lower()
    assert "ollama" in prompt.lower()


def test_memory_store_tracks_online_results(tmp_path):
    """Online result records should be kept separately from the local preference store."""
    store = MemoryStore(path=tmp_path / "memory.json")

    store.record_online_result(
        provider="perplexity",
        prompt="debugging a Python error",
        result="check the traceback and isolate the failing module",
    )

    assert store.data["online_results"][0]["provider"] == "perplexity"
    assert "traceback" in store.data["online_results"][0]["result"].lower()
