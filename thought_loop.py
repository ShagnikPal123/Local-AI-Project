"""Background thought loop — lets Nyx Ichos "stay in thought".

When a task needs research or study, the assistant does not have to answer
instantly. A background thought keeps running after the first acknowledgement:
it searches, reads, verifies, and only then posts the final answer. This powers
the App/Web flow where the UI shows live "thinking" milestones and polls for
the completed result — without blocking other chats or forcing the user to
prompt again.

The ChatService reports interim milestones (searching, reading, verifying)
through an optional callback; this module runs that work on a daemon thread and
exposes status/result for polling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import uuid

from chat_service import ChatService


@dataclass
class Thought:
    """State of one background thought."""

    thought_id: str
    task: str
    status: str = "queued"  # queued | thinking | complete | error | cancelled
    milestones: List[str] = field(default_factory=list)
    result: Optional[str] = None
    provider: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "thought_id": self.thought_id,
            "task": self.task[:200] + ("..." if len(self.task) > 200 else ""),
            "status": self.status,
            "milestones": self.milestones,
            "result": self.result,
            "provider": self.provider,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BackgroundThinker:
    """Run a chat task on a daemon thread and expose live status."""

    def __init__(
        self,
        service: ChatService,
        task: str,
        thought_id: Optional[str] = None,
        attribute_id: Optional[str] = None,
    ):
        self.service = service
        self.task = task
        self.attribute_id = attribute_id
        self.thought = Thought(
            thought_id=thought_id or uuid.uuid4().hex[:12],
            task=task,
        )
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._cancelled = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> "BackgroundThinker":
        """Begin the background thought (idempotent)."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self
            self.thought.status = "thinking"
            self.thought.started_at = _now()
            self._thread = threading.Thread(
                target=self._run,
                name=f"thought-{self.thought.thought_id}",
                daemon=True,
            )
            self._thread.start()
        return self

    def _run(self) -> None:
        try:
            response, provider = self.service.chat(
                self.task,
                attribute_id=self.attribute_id,
                interim_callback=self._milestone,
            )
            with self._lock:
                self.thought.result = response
                self.thought.provider = provider
                self.thought.status = "complete"
                self.thought.finished_at = _now()
        except Exception as error:  # pragma: no cover - depends on provider
            with self._lock:
                self.thought.error = str(error)
                self.thought.status = "error"
                self.thought.finished_at = _now()

    def _milestone(self, message: str) -> None:
        with self._lock:
            if self._cancelled:
                return
            self.thought.milestones.append(message)

    def cancel(self) -> bool:
        """Request cancellation; the running turn finishes its current step."""
        with self._lock:
            self._cancelled = True
            was_alive = self._thread is not None and self._thread.is_alive()
        if was_alive:
            self.thought.status = "cancelled"
            self.thought.finished_at = _now()
        return was_alive

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return self.thought.to_dict()

    def wait(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Block until the thought completes (or the timeout elapses)."""
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        return self.status()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_THOUGHTS: Dict[str, BackgroundThinker] = {}
_REGISTRY_LOCK = threading.Lock()


def start_background_thought(
    service: ChatService,
    task: str,
    attribute_id: Optional[str] = None,
) -> BackgroundThinker:
    """Start a background thought and register it for polling."""
    thinker = BackgroundThinker(
        service=service,
        task=task,
        attribute_id=attribute_id,
    )
    thinker.start()
    with _REGISTRY_LOCK:
        _THOUGHTS[thinker.thought.thought_id] = thinker
    return thinker


def get_thought(thought_id: str) -> Optional[BackgroundThinker]:
    with _REGISTRY_LOCK:
        return _THOUGHTS.get(thought_id)


def list_thoughts(limit: int = 20) -> List[Dict[str, Any]]:
    with _REGISTRY_LOCK:
        thoughts = list(_THOUGHTS.values())
    return [t.status() for t in thoughts[-limit:]]


def cleanup_thoughts(max_age_seconds: float = 3600.0) -> int:
    """Drop finished thoughts older than max_age_seconds."""
    cutoff = time.time() - max_age_seconds
    expired = []
    with _REGISTRY_LOCK:
        for thought_id, thinker in _THOUGHTS.items():
            finished = thinker.status().get("finished_at")
            if finished and datetime.fromisoformat(finished).timestamp() < cutoff:
                expired.append(thought_id)
        for thought_id in expired:
            _THOUGHTS.pop(thought_id, None)
    return len(expired)


def continue_turn_in_background(service: ChatService, task: str) -> Tuple[str, str]:
    """Acknowledge a research task immediately, then finish it in background.

    Returns (acknowledgement, thought_id). The caller (App/Web) can poll
    get_thought(thought_id) and post the final result when it completes.
    """
    thinker = start_background_thought(service, task)
    ack = (
        "I'm working on this in the background — researching and studying it now. "
        f"Thought ID: {thinker.thought.thought_id}"
    )
    return ack, thinker.thought.thought_id
