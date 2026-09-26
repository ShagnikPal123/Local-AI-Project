"""How Identity 0 talks to its members: one answer, a streamed answer, or a panel of several at once.

Streaming goes through the router (``router.stream(prefer=…, exclude=["identity0"])``) on a helper
thread, bridged to a generator with a queue. That keeps everything the router already gets right —
several keys per provider with failover, the key-health ledger, metrics, image routing, free-only
rules — and it means a lead that fails falls back along the router's chain instead of ending the turn.

One-shot calls (shadows, helpers, the judge, evaluations) go straight to the member: Ollama's
``/api/chat`` with the real message list, the own model's local server, or ``model_hub.complete``
for everyone else. None of these functions raise: a member that fails is an ``ok: False`` answer.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any, Callable, Deque, Dict, Iterator, List, Optional, Sequence, Tuple

from identity0.members import split_id

_depth = threading.local()


def inside() -> bool:
    """True on a thread that is already doing work for Identity 0 (its re-entry guard)."""
    return getattr(_depth, "n", 0) > 0


class _Guard:
    def __enter__(self) -> None:
        _depth.n = getattr(_depth, "n", 0) + 1

    def __exit__(self, *_exc: Any) -> None:
        _depth.n = max(0, getattr(_depth, "n", 1) - 1)


def guard() -> _Guard:
    return _Guard()


class Budget:
    """At most ``limit()`` spends per rolling hour — shadow and judge calls must not eat free quotas."""

    def __init__(self, limit: Callable[[], int]) -> None:
        self._limit = limit
        self._times: Deque[float] = deque()
        self._lock = threading.Lock()

    def left(self) -> int:
        with self._lock:
            return self._left()

    def _left(self) -> int:
        cutoff = time.time() - 3600
        while self._times and self._times[0] < cutoff:
            self._times.popleft()
        return max(0, int(self._limit()) - len(self._times))

    def spend(self, calls: int = 1) -> bool:
        """Take ``calls`` from this hour's allowance, all or nothing (a judge reads twice, so it takes two)."""
        with self._lock:
            if self._left() < max(1, calls):
                return False
            now = time.time()
            self._times.extend([now] * max(1, calls))
        return True


def _setting(key: str, default: int) -> int:
    try:
        from identity0.state import get_settings

        return int(get_settings().get(key, default))
    except Exception:  # noqa: BLE001
        return default


API_BUDGET = Budget(lambda: _setting("api_shadow_per_hour", 6))
JUDGE_BUDGET = Budget(lambda: _setting("judge_per_hour", 20))


def flatten(messages: Sequence[Dict[str, Any]], system: str = "") -> Tuple[str, str]:
    """A message list as (system, prompt) for APIs that take one prompt."""
    systems = [system] if system else []
    turns: List[str] = []
    for message in messages:
        role = str(message.get("role", "user"))
        content = str(message.get("content", "") or "")
        if role == "system":
            systems.append(content)
        else:
            turns.append(f"{'User' if role == 'user' else 'Assistant'}: {content}")
    prompt = "\n\n".join(turns[-12:])
    return "\n\n".join(s for s in systems if s), prompt


def _ollama_messages(messages: Sequence[Dict[str, Any]], vision: bool) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    for message in messages:
        item = {"role": message.get("role", "user"), "content": str(message.get("content", "") or "")}
        images = message.get("images") or []
        if images and vision:
            item["images"] = [img.get("data", "") for img in images if isinstance(img, dict) and img.get("data")]
        elif images:
            from providers.base import image_note

            item["content"] = f"{item['content']}\n\n{image_note(images)}".strip()
        cleaned.append(item)
    return cleaned


#: Callable without the app's router (a job process): local models only — an online key needs the
#: router's consent rules, which live in the app.
_LOCAL_PROVIDERS = {"self", "ollama", "local"}


def permitted(member: str, router: Any = None) -> Tuple[bool, str]:
    """Whether Identity 0 may call this member right now: it is up, and the owner consented to any cost.

    ``members.available`` already refuses a paid provider that is not the owner's own pick, so a member
    that is not in that list is either down, unknown, or would spend money nobody asked to spend.
    """
    provider, _model = split_id(member)
    if provider == "self":
        return True, ""
    if router is None:
        router = _shared_router()
    if router is None:
        ok = provider in _LOCAL_PROVIDERS
        return ok, "" if ok else f"{provider} can only be called from the app, with the owner's keys"
    try:
        reason = router.unavailable_reason(provider)
    except Exception:  # noqa: BLE001
        reason = ""
    if reason:
        return False, str(reason)
    try:
        from identity0 import members as members_module

        pool = members_module.available(router)
    except Exception:  # noqa: BLE001
        return provider in _LOCAL_PROVIDERS, "cannot check which models are available"
    if any(m.id == member for m in pool):
        return True, ""
    if any(m.provider == provider and m.free for m in pool):
        return True, ""  # same provider, another model (an agent's own pick)
    return False, f"Big Kahuna does not spend on {provider} unless the owner picks it"


def _shared_router() -> Any:
    try:
        from identity0.provider import shared_router

        return shared_router()
    except Exception:  # noqa: BLE001
        return None


