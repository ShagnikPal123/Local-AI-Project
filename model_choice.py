"""The model the owner picked, remembered across restarts, and which billable providers they allowed.

Request H6: "the model keeps referring back to Gemini". ``SETTINGS.preferred_online_provider``
came from ``PREFERRED_ONLINE_PROVIDER`` (default gemini) on every start, so every engine restart
and every update quietly undid the owner's switch. The pick is now saved here and re-applied
when settings load.

Request H11: picking Claude, OpenAI, Kimi, DeepSeek or Perplexity yourself is consent to use
that key. Free-only mode still keeps them out of *automatic* fallback until then, so Nyx never
starts spending on its own; ``key_pool`` marks a key as needing payment only when its API says so.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from paths import data_path


def _path():
    return data_path("model_choice.json")


def load() -> Dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: Dict[str, Any]) -> None:
    path = _path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def allowed_paid() -> List[str]:
    return [str(n) for n in load().get("allowed_paid", []) if str(n).strip()]


def remember(provider: str, model: str = "") -> Dict[str, Any]:
    """Save an explicit pick; a billable provider picked by the owner counts as allowed."""
    name = (provider or "").strip().lower()
    data = load()
    if name:
        data["provider"] = name
        allowed = set(allowed_paid())
        allowed.add(name)
        data["allowed_paid"] = sorted(allowed)
    if model:
        models = data.get("models") if isinstance(data.get("models"), dict) else {}
        models[name or data.get("provider", "")] = model.strip()
        data["models"] = models
    _save(data)
    return data


def forget_allowed(provider: str) -> None:
    data = load()
    data["allowed_paid"] = [n for n in allowed_paid() if n != (provider or "").strip().lower()]
    _save(data)


def apply(settings: Any) -> None:
    """Put the saved pick back into live settings. Never raises."""
    try:
        data = load()
        provider = str(data.get("provider") or "").strip().lower()
        if provider:
            settings.preferred_online_provider = provider
        for name, model in (data.get("models") or {}).items():
            field = f"{name}_model"
            if model and hasattr(settings, field):
                setattr(settings, field, str(model))
    except Exception:  # pragma: no cover - a bad file must not stop settings loading
        pass
