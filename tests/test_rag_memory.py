"""Tests for the RAG memory module."""

from memory import MemoryStore
from rag_memory import RagMemory, TokenOverlapIndex


def test_token_overlap_index_search():
    index = TokenOverlapIndex()
    index.add("a", "python coding tips for beginners", {"kind": "test"})
    index.add("b", "recipes for chocolate cake", {"kind": "test"})
    results = index.search("python coding", limit=5)
    assert results
    assert results[0]["id"] == "a"


def test_token_overlap_index_clear():
    index = TokenOverlapIndex()
    index.add("a", "some text here", {})
    index.clear()
    assert index.search("text") == []


def test_rag_memory_searches_important_memories(tmp_path):
    memory = MemoryStore(path=tmp_path / "memory.json")
    memory.remember_important("favorite color", "The user loves deep blue.")
    rag = RagMemory(memory=memory)
    results = rag.search("favorite color", limit=5)
    assert results
    assert results[0]["metadata"]["kind"] == "important"


def test_rag_memory_searches_preferences(tmp_path):
    memory = MemoryStore(path=tmp_path / "memory.json")
    memory.remember("coffee", "black, no sugar")
    rag = RagMemory(memory=memory)
    results = rag.search("coffee", limit=5)
    assert results
    assert results[0]["metadata"]["kind"] == "preference"


def test_rag_memory_no_match_returns_empty(tmp_path):
    memory = MemoryStore(path=tmp_path / "memory.json")
    rag = RagMemory(memory=memory)
    assert rag.search("nothing relevant here") == []


def test_rag_memory_mark_dirty_reindexes(tmp_path):
    memory = MemoryStore(path=tmp_path / "memory.json")
    rag = RagMemory(memory=memory)
    assert rag.search("topic") == []
    memory.remember_important("topic", "content about topic")
    rag.mark_dirty()
    assert rag.search("topic")


def test_build_context_prompt_empty_when_no_results(tmp_path):
    memory = MemoryStore(path=tmp_path / "memory.json")
    rag = RagMemory(memory=memory)
    assert rag.build_context_prompt("anything") == ""


def test_build_context_prompt_renders_results(tmp_path):
    memory = MemoryStore(path=tmp_path / "memory.json")
    memory.remember_important("project", "The project is called Nyx.")
    rag = RagMemory(memory=memory)
    prompt = rag.build_context_prompt("project")
    assert "Retrieved memory context" in prompt
    assert "Nyx" in prompt
