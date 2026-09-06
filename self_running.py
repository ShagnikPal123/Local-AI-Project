"""Autonomous self-running scheduler and background loop supervisor."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class ScheduledTask:
    """A recurring or one-shot task managed by the self-running daemon."""

    def __init__(
        self,
        task_id: str,
        name: str,
        handler: Callable[[], Any],
        interval_seconds: float,
        one_shot: bool = False,
    ):
        self.task_id = task_id
        self.name = name
        self.handler = handler
        self.interval = interval_seconds
        self.one_shot = one_shot
        self.last_run: Optional[float] = None
        self.run_count = 0
        self.last_error: Optional[str] = None


class SelfRunningSupervisor:
    """Supervises self-running background maintenance, model checks, and heartbeats."""

    def __init__(self, heartbeat_interval: float = 10.0):
        self.heartbeat_interval = heartbeat_interval
        self._tasks: Dict[str, ScheduledTask] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def register_task(
        self,
        task_id: str,
        name: str,
        handler: Callable[[], Any],
        interval_seconds: float = 60.0,
        one_shot: bool = False,
    ) -> None:
        """Register a background job."""
        with self._lock:
            self._tasks[task_id] = ScheduledTask(
                task_id=task_id,
                name=name,
                handler=handler,
                interval_seconds=interval_seconds,
                one_shot=one_shot,
            )

    def start(self) -> None:
        """Start the background autonomous thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            logger.info("Self-running supervisor started.")

    def stop(self) -> None:
        """Stop background execution."""
        with self._lock:
            self._running = False
            logger.info("Self-running supervisor stopping.")

    def is_running(self) -> bool:
        return self._running

    def status(self) -> Dict[str, Any]:
        """Return supervisor health and task statistics."""
        with self._lock:
            task_stats = []
            for t in self._tasks.values():
                task_stats.append({
                    "task_id": t.task_id,
                    "name": t.name,
                    "interval_seconds": t.interval,
                    "run_count": t.run_count,
                    "last_run": datetime.fromtimestamp(t.last_run, tz=timezone.utc).isoformat() if t.last_run else None,
                    "last_error": t.last_error,
                })
            return {
                "running": self._running,
                "task_count": len(self._tasks),
                "tasks": task_stats,
            }

    def _loop(self) -> None:
        while self._running:
            now = time.time()
            to_remove = []

            with self._lock:
                tasks_snapshot = list(self._tasks.values())

            for task in tasks_snapshot:
                if not self._running:
                    break
                if task.last_run is None or (now - task.last_run) >= task.interval:
                    try:
                        task.handler()
                        task.run_count += 1
                        task.last_error = None
                    except Exception as e:
                        logger.exception("Task '%s' failed", task.name)
                        task.last_error = str(e)
                    finally:
                        task.last_run = time.time()

                    if task.one_shot:
                        to_remove.append(task.task_id)

            if to_remove:
                with self._lock:
                    for tid in to_remove:
                        self._tasks.pop(tid, None)

            # Sleep in short increments for responsive shutdown
            for _ in range(int(self.heartbeat_interval * 10)):
                if not self._running:
                    break
                time.sleep(0.1)


# Global supervisor instance
SELF_RUNNER = SelfRunningSupervisor()
