"""System event log for the HUD (ROADMAP DD12).

A bounded, in-memory record of what the system actually did — provider calls,
agent steps, safety throttles, permission decisions. The HUD streams this in the
style of the reference mockup, with the difference that these lines are real.

Bounded on purpose: an unbounded log in a long-running local process is a slow
memory leak, and the HUD only ever renders the tail.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Deque, Dict, List, Optional


class EventLevel(Enum):
    INFO = "info"
    OK = "ok"
    WARN = "warn"
    ERROR = "error"


@dataclass(frozen=True)
class Event:
    timestamp: float
    level: EventLevel
    source: str      # router | agent | safety | auth | chat | system
    message: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "time": time.strftime("%H:%M:%S", time.localtime(self.timestamp)),
            "level": self.level.value,
            "source": self.source,
            "message": self.message,
        }


_MAX_EVENTS = 500


class EventLog:
    """Thread-safe ring buffer of system events."""

    def __init__(self, capacity: int = _MAX_EVENTS) -> None:
        self._events: Deque[Event] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._sequence = 0

    def record(
        self,
        message: str,
        source: str = "system",
        level: EventLevel = EventLevel.INFO,
    ) -> None:
        """Append an event. Never raises — logging must not break the caller."""
        try:
            event = Event(
                timestamp=time.time(),
                level=level,
                source=str(source)[:24],
                message=str(message)[:240],
            )
            with self._lock:
                self._events.append(event)
                self._sequence += 1
        except Exception:  # pragma: no cover - defensive
            pass

    def tail(self, limit: int = 60, level: Optional[EventLevel] = None) -> List[Dict[str, Any]]:
        """Most recent events, newest last so the HUD can append naturally."""
        with self._lock:
            events = list(self._events)
        if level is not None:
            events = [e for e in events if e.level is level]
        return [e.as_dict() for e in events[-max(1, limit):]]

    def snapshot(self, limit: int = 60) -> Dict[str, Any]:
        with self._lock:
            total = self._sequence
            counts = {lv.value: 0 for lv in EventLevel}
            for event in self._events:
                counts[event.level.value] += 1
        return {
            "events": self.tail(limit),
            "total_recorded": total,
            "counts": counts,
            "capacity": self._events.maxlen,
        }

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


EVENT_LOG = EventLog()


# Convenience wrappers so call sites stay short and readable.
def info(message: str, source: str = "system") -> None:
    EVENT_LOG.record(message, source, EventLevel.INFO)


def ok(message: str, source: str = "system") -> None:
    EVENT_LOG.record(message, source, EventLevel.OK)


def warn(message: str, source: str = "system") -> None:
    EVENT_LOG.record(message, source, EventLevel.WARN)


def error(message: str, source: str = "system") -> None:
    EVENT_LOG.record(message, source, EventLevel.ERROR)
