"""The equalize page: Claude Code sessions read from their transcripts, and what needs the owner."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import claude_sessions as cs

NOW = 1_800_000_000.0


def at(seconds_ago: float) -> str:
    return datetime.fromtimestamp(NOW - seconds_ago, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def entry(kind, content, ago, **extra):
    return {"type": kind, "message": {"role": kind, "content": content}, "timestamp": at(ago), **extra}


def tool(name):
    return [{"type": "tool_use", "name": name, "input": {}}]


def test_states_are_read_from_the_last_real_entry():
    assert cs.read_state([entry("assistant", tool("AskUserQuestion"), 5)], NOW, 5)["state"] == "needs_you"
    assert cs.read_state([entry("assistant", tool("Bash"), 5)], NOW, 5)["state"] == "working"
    stuck = cs.read_state([entry("assistant", tool("Bash"), 300)], NOW, 300)
    assert stuck["state"] == "needs_you" and "approve Bash" in stuck["why"]
    assert cs.read_state([entry("user", "do it", 10)], NOW, 10)["state"] == "working"
    assert cs.read_state([entry("assistant", [{"type": "text", "text": "Done."}], 600)], NOW, 600)["state"] == "your_turn"
    assert cs.read_state([entry("assistant", "Done.", 3 * 86400)], NOW, 3 * 86400)["state"] == "idle"
    noise = [entry("assistant", tool("AskUserQuestion"), 50), {"type": "attachment", "timestamp": at(1)}]
    assert cs.read_state(noise, NOW, 1)["state"] == "needs_you", "attachments and system notes are skipped"


def test_sessions_are_listed_needs_you_first_with_their_titles(tmp_path, monkeypatch):
    project = tmp_path / "C--work-site"
    project.mkdir()
    done = project / "a.jsonl"
    done.write_text("\n".join(json.dumps(e) for e in [
        entry("user", "<system-reminder>x</system-reminder>Build the landing page", 900, cwd="C:/work/site"),
        entry("assistant", "Built it.", 800, cwd="C:/work/site")]), encoding="utf-8")
    asking = project / "b.jsonl"
    asking.write_text("\n".join(json.dumps(e) for e in [
        entry("user", "Plan the API", 100, cwd="C:/work/api"),
        {"type": "custom-title", "customTitle": "API plan"},
        entry("assistant", tool("ExitPlanMode"), 60, cwd="C:/work/api")]), encoding="utf-8")
    monkeypatch.setattr(time, "time", lambda: NOW)
    import os

    os.utime(done, (NOW - 800, NOW - 800))
    os.utime(asking, (NOW - 60, NOW - 60))
    rows = cs.sessions(now=NOW, base=tmp_path)
    assert [r["id"] for r in rows] == ["b", "a"]
    assert rows[0]["state"] == "needs_you" and rows[0]["title"] == "API plan" and rows[0]["project"] == "api"
    assert rows[1]["title"] == "Build the landing page" and rows[1]["state"] == "your_turn"


def test_equalize_routes_are_the_owner_s():
    from fastapi.testclient import TestClient

    import deploy_mode
    import server

    remote = TestClient(server.app, client=("203.0.113.9", 50081))
    for path in ("/api/equalize/sessions", "/api/equalize/needs-you"):
        assert remote.get(path).status_code in (401, 403)
    assert "/api/equalize" in deploy_mode.HOSTED_BLOCKED_PREFIXES
