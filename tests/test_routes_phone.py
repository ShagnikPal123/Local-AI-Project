"""Owner routes for the phone connection: the switch, the one-minute key, and removing a phone.

The phone server itself is replaced by a stand-in, so no port is opened.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import phone_gateway
import phone_pairing
import routes_phone as routes


class FakeGateway:
    def __init__(self) -> None:
        self.running = False
        self.port = 8765

    def status(self):
        return {"enabled": self.running, "running": self.running, "port": self.port, "error": "",
                "urls": ["http://192.168.1.5:8765/"] if self.running else []}

    def start(self, port=None):
        self.running = True
        self.port = port or self.port
        return self.status()

    def stop(self):
        self.running = False
        return self.status()


@pytest.fixture
def client(monkeypatch, tmp_path):
    fake = FakeGateway()
    book = phone_pairing.PhoneBook(path=tmp_path / "phones.json")
    monkeypatch.setattr(phone_gateway, "gateway", lambda: fake)
    monkeypatch.setattr(phone_pairing, "book", lambda: book)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes._owner] = lambda: object()
    return TestClient(app), fake, book


def test_off_by_default_and_no_key_while_off(client):
    http, _fake, _book = client
    state = http.get("/api/phone").json()
    assert state["running"] is False and state["devices"] == [] and state["key_seconds_left"] == 0
    refused = http.post("/api/phone/key")
    assert refused.status_code == 409 and "Allow my phone" in refused.json()["detail"]


def test_turn_on_then_get_a_key_that_connects_a_phone(client):
    http, _fake, book = client
    assert http.post("/api/phone/gateway", json={"enabled": True}).json()["running"] is True
    made = http.post("/api/phone/key").json()
    assert made["expires_in"] == 60 and made["key_seconds_left"] > 0
    token = book.redeem(made["key"], "Pixel", "192.168.1.20")["token"]
    assert token and http.get("/api/phone").json()["devices"][0]["name"] == "Pixel"


def test_turning_off_forgets_the_key(client):
    http, _fake, book = client
    http.post("/api/phone/gateway", json={"enabled": True})
    key = http.post("/api/phone/key").json()["key"]
    state = http.post("/api/phone/gateway", json={"enabled": False}).json()
    assert state["running"] is False and state["key_seconds_left"] == 0
    with pytest.raises(phone_pairing.PairingError):
        book.redeem(key, "Late", "a")


def test_port_must_be_a_normal_one(client):
    http, _fake, _book = client
    assert http.post("/api/phone/gateway", json={"enabled": True, "port": 80}).status_code == 400
    assert http.post("/api/phone/gateway", json={"enabled": True, "port": 9000}).json()["port"] == 9000


def test_remove_a_phone(client):
    http, _fake, book = client
    http.post("/api/phone/gateway", json={"enabled": True})
    device = book.redeem(http.post("/api/phone/key").json()["key"], "Pixel", "a")["device"]
    assert http.delete(f"/api/phone/devices/{device['id']}").json()["devices"] == []
    assert http.delete(f"/api/phone/devices/{device['id']}").status_code == 404


def test_these_routes_need_the_owner(monkeypatch):
    app = FastAPI()
    app.include_router(routes.router)
    http = TestClient(app, client=("203.0.113.9", 1))              # not the computer itself, and no sign-in
    assert http.get("/api/phone").status_code in (401, 403)
    assert http.post("/api/phone/key").status_code in (401, 403)
