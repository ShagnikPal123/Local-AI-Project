from memory import MemoryStore

def test_checkpoint_survives_reload(tmp_path):
    path = tmp_path / "memory.json"
    store = MemoryStore(path)
    store.remember_conversation("chat-1", "important progress", "continue testing")
    reloaded = MemoryStore(path)
    assert reloaded.latest_checkpoint("chat-1")["next_step"] == "continue testing"
