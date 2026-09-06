"""HTTP tests that stay entirely offline through respx."""

import httpx
import pytest
import respx

from config import SETTINGS
from openai_mcp.client import OPENAI_API_BASE, OpenAIAPIError, openai_request


@pytest.mark.asyncio
@respx.mock
async def test_openai_request_sends_project_key(monkeypatch):
    monkeypatch.setattr(SETTINGS, "openai_api_key", "test-key")
    route = respx.get(f"{OPENAI_API_BASE}/models").mock(return_value=httpx.Response(200, json={"data": []}))
    assert await openai_request("GET", "/models") == {"data": []}
    assert route.calls.last.request.headers["Authorization"] == "Bearer test-key"


@pytest.mark.asyncio
async def test_openai_request_rejects_missing_key(monkeypatch):
    monkeypatch.setattr(SETTINGS, "openai_api_key", "")
    with pytest.raises(OpenAIAPIError, match="not configured"):
        await openai_request("GET", "/models")

