"""Shared test fixtures.

Isolates on-disk state so the suite cannot write into the user's real data.

Before this existed, any test constructing a bare ``ChatService`` fell through to
the default ``chats.json`` / ``memory.json`` in the project root and appended to
them. A single run added ~50 assistant messages to real chat history, and the
accumulated junk made ``test_chat_sessions`` fail intermittently depending on
what previous runs had left behind.
"""

from pathlib import Path

import pytest

import chat_sessions
import memory


@pytest.fixture(autouse=True)
def isolate_persistent_stores(tmp_path, monkeypatch):
    """Point the default chat and memory files at a per-test temp directory.

    Tests that pass an explicit path or store are unaffected; this only replaces
    the fallback used when nothing is supplied.
    """
    original_memory_init = memory.MemoryStore.__init__
    original_chat_init = chat_sessions.ChatSessionStore.__init__

    def memory_init(self, path=None):
        if path is None:
            path = tmp_path / "memory.json"
        original_memory_init(self, path=path)

    def chat_init(self, path=None, memory_store=None):
        if path is None:
            path = tmp_path / "chats.json"
        original_chat_init(self, path=path, memory_store=memory_store)

    monkeypatch.setattr(memory.MemoryStore, "__init__", memory_init)
    monkeypatch.setattr(chat_sessions.ChatSessionStore, "__init__", chat_init)
    yield
