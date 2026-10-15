"""The slider under the composer, and the questions you answer with a click.

Project Null N82–N85. Normal is the quick chat that thinks out loud, Co-work keeps
working with a visible checklist, Plan writes the plan and may not change anything
until the owner approves it — that last one is a safety property, so it has real
tests rather than a trusting glance at the prompt.
"""

from __future__ import annotations

import types

import pytest

import chat_modes
import question_cards
from permissions import PermissionDenied


class _Service:
    """Just enough of a ChatService for the mode to be applied to."""

    def __init__(self) -> None:
        self.conversation_history = [{"role": "system", "content": "standing instructions"}]
        self.tool_guard = None


# --- the modes ------------------------------------------------------------------------


def test_the_modes_are_named_and_unknown_words_fall_back_to_normal():
    assert chat_modes.normalize("Co-Work") == "cowork"
    assert chat_modes.normalize("plan_approved") == "plan_go"
    assert chat_modes.normalize("") == "normal"
    assert chat_modes.normalize("nonsense") == "normal"


def test_normal_is_the_fast_one_and_cowork_gets_room_to_work():
    normal = chat_modes.settings_for("normal")
    assert normal["skip_optimizer"] and normal["skip_consult"], "the slow extras are what made it feel slow"
    assert normal["force_full"] is False, "the quick path is allowed to answer"

    cowork = chat_modes.settings_for("cowork")
    assert cowork["max_steps"] > normal["max_steps"] and cowork["checklist"] is True
    assert cowork["read_only"] is False


def test_the_note_changes_with_the_mode_and_never_stacks_up():
    service = _Service()
    chat_modes.prepare(service, "normal")
    chat_modes.prepare(service, "cowork")
    notes = [m for m in service.conversation_history if str(m["content"]).startswith(chat_modes.PREFIX)]
    assert len(notes) == 1 and "Co-work" in notes[0]["content"]
    assert "think out loud" in chat_modes.note_for("normal").lower()
    assert "```plan" in chat_modes.note_for("plan")


# --- plan mode may not act ------------------------------------------------------------


def test_a_planning_turn_can_read_but_cannot_change_anything():
    service = _Service()
    switches = chat_modes.prepare(service, "plan")
    assert switches["read_only"] is True
    guard = service.tool_guard
    assert callable(guard)

    guard("search_web", "web")        # looking things up is how it writes a good plan
    guard("file_excerpt", "files")    # reading a file it is asked about
    for name, category in (("write_file", "files"), ("run_command", "shell"), ("trading_order", "finance"),
                           ("send_email", "email"), ("improve_self", "code")):
        with pytest.raises(PermissionDenied):
            guard(name, category)


def test_the_plan_gate_narrows_an_existing_gate_and_never_widens_it():
    def only_web(name: str, category: str) -> None:
        if category != "web":
            raise PermissionDenied("Free Will says no.")

    service = _Service()
    service.tool_guard = only_web
    chat_modes.prepare(service, "plan")
    service.tool_guard("search_web", "web")
    with pytest.raises(PermissionDenied):
        service.tool_guard("file_excerpt", "files")  # allowed by Plan, refused by the gate underneath


def test_the_approved_turn_is_the_one_allowed_to_work():
    service = _Service()
    switches = chat_modes.prepare(service, "plan_go")
    assert switches["read_only"] is False and switches["max_steps"] >= 48
    assert service.tool_guard is None
    assert "approved" in chat_modes.note_for("plan_go").lower()


# --- the checklist --------------------------------------------------------------------


def test_the_checklist_is_cleaned_and_shown_to_the_owner():
    events = []
    context = types.SimpleNamespace(emit=lambda kind, **payload: events.append((kind, payload)))
    import tool_context

    token = tool_context._CURRENT.set(context)  # type: ignore[attr-defined]
    try:
        result = chat_modes.tool_update_checklist([
            {"text": "Read the file", "status": "done"},
            {"text": "Write the tests", "status": "doing"},
            "Run them",
            {"text": "", "status": "todo"},
            {"text": "Odd one", "status": "sideways"},
        ])
    finally:
        tool_context._CURRENT.reset(token)  # type: ignore[attr-defined]

    assert "1/4 done" in result
    kind, payload = events[0]
    assert kind == "checklist"
    assert [item["status"] for item in payload["items"]] == ["done", "doing", "todo", "todo"]
    assert payload["items"][2]["text"] == "Run them"


