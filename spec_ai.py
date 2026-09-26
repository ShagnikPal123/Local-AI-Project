"""Ask a live model for a JSON spec (used by the Game Studio, Request H5).

A spec is data the app validates and renders, never code it runs (AGENTS.md
invariant 2). This module only fetches the JSON; each caller owns the grammar
and throws away anything outside it.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Tuple

#: Tried after the owner's own pick, strongest first.
PROVIDER_ORDER = ("gemini", "nvidia", "deepseek", "openai", "claude", "groq", "mistral")


class SpecAIError(ValueError):
    """No model could give a usable spec; the sentence is safe to show."""


def _available(provider: str) -> bool:
    try:
        from agent_runtime import _router as shared

        return shared().unavailable_reason(provider, explicit=False) is None
    except Exception:  # noqa: BLE001 - a provider we cannot ask about is a provider we do not ask
        return False


def candidates() -> List[Tuple[str, str]]:
    """Every model that can answer now: the owner's pick first, then the rest in order."""
    from config import SETTINGS

    preferred = (getattr(SETTINGS, "preferred_online_provider", "") or "").strip().lower()
    found: List[Tuple[str, str]] = []
    for name in [preferred] + [item for item in PROVIDER_ORDER if item != preferred]:
        if not name or not _available(name) or any(name == seen for seen, _model in found):
            continue
        if name == "gemini":
            found.append((name, getattr(SETTINGS, "gemini_smart_model", "") or getattr(SETTINGS, "gemini_model", "")))
        else:
            found.append((name, str(getattr(SETTINGS, f"{name}_model", "") or "")))
    return found


def provider() -> Tuple[str, str]:
    """The owner's model if it can answer, else the first other one that can."""
    found = candidates()
    if not found:
        raise SpecAIError("No model is available right now — add or fix a key in Keys & Models.")
    return found[0]


def json_from(text: str) -> Dict[str, Any]:
    """Pull the object out of a reply that may be fenced or have a sentence around it."""
    body = (text or "").strip()
    if "```" in body:
        blocks = re.findall(r"```(?:json)?\s*(.+?)```", body, re.DOTALL)
        if blocks:
            body = blocks[0].strip()
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end <= start:
        raise SpecAIError("The model did not answer with a spec. Try again.")
    try:
        parsed = json.loads(body[start:end + 1])
    except ValueError as error:
        raise SpecAIError("The model's answer was not readable JSON. Try again.") from error
    if not isinstance(parsed, dict):
        raise SpecAIError("The model's answer was not an object.")
    return parsed


def ask_json(system: str, prompt: str, *, max_tokens: int = 2600, timeout: float = 90.0,
             attempts: int = 3) -> Dict[str, Any]:
    """One structured answer from a live model, moving to the next model when one fails.

    Free tiers fail often and fast (NVIDIA answered "503 Service temporarily
    overloaded" to a Game Studio design on 2026-09-16), so one refusal must not
    end the request while another configured model could answer. The whole call
    stays inside ``timeout``; a slow model uses up the time, a quick refusal does not.
    """
    import model_hub

    deadline = time.monotonic() + timeout
    problems: List[str] = []
    for name, model in candidates()[:max(1, attempts)]:
        left = deadline - time.monotonic()
        if left < 10:
            break
        try:
            reply = model_hub.complete(name, model, prompt, system=system, max_tokens=max_tokens, timeout=left)
            return json_from(getattr(reply, "text", "") or "")
        except (model_hub.ModelCallError, SpecAIError) as error:
            problems.append(f"{name}: {str(error)[:160]}")
    if not problems:
        raise SpecAIError("No model is available right now — add or fix a key in Keys & Models.")
    raise SpecAIError("No model could answer right now (" + "; ".join(problems) + "). Try again in a minute.")
