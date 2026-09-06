"""Small presentation helpers shared by the MCP tools."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def to_json(data: Any) -> str:
    """Return predictable, readable JSON for an MCP client."""

    return json.dumps(data, indent=2, default=str)


def unix_to_readable(timestamp: int | float | None) -> str:
    """Make API timestamps useful to people while retaining UTC."""

    if timestamp is None:
        return "unknown"
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def format_models(models: list[dict[str, Any]]) -> str:
    """Format model metadata without assuming every optional field exists."""

    if not models:
        return "No models returned."
    return "\n".join(
        [f"Found {len(models)} model(s):", ""]
        + [f"- **{model.get('id', 'unknown')}** (owned by {model.get('owned_by', 'unknown')})" for model in models]
    )


def format_chat(response: dict[str, Any]) -> str:
    """Extract the ordinary text response and optional token count."""

    choices = response.get("choices", [])
    content = choices[0].get("message", {}).get("content", "") if choices else ""
    usage = response.get("usage", {})
    suffix = f"\n\nTokens used: {usage.get('total_tokens', '?')}" if usage else ""
    return f"{content or '(empty response)'}{suffix}"


def format_embeddings(response: dict[str, Any]) -> str:
    """Avoid returning huge vectors in the default human-readable response."""

    entries = response.get("data", [])
    lines = [f"Generated {len(entries)} embedding(s)."]
    for entry in entries:
        vector = entry.get("embedding", [])
        lines.append(f"- Index {entry.get('index', '?')}: dimension {len(vector)}")
    return "\n".join(lines)


def format_moderation(response: dict[str, Any]) -> str:
    """Summarize each moderation result and the triggered categories."""

    lines = []
    for index, result in enumerate(response.get("results", [])):
        categories = result.get("categories", {})
        triggered = ", ".join(name for name, hit in categories.items() if hit) or "none"
        lines.append(f"- Input {index}: {'FLAGGED' if result.get('flagged') else 'clear'} ({triggered})")
    return "\n".join(lines) or "No moderation results returned."

