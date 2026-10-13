"""The notch assistant's state (equalize_assistant.py): settings, timers, steps, the fast file read, intents."""

import json
import types

import pytest

import equalize_assistant as ea


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(ea, "STORE", tmp_path / "assistant.json")
    monkeypatch.setattr(ea, "JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr(ea, "_jobs", {})
    monkeypatch.setattr(ea, "_jobs_loaded", True)
    monkeypatch.setattr(ea, "catalog", lambda: [{"id": "avatar:halo", "name": "Halo", "kind": "avatar", "color": "#fff"}])
    monkeypatch.setattr(ea, "_claude_live", lambda: [])


def test_settings_are_clamped_and_unknown_keys_ignored():
    state = ea.update({"sound": {"volume": 7, "mode": "loud", "bogus": 1}, "activation": {"gestures": ["clap", "nope"]},
                       "pinned": [{"name": "GitHub", "kind": "github", "target": "me/repo"}], "hack": True})
    assert state["sound"]["volume"] == 1.0 and state["sound"]["mode"] == "ai" and "bogus" not in state["sound"]
    assert state["activation"]["gestures"] == ["clap"]
    assert state["pinned"][0]["color"] == ea.APP_COLORS["github"] and "hack" not in state


def test_timers_parse_and_expire():
    assert ea.parse_timer("set a timer for 5 minutes") == 300
    assert ea.parse_timer("timer 1h 30m") == 5400
    assert ea.parse_timer("five minutes") is None
    timer = ea.add_timer(90, "tea")
    assert [t["id"] for t in ea.settings()["timers"]] == [timer["id"]]
    assert ea.remove_timer(timer["id"]) and ea.settings()["timers"] == []


def test_tool_calls_become_readable_steps():
    edit = ea.step_from_tool("Edit", {"file_path": "src/invoice.ts", "old_string": "const TVA = 0.196",
                                      "new_string": "const TVA = 0.20"})
    assert edit["kind"] == "edit" and edit["title"] == "Edit invoice.ts"
    assert [(line["sym"], line["text"]) for line in edit["diff"]] == [("-", "const TVA = 0.196"), ("+", "const TVA = 0.20")]
    mail = ea.step_from_tool("email_send", {"to": "hello@exemple.fr", "subject": "Ton devis", "body": "Salut"})
    assert mail["kind"] == "email" and mail["email"]["to"] == "hello@exemple.fr"
    assert ea.step_from_tool("run_command", {"command": "npm test"})["title"] == "Run npm test"


def test_a_task_streams_steps_and_finishes():
    def turn(agent, task, sink):
        sink({"type": "tool.start", "name": "email_send", "args": {"to": "a@b.co", "subject": "Hi", "body": "Yo"}})
        sink({"type": "answer.delta", "text": "Sent the draft."})
        return "Sent the draft."

    job = ea._job({"id": "avatar:halo", "name": "Halo", "kind": "avatar", "color": "#fff"}, "mail Sam", "general")
    ea._run_chat(job, job["agent"], "mail Sam", turn=turn)
    done = ea.job(job["id"])
    assert done["status"] == "done" and done["work"] == "email" and done["result"] == "Sent the draft."
    assert ea.work("avatar:halo")["id"] == job["id"]
    assert any(a["id"] == "avatar:halo" and a["state"] == "finished" for a in ea.agents())


def test_claude_stream_json_lines_become_steps():
    job = ea._job({"id": "claude", "name": "Claude Code", "kind": "claude", "color": "#f00"}, "fix", "code")
    line = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Read", "input": {"file_path": "/x/src/invoice.ts"}}]}})
    assert ea._claude_events(line, job) is None
    assert ea._claude_events(json.dumps({"type": "result", "result": "All done"}), job) == "All done"
    assert job["steps"][-1]["title"] == "Read invoice.ts"


def test_unknown_agent_and_empty_task_are_refused():
    with pytest.raises(ValueError):
        ea.start_task("nobody", "do it")
    with pytest.raises(ValueError):
        ea.start_task("ichos", "  ")


def test_spending_report_is_read_without_a_model(tmp_path, monkeypatch):
    sheet = tmp_path / "spending.csv"
    sheet.write_text("Date,Description,Amount\n1/2,Starbucks,4.50\n1/3,Rent,1500.00\n1/4,Uber,23.10\n"
                     "1/5,Netflix,15.99\n1/6,Grocer,82.40\n", encoding="utf-8")
    fake = types.SimpleNamespace(get_upload=lambda _id: {"path": str(sheet), "name": "spending.csv", "kind": "file"},
                                 kind_for=lambda *_a: "file", extract_document_text=lambda *_a: "")
    monkeypatch.setitem(__import__("sys").modules, "uploads", fake)
    result = ea.read_file("u1")
    assert result["kind"] == "spending" and result["report"]["count"] == 5
    assert result["report"]["total"] == 1625.99 and result["report"]["biggest"][0]["label"] == "Rent"
    assert "Spending report" in result["summary"]


def test_intents_for_email_and_timers():
    assert ea.intent("send it to sam@example.com", has_file=True) == {"action": "email", "to": "sam@example.com",
                                                                      "subject": ""}
    assert ea.intent("email this report")["action"] == "email"
    assert ea.intent("set a timer for 10 minutes")["seconds"] == 600
    assert ea.intent("what's the weather")["action"] == "chat"


def test_voice_from_a_description_picks_gender_accent_and_tone():
    voices = [{"id": "en-GB-RyanNeural", "locale": "en-GB", "gender": "Male", "styles": []},
              {"id": "en-GB-SoniaNeural", "locale": "en-GB", "gender": "Female", "styles": []},
              {"id": "en-US-JennyNeural", "locale": "en-US", "gender": "Female", "styles": ["Friendly"]}]
    picked = ea.voice_from_description("a calm, deep British man", voices)
    assert picked["voice_id"] == "en-GB-RyanNeural" and picked["rate"] == "-12%" and picked["pitch"] == "-8Hz"


def test_avatar_personality_is_kept_only_when_chosen():
    ea.set_avatar(name="Nova", image="up1", personality="Dry wit, very short answers.")
    assert ea.personality_note() == ""
    ea.set_avatar(keep_personality=True)
    assert "Dry wit" in ea.personality_note()
    ea.reset_avatar()
    assert ea.settings()["avatar"]["name"] == "Io" and ea.personality_note() == ""
