"""Where notifications are raised from: the chat route, approval cards and scheduled tasks."""

from __future__ import annotations

import pytest

import notifications as n


def test_the_chat_route_hands_a_finished_turn_to_notifications(monkeypatch):
    import routes_live

    seen = []
    monkeypatch.setattr(n, "turn_finished", lambda chat_id, state, reply, seconds: seen.append((chat_id, state, reply, seconds)))
    routes_live._notify_finished("c1", "done", {"reply": "All finished."}, 42.0)
    routes_live._notify_finished("c1", "error", None, 1.0)
    assert seen == [("c1", "done", "All finished.", 42.0), ("c1", "error", "", 1.0)]
    monkeypatch.setattr(n, "turn_finished", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    routes_live._notify_finished("c1", "done", {"reply": "x"}, 1.0)          # never raises into the turn


def test_an_approval_card_notifies_the_owner(monkeypatch):
    import permissions
    import tool_context

    seen = []
    monkeypatch.setattr(n, "help_needed", lambda summary, chat_id="": seen.append((summary, chat_id)))
    monkeypatch.setattr(permissions, "APPROVAL_TIMEOUT_SECONDS", 0.2)
    ctx = tool_context.ToolContext(turn_id="t1", chat_id="c1", sink=lambda event: None)
    with tool_context.use_context(ctx):
        with pytest.raises(permissions.PermissionDenied):
            permissions.ask("files.write", "Write notes.txt")      # nobody answers: it times out, after the notice
    assert seen == [("Write notes.txt", "c1")]


def test_a_scheduled_task_that_runs_tells_the_owner(monkeypatch):
    import avatars
    import scheduled

    seen = []
    monkeypatch.setattr(n, "task_ran", lambda title, ok, reply="": seen.append((title, ok, reply)))
    monkeypatch.setattr(avatars, "run", lambda avatar, text, kind="talk", wait=0: {"ok": True, "reply": "Sent three items."})
    task = scheduled.create({"title": "Morning digest", "prompt": "Send the digest", "avatar": "a1"})
    assert scheduled.run_now(task["id"])["ok"] is True
    assert seen == [("Morning digest", True, "Sent three items.")]