def test_an_empty_checklist_asks_for_the_shape_instead_of_showing_nothing():
    assert "status" in chat_modes.tool_update_checklist([])


# --- question cards -------------------------------------------------------------------


def test_a_question_needs_a_question_and_at_least_two_answers():
    good = question_cards.parse('{"question": "Which one?", "options": ['
                                '{"label": "A", "means": "fast", "recommended": true}, {"label": "B"}]}')
    assert good["options"][0]["recommended"] is True and good["options"][1]["means"] == ""
    assert good["other"], "there is always a box for an approach it did not think of"

    assert question_cards.parse('{"question": "Which?", "options": [{"label": "only one"}]}') is None
    assert question_cards.parse("not json") is None
    assert question_cards.parse('{"options": [{"label": "A"}, {"label": "B"}]}') is None


def test_questions_are_found_in_an_answer_and_duplicates_dropped():
    answer = (
        "Here is what I would do.\n\n"
        '```question\n{"question": "Which database?", "options": [{"label": "SQLite", "means": "one file"}, '
        '{"label": "SQLite", "means": "again"}, {"label": "Postgres", "means": "a server"}]}\n```\n'
        "And nothing else."
    )
    cards = question_cards.find_all(answer)
    assert len(cards) == 1
    assert [o["label"] for o in cards[0]["options"]] == ["SQLite", "Postgres"]


def test_the_answer_carries_the_question_and_what_the_choice_meant():
    card = question_cards.parse('{"question": "Which database?", "options": ['
                                '{"label": "SQLite", "means": "one file"}, {"label": "Postgres", "means": "a server"}]}')
    message = question_cards.answer_message(card, ["SQLite"], other="")
    assert "**Which database?**" in message and "SQLite (one file)" in message

    typed = question_cards.answer_message(card, [], other="DuckDB, it is columnar")
    assert "My own approach: DuckDB" in typed


def test_the_model_is_told_how_to_ask_a_question_with_readable_json():
    from pathlib import Path

    import chat_service

    source = Path(chat_service.__file__).read_text(encoding="utf-8")
    assert "{QUESTION_RULE}" in source, "the rule has to be inside the system prompt, not just defined"
    assert "`question`" in question_cards.FORMAT_RULE
    # The rule is inserted as a value, so doubled braces would reach the model as "{{".
    assert "{{" not in question_cards.FORMAT_RULE and "}}" not in question_cards.FORMAT_RULE


# --- Swarm and Auto (Update 1, U5/U6) -----------------------------------------------------


@pytest.mark.parametrize("text, mode", [
    ("hi there", "normal"),
    ("what is the capital of France?", "normal"),
    ("can you explain how rust lifetimes work?", "normal"),
    ("build me a todo app with React", "cowork"),
    ("can you fix the bug in server.py?", "cowork"),
    ("make a plan for my website redesign", "plan"),
    ("how should we approach building a game engine?", "plan"),
    ("fix every failing test in the repo", "swarm"),
    ("upload these files to the project and fix the small errors in each file", "swarm"),
    ("- fix the login bug\n- add a dark mode\n- write tests for the cart\n- update the README", "swarm"),
])
def test_auto_picks_a_mode_from_the_words(text, mode):
    picked, reason = chat_modes.choose(text)
    assert picked == mode, (text, picked, reason)
    assert reason, "Auto always says why it picked what it picked"


def test_auto_never_acts_on_a_request_to_plan_even_with_many_parts():
    picked, _ = chat_modes.choose("make a plan to fix every failing test in parallel before you start")
    assert picked == "plan"
    service = _Service()
    switches = chat_modes.prepare(service, "auto", "write a spec for the new login page, don't change anything yet")
    assert switches["mode"] == "plan" and switches["read_only"] and switches["auto"] is True
    with pytest.raises(PermissionDenied):
        service.tool_guard("write_file", "files")


def test_auto_and_swarm_are_modes_and_other_modes_are_untouched_by_resolve():
    assert chat_modes.normalize("Swarm") == "swarm" and chat_modes.normalize("automatic") == "auto"
    assert chat_modes.resolve("cowork", "make a plan") == ("cowork", ""), "only Auto reads the message"
    assert chat_modes.resolve("auto", "hi")[0] == "normal"


