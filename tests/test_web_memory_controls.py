"Tests for web-access permission and important memory controls."""

from unittest.mock import MagicMock, patch
from chat_service import ChatService
from memory import MemoryStore
from router import Router

def test_important_memory_is_persisted(tmp_path):
    store = MemoryStore(tmp_path / "memory.json")
    store.remember_important("project", "Use pytest for verification")
    assert "Use pytest for verification" in store.build_context_prompt()


def test_web_access_can_be_disabled():
    with patch("router.get_device_profile", return_value=MagicMock()), patch(
        "router.select_tier", return_value=MagicMock(name="large")
    ), patch("router.OllamaProvider"), patch("router.PerplexityProvider"), patch(
        "router.is_online", return_value=True
    ):
        router = Router(web_access=False)
        assert router.web_access_status() == {
            "enabled": False,
            "online": True,
            "available": False,
        }
        assert router._online_available() is False

def test_chat_service_controls_web_access(tmp_path):
    with patch("chat_service.Router") as router_class:
        router = router_class.return_value
        router.web_access_status.return_value = {
            "enabled": True,
            "online": False,
            "available": False,
        }
        service = ChatService(memory_path=str(tmp_path / "memory.json"))
        service.set_web_access(False)
        router.set_web_access.assert_called_once_with(False)
