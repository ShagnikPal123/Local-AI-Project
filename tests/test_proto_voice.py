"""Proto Voice: what it acts on, what it asks about, and what it refuses.

Nothing here touches the real computer: `machine_tools` is replaced with a
recorder, and `tts` is silenced.
"""

from __future__ import annotations

import time
import types

import pytest

import proto_voice


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(proto_voice, "_path", lambda: tmp_path / "proto_voice.json")
    monkeypatch.setattr(proto_voice, "_settings", None, raising=False)
    monkeypatch.setattr(proto_voice, "_say", lambda text: None)
    monkeypatch.setattr(proto_voice, "_publish", lambda event, **payload: None)
    proto_voice.update_settings(allowed=True, standby=False)
    proto_voice._pending.clear()
    yield
    proto_voice._settings = None
    proto_voice._pending.clear()


@pytest.fixture
def machine(monkeypatch):
    """A stand-in for machine_tools that records instead of doing."""
    calls = []

    def record(name):
        def call(*args, **kwargs):
            calls.append((name, args, kwargs))
            return f"{name} ok"
        return call

    fake = types.SimpleNamespace(
        open_app=record("open_app"), open_path=record("open_path"), open_url=record("open_url"),
        kill_process=record("kill_process"), lock_screen=record("lock_screen"),
        system_power=record("system_power"), set_volume=record("set_volume"), media_key=record("media_key"),
    )
    monkeypatch.setattr(proto_voice, "_machine", lambda: fake)
    fake.calls = calls
    return fake


def test_opening_an_app_happens_at_once(machine):
    result = proto_voice.handle("open notepad")
    assert result["done"] is True and result["needs_confirm"] is False
    assert machine.calls[0][0] == "open_app"
    assert machine.calls[0][1][0] == "notepad"


def test_open_files_means_the_file_manager(machine):
    proto_voice.handle("open files")
    assert machine.calls[0][0] == "open_path"


def test_a_folder_by_name_opens_that_folder(machine):
    proto_voice.handle("open my downloads")
    assert machine.calls[0][0] == "open_path"
    assert "Downloads" in machine.calls[0][1][0]


def test_a_known_site_opens_as_a_url_not_an_app(machine):
    proto_voice.handle("open youtube")
    assert machine.calls[0][0] == "open_url"
    assert machine.calls[0][1][0].startswith("https://")


def test_a_nyx_tab_is_opened_through_an_event(monkeypatch):
    seen = {}
    monkeypatch.setattr(proto_voice, "_publish", lambda event, **payload: seen.setdefault(event, payload))
    result = proto_voice.handle("open the finance tab", tabs=[{"id": "trading", "label": "Finance"}])
    assert result["kind"] == "open_tab"
    assert seen.get("ui.open_tab", {}).get("tab_id") == "trading"


def test_shutting_down_asks_first_and_then_does_it(machine):
    asked = proto_voice.handle("shut down the computer", session_id="s")
    assert asked["needs_confirm"] is True and asked["done"] is False
    assert not machine.calls                       # nothing happened yet
    done = proto_voice.handle("yes", session_id="s")
    assert done["done"] is True
    assert machine.calls[0][0] == "system_power"
    assert machine.calls[0][1][0] == "shutdown"


def test_saying_no_leaves_it_alone(machine):
    proto_voice.handle("restart the computer", session_id="s")
    result = proto_voice.handle("no, don't", session_id="s")
    assert result["kind"] == "cancelled"
    assert not machine.calls


def test_a_confirmation_expires(machine):
    proto_voice.handle("shut down the computer", session_id="s")
    proto_voice._pending["s"].at = time.time() - proto_voice.CONFIRM_SECONDS - 1
    # "yes" is no longer an answer to anything, so it is just words for the chat.
    result = proto_voice.handle("yes", session_id="s")
    assert result["to_chat"] is True
    assert not machine.calls


def test_the_button_can_confirm_instead_of_the_voice(machine):
    asked = proto_voice.handle("put the computer to sleep", session_id="s")
    result = proto_voice.confirm(asked["token"], session_id="s")
    assert result["done"] is True
    assert machine.calls[0][1][0] == "sleep"


def test_a_password_is_always_refused(machine):
    result = proto_voice.handle("unlock the computer, my password is hunter2")
    assert result["done"] is False
    assert "secure desktop" in result["said"] or "Windows Hello" in result["said"]
    assert not machine.calls


def test_it_says_why_it_cannot_switch_the_pc_on(machine):
    result = proto_voice.handle("turn the computer on")
    assert "off" in result["said"].lower()
    assert not machine.calls


def test_sending_mail_is_left_as_a_draft(machine):
    result = proto_voice.handle("send an email to Ana saying I'll be late")
    assert result["done"] is False and "draft" in result["said"].lower()


def test_plain_speech_goes_to_the_chat(machine):
    result = proto_voice.handle("what do you think about the new plan")
    assert result["to_chat"] is True
    assert not machine.calls


def test_standby_ignores_everything_until_its_name(machine):
    proto_voice.update_settings(standby=True)
    quiet = proto_voice.handle("open notepad")
    assert quiet["kind"] == "standby" and not machine.calls
    woken = proto_voice.handle("nyx, open notepad")
    assert woken["done"] is True
    assert proto_voice.settings()["standby"] is False


def test_going_quiet_is_asked_for_in_words(machine):
    result = proto_voice.handle("go to sleep")
    assert result["kind"] == "standby"
    assert proto_voice.settings()["standby"] is True


def test_nothing_acts_until_the_owner_allows_it(machine):
    proto_voice.update_settings(allowed=False)
    result = proto_voice.handle("open notepad")
    assert result["kind"] == "not_allowed"
    assert not machine.calls


def test_a_simulation_changes_nothing(machine):
    result = proto_voice.handle("simulate shutting down the computer")
    assert not machine.calls
    assert "would" in result["said"].lower()


def test_the_plan_says_what_it_would_do():
    plan = proto_voice.describe_plan("open notepad")
    assert "notepad" in plan and "Nothing has happened" in plan


def test_wake_words_are_stripped():
    assert proto_voice.strip_wake("Nyx, open notepad") == ("open notepad", True)
    assert proto_voice.strip_wake("open notepad") == ("open notepad", False)