def test_swarm_gets_room_to_work_and_is_told_its_size(monkeypatch):
    import swarm

    monkeypatch.setattr(swarm, "limit", lambda: 12)
    monkeypatch.setattr(swarm, "parallel", lambda size=0: 4)
    switches = chat_modes.settings_for("swarm")
    assert switches["swarm"] == 12 and switches["max_steps"] >= 48 and switches["checklist"]
    assert not switches["read_only"], "a swarm does the work; the agents' own permission checks still apply"

    service = _Service()
    chat_modes.prepare(service, "swarm")
    note = service.conversation_history[-1]["content"]
    assert note.startswith(chat_modes.PREFIX) and "up to 12" in note and "4 at a time" in note
    assert "dispatch_agents" in note and '{"agent"' in note, "the braces in the template must reach the model single"

    # Switching back to Normal replaces the swarm's note instead of stacking a second one.
    chat_modes.prepare(service, "normal")
    notes = [m for m in service.conversation_history if str(m.get("content", "")).startswith(chat_modes.PREFIX)]
    assert len(notes) == 1 and "Normal" in notes[0]["content"]


# --- Integrity (Fixer Upper S26, S39) ------------------------------------------------------------------------------


def test_integrity_nudge_fires_on_a_refusal_or_an_unused_keyboard():
    assert chat_modes.integrity_nudge("go on", "I'm unable to directly control the browser or simulate typing.", [])
    assert chat_modes.integrity_nudge("type hi in the doc", "The doc is ready for you.", ["open_link"])
    assert chat_modes.integrity_nudge("can you click the blue button?", "Sure, it's on the right.", [])


def test_integrity_nudge_stays_quiet_when_the_work_was_done_or_blocked():
    assert not chat_modes.integrity_nudge("type hi in the doc", "Typed hi.", ["screen_view", "keyboard_type"])
    assert not chat_modes.integrity_nudge("type hi", "I can't: your screen is off-limits.", ["keyboard_type"],
                                          "Not on the owner's screen: The owner's screen is off-limits")
    assert not chat_modes.integrity_nudge("how do I sign in to gmail?", "Open gmail.com and press Sign in.", [])
    assert not chat_modes.integrity_nudge("hello", "Hi! How can I help?", [])


def test_plan_mode_blocks_the_real_mouse_and_keyboard_tool_names():
    guard = chat_modes.plan_guard()
    from permissions import PermissionDenied

    for name in ("keyboard_type", "mouse_click", "own_computer_type"):
        with pytest.raises(PermissionDenied):
            guard(name, "general")


# ---------------------------------------------------------------------------
# Code inside the normal chat (Drive doc 2, 2.1)
# ---------------------------------------------------------------------------


def test_code_session_needs_a_real_folder(tmp_path):
    assert chat_modes.code_session("") is None
    assert chat_modes.code_session(str(tmp_path / "missing")) is None
    file = tmp_path / "a.txt"
    file.write_text("x")
    assert chat_modes.code_session(str(file)) is None
    session = chat_modes.code_session(str(tmp_path), "nonsense")
    assert session["folder"] == str(tmp_path.resolve())
    assert session["environment"] == "local" and session["environment_label"] == "This PC"


def test_code_note_is_replaced_each_turn_and_dropped_when_back_in_chat(tmp_path):
    service = _Service()
    chat_modes.prepare_code(service, str(tmp_path), "local")
    chat_modes.prepare_code(service, str(tmp_path), "review")
    notes = [m["content"] for m in service.conversation_history if m["content"].startswith(chat_modes.CODE_PREFIX)]
    assert len(notes) == 1 and str(tmp_path.resolve()) in notes[0] and "Review first" in notes[0]
    assert chat_modes.prepare_code(service, "", None) is None
    assert not any(m["content"].startswith(chat_modes.CODE_PREFIX) for m in service.conversation_history)


def test_review_first_reads_but_never_writes_or_runs():
    guard = chat_modes.code_review_guard()
    guard("read_file", "files.read")
    guard("search_web", "web")
    for name, category in (("write_file", "files.write"), ("run_command", "shell"), ("delete_path", "files.delete"),
                           ("run_python", "code"), ("make_folder", "files.write")):
        with pytest.raises(PermissionDenied):
            guard(name, category)


def test_review_first_keeps_the_gate_already_there():
    def inner(name, category):
        raise PermissionDenied("owner said no")

    with pytest.raises(PermissionDenied, match="owner said no"):
        chat_modes.code_review_guard(inner)("read_file", "files.read")
