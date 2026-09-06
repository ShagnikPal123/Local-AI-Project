import httpx
import pytest
import respx

from config import SETTINGS
from openai_mcp import server
from openai_mcp.client import OPENAI_API_BASE


@pytest.mark.asyncio
@respx.mock
async def test_list_models_formats_response(monkeypatch):
    monkeypatch.setattr(SETTINGS, "openai_api_key", "test-key")
    respx.get(f"{OPENAI_API_BASE}/models").mock(return_value=httpx.Response(200, json={"data": [{"id": "test-model"}]}))
    assert "test-model" in await server.openai_list_models(server.ListModelsInput())


@pytest.mark.asyncio
@respx.mock
async def test_chat_completion_sends_messages(monkeypatch):
    monkeypatch.setattr(SETTINGS, "openai_api_key", "test-key")
    route = respx.post(f"{OPENAI_API_BASE}/chat/completions").mock(return_value=httpx.Response(200, json={"choices": [{"message": {"content": "Hi"}}]}))
    result = await server.openai_chat_completion(server.ChatCompletionInput(model="gpt-4o-mini", messages=[server.ChatMessage(role="user", content="Hello")]))
    assert result == "Hi"
    assert b"Hello" in route.calls.last.request.content

