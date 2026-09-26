"""The "mini AI": one short answer from the fastest configured model, within a time budget.

Used where a person is waiting on a menu, not a chat — guessing a mistyped
/command, deciding whether a message typed mid-answer should queue or branch.
The full router carries the 37 KB system prompt habits and fallback chain of a
chat turn; through it these little questions took 6+ seconds. A direct call to
a small model answers in well under a second (Gemini Flash-Lite: 0.6 s,
measured 2026-09-15).

Returns None when nothing answers in time; callers always have an offline answer.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout, as_completed
from typing import Any, List, Optional, Tuple

#: Small, fast models in the order they are tried. Only configured providers are used.
CANDIDATES: List[Tuple[str, str]] = [
    ("groq", "llama-3.1-8b-instant"),
    ("gemini", "gemini-flash-lite-latest"),
    ("nvidia", "nvidia/nemotron-3.5-lightning-30b-a3b"),
    ("openai", "gpt-5-nano"),
]

_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="nyx-mini")


def race(candidates: List[Tuple[str, str]], prompt: str, *, system: str = "", budget_seconds: float = 3.0,
         max_tokens: int = 300) -> Optional[Any]:
    """Ask every configured (provider, model) at once; the first non-empty ModelReply wins, or None.

    Free tiers are flaky (on 2026-09-15 Gemini timed out on every other request
    while NVIDIA answered 503), so asking them one after another spent the whole
    budget waiting on the first.
    """
    import model_hub
    from config import SETTINGS

    runnable = []
    for provider, model in candidates:
        try:
            if not model_hub.is_configured(provider):
                continue
        except Exception:  # noqa: BLE001 - a broken key store means "not configured"
            continue
        if getattr(SETTINGS, "free_only", False) and provider in ("openai", "claude"):
            continue
        runnable.append((provider, model or model_hub.default_model(provider, "text")))
    if not runnable:
        return None
    deadline = time.monotonic() + budget_seconds
    futures = [_pool.submit(model_hub.complete, provider, model, prompt, system=system, max_tokens=max_tokens,
                            timeout=budget_seconds) for provider, model in runnable]
    try:
        for future in as_completed(futures, timeout=max(0.1, deadline - time.monotonic())):
            try:
                reply = future.result()
            except Exception:  # noqa: BLE001 - another candidate may still answer
                continue
            if reply.text:
                return reply
    except FutureTimeout:
        return None
    return None


def quick_text(prompt: str, budget_seconds: float = 3.0, max_tokens: int = 300) -> Optional[str]:
    """The first answer any small model gives inside the budget, or None."""
    reply = race(CANDIDATES, prompt, budget_seconds=budget_seconds, max_tokens=max_tokens)
    return reply.text if reply is not None else None
