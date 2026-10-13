"""Ultra Fast (ultrafast.py): Jev's select-don't-generate pattern, run locally and dry."""

import ultrafast


def plan(text):
    return ultrafast.plan_local(text)


def test_commands_map_to_closed_actions():
    assert plan("go to youtube")["action"] == "open_site"
    tab = plan("close this tab")
    assert (tab["action"], tab["args"]) == ("shortcut", {"key": "close_tab"})
    assert plan("volume up")["args"] == {"op": "up"}
    assert plan("next song")["args"] == {"op": "next"}
    assert plan("scroll down a lot")["args"] == {"direction": "down", "amount": 15}
    assert plan("take a screenshot")["args"] == {"op": "screenshot"}


def test_search_engine_and_payload_come_from_the_words():
    result = plan("search youtube for lofi hip hop")
    assert result["action"] == "search"
    assert result["args"]["engine"] == "youtube" and result["args"]["text"] == "lofi hip hop"


def test_typed_text_is_a_span_of_what_was_said():
    result = plan("type hello world and press enter")
    assert result["action"] == "type_text"
    assert result["args"]["text"] == "hello world" and result["args"]["submit"] is True
    assert result["args"]["text"] in ultrafast.text_candidates("type hello world and press enter").values()


def test_questions_and_multi_step_jobs_are_not_desktop_commands():
    assert plan("what is the capital of france?")["action"] == "chat"
    assert plan("buy milk on amazon")["action"] == "task"


def test_compound_runs_each_step(monkeypatch):
    monkeypatch.setattr(ultrafast, "installed_apps", lambda: {"notepad": "notepad.exe"})
    monkeypatch.setattr(ultrafast.time, "sleep", lambda _s: None)
    result = ultrafast.handle("open notepad and type buy milk", dry_run=True)
    assert result["handled"] and [s["action"] for s in result["plan"]["steps"]] == ["open_app", "type_text"]


def test_unknown_shortcut_or_low_confidence_is_refused():
    assert ultrafast.execute({"action": "shortcut", "args": {"key": "rm -rf"}, "confidence": 1}, dry_run=True)["ok"] is False
    assert ultrafast.execute({"action": "open_app", "args": {}, "confidence": 0.1}, dry_run=True)["ok"] is False


def test_jev_is_used_only_with_a_key(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(ultrafast, "jev_key", lambda: "")
    assert ultrafast.plan("go to github")["via"] == "local"


def test_jev_answers_are_checked_against_the_closed_sets(monkeypatch):
    import io
    import json

    answers = {"action": {"choice": "shortcut", "confidence": 0.9}, "shortcut": {"choice": "format_disk", "confidence": 0.99}}

    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(ultrafast, "installed_apps", lambda: {})
    monkeypatch.setattr(ultrafast.urllib.request, "urlopen",
                        lambda *_a, **_k: Reply(json.dumps({"answers": answers}).encode()))
    result = ultrafast.plan_jev("format my disk", key="test-key")
    assert result["args"]["key"] == "" and result["confidence"] == 0.0


def test_judge_ranks_drafts_and_never_sends():
    raw = ('{"intent": "wants a refund", "risk": "medium", "risk_why": "annoyed", "needs": "a date", '
           '"best_action": "apologise and give a date", "replies": [{"text": "b", "score": 40}, {"text": "a", "score": 90}]}')
    result = ultrafast.judge("Them: where is my money", ask=lambda _p: raw)
    assert result["intent"] == "wants a refund" and [r["text"] for r in result["replies"]] == ["a", "b"]


def test_chat_mode_is_registered():
    import chat_modes

    assert chat_modes.normalize("ultra_fast") == "ultrafast"
    assert chat_modes.settings_for("ultrafast")["ultrafast"] is True
