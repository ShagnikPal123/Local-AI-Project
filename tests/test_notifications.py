"""Notifications: which notices fire, where they go, and that none can flood the owner or break a turn.

Delivery is replaced by recorders, so nothing shows a toast, a Windows notification or sends a text.
"""

from __future__ import annotations

import pytest

import notifications as n


@pytest.fixture
def rec(monkeypatch):
    """Record deliveries instead of making them, and start from a clean slate."""
    sent = {"toast": [], "desktop": [], "phone": []}
    monkeypatch.setattr(n, "_deliver_toast", lambda kind, title, text, level, chat_id: sent["toast"].append(
        {"kind": kind, "title": title, "text": text, "level": level, "chat_id": chat_id}))
    monkeypatch.setattr(n, "_deliver_desktop", lambda title, text: sent["desktop"].append((title, text)))
    monkeypatch.setattr(n, "_deliver_phone", lambda text, origin: sent["phone"].append((text, origin)) or True)
    monkeypatch.setattr(n, "_chat_linked_to_phone", lambda chat_id: chat_id == "linked")
    monkeypatch.setattr(n, "chat_title", lambda chat_id: {"c1": "Trip to Lisbon", "linked": "Taxes"}.get(chat_id, "A chat"))
    monkeypatch.setattr(n, "_announce", lambda: None)
    n._recent_keys.clear()
    n._phone_times.clear()
    import presence

    presence.reset()
    return sent


def test_the_defaults_are_a_bottom_right_box_and_no_texts():
    current = n.settings()
    assert current["position"] == "bottom-right" and current["phone"] == "off" and current["away"] == "auto"
    assert all(current["kinds"].values()) and current["channels"] == {"toast": True, "desktop": False}


def test_a_corner_can_be_chosen_and_nonsense_is_refused():
    for corner in ("top-left", "top-center", "top-right", "bottom-right"):
        assert n.update({"position": corner})["position"] == corner and n.settings()["position"] == corner
    with pytest.raises(ValueError):
        n.update({"position": "middle-of-the-screen"})
    with pytest.raises(ValueError):
        n.update({"phone": "sometimes"})
    with pytest.raises(ValueError):
        n.update({"kinds": {"gossip": True}})
    assert n.settings()["position"] == "bottom-right"                     # the refused value changed nothing


def test_numbers_are_clamped_and_settings_survive_a_corrupt_file(tmp_path):
    assert n.update({"min_seconds": 99999})["min_seconds"] == 3600 and n.update({"away_minutes": 0})["away_minutes"] == 1
    n._path().write_text("{ not json", encoding="utf-8")
    assert n.settings()["position"] == "bottom-right"


def test_a_notice_goes_to_the_box_with_its_chat(rec):
    result = n.notify("done", "Done. The plan is ready.", chat_id="c1")
    assert result == {"sent": ["toast"]}
    assert rec["toast"] == [{"kind": "done", "title": "Trip to Lisbon", "text": "Done. The plan is ready.", "level": "ok",
                             "chat_id": "c1"}]
    assert rec["phone"] == [] and rec["desktop"] == []
    assert n.recent()[0]["title"] == "Trip to Lisbon"


def test_each_kind_and_channel_can_be_switched_off(rec):
    n.update({"kinds": {"done": False}})
    assert n.notify("done", "x", chat_id="c1") == {"sent": [], "skipped": "switched off"}
    n.update({"channels": {"toast": False, "desktop": True}})
    assert n.notify("help", "Needs you: approve a file write", now=2000.0)["sent"] == ["desktop"]
    assert rec["toast"] == [] and rec["desktop"] == [("Nyx", "Needs you: approve a file write")]


def test_the_same_notice_twice_in_a_moment_is_one_notice(rec):
    assert n.notify("done", "Done.", chat_id="c1", now=1000.0)["sent"] == ["toast"]
    assert n.notify("done", "Done.", chat_id="c1", now=1001.0) == {"sent": [], "skipped": "just sent"}
    assert n.notify("done", "Done.", chat_id="c1", now=1010.0)["sent"] == ["toast"]
    assert n.notify("done", "", chat_id="c1")["skipped"] == "empty"
    with pytest.raises(ValueError):
        n.notify("gossip", "x")


def test_the_phone_is_texted_only_when_the_owner_said_so(rec):
    n.notify("done", "Done one.", chat_id="c1", now=1000.0)
    assert rec["phone"] == []                                          # off by default
    n.update({"phone": "always"})
    n.notify("done", "Done two.", chat_id="c1", now=100.0)
    assert rec["phone"] == [("Trip to Lisbon: Done two.", "notice:done")]


def test_away_mode_texts_only_when_the_owner_is_gone(rec):
    import presence

    n.update({"phone": "away", "away_minutes": 10})
    presence.mark_active("chat", now=1_000_000.0)
    n.notify("done", "Done while at the PC.", chat_id="c1", now=1_000_060.0)
    assert rec["phone"] == [] and n.is_away(now=1_000_060.0) is False
    n.notify("done", "Done while gone.", chat_id="c1", now=1_000_000.0 + 11 * 60)
    assert len(rec["phone"]) == 1 and n.is_away(now=1_000_000.0 + 11 * 60) is True


def test_marking_yourself_gone_texts_even_with_the_setting_off(rec):
    n.set_away("on")
    assert n.is_away() is True
    n.notify("help", "Needs you: approve a file write", now=1005.0)
    assert len(rec["phone"]) == 1
    n.set_away("off")
    assert n.is_away() is False
    n.notify("help", "Needs you: approve something else", now=1500.0)
    assert len(rec["phone"]) == 1


