"""The light model behind Pico: the best local Ollama model that is small enough and fits this PC.

Pico is the lineup's light level ("for phones and lesser laptops"), so each Pico size has a size cap in GB on disk
(``model_lineup.PICO_LOCAL_GB``). Pulse takes the smallest, Overtone (cap 0) the biggest that fits. Nothing here
downloads anything: no installed model that fits means Pico's quick answers go to the normal chain instead.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

_GB = 1024 ** 3

#: Models that are not for chatting (embeddings, vision encoders) are never picked.
_SKIP = ("embed", "bge-", "nomic", "minilm", "clip", "rerank", "whisper")


def _candidates(installed: List[Dict[str, Any]], max_gb: float, fits: Callable[[float], str]) -> List[Tuple[float, str]]:
    found: List[Tuple[float, str]] = []
    for model in installed:
        name = str(model.get("name") or "")
        size_gb = float(model.get("bytes") or 0) / _GB
        if not name or size_gb <= 0 or any(word in name.lower() for word in _SKIP):
            continue
        if max_gb and size_gb > max_gb:
            continue
        if fits(size_gb) == "no":
            continue
        found.append((size_gb, name))
    return found


def pick(max_gb: float, *, installed: Optional[List[Dict[str, Any]]] = None,
         fits: Optional[Callable[[float], str]] = None) -> Optional[Tuple[str, str, str]]:
    """(provider, model, why) for a Pico size, or None when no installed model is small enough.

    With a cap, the biggest model under it (more capable, still light). With no cap (Overtone), the biggest that
    fits this PC's memory.
    """
    import local_models

    if installed is None:
        installed = local_models.installed_models()
    fits = fits or local_models.fits
    found = _candidates(installed, max_gb, fits)
    if not found:
        return None
    size_gb, name = max(found)
    cap = f"under {max_gb:g} GB" if max_gb else "the biggest that fits this PC"
    return "ollama", name, f"local {name} ({size_gb:.1f} GB, {cap})"
