"Tests for chat limits, retained learning, and sub-agent planning."""

from chat_sessions import ChatSessionStore
from sub_agents import SubAgentCoordinator

def test_chat_limit_is_bounded(tmp_path):
    """Chats are browser-style tabs now (the limit was 5); it is still finite."""
    store = ChatSessionStore(tmp_path / "chats.json")
    for index in range(ChatSessionStore.MAX_CHATS):
        store.create(f"Chat {index}")
    try:
        store.create("Too many")
        assert False
    except RuntimeError:
        pass

def test_sub_agents_select_specialists():
    names = [item["agent"] for item in SubAgentCoordinator().plan("research and implement code")]
    assert names == ["researcher", "coder", "reviewer"]
