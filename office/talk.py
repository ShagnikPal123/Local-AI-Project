"""One agent, one model call — with the limits, cleaning and salvage that make hundreds of them survivable.

Everything an office agent says goes through :func:`ask`. It routes to the agent's own model
(``router.stream(prefer=…, prefer_model=…)``) so provider keys, key failover and metrics keep working exactly as
they do for a chat turn, and it holds two gates while it runs:

* a **global** gate, sized by the Power setting, so an office cannot take the whole machine;
* a **per-provider** gate, because free API keys rate-limit long before the CPU does.

A model that fails is an answer too (``ok=False``): one silent agent must never end a job. Replies are cleaned of
thinking blocks and tool calls before they are shown, and :func:`parse_json` salvages the JSON out of a reply
that wrapped it in prose or a fence — small models do that constantly, and a lost plan costs the owner a minute
of watching an office do nothing.
"""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from office import casting

_THINK_RE = re.compile(r"<(thinking|think|reasoning)>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TOOL_RE = re.compile(r"<tool_call>.*?(?:</tool_call>|$)", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


@dataclass
class Answer:
    text: str = ""
    ok: bool = False
    error: str = ""
    ms: int = 0
    member: str = ""
    provider: str = ""

    @property
    def clean(self) -> str:
        return clean(self.text)


class Gates:
    """The two limits an office lives inside. Rebuilt whenever the Power setting or focus mode changes."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._global: Optional[threading.BoundedSemaphore] = None
        self._size = 0
        self._per_provider: Dict[str, threading.BoundedSemaphore] = {}
        self._cooldown: Dict[str, float] = {}

    def resize(self, concurrency: int) -> None:
        with self._lock:
            self._size = max(1, int(concurrency))
            self._global = threading.BoundedSemaphore(self._size)
            self._per_provider.clear()

    def size(self) -> int:
        with self._lock:
            if self._global is None:
                self.resize(casting.capacity().concurrency)
            return self._size

    def _provider_gate(self, provider: str) -> threading.BoundedSemaphore:
        with self._lock:
            gate = self._per_provider.get(provider)
            if gate is None:
                gate = threading.BoundedSemaphore(casting.provider_slots(provider))
                self._per_provider[provider] = gate
            return gate

    def cool(self, provider: str, seconds: float = 60.0) -> None:
        """A provider that just rate-limited us stops being handed out for a while."""
        with self._lock:
            self._cooldown[provider] = time.time() + seconds

    def cooling(self, provider: str) -> bool:
        with self._lock:
            return self._cooldown.get(provider, 0.0) > time.time()

    def acquire(self, provider: str, timeout: float = 120.0) -> bool:
        with self._lock:
            if self._global is None:
                self.resize(casting.capacity().concurrency)
            gate = self._global
        assert gate is not None
        if not gate.acquire(timeout=timeout):
            return False
        if not self._provider_gate(provider).acquire(timeout=timeout):
            _release(gate)
            return False
        return True

    def release(self, provider: str) -> None:
        _release(self._provider_gate(provider))
        with self._lock:
            gate = self._global
        if gate is not None:
            _release(gate)


def _release(semaphore: threading.BoundedSemaphore) -> None:
    try:
        semaphore.release()
    except ValueError:  # pragma: no cover - a resize while a call was in flight
        pass


GATES = Gates()
_pool = ThreadPoolExecutor(max_workers=32, thread_name_prefix="office-model")


def clean(text: str) -> str:
    """What an agent actually said: no thinking, no tool calls, no stray fences."""
    without = _TOOL_RE.sub("", _THINK_RE.sub("", text or ""))
    without = re.sub(r"</?(thinking|think|reasoning)>", "", without, flags=re.IGNORECASE)
    return without.strip()


def first_object(text: str) -> str:
    """The first balanced ``{...}`` in the text, ignoring braces inside strings."""
    start = (text or "").find("{")
    if start == -1:
        return ""
    depth, in_string, escaped = 0, False, False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return text[start:]  # cut off mid-object: try to repair it below


def parse_json(text: str) -> Optional[Dict[str, Any]]:
    """A dict out of whatever the model produced, or None. Never raises."""
    body = clean(text)
    body = _FENCE_RE.sub("", body.strip())
    for candidate in (body, first_object(body)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except ValueError:
            pass
    # Cut off mid-answer (a token budget ending on a comma): close what is open and try once more.
    chunk = first_object(body)
    if chunk:
        repaired = chunk.rstrip().rstrip(",")
        opens = repaired.count("{") - repaired.count("}")
        brackets = repaired.count("[") - repaired.count("]")
        if repaired.count('"') % 2:
            repaired += '"'
        repaired += "]" * max(0, brackets) + "}" * max(0, opens)
        try:
            data = json.loads(repaired)
            if isinstance(data, dict):
                return data
        except ValueError:
            return None
    return None


def split_member(member: str) -> tuple:
    provider, _, model = (member or "").partition(":")
    return provider, ("" if model in ("", "default") else model)


def ask(member: str, messages: List[Dict[str, Any]], *, system: str = "", max_tokens: int = 900,
        timeout: float = 90.0, cancelled: Optional[Callable[[], bool]] = None, router: Any = None,
        thinking: bool = False) -> Answer:
    """One answer from one agent's own model. Never raises."""
    provider, model = split_member(member)
    body: List[Dict[str, Any]] = ([{"role": "system", "content": system}] if system else []) + list(messages)
    router = router if router is not None else casting.shared_router()
    answer = Answer(member=member)
    if cancelled is not None and cancelled():
        answer.error = "stopped"
        return answer
    gate_provider = provider or "any"
    if not GATES.acquire(gate_provider, timeout=max(30.0, timeout)):
        answer.error = "the office is busy"
        return answer
    started = time.perf_counter()
    try:
        future = _pool.submit(_stream, router, body, provider, model, cancelled, thinking, max_tokens)
        text, used = future.result(timeout=timeout)
        answer.text, answer.provider, answer.ok = text, used, bool((text or "").strip())
        if not answer.ok:
            answer.error = "empty answer"
    except FutureTimeout:
        answer.error = f"no answer within {int(timeout)}s"
    except Exception as error:  # noqa: BLE001 - a failing model is an answer, not a crash
        detail = str(error)[:300]
        answer.error = detail or type(error).__name__
        if "429" in detail or "rate" in detail.lower() or "quota" in detail.lower():
            GATES.cool(provider)
    finally:
        answer.ms = int((time.perf_counter() - started) * 1000)
        GATES.release(gate_provider)
    return answer


def _stream(router: Any, body: List[Dict[str, Any]], provider: str, model: str,
            cancelled: Optional[Callable[[], bool]], thinking: bool, max_tokens: int) -> tuple:
    """The call itself, on a pool thread so :func:`ask` can put a deadline on it."""
    kwargs: Dict[str, Any] = {"smart": False, "thinking": thinking}
    if cancelled is not None:
        kwargs["cancelled"] = cancelled
    if provider and provider != "identity0":
        kwargs["prefer"] = provider
        # Never fall back into Big Kahuna for a worker: it would plan a whole turn for one small step.
        kwargs["exclude"] = ["identity0"]
        if model:
            kwargs["prefer_model"] = model
    elif provider == "identity0":
        kwargs["prefer"] = "identity0"
    return router.stream(body, None, **kwargs)


def ask_lead(messages: List[Dict[str, Any]], *, system: str = "", max_tokens: int = 1400, timeout: float = 150.0,
             cancelled: Optional[Callable[[], bool]] = None, router: Any = None, turn_id: str = "") -> Answer:
    """The top manager's call: through Big Kahuna, so Identity 0 leads the office the way it leads a chat.

    ``turn_id`` lets Identity 0 treat this as a real turn it can learn from (its ``set_current_turn`` contract);
    without one it answers solo, which is cheaper and is what a small amendment wants.
    """
    marked = False
    if turn_id:
        try:
            from identity0 import provider as kahuna_provider

            kahuna_provider.set_current_turn(turn_id)
            marked = True
        except Exception:  # noqa: BLE001
            marked = False
    try:
        return ask("identity0:default", messages, system=system, max_tokens=max_tokens, timeout=timeout,
                   cancelled=cancelled, router=router)
    finally:
        if marked:
            try:
                from identity0 import provider as kahuna_provider

                kahuna_provider.set_current_turn("")
            except Exception:  # noqa: BLE001
                pass
