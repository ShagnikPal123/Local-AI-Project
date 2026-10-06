"""Nyx's own computer (Update 1, U49): it works on a sandbox of its own, and the owner's screen stays theirs.

The owner: "it will basically have its own computer setup so when I don't want it to use my screen it works on this
one and won't interrupt me unless I say it can or it asks." The sandbox itself (Cua, in Docker or Cua Cloud) is
faked here; what is under test is the promise around it — where Nyx may work, that it asks, that a yes runs out,
and that every action really goes to its own computer.
"""

from __future__ import annotations

import base64

import pytest

import computer_control
import own_computer
import permissions
from permissions import PermissionDenied


class FakeTransport:
    def __init__(self) -> None:
        self.calls = []
        self.closed = False

    def request(self, op, timeout=0, **args):
        self.calls.append((op, args))
        if op == "screenshot":
            return base64.b64encode(b"\x89PNG fake").decode()
        if op == "screen_size":
            return {"width": 1280, "height": 800}
        if op == "shell":
            return {"stdout": "Linux nyx 6.1", "stderr": "", "returncode": 0}
        return True

    def close(self):
        self.closed = True


@pytest.fixture
def computer(monkeypatch):
    fake = FakeTransport()
    box = own_computer.OwnComputer(transport=fake)
    monkeypatch.setattr(own_computer, "COMPUTER", box)
    monkeypatch.setattr(own_computer, "readiness", lambda: {"ready": True, "next": ""})
    monkeypatch.setattr(own_computer, "_grant_until", 0.0)
    return box, fake


def test_its_own_computer_starts_on_first_use_and_every_action_goes_there(computer):
    box, fake = computer
    assert box.state == "off"
    assert "Clicked left at 10,20" in box.click(10, 20)
    assert box.state == "on" and fake.calls[0][0] == "start", "the first action starts the set-up computer"
    box.type_text("hello")
    box.keys("ctrl+l")
    box.scroll(-3)
    box.open("https://example.com")
    assert box.screenshot() == b"\x89PNG fake" and box.screen_size()["width"] == 1280
    assert "Linux nyx" in box.shell("uname -a")
    ops = [op for op, _ in fake.calls]
    assert ops == ["start", "click", "type", "keys", "scroll", "open", "screenshot", "screen_size", "shell"]
    assert dict(fake.calls[3][1])["keys"] == ["ctrl", "l"]
    assert [a["kind"] for a in box.view()["actions"]][-3:] == ["scroll", "open", "shell"]

    box.stop()
    assert box.state == "off" and fake.closed


def test_a_computer_that_is_not_set_up_says_what_to_do_next(monkeypatch):
    box = own_computer.OwnComputer(transport=FakeTransport())
    monkeypatch.setattr(own_computer, "readiness",
                        lambda: {"ready": False, "next": "Install Docker Desktop, then press Check again."})
    with pytest.raises(own_computer.OwnComputerError, match="Install Docker Desktop"):
        box.click(1, 1)
    assert box.state == "off"


def test_readiness_names_the_one_missing_piece(monkeypatch):
    monkeypatch.setattr(own_computer, "sdk_installed", lambda: True)
    monkeypatch.setattr(own_computer, "docker_state", lambda: "missing")
    assert "Docker Desktop" in own_computer.readiness()["next"]
    monkeypatch.setattr(own_computer, "docker_state", lambda: "stopped")
    assert "Open Docker Desktop" in own_computer.readiness()["next"]
    monkeypatch.setattr(own_computer, "docker_state", lambda: "ready")
    assert own_computer.readiness()["ready"] is True

    own_computer.save(provider="cloud")
    monkeypatch.setattr(own_computer, "cloud_key", lambda: "")
    assert "Cua Cloud API key" in own_computer.readiness()["next"]
    monkeypatch.setattr(own_computer, "cloud_key", lambda: "k")
    assert "name of the sandbox" in own_computer.readiness()["next"]
    own_computer.save(cloud_name="nyx-box")
    assert own_computer.readiness()["ready"] is True
    with pytest.raises(own_computer.OwnComputerError):
        own_computer.save(my_screen="sometimes")


def test_never_keeps_nyx_off_the_owners_screen(computer, monkeypatch):
    own_computer.save(my_screen="never")
    with pytest.raises(PermissionDenied, match="own computer"):
        own_computer.host_gate("mouse click")

    clicked = []
    monkeypatch.setattr(computer_control, "click", lambda *a, **k: clicked.append(a) or (1, 1))
    reply = computer_control._owner_screen("mouse_click", computer_control.tool_mouse_click)(x=5, y=5)
    assert reply.startswith("Not on the owner's screen") and not clicked, "the real mouse was never touched"


def test_ask_first_shows_an_approval_and_a_yes_lasts_for_a_while(computer, monkeypatch):
    own_computer.save(my_screen="ask", grant_minutes=10)
    asked = []
    monkeypatch.setattr(permissions, "ask", lambda category, summary, detail="": asked.append(summary))
    own_computer.host_gate("mouse click")
    own_computer.host_gate("keyboard type")
    assert asked == ["Use your screen: mouse click"], "one yes covers the next minutes, not one click"
    assert own_computer.status()["grant"]["active"] is True

    own_computer.revoke_grant()

    def say_no(category, summary, detail=""):
        raise PermissionDenied("The user declined this action")

    monkeypatch.setattr(permissions, "ask", say_no)
    with pytest.raises(PermissionDenied):
        own_computer.host_gate("mouse click")


def test_allow_works_on_the_owners_screen_without_asking(computer, monkeypatch):
    own_computer.save(my_screen="allow")
    monkeypatch.setattr(permissions, "ask", lambda *a, **k: pytest.fail("allow never asks"))
    own_computer.host_gate("screen view")


def test_the_tools_say_where_they_act_and_report_failures_as_text(computer, monkeypatch):
    box, fake = computer

    class Registry:
        def __init__(self):
            self.tools = {}

        def register(self, name, description, params, handler, category="general", label=None):
            self.tools[name] = (description, handler, category)

    registry = Registry()
    own_computer.register_own_computer_tools(registry)
    assert set(registry.tools) == {"own_computer_view", "own_computer_click", "own_computer_type", "own_computer_keys",
                                   "own_computer_scroll", "own_computer_open", "own_computer_shell"}
    assert all("not the owner's screen" in d and c == "own_computer" for d, _, c in registry.tools.values())
    assert "own_computer" in permissions.CATEGORIES

    assert "on Nyx's computer" in registry.tools["own_computer_click"][1](x=3, y=4)
    monkeypatch.setattr(own_computer, "readiness", lambda: {"ready": False, "next": "Install Docker Desktop."})
    box.state = "off"
    assert registry.tools["own_computer_type"][1](text="hi").startswith("Error: Nyx's own computer is not set up yet")


def test_the_cloud_key_is_stored_as_a_secret_and_never_shown(monkeypatch):
    saved = {}
    import secret_store

    monkeypatch.setattr(secret_store, "set_keys", lambda name, keys: saved.__setitem__(name, list(keys)) or list(keys))
    monkeypatch.setattr(secret_store, "get_keys", lambda name: saved.get(name, []))
    view = own_computer.set_cloud_key("sk-cua-123456")
    assert saved == {"cua": ["sk-cua-123456"]}
    assert view["cloud_key"] is True and "sk-cua" not in str(view)
