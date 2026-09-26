"""Leaving the site and coming back: the nyx_client cookie and per-device state."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

import client_state
from client_state import ClientCookieMiddleware, ClientStateError


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(client_state, "data_path", lambda rel: (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True) or tmp_path / rel)
    return tmp_path


def _run_middleware(headers):
    """Drive the ASGI middleware once; return (scope state, response headers, body chunks)."""
    seen = {}
    sent = []

    async def app(scope, receive, send):
        seen["client"] = scope["state"]["nyx_client"]
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/event-stream")]})
        await send({"type": "http.response.body", "body": b"data: 1\n\n", "more_body": True})
        await send({"type": "http.response.body", "body": b"data: 2\n\n", "more_body": False})

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request"}

    asyncio.run(ClientCookieMiddleware(app)({"type": "http", "headers": headers, "scheme": "http"}, receive, send))
    return seen, dict(sent[0]["headers"]), [m.get("body") for m in sent[1:]]


def test_new_browser_gets_a_long_lived_http_only_cookie():
    seen, headers, bodies = _run_middleware([])
    cookie = headers[b"set-cookie"].decode()
    assert cookie.startswith(f"nyx_client={seen['client']};")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Max-Age=34560000" in cookie
    assert "Secure" not in cookie  # plain-http localhost would never send it back
    assert bodies == [b"data: 1\n\n", b"data: 2\n\n"]  # streamed chunks pass through untouched


def test_returning_browser_keeps_its_id_and_gets_no_new_cookie():
    seen, headers, _ = _run_middleware([(b"cookie", b"theme=dark; nyx_client=abcdefgh12345678")])
    assert seen["client"] == "abcdefgh12345678" and b"set-cookie" not in headers


@pytest.mark.parametrize("bad", [b"nyx_client=../../etc", b"nyx_client=short", b"nyx_client=\"a b\"", b"%%%garbage"])
def test_malformed_or_hostile_cookies_are_replaced(bad):
    seen, headers, _ = _run_middleware([(b"cookie", bad)])
    assert b"set-cookie" in headers and "/" not in seen["client"] and ".." not in seen["client"]


def test_device_state_round_trip_patch_and_forget(store):
    device = "device-aaaaaaaa"
    assert client_state.get_state(device) == {}
    client_state.put_state(device, {"active_tab": "chat", "draft": "hello"})
    assert client_state.patch_state(device, {"draft": None, "scroll": 120}) == {"active_tab": "chat", "scroll": 120}
    client_state.forget(device)
    assert client_state.get_state(device) == {}


def test_signed_in_devices_share_a_baseline_and_the_device_wins(store):
    laptop, phone = "laptop-aaaaaaaa", "phone-bbbbbbbb"
    client_state.put_state(laptop, {"active_tab": "keys", "theme": "dark"}, account="Owner@Example.com")
    assert client_state.get_state(phone, account="owner@example.com") == {"active_tab": "keys", "theme": "dark"}
    client_state.patch_state(phone, {"active_tab": "chat"}, account="owner@example.com")
    assert client_state.get_state(phone, account="owner@example.com")["active_tab"] == "chat"
    assert client_state.get_state(laptop)["active_tab"] == "keys"  # without the account, only the device's own state
    assert not any("example" in p.name for p in (store / "client_state").iterdir())  # account hashed, not in filenames


def test_replacing_state_drops_removed_keys_from_the_shared_baseline_too(store):
    device = "laptop-aaaaaaaa"
    client_state.put_state(device, {"draft": "half-written email", "tab": "chat"}, account="me@x.com")
    client_state.put_state(device, {"tab": "chat"}, account="me@x.com")
    assert client_state.get_state(device, account="me@x.com") == {"tab": "chat"}  # the cleared draft stays cleared


def test_forgetting_one_device_keeps_the_account_baseline(store):
    client_state.put_state("laptop-aaaaaaaa", {"tab": "keys"}, account="me@x.com")
    client_state.forget("laptop-aaaaaaaa")
    assert client_state.get_state("phone-bbbbbbbb", account="me@x.com") == {"tab": "keys"}


def test_limits_and_validation(store):
    with pytest.raises(ClientStateError):
        client_state.get_state("../escape")
    with pytest.raises(ClientStateError):
        client_state.put_state("device-aaaaaaaa", ["not", "an", "object"])  # type: ignore[arg-type]
    with pytest.raises(ClientStateError, match="KB cap"):
        client_state.put_state("device-aaaaaaaa", {"blob": "x" * (300 * 1024)})


def test_state_survives_over_http_with_the_cookie(store):
    import server

    browser = TestClient(server.app, client=("127.0.0.1", 50051))
    first = browser.put("/api/client/state", json={"state": {"active_tab": "dashboard", "draft": "hi"}})
    assert first.status_code == 200 and "nyx_client" in browser.cookies
    assert browser.patch("/api/client/state", json={"patch": {"draft": None}}).json()["state"] == {"active_tab": "dashboard"}
    assert browser.get("/api/client/state").json() == {"state": {"active_tab": "dashboard"}}
    other = TestClient(server.app, client=("127.0.0.1", 50052))
    assert other.get("/api/client/state").json() == {"state": {}}  # a different browser has its own state
    assert browser.delete("/api/client/state").json() == {"ok": True}
    assert browser.get("/api/client/state").json() == {"state": {}}
