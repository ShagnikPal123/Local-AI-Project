"Tests for explicit memory lifecycle operations."""

from memory import MemoryStore

def test_memory_remove_and_clear(tmp_path):
    store = MemoryStore(tmp_path / "memory.json")
    store.remember_important("project", "Use local tests")
    store.remember_important("style", "Prefer concise code")
    assert store.remove_important("project") is True
    assert store.remove_important("missing") is False
    assert store.clear_important() == 1
    assert store.get_important() == []
