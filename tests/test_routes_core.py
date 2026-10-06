"""The Core view's processes list shows everything running, not five hand-picked kinds (U31)."""

from __future__ import annotations

import threading

import pytest

import routes_core


@pytest.fixture
def client():
    import server
    from fastapi.testclient import TestClient

    return TestClient(server.app, client=("127.0.0.1", 50133))


def _hold(event):
    event.wait(10)


def test_a_worker_thread_nobody_listed_shows_in_the_overview(client):
    """Threads were found and then thrown away here, so new features never showed (the bug U31 is about)."""
    release = threading.Event()
    worker = threading.Thread(target=_hold, args=(release,), name="nyx-photo-sorter-9a8b7c6d", daemon=True)
    worker.start()
    try:
        processes = client.get("/api/core/overview").json()["processes"]
    finally:
        release.set()
        worker.join(5)
    row = next(p for p in processes if p["id"] == "nyx-photo-sorter-9a8b7c6d")
    assert row["label"] == "Photo sorter" and row["group"] == "job"


def test_a_running_research_job_shows_with_where_to_watch_it(monkeypatch, tmp_path):
    import research_engine

    release = threading.Event()

    def slow_model(prompt, system="", max_tokens=0):
        release.wait(10)
        return "## Summary\nok [1]"

    jobs = research_engine.ResearchJobs(model_fn=slow_model, web_search=lambda q: [], paper_search=lambda q, n: [
        {"kind": "paper", "title": "A paper", "authors": ["Ada Lovelace"], "year": 2024, "abstract": "Text."}],
        store_dir=tmp_path / "research")
    monkeypatch.setattr(research_engine, "RESEARCH", jobs)
    monkeypatch.setattr(research_engine, "_auto_teach", lambda: False)
    job = jobs.start("Does the processes view see research?")
    try:
        rows = [p for p in routes_core._processes() if job["job_id"] in p["id"]]
    finally:
        release.set()
        # Finish while the fakes are still in place: a job that ends after the test would teach the real brain.
        for thread in threading.enumerate():
            if thread.name == f"nyx-research-{job['job_id']}":
                thread.join(10)
    assert len(rows) == 1, rows                       # the job, not also its thread
    assert rows[0]["tab"] == "research" and rows[0]["label"] == "Research · standard"
    assert "Does the processes view see research?" in rows[0]["detail"]


def test_the_rows_keep_the_shape_the_page_reads(client):
    processes = client.get("/api/core/overview").json()["processes"]
    for row in processes:
        assert {"kind", "id", "label", "detail", "status", "group", "tab"} <= set(row)