def test_a_chat_the_owner_connected_to_whatsapp_always_reaches_the_phone(rec):
    n.notify("done", "Done.", chat_id="linked", now=1000.0)
    assert len(rec["phone"]) == 1 and rec["phone"][0][0].startswith("Taxes:")


def test_urgent_never_overrides_off_and_nothing_floods_the_phone(rec):
    assert n.notify("message", "Server is on fire", title="Nyx", urgent=True, now=1000.0)["sent"] == ["toast"]
    assert rec["phone"] == []                                          # "off" means off, even for the AI's urgent flag
    n.update({"phone": "always"})
    for index in range(20):
        n.notify("message", f"Update number {index}", title="Nyx", now=100.0 + index * 5)
    assert len(rec["phone"]) == n.PHONE_PER_HOUR


def test_a_long_turn_is_done_a_short_one_is_not_worth_a_ping(rec):
    assert n.turn_finished("c1", "done", "Short answer.", seconds=3)["skipped"] == "short turn"
    result = n.turn_finished("c1", "done", "Here is the full plan for the week.\nStep 1", seconds=40)
    assert result["sent"] == ["toast"] and rec["toast"][0]["text"] == "Done. Here is the full plan for the week. Step 1"
    assert n.turn_finished("c1", "stopped", "", seconds=99)["skipped"] == "stopped by the owner"


def test_a_question_or_an_error_means_the_chat_needs_you_however_short(rec):
    card = 'Which one?\n```question\n{"question": "Pick", "options": ["a", "b"]}\n```'
    assert n.turn_finished("c1", "done", card, seconds=1)["sent"] == ["toast"]
    assert rec["toast"][-1]["kind"] == "help" and "question" in rec["toast"][-1]["text"]
    n.turn_finished("c1", "error", "", seconds=1)
    assert rec["toast"][-1]["kind"] == "help" and "error" in rec["toast"][-1]["text"] and rec["toast"][-1]["level"] == "warn"


def test_an_approval_and_a_scheduled_task_each_make_a_notice(rec):
    assert n.help_needed("Nyx wants to write a file")["sent"] == ["toast"]
    assert rec["toast"][-1]["text"] == "Needs you: Nyx wants to write a file"
    n.task_ran("Morning digest", True, "Sent three items.")
    assert rec["toast"][-1]["kind"] == "schedule" and "Morning digest ran. Sent three items." == rec["toast"][-1]["text"]
    n.task_ran("Weekly report", False, "avatar busy")
    assert rec["toast"][-1]["kind"] == "help" and "did not work" in rec["toast"][-1]["text"]


def test_a_failing_channel_never_breaks_the_caller(monkeypatch):
    n._recent_keys.clear()
    monkeypatch.setattr(n, "_announce", lambda: None)
    monkeypatch.setattr(n, "chat_title", lambda chat_id: "A chat")
    monkeypatch.setattr(n, "_deliver_toast", lambda *a: (_ for _ in ()).throw(RuntimeError("no window")))
    assert n.turn_finished("c1", "done", "x", seconds=60) == {"sent": [], "skipped": "error"}
    assert n.help_needed("anything") == {"sent": [], "skipped": "error"}


def test_the_notify_tool_tells_the_model_where_it_went(rec):
    assert "toast" in n.tool_notify_owner("The build finished", title="Build")
    n.update({"channels": {"toast": False}})
    assert "nowhere" in n.tool_notify_owner("Another thing", title="Build")
    assert n.tool_notify_owner("Another thing", title="Build").startswith("Nothing shown (just sent)")


def test_the_routes_read_and_change_the_settings(rec, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import routes_notifications as routes
    import server_auth

    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes._owner] = lambda: object()
    app.dependency_overrides[server_auth.require_session] = lambda: object()
    client = TestClient(app)
    view = client.get("/api/notifications").json()
    assert view["settings"]["position"] == "bottom-right" and "top-left" in view["positions"] and view["recent"] == []
    changed = client.post("/api/notifications/settings", json={"position": "top-left", "phone": "away",
                                                               "kinds": {"schedule": False}}).json()
    assert changed["settings"]["position"] == "top-left" and changed["settings"]["kinds"]["schedule"] is False
    assert client.post("/api/notifications/settings", json={"position": "nowhere"}).status_code == 400
    client.post("/api/notifications/settings", json={"phone": "off"})
    assert client.post("/api/notifications/test", json={"kind": "done"}).json()["sent"] == ["toast"]
    assert client.post("/api/notifications/test", json={"kind": "gossip"}).status_code == 400
    assert client.get("/api/notifications").json()["recent"][0]["source"] == "test"


def test_away_and_back_from_the_phone_flip_the_switch(tmp_path, monkeypatch):
    from tests.test_whatsapp_link import FakeAvatars, FakeChats, FakeTransport, _pair
    import whatsapp_link as wa

    monkeypatch.setattr(wa, "data_path", lambda name: tmp_path / name)
    monkeypatch.setattr(wa, "sdk_installed", lambda: True)
    monkeypatch.setattr(wa, "device_fingerprint", lambda: "pc-a")
    monkeypatch.setattr(wa, "pc_name", lambda: "DESKTOP-A")
    monkeypatch.setattr(n, "_announce", lambda: None)
    link = wa.WhatsAppLink(transport=FakeTransport(), turn=lambda text, lane=None: "ok",
                           state_path=tmp_path / "whatsapp" / "link.json", chats=FakeChats(), avatars=FakeAvatars())
    _pair(link)
    link.handle_incoming("/away")
    assert n.settings()["away"] == "on" and "text you here" in link.transport.sent()[-1]
    link.handle_incoming("/back")
    assert n.settings()["away"] == "auto" and "Welcome back" in link.transport.sent()[-1]
