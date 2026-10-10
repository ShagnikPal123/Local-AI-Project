"""Ichos → Claude Code: the right command, the answer read back, follow-ups resume the same session."""

import json
import subprocess

import pytest


@pytest.fixture()
def bridge(tmp_path, monkeypatch):
    import claude_bridge

    monkeypatch.setattr(claude_bridge, "_sessions_path", lambda: tmp_path / "claude_bridge.json")
    monkeypatch.setattr(claude_bridge, "find_claude", lambda: "claude")
    return claude_bridge


def fake(answer="Done.", session="sess-1", code=0, calls=None):
    def run(command, **kwargs):
        if calls is not None:
            calls.append((command, kwargs["cwd"]))
        out = json.dumps({"result": answer, "session_id": session, "is_error": False, "total_cost_usd": 0.01})
        return subprocess.CompletedProcess(command, code, stdout=out, stderr="")
    return run


def test_a_task_runs_headless_in_the_folder_and_reads_the_answer(bridge, tmp_path):
    calls = []
    reply = bridge.ask("add a test", str(tmp_path), runner=fake(calls=calls))
    command, cwd = calls[0]
    assert command[:3] == ["claude", "-p", "add a test"] and "--output-format" in command and "json" in command
    assert command[command.index("--permission-mode") + 1] == "acceptEdits"
    assert cwd == str(tmp_path) and reply["ok"] and reply["text"] == "Done." and reply["session_id"] == "sess-1"


def test_a_follow_up_resumes_the_last_session(bridge, tmp_path):
    bridge.ask("first", str(tmp_path), runner=fake(session="sess-9"))
    calls = []
    bridge.ask("and then", str(tmp_path), continue_last=True, runner=fake(calls=calls))
    assert calls[0][0][-2:] == ["--resume", "sess-9"]


def test_failures_are_plain_sentences(bridge, tmp_path, monkeypatch):
    assert bridge.ask("  ", str(tmp_path))["ok"] is False
    assert "No folder" in bridge.ask("x", str(tmp_path / "missing"))["text"]
    monkeypatch.setattr(bridge, "find_claude", lambda: None)
    assert "not installed" in bridge.ask("x", str(tmp_path))["text"]


def test_an_unknown_mode_falls_back_to_accept_edits(bridge, tmp_path):
    calls = []
    bridge.ask("x", str(tmp_path), mode="bypassPermissions", runner=fake(calls=calls))
    assert calls[0][0][calls[0][0].index("--permission-mode") + 1] == "acceptEdits"
