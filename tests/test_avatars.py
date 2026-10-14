"""Avatars: defaults ship off, edits sit beside the defaults, the guard denies by default, and the clock runs only
what is due."""

from datetime import datetime

import pytest


@pytest.fixture()
def av(tmp_path, monkeypatch):
    import avatars as module

    monkeypatch.setattr(module, "_path", lambda: tmp_path / "avatars.json")
    monkeypatch.setattr(module, "_publish", lambda avatar_id: None)
    monkeypatch.setattr(module, "_alert", lambda *a, **k: alerts.append(a))
    alerts = []
    module.test_alerts = alerts
    turns = []

    def turn(avatar, text):
        turns.append((avatar["id"], text))
        if text.startswith("[Watch]"):
            return "ALERT: it will rain at 3pm"
        return f"{avatar['name']} did it"

    monkeypatch.setattr(module, "_TURN", turn)
    module.test_turns = turns
    return module


def test_seven_defaults_ship_switched_off_with_new_names(av):
    names = [a["name"] for a in av.list_avatars()]
    assert names == ["Orbit", "Halo", "Quasar", "Vector", "Parallax", "Lemma", "Perigee"]
    assert not any(a["enabled"] for a in av.list_avatars())
    assert av.get("vector")["model"] == "local"
    assert set(av.get("vector")["functions"].values()) == {"allow", "ask"}


def test_an_edit_is_kept_beside_the_default_and_reset_drops_it(av):
    av.update("orbit", {"enabled": True, "does": "Ship the website", "schedule": {"mode": "all_year"}})
    edited = av.get("orbit")
    assert edited["enabled"] and edited["does"] == "Ship the website" and edited["edited"]
    assert edited["schedule"]["mode"] == "all_year"
    back = av.reset("orbit")
    assert not back["enabled"] and back["does"].startswith("Give me a goal")


def test_bad_values_are_dropped_not_stored(av):
    made = av.create({"name": "  Nova  ", "main": "rocket", "schedule": {"mode": "forever", "every_minutes": 1,
                                                                          "start": "25:00"},
                      "functions": {"web": "allow", "teleport": "allow", "money": "allow"}, "icon": "<script>"})
    assert made["name"] == "Nova" and made["main"] == "custom"
    assert made["schedule"]["mode"] == "on_call" and made["schedule"]["every_minutes"] == 15
    assert made["schedule"]["start"] == "08:00"
    assert made["functions"] == {"talk": "allow", "web": "allow", "money": "ask"}  # money always asks
    assert made["icon"] == "ph-user-circle"
    with pytest.raises(av.AvatarError):
        av.create({"name": "   "})


def test_copy_from_a_template_and_delete(av):
    copy = av.create({"name": "Orbit Two"}, template="orbit")
    assert copy["functions"] == av.get("orbit")["functions"] and not copy["builtin"]
    assert av.delete(copy["id"]) and av.get(copy["id"]) is None
    assert av.delete("lemma") and "lemma" not in [a["id"] for a in av.list_avatars()]
    av.restore_defaults()
    assert av.get("lemma") is not None


def test_the_guard_denies_what_is_not_switched_on(av, monkeypatch):
    from permissions import PermissionDenied
    import permissions

    asked = []
    monkeypatch.setattr(permissions, "ask", lambda category, summary, detail="": asked.append(category))
    guard = av.AvatarGuard(av.get("parallax"))  # web + send(ask)
    guard("search_web", "web")
    guard("avatar_note", "agents")
    guard("ui_notify", "ui")
    guard("whatsapp_send", "whatsapp")
    assert asked == ["whatsapp"]
    for name, category in [("read_file", "files.read"), ("delete_path", "files.delete"), ("system_power", "system"),
                           ("ui_set_theme", "ui"), ("avatar_create", "agents"), ("avatar_ask", "agents"),
                           ("run_command", "shell")]:
        with pytest.raises(PermissionDenied):
            guard(name, category)
    guard = av.AvatarGuard(av.get("quasar"))  # has Team up
    guard("avatar_ask", "agents")
    guard("delegate_task", "agents")


def test_talking_logs_activity_and_counts_runs(av):
    result = av.run("lemma", "Explain entropy")
    assert result["ok"] and result["reply"] == "Lemma did it"
    seen = av.get("lemma")
    assert seen["runs_today"] == 1 and seen["activity"][0]["input"] == "Explain entropy"


