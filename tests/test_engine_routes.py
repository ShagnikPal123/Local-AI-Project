"""Engine control over HTTP: status, stop, restart, start-with-Windows.

These are owner actions on the owner's machine. Unclaimed, only a caller on this
computer may use them; claimed, only an admin session may — an invited tester
must not be able to switch the owner's engine off.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import launcher
import server
import server_auth
from auth import AuthStore

OWNER = "owner@example.com"
PASSWORD = "a-long-enough-passphrase"


@pytest.fixture
def store(tmp_path, monkeypatch):
    fresh = AuthStore(tmp_path / "auth.json")
    monkeypatch.setattr(server_auth, "AUTH_STORE", fresh)
    monkeypatch.setattr(server, "AUTH_STORE", fresh)
    return fresh


@pytest.fixture
def hooks(monkeypatch):
    calls = SimpleNamespace(stopped=0, restarted=0, autostart=[])
    monkeypatch.setattr(server, "ENGINE_HOOKS", {
        "stop": lambda: setattr(calls, "stopped", calls.stopped + 1),
        "restart": lambda: setattr(calls, "restarted", calls.restarted + 1),
        "port": 8000,
        "pid": 1234,
        "launcher": True,
    })
    # Run the deferred action immediately instead of on a timer thread.
    monkeypatch.setattr(server, "_later", lambda action, delay=0.4: action())
    monkeypatch.setattr(launcher, "autostart_enabled", lambda: bool(calls.autostart and calls.autostart[-1]))
    monkeypatch.setattr(launcher, "set_autostart", lambda on: calls.autostart.append(on) or on)
    monkeypatch.setattr(launcher, "url_handler_registered", lambda: True)
    return calls


@pytest.fixture
def local(store):
    return TestClient(server.app, client=("127.0.0.1", 50123))


@pytest.fixture
def remote(store):
    return TestClient(server.app, client=("203.0.113.9", 50123))


def test_status_says_whether_one_click_start_is_wired_up(local, hooks):
    body = local.get("/api/engine").json()
    assert body["managed"] is True
    assert body["port"] == 8000
    assert body["link_registered"] is True
    assert "autostart" in body


def test_stop_and_restart_reach_the_launcher(local, hooks):
    assert local.post("/api/engine/restart").status_code == 200
    assert local.post("/api/engine/stop").status_code == 200
    assert hooks.restarted == 1 and hooks.stopped == 1


def test_autostart_can_be_switched_from_the_app(local, hooks):
    response = local.post("/api/engine/autostart", json={"enabled": True})
    assert response.status_code == 200
    assert hooks.autostart == [True]
    assert response.json()["autostart"] is True


def test_an_engine_started_by_hand_says_so_instead_of_pretending(local, monkeypatch, store):
    monkeypatch.setattr(server, "ENGINE_HOOKS", {})
    response = local.post("/api/engine/stop")
    assert response.status_code == 409
    assert "by hand" in response.json()["detail"]


def test_another_computer_cannot_control_an_unclaimed_engine(remote, hooks):
    assert remote.post("/api/engine/stop").status_code == 403
    assert remote.post("/api/engine/autostart", json={"enabled": False}).status_code == 403
    assert hooks.stopped == 0 and hooks.autostart == []


def test_once_claimed_engine_control_needs_a_signed_in_admin(local, hooks, store):
    store.bootstrap_owner(OWNER)
    store.set_password(OWNER, PASSWORD)

    assert local.post("/api/engine/stop").status_code == 401

    token = local.post("/api/auth/login", json={"email": OWNER, "password": PASSWORD}).json()["token"]
    ok = local.post("/api/engine/stop", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200
    assert hooks.stopped == 1


def test_the_status_route_requires_a_session_once_claimed(local, hooks, store):
    store.bootstrap_owner(OWNER)
    assert local.get("/api/engine").status_code == 401
