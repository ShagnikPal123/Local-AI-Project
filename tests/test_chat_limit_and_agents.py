"Tests for chat limits, retained learning, and sub-agent planning."""

from chat_sessions import ChatSessionStore
from sub_agents import SubAgentCoordinator

def test_chat_limit_is_five(tmp_path):
    store = ChatSessionStore(tmp_path / "chats.json")
    for index in range(5):
        store.create(f"Chat {index}")
    try:
        store.create("Too many")
        assert False
    except RuntimeError:
        pass

def test_sub_agents_select_specialists():
    names = [item["agent"] for item in SubAgentCoordinator().plan("research and implement code")]
    assert names == ["researcher", "coder", "reviewer"]