def test_a_watch_alerts_only_on_news(av):
    av.add_item("parallax", "watches", {"what": "Rain in Austin", "every_minutes": 30, "phone": True})
    watch = av.get("parallax")["watches"][0]
    result = av.run_watch("parallax", watch["id"])
    assert result["alert"] and av.test_alerts
    assert av.get("parallax")["watches"][0]["last"].startswith("ALERT")


def test_the_clock_runs_only_what_is_due(av):
    now = datetime(2026, 10, 12, 10, 0)  # a Monday, 10:00
    assert av.tick(now) == []  # all off
    av.update("perigee", {"enabled": True})  # all day 08–20, every 60
    av.update("lemma", {"enabled": True})  # on call: no check-ins
    av.add_item("quasar", "lessons", {"name": "Weekly report", "steps": ["Collect", "Write"], "repeat": "weekly"})
    av.update("quasar", {"enabled": True, "schedule": {"mode": "on_call"}})
    done = av.tick(now)
    kinds = sorted((d["id"], d["kind"]) for d in done)
    assert kinds == [("perigee", "check-in"), ("quasar", "lesson")]
    assert av.tick(now) == []  # nothing due again straight away
    assert av.due_work(av.get("perigee"), datetime(2026, 10, 12, 22, 0), {}) == []  # after hours


def test_the_daily_cap_stops_the_clock(av):
    av.update("orbit", {"enabled": True, "max_runs_per_day": 1, "schedule": {"mode": "all_year", "every_minutes": 15}})
    rt = {"day": "2026-10-12", "runs_today": 1}
    assert av.due_work(av.get("orbit"), datetime(2026, 10, 12, 10, 0), rt) == []


def test_a_team_leads_hands_off_and_wraps_up(av):
    result = av.team(["Quasar", "Lemma", "@orbit"], "Plan a study week")
    assert result["lead"] == "Quasar" and len(result["turns"]) == 4
    assert [t[0] for t in av.test_turns] == ["quasar", "lemma", "orbit", "quasar"]
    with pytest.raises(av.AvatarError):
        av.team(["Quasar", "Nobody"], "x")


def test_chat_tools(av):
    assert "@Orbit" in av.tool_avatar_list()
    assert av.tool_avatar_ask("@halo", "Remind me").startswith("Halo answered")
    assert av.tool_avatar_ask("Teleport", "hi").startswith("Error")
    made = av.tool_avatar_create("Comet", "Track my runs", main_function="life", schedule="all_day", functions="web, files")
    assert "Comet" in made and av.find("comet")["functions"] == {"talk": "allow", "web": "allow", "files": "allow"}
    assert "Parallax" in av.tool_avatar_watch("BTC above 100k", 15)
    assert "Quasar" in av.tool_avatar_teach("Inbox zero", "Open mail\nArchive newsletters", "daily")
    av.tool_avatar_goal("Learn Rust", "Read the book; Build a CLI", avatar="Lemma")
    assert "Recorded" in av.tool_avatar_progress("rust", "Chapter 3", step_done="read the book", avatar="Lemma")
    goal = av.get("lemma")["goals"][0]
    assert goal["steps"][0]["done"] and goal["progress"] == "Chapter 3"
    assert "Learn Rust" in av.note_for(av.get("lemma"))


def test_every_avatar_has_a_personality_even_old_records(av):
    assert av.get("lemma")["personality"] == "homework_helper"
    made = av.create({"name": "Pulsar"})
    assert made["personality"] == av.FALLBACK_PERSONALITY
    custom = av.update(made["id"], {"personality": "custom", "personality_custom": "Dry wit, short sentences."})
    assert "Dry wit" in av.note_for(custom)
    cleared = av.update(made["id"], {"personality": "custom", "personality_custom": ""})
    assert cleared["personality"] == av.FALLBACK_PERSONALITY
    assert av.clean({"id": "halo", "name": "Halo"})["personality"] == "close_friend"  # stored before personalities


def test_long_text_keeps_its_line_breaks_so_save_can_settle(av):
    """The editor compares what the box holds with what came back; flattened lines left Save lit forever."""
    text = "First do this.\n\nThen   that.\n\n\n\nLast."
    saved = av.update("orbit", {"does": text})
    assert saved["does"] == "First do this.\n\nThen that.\n\nLast."
    assert av.update("orbit", {"does": saved["does"]})["does"] == saved["does"]  # a second save changes nothing
    custom = av.update("orbit", {"personality": "custom", "personality_custom": "calm\ndry humour"})
    assert custom["personality_custom"] == "calm\ndry humour"
