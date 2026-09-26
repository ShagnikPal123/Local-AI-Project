"""Self-improvement sessions: parse, lifecycle, and the approval gate.

The property that matters most: a session can *propose* but never *apply*.
Every outcome lands as a draft in the change-review queue, which only an owner
can move forward — the same gate tests in ``test_change_review.py`` try to
break, so these tests assume it and check the engine feeds it correctly.
"""

import threading
import time

import pytest

import improvement_engine
from improvement_engine import (
    ENGINE,
    SelfImprovementError,
    SelfImprovementEngine,
    parse_proposals,
)
from tests.conftest import *  # noqa: F401,F403 — shared store isolation


# --- reply parsing (model output is untrusted input) ---------------------------


def test_none_reply_yields_nothing():
    assert parse_proposals("NONE") == []
    assert parse_proposals("") == []
    assert parse_proposals("none.") == []


def test_a_well_formed_reply_parses():
    reply = (
        "TITLE: Split the giant chat function\n"
        "FILE: chat_service.py\n"
        "CHANGE: Extract the tool-loop into its own method.\n"
        "WHY: Smaller functions are easier to test.\n"
        "---\n"
        "TITLE: Cache folder listings\n"
        "FILE: folder_reader.py\n"
        "CHANGE: Memoize list_folders for a few seconds.\n"
        "WHY: Avoids re-reading the disk on every tab open.\n"
        "---\n"
    )
    proposals = parse_proposals(reply)
    assert [p["file"] for p in proposals] == ["chat_service.py", "folder_reader.py"]
    assert proposals[0]["title"] == "Split the giant chat function"
    assert proposals[1]["why"] == "Avoids re-reading the disk on every tab open."


def test_a_proposal_missing_change_is_dropped():
    reply = "TITLE: Half a proposal\nFILE: chat_service.py\nWHY: no change line\n---\n"
    assert parse_proposals(reply) == []


def test_non_python_files_are_rejected():
    reply = (
        "TITLE: Edit the frontend\nFILE: App.tsx\nCHANGE: Tweak something.\nWHY: Better UI.\n---\n"
    )
    assert parse_proposals(reply) == []


def test_path_separators_in_file_are_stripped():
    """The change gate rejects targets with path separators; strip them early."""
    reply = (
        "TITLE: Fix connectors\nFILE: connectors/finance_connector.py\n"
        "CHANGE: Cache the quote call.\nWHY: Faster.\n---\n"
    )
    proposals = parse_proposals(reply)
    assert proposals and proposals[0]["file"] == "finance_connector.py"


def test_long_fields_are_clamped():
    reply = "TITLE: " + "x" * 500 + "\nFILE: chat_service.py\nCHANGE: " + "y" * 2000 + \
        "\nWHY: " + "z" * 800 + "\n---\n"
    proposals = parse_proposals(reply)
    assert proposals[0]["title"] == "x" * 120
    assert len(proposals[0]["change"]) == 600
    assert len(proposals[0]["why"]) == 300


# --- sessions -----------------------------------------------------------------


@pytest.fixture
def isolated_engine(monkeypatch):
    """A fresh engine per test: no shared state, no real model, no real writes."""
    return SelfImprovementEngine()


def _stub_model(replies):
    """A model_fn serving scripted replies; records prompts it was given."""
    calls: list[str] = []
    lock = threading.Lock()

    def model_fn(prompt, *, system="", max_tokens=0, **_kw):
        with lock:
            calls.append(prompt)
        return replies.pop(0)

    model_fn.calls = calls  # type: ignore[attr-defined]
    return model_fn


def test_start_rejects_an_empty_goal(isolated_engine):
    with pytest.raises(ValueError):
        isolated_engine.start("   ")
    assert isolated_engine.list_sessions() == []


def test_only_one_session_runs_at_a_time(isolated_engine):
    replies = _stub_model(["NONE"] * 8)
    isolated_engine.start("first goal", model_fn=replies)
    with pytest.raises(RuntimeError, match="already running"):
        isolated_engine.start("second goal", model_fn=replies)
    session_id = isolated_engine.list_sessions()[0]["session_id"]
    isolated_engine.stop(session_id)
    assert isolated_engine.get(session_id)["status"] in ("stopping", "stopped", "done")


def test_stop_of_unknown_session_is_an_error(isolated_engine):
    with pytest.raises(SelfImprovementError):
        isolated_engine.stop("nope")


def test_get_of_unknown_session_is_none(isolated_engine):
    assert isolated_engine.get("nope") is None


def test_a_session_files_proposals_as_drafts(monkeypatch, isolated_engine, tmp_path):
    """The core promise: analysis output reaches the review queue, and only as drafts."""
    from change_review import ChangeLog, ChangeOrigin, ChangeStatus

    fresh = ChangeLog(tmp_path / "changes.json")

    reply = (
        "TITLE: Extract the tool loop\n"
        "FILE: chat_service.py\n"
        "CHANGE: Move the tool loop into a method.\n"
        "WHY: Testable.\n---\n"
    )
    monkeypatch.setattr("change_review.CHANGE_LOG", fresh)

    isolated_engine.start("make chat_service smaller", model_fn=_stub_model([reply]))
    _wait_for_engine(isolated_engine)

    assert isolated_engine.list_sessions()[0]["proposals_filed"] == 1
    changes = fresh.list_changes()
    assert len(changes) == 1
    recorded = changes[0]
    assert recorded["status"] == ChangeStatus.DRAFT.value
    assert recorded["origin"] == ChangeOrigin.AGENT.value
    assert "chat_service.py" in recorded["target"]
    assert "Nyx (self-improvement)" in recorded["author"]


def test_stopped_session_reports_status(isolated_engine):
    replies = _stub_model(["NONE"] * 8)
    session = isolated_engine.start("watch the status", model_fn=replies)
    isolated_engine.stop(session["session_id"])
    _wait_for_engine(isolated_engine)
    final = isolated_engine.get(session["session_id"])
    assert final["status"] in ("stopped", "done")
    assert final["ended_at"] is not None


def test_a_failing_model_fails_the_session(isolated_engine):
    def boom(prompt, *, system="", max_tokens=0, **_kw):
        raise RuntimeError("provider down")

    isolated_engine.start("this will fail", model_fn=boom)
    _wait_for_engine(isolated_engine)
    session = isolated_engine.list_sessions()[0]
    assert session["status"] == "error"
    assert "provider down" in session["error"]


def test_the_engine_uses_the_injected_model(isolated_engine):
    model_fn = _stub_model(["NONE"])
    isolated_engine.start("who answers", model_fn=model_fn)
    _wait_for_engine(isolated_engine)
    assert len(model_fn.calls) == 1
    prompt = model_fn.calls[0]
    assert "make chat" in prompt or "who answers" in prompt
    assert "TITLE:" in prompt  # the format instructions are present


def _wait_for_engine(engine, timeout: float = 5.0) -> None:
    """Wait for a *terminal* status: "stopping" is mid-flight, not finished."""
    terminal = ("done", "stopped", "error")
    deadline = time.time() + timeout
    while time.time() < deadline:
        sessions = engine.list_sessions()
        if sessions and sessions[0]["status"] in terminal:
            return
        time.sleep(0.02)
    raise AssertionError(f"session did not finish in time (status: {sessions[0]['status'] if sessions else 'none'})")


def test_a_fresh_engine_has_no_sessions(isolated_engine):
    assert isolated_engine.list_sessions() == []
    assert ENGINE is not None  # the shared production engine exists
