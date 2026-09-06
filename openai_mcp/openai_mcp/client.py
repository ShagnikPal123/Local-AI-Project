"""One authenticated HTTP path shared by every OpenAI MCP tool."""

from __future__ import annotations

from typing import Any

import httpx

from config import SETTINGS

OPENAI_API_BASE = "https://api.openai.com/v1"
DEFAULT_TIMEOUT_SECONDS = 30.0


class OpenAIAPIError(Exception):
    """Raised when an OpenAI API call cannot return a usable result."""


def get_api_key() -> str:
    """Read the key through the project's only configuration layer."""

    key = SETTINGS.openai_api_key
    if not key:
        raise OpenAIAPIError("OPENAI_API_KEY is not configured in the project settings.")
    return key


def _describe_http_error(error: httpx.HTTPStatusError) -> str:
    """Turn a remote failure into a concise, actionable MCP result."""

    status = error.response.status_code
    try:
        detail = error.response.json().get("error", {}).get("message", "")
    except ValueError:
        detail = error.response.text[:300]
    if status == 401:
        return "OpenAI authentication failed (401). Check OPENAI_API_KEY."
    if status == 429:
        return "OpenAI rate limited the request (429). Check usage limits and retry."
    if status == 404:
        return f"OpenAI resource not found (404). {detail}".strip()
    return f"OpenAI API request failed ({status}). {detail}".strip()


async def openai_request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make one authenticated request and return its parsed JSON object."""

    headers = {"Authorization": f"Bearer {get_api_key()}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            response = await client.request(
                method, f"{OPENAI_API_BASE}{path}", headers=headers,
                json=json_body, params=params,
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as error:
        raise OpenAIAPIError(_describe_http_error(error)) from error
    except httpx.TimeoutException as error:
        raise OpenAIAPIError(f"OpenAI request timed out after {DEFAULT_TIMEOUT_SECONDS}s.") from error
    except httpx.RequestError as error:
        raise OpenAIAPIError(f"Could not reach OpenAI ({type(error).__name__}).") from error
    except ValueError as error:
        raise OpenAIAPIError("OpenAI returned invalid JSON.") from error