def complete(member: str, messages: Sequence[Dict[str, Any]], *, max_tokens: int = 800, temperature: float = 0.3,
             timeout: float = 60, system: str = "", router: Any = None) -> Dict[str, Any]:
    """One answer from exactly this member. Never raises.

    Router providers are called directly (their own keys, timeouts and model handling), so what a
    shadow or judge sees is what the lead would have seen; Ollama goes to ``/api/chat`` with a token
    cap when there is no router; anything else falls back to ``model_hub``.
    """
    provider, model = split_id(member)
    router = router if router is not None else _shared_router()
    started = time.perf_counter()
    result: Dict[str, Any] = {"member": member, "text": "", "ok": False, "error": "", "ms": 0}
    allowed, why = permitted(member, router)
    if not allowed:
        result["error"] = why[:300]
        return result
    body = ([{"role": "system", "content": system}] if system else []) + list(messages)
    try:
        providers = getattr(router, "providers", {}) or {}
        if provider == "self":
            from identity0.model import client

            text = client.complete(body, max_tokens=max_tokens, temperature=temperature)
        elif provider in providers and provider != "identity0":
            from router import _without_images

            chosen = providers[provider]
            prepared = body if getattr(chosen, "supports_vision", False) else _without_images(body)
            parts: List[str] = []
            deadline = time.time() + timeout
            with guard():
                for event in chosen.stream_events(prepared, model=model or None, thinking=False):
                    if event.get("type") == "text":
                        parts.append(event.get("text", ""))
                    if time.time() > deadline:
                        break
            text = "".join(parts)
        elif provider == "ollama":
            import requests
            import local_models
            from providers.ollama_provider import NUM_CTX
            from identity0.members import _ollama_vision

            response = requests.post(local_models.host() + "/api/chat", timeout=timeout, json={
                "model": model, "messages": _ollama_messages(body, _ollama_vision(model)), "stream": False,
                "think": False, "options": {"num_predict": max_tokens, "temperature": temperature, "num_ctx": NUM_CTX}})
            response.raise_for_status()
            text = str((response.json().get("message") or {}).get("content") or "")
        else:
            import model_hub

            joined_system, prompt = flatten(messages, system)
            text = model_hub.complete(provider, model, prompt, system=joined_system, max_tokens=max_tokens,
                                      timeout=timeout).text
        text = (text or "").strip()
        result.update(text=text, ok=bool(text), error="" if text else "empty answer")
    except Exception as error:  # noqa: BLE001 - a failing member is an answer too
        try:
            from providers.custom import scrub_secrets

            message = scrub_secrets(str(error))
        except Exception:  # noqa: BLE001
            message = type(error).__name__
        result["error"] = message[:300]
    result["ms"] = round((time.perf_counter() - started) * 1000)
    return result


def stream(router: Any, member: str, messages: List[Dict[str, Any]], *, thinking: bool = False,
           cancelled: Optional[Callable[[], bool]] = None) -> Iterator[Dict[str, Any]]:
    """Router-style events for one lead: ``provider``, ``text``, ``thought``, ``reset``, and a final ``done``.

    ``done`` carries ``{"provider", "text", "error"}`` — the provider that really answered (the router
    may have fallen back) — so the caller logs the right member.
    """
    provider, model = split_id(member)
    events: "queue.Queue[Optional[Dict[str, Any]]]" = queue.Queue()
    stopped = threading.Event()

    def is_cancelled() -> bool:
        return stopped.is_set() or bool(cancelled and cancelled())

    def work() -> None:
        outcome: Dict[str, Any] = {"type": "done", "provider": "", "text": "", "error": ""}
        with guard():
            try:
                text, used = router.stream(messages, events.put, thinking=thinking, cancelled=is_cancelled,
                                           prefer=provider if provider != "self" else None,
                                           prefer_model=model or None, exclude=["identity0"])
                outcome.update(provider=used, text=text)
            except Exception as error:  # noqa: BLE001 - reported through the done event
                outcome["error"] = str(error)[:400]
        events.put(outcome)
        events.put(None)

    worker = threading.Thread(target=work, name="kahuna-lead", daemon=True)
    worker.start()
    try:
        while True:
            event = events.get()
            if event is None:
                break
            yield event
    finally:
        stopped.set()


def panel(messages: Sequence[Dict[str, Any]], members: Sequence[str], *, budget_s: float = 40,
          max_tokens: int = 600, system: str = "") -> Dict[str, Any]:
    """Ask several members at once; whatever is back within the budget counts."""
    answers: List[Dict[str, Any]] = []
    if not members:
        return {"answers": answers, "best": None}
    pool = ThreadPoolExecutor(max_workers=min(4, len(members)), thread_name_prefix="kahuna-panel")
    futures = [pool.submit(complete, m, messages, max_tokens=max_tokens, timeout=budget_s, system=system)
               for m in members]
    done, _ = wait(futures, timeout=budget_s)
    pool.shutdown(wait=False, cancel_futures=True)
    for future in done:
        try:
            answers.append(future.result())
        except Exception:  # noqa: BLE001
            continue
    good = [a for a in answers if a["ok"]]
    return {"answers": answers, "best": max(good, key=lambda a: len(a["text"])) if good else None}


NOTE_PREFIX = "[Big Kahuna helpers]"


def helpers_note(answers: Sequence[Dict[str, Any]]) -> str:
    """Helpers' drafts as context for the lead, the same way consult.py hands over second opinions."""
    lines = [NOTE_PREFIX, "Identity 0 asked other models first. Use what is right, fix what is wrong, and write "
             "the final answer yourself. Do not mention them unless it helps the user."]
    for answer in answers:
        if answer.get("ok"):
            lines.append(f"\n— {answer['member']}:\n{answer['text'][:2500]}")
    return "\n".join(lines)
