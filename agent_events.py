"""In-process event bus: how the UI watches the assistant work.

Before this, a chat turn was one blocking HTTP call. The user sent a prompt and
stared at a spinner until a finished answer came back — no way to see what the
assistant was doing, which tool it was running, or whether it had hung. The owner
asked for the opposite: "the AI should be showing that it's working, and what
it's working on, and thought process."

Everything observable is published here as small JSON-able dicts, and the server
turns subscriptions into Server-Sent Events. Three kinds of channel:

``turn:<id>``
    One chat turn: status, thoughts, tool calls, answer tokens, done.
``ui``
    Workspace-wide commands: theme changes, tab changes, the AI cursor.
``activity``
    A running log of what happened, for the developer panel and dashboards.

Publishing never raises and never blocks. A slow or vanished subscriber must not
be able to stall a tool call, so each subscriber gets a bounded queue and the
oldest event is dropped when it overflows.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Dict, Iterable, List, Optional

#: Per-subscriber backlog. A browser tab that stops reading (asleep laptop, a
#: stalled proxy) must not grow memory without bound; a turn rarely emits more
#: than a few hundred events, so this is generous.
_MAX_QUEUE = 2000

#: Recent events kept per channel so a subscriber that connects a moment after a
#: turn starts still sees its opening events instead of a blank timeline.
_REPLAY = 200


class Subscription:
    """A thread-safe inbox for one listener. Use as a context manager."""

    def __init__(self, bus: "EventBus", channels: Iterable[str]) -> None:
        self._bus = bus
        self.channels = frozenset(channels)
        self._queue: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=_MAX_QUEUE)
        self.closed = False

    def _offer(self, event: Dict[str, Any]) -> None:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            # Drop the oldest rather than the newest: the latest state is what
            # the user is waiting to see.
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(event)
            except (queue.Empty, queue.Full):
                pass

    def get(self, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Next event, or None when ``timeout`` passes with nothing to read."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self) -> List[Dict[str, Any]]:
        """Everything queued right now, without waiting."""
        items: List[Dict[str, Any]] = []
        while True:
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                return items

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self._bus._unsubscribe(self)

    def __enter__(self) -> "Subscription":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


class EventBus:
    """Fan-out publisher with a short replay buffer per channel."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: List[Subscription] = []
        self._recent: Dict[str, List[Dict[str, Any]]] = {}

    def publish(self, channel: str, event: Dict[str, Any]) -> None:
        """Deliver ``event`` to every subscriber of ``channel``. Never raises."""
        try:
            payload = dict(event)
            payload.setdefault("ts", time.time())
            payload.setdefault("channel", channel)
            with self._lock:
                recent = self._recent.setdefault(channel, [])
                recent.append(payload)
                if len(recent) > _REPLAY:
                    del recent[: len(recent) - _REPLAY]
                targets = [s for s in self._subscribers if channel in s.channels]
            for subscriber in targets:
                subscriber._offer(payload)
        except Exception:  # pragma: no cover - publishing must never break a turn
            pass

    def subscribe(self, channels: Iterable[str], replay: bool = False) -> Subscription:
        """Start listening. ``replay`` pre-loads each channel's recent events."""
        subscription = Subscription(self, channels)
        with self._lock:
            self._subscribers.append(subscription)
            if replay:
                for channel in subscription.channels:
                    for event in self._recent.get(channel, []):
                        subscription._offer(event)
        return subscription

    def recent(self, channel: str, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._recent.get(channel, [])[-max(1, limit):])

    def forget(self, channel: str) -> None:
        """Drop a finished turn's replay buffer so memory does not accumulate."""
        with self._lock:
            self._recent.pop(channel, None)

    def subscriber_count(self, channel: Optional[str] = None) -> int:
        with self._lock:
            if channel is None:
                return len(self._subscribers)
            return sum(1 for s in self._subscribers if channel in s.channels)

    def _unsubscribe(self, subscription: Subscription) -> None:
        with self._lock:
            try:
                self._subscribers.remove(subscription)
            except ValueError:
                pass


BUS = EventBus()


def publish_ui(type: str, **payload: Any) -> None:  # noqa: A002 - "type" is the wire name
    """Workspace-wide command or change: theme, tabs, cursor, notifications."""
    BUS.publish("ui", {"type": type, **payload})


def publish_activity(type: str, **payload: Any) -> None:  # noqa: A002
    """Append to the running activity log."""
    BUS.publish("activity", {"type": type, **payload})


def turn_channel(turn_id: str) -> str:
    return f"turn:{turn_id}"
