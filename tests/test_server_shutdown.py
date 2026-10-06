"""Engine shutdown finishes on its own.

The shutdown hook used to wait on every task in the event loop. That includes the server's own task
(uvicorn's serve, TestClient's portal), which is waiting for shutdown to finish — so shutdown waited
on itself: TestClient never exited, and uvicorn paid a timeout per foreign task on every restart.
"""

import asyncio
import threading
import time

from fastapi.testclient import TestClient

import server

DEADLINE = 30.0


def _within_deadline(action) -> float:
    """Run ``action`` on a daemon thread so a hang fails this test instead of stalling the suite."""
    outcome = {}

    def run() -> None:
        started = time.monotonic()
        try:
            action()
        except BaseException as error:  # noqa: BLE001 - re-raised on the test thread below
            outcome["error"] = error
        outcome["seconds"] = time.monotonic() - started

    worker = threading.Thread(target=run, name="nyx-test-shutdown", daemon=True)
    worker.start()
    worker.join(DEADLINE)
    assert not worker.is_alive(), f"shutdown did not finish within {DEADLINE:.0f}s"
    if "error" in outcome:
        raise outcome["error"]
    return outcome["seconds"]


def test_testclient_enters_and_exits(monkeypatch):
    monkeypatch.setenv("NYX_NO_BACKGROUND", "1")
    client = TestClient(server.app)

    def enter_and_exit() -> None:
        with client:
            assert client.get("/api/health").status_code == 200

    seconds = _within_deadline(enter_and_exit)
    # Waiting on a foreign task costs at least SHUTDOWN_TIMEOUT even when it does not hang forever.
    assert seconds < server.SHUTDOWN_TIMEOUT


def test_shutdown_lets_nyx_work_finish_and_cancels_what_overruns(monkeypatch):
    monkeypatch.setenv("NYX_NO_BACKGROUND", "1")
    monkeypatch.setattr(server, "SHUTDOWN_TIMEOUT", 0.5)
    client = TestClient(server.app)
    tasks = {}

    async def start_work() -> None:
        tasks["quick"] = server.spawn_background(asyncio.sleep(0.05, "done"), name="nyx-test-quick")
        tasks["stuck"] = server.spawn_background(asyncio.sleep(3600), name="nyx-test-stuck")

    def run() -> None:
        with client:
            client.portal.call(start_work)

    seconds = _within_deadline(run)
    assert tasks["quick"].result() == "done"
    assert tasks["stuck"].cancelled()
    assert seconds < 5
    assert not server._BACKGROUND_TASKS
