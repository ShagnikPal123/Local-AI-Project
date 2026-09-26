"""Chat turns that outlive the tab that started them.

The owner: "Chats can run outside of their window and tab." A turn already ran
on a worker thread, so closing the tab never killed it — but its events went to
exactly one HTTP response. Reload the page, open a second window, or switch to
another chat and back, and the turn became invisible: still working, with no way
to see it until the final answer appeared in the history.

Every turn now writes its events to a ``TurnRecord`` here. Any number of viewers
can attach at any moment: they get a compact replay of what already happened,
then follow live. Workspace-wide ``turn.state`` events on the ``ui`` channel let
every open window show which chats are busy, and finished turns stay readable
for a while so "it finished while I was away" still shows its steps.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

#: Raw events kept per turn. Answer text arrives in many small chunks; past this
#: many events, new chunks are folded into the previous one instead of appended.
_MAX_EVENTS = 20_000

#: Finished turns kept for late viewers, and for how long.
_KEEP_FINISHED = 60
_FINISHED_TTL_SECONDS = 30 * 60

#: At most this often per turn, a status change is announced workspace-wide.
_STATE_ANNOUNCE_INTERVAL = 0.6

#: Events that are merged when replaying to a viewer who joins late.
_MERGEABLE = frozenset({"answer.delta", "thought.delta"})

_FINAL = frozenset({"done", "error", "stopped"})


@dataclass
class TurnRecord:
    turn_id: str
    chat_id: str
    message: str
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    state: str = "running"          # running | done | error | stopped
    status: str = "Starting"
    provider: str = ""
    reply_preview: str = ""
    #: Latest agent.update per agent id, so a viewer sees current agent states
    #: even when the replay is compacted.
    agents: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    tools_running: int = 0
    events: List[Dict[str, Any]] = field(default_factory=list)
    cancel: threading.Event = field(default_factory=threading.Event)
    _cond: threading.Condition = field(default_factory=threading.Condition)
    _last_announce: float = 0.0

    def summary(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "chat_id": self.chat_id,
            "message": self.message[:200],
            "state": self.state,
            "status": self.status,
            "provider": self.provider,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_seconds": round((self.finished_at or time.time()) - self.started_at, 1),
            "reply_preview": self.reply_preview[:240],
            "agents": list(self.agents.values()),
            "tools_running": self.tools_running,
            "events": len(self.events),
        }

    @property
    def finished(self) -> bool:
        return self.state != "running"


class TurnRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._turns: Dict[str, TurnRecord] = {}

    # --- lifecycle ------------------------------------------------------------

    def start(self, turn_id: str, chat_id: str, message: str) -> TurnRecord:
        record = TurnRecord(turn_id=turn_id, chat_id=chat_id or "default", message=message or "")
        with self._lock:
            self._prune()
            self._turns[turn_id] = record
        self._announce(record, force=True)
        return record

    def get(self, turn_id: str) -> Optional[TurnRecord]:
        with self._lock:
            return self._turns.get(turn_id)

    def cancel(self, turn_id: str) -> bool:
        record = self.get(turn_id)
        if record is None or record.finished:
            return False
        record.cancel.set()
        return True

    def active(self, include_recent: bool = True) -> List[Dict[str, Any]]:
        with self._lock:
            self._prune()
            records = list(self._turns.values())
        items = [r.summary() for r in records if include_recent or not r.finished]
        return sorted(items, key=lambda s: (s["state"] != "running", -s["started_at"]))

    def running_for_chat(self, chat_id: str) -> Optional[TurnRecord]:
        with self._lock:
            for record in self._turns.values():
                if record.chat_id == chat_id and not record.finished:
                    return record
        return None

    # --- events ---------------------------------------------------------------

    def append(self, turn_id: str, event: Dict[str, Any]) -> None:
        """Record one event for a turn and wake its viewers. Never raises."""
        record = self.get(turn_id)
        if record is None:
            return
        try:
            kind = event.get("type", "")
            with record._cond:
                if (
                    len(record.events) >= _MAX_EVENTS
                    and kind in _MERGEABLE
                    and record.events
                    and record.events[-1].get("type") == kind
                ):
                    record.events[-1] = {**record.events[-1], "text": record.events[-1].get("text", "") + event.get("text", "")}
                else:
                    record.events.append(event)
                self._track(record, event)
                record._cond.notify_all()
            self._announce(record, force=kind in _FINAL or kind in ("turn.start", "agent.update", "approval.request"))
        except Exception:  # pragma: no cover - recording must never break a turn
            pass

    def finish(self, turn_id: str, state: str = "done") -> None:
        record = self.get(turn_id)
        if record is None:
            return
        with record._cond:
            if record.state == "running":
                record.state = state
                record.finished_at = time.time()
            record._cond.notify_all()
        self._announce(record, force=True)

    def follow(self, turn_id: str, since: int = 0, heartbeat: float = 10.0) -> Iterator[Optional[Dict[str, Any]]]:
        """Yield the turn's events from ``since``; ``None`` means "send a keep-alive".

        A viewer joining at 0 while text was streaming gets the text merged into a
        few events rather than thousands of fragments. The generator ends once
        the turn has finished and every event has been delivered.
        """
        record = self.get(turn_id)
        if record is None:
            return
        with record._cond:
            backlog = list(record.events[since:])
            index = since + len(backlog)
        for event in _compact(backlog):
            yield event

        while True:
            with record._cond:
                if index >= len(record.events) and not record.finished:
                    record._cond.wait(timeout=heartbeat)
                fresh = record.events[index:]
                index += len(fresh)
                done = record.finished and index >= len(record.events)
            if fresh:
                for event in fresh:
                    yield event
            elif not done:
                yield None
            if done:
                return

    # --- internals ------------------------------------------------------------

    @staticmethod
    def _track(record: TurnRecord, event: Dict[str, Any]) -> None:
        kind = event.get("type", "")
        if kind == "status" and event.get("text"):
            record.status = str(event["text"])[:160]
        elif kind == "tool.start":
            record.tools_running += 1
            record.status = str(event.get("label") or event.get("name") or record.status)[:160]
        elif kind == "tool.end":
            record.tools_running = max(0, record.tools_running - 1)
        elif kind == "agent.update" and event.get("agent_id"):
            record.agents[str(event["agent_id"])] = {
                k: event.get(k) for k in ("agent_id", "name", "emoji", "color", "status", "step", "understanding", "seconds")
            }
            if event.get("status") == "working":
                record.status = f"{event.get('emoji', '')} {event.get('name', 'Agent')}: {event.get('step', 'working')}".strip()[:160]
        elif kind == "answer.delta":
            record.reply_preview = (record.reply_preview + event.get("text", ""))[-600:]
            record.status = "Writing the answer"
        elif kind == "answer.reset":
            record.reply_preview = ""
        elif kind == "done":
            record.state = "done"
            record.finished_at = time.time()
            record.provider = str(event.get("provider") or "")
            record.reply_preview = str(event.get("reply") or record.reply_preview)[:600]
            record.status = "Done"
        elif kind == "error":
            record.state = "error"
            record.finished_at = time.time()
            record.status = str(event.get("message") or "Error")[:160]
        elif kind == "stopped":
            record.state = "stopped"
            record.finished_at = time.time()
            record.status = "Stopped"

    def _announce(self, record: TurnRecord, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - record._last_announce < _STATE_ANNOUNCE_INTERVAL:
            return
        record._last_announce = now
        try:
            from agent_events import publish_ui

            summary = record.summary()
            summary.pop("events", None)
            publish_ui("turn.state", **summary)
        except Exception:
            pass

    def _prune(self) -> None:
        now = time.time()
        finished = sorted(
            (r for r in self._turns.values() if r.finished),
            key=lambda r: r.finished_at or 0,
        )
        for record in finished:
            if now - (record.finished_at or now) > _FINISHED_TTL_SECONDS:
                self._turns.pop(record.turn_id, None)
        finished = [r for r in finished if r.turn_id in self._turns]
        for record in finished[: max(0, len(finished) - _KEEP_FINISHED)]:
            self._turns.pop(record.turn_id, None)


def _compact(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge consecutive text fragments so a late viewer replays quickly."""
    merged: List[Dict[str, Any]] = []
    for event in events:
        kind = event.get("type")
        if (
            kind in _MERGEABLE
            and merged
            and merged[-1].get("type") == kind
            and merged[-1].get("agent") == event.get("agent")
        ):
            merged[-1] = {**merged[-1], "text": merged[-1].get("text", "") + event.get("text", "")}
        else:
            merged.append(dict(event))
    return merged


TURNS = TurnRegistry()
