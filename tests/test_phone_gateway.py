"""Phone gateway: closed by default, home network only, and a phone sees only what pairing gave it.

The chat list and the AI are fakes; no port is opened and no model runs.
"""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

import phone_gateway as pg
import phone_pairing as pp


class FakeChats:
    def __init__(self) -> None:
        self.data = {"c1": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"},
                            {"role": "system", "content": "secret system text"}]}
        self.made = 0

    def recent(self, limit):
        return [{"id": cid, "title": f"Chat {cid}", "preview": "p", "updated_at": "2026-10-14"} for cid in self.data][:limit]

    def exists(self, chat_id):
        return chat_id in self.data

    def messages(self, chat_id):
        return self.data[chat_id]

    def create(self, title):
        self.made += 1
        self.data[f"n{self.made}"] = []
        return f"n{self.made}"


@pytest.fixture
def world(tmp_path):
    book = pp.PhoneBook(path=tmp_path / "phones.json")
    chats = FakeChats()
    calls = []

    def turn(chat_id, text):
        calls.append((chat_id, text))
        return f"echo: {text}"

    app = pg.build_app(book=book, chats=chats, turn=turn)
    home = TestClient(app, client=("192.168.1.20", 5000))
    return book, chats, calls, app, home


def paired(world):
    book, _chats, _calls, _app, home = world
    key = book.mint()["key"]
    token = home.post("/pair", json={"key": key, "name": "Pixel"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_home_network_addresses_only():
    assert pg.on_home_network("192.168.0.5") and pg.on_home_network("10.1.2.3") and pg.on_home_network("172.20.0.9")
    assert pg.on_home_network("127.0.0.1") and pg.on_home_network("::ffff:192.168.1.4")
    assert not pg.on_home_network("8.8.8.8") and not pg.on_home_network("2001:db8::1") and not pg.on_home_network("")
    assert not pg.on_home_network("testclient")


def test_outside_addresses_are_refused_before_anything_else(world):
    book, _chats, _calls, app, _home = world
    outside = TestClient(app, client=("8.8.4.4", 5000))
    assert outside.get("/").status_code == 403
    key = book.mint()["key"]
    assert outside.post("/pair", json={"key": key}).status_code == 403
    assert book.devices() == []                                  # the key was never even tried


def test_page_is_served_with_a_strict_policy(world):
    reply = world[4].get("/")
    assert reply.status_code == 200 and "default-src 'none'" in reply.headers["content-security-policy"]
    assert "innerHTML" not in pg.PAGE                           # messages go in as text, never as markup


def test_every_chat_door_needs_a_token(world):
    home = world[4]
    for method, path in (("get", "/api/chats"), ("get", "/api/chats/c1"), ("post", "/api/chats"),
                         ("post", "/api/chats/c1/send")):
        reply = getattr(home, method)(path, **({"json": {"text": "x"}} if method == "post" else {}))
        assert reply.status_code == 401, path
    assert home.get("/api/chats", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert home.get("/docs").status_code == 404 and home.get("/openapi.json").status_code == 404


def test_wrong_key_is_refused_and_right_key_pairs(world):
    book, _c, _calls, _a, home = world
    book.mint()
    bad = home.post("/pair", json={"key": "ZZZZ-ZZZZ"})
    assert bad.status_code == 400 and "wrong or has run out" in bad.json()["detail"]
    assert paired(world)["Authorization"].startswith("Bearer ")
    assert book.devices()[0]["name"] == "Pixel"


def test_phone_lists_reads_and_starts_chats(world):
    home = world[4]
    headers = paired(world)
    assert home.get("/api/chats", headers=headers).json()["chats"][0]["title"] == "Chat c1"
    messages = home.get("/api/chats/c1", headers=headers).json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]          # the system line is not shown
    assert home.get("/api/chats/missing", headers=headers).status_code == 404
    made = home.post("/api/chats", json={"title": "Trip"}, headers=headers).json()["id"]
    assert made in world[1].data


def test_sending_runs_one_turn_and_returns_the_reply(world):
    _b, _c, calls, _a, home = world
    headers = paired(world)
    reply = home.post("/api/chats/c1/send", json={"text": "  what's up  "}, headers=headers)
    assert reply.json() == {"reply": "echo: what's up"} and calls == [("c1", "what's up")]
    assert home.post("/api/chats/c1/send", json={"text": "   "}, headers=headers).status_code == 400
    assert home.post("/api/chats/c1/send", json={"text": "x" * (pg.TEXT_LIMIT + 1)}, headers=headers).status_code == 400
    assert home.post("/api/chats/nope/send", json={"text": "hi"}, headers=headers).status_code == 404


def test_a_chat_that_is_answering_refuses_a_second_message(tmp_path):
    book = pp.PhoneBook(path=tmp_path / "p.json")
    chats = FakeChats()
    started, release = threading.Event(), threading.Event()

    def slow(chat_id, text):
        started.set()
        release.wait(5)
        return "done"

    home = TestClient(pg.build_app(book=book, chats=chats, turn=slow), client=("192.168.1.9", 1))
    token = home.post("/pair", json={"key": book.mint()["key"], "name": "P"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    first = {}
    worker = threading.Thread(target=lambda: first.update(r=home.post("/api/chats/c1/send", json={"text": "a"}, headers=headers)))
    worker.start()
    assert started.wait(5)
    assert home.get("/api/chats", headers=headers).json()["chats"][0]["working"] is True
    assert home.post("/api/chats/c1/send", json={"text": "b"}, headers=headers).status_code == 409
    release.set()
    worker.join(5)
    assert first["r"].json() == {"reply": "done"}
    assert home.get("/api/chats", headers=headers).json()["chats"][0]["working"] is False


def test_an_ai_failure_reaches_the_phone_as_words(tmp_path):
    book = pp.PhoneBook(path=tmp_path / "p.json")

    def broken(chat_id, text):
        raise RuntimeError("model offline")

    home = TestClient(pg.build_app(book=book, chats=FakeChats(), turn=broken), client=("192.168.1.9", 1))
    token = home.post("/pair", json={"key": book.mint()["key"], "name": "P"}).json()["token"]
    reply = home.post("/api/chats/c1/send", json={"text": "hi"}, headers={"Authorization": f"Bearer {token}"})
    assert reply.status_code == 500 and "model offline" in reply.json()["detail"]


def test_a_removed_phone_stops_working_at_once(world):
    book, _c, _calls, _a, home = world
    headers = paired(world)
    assert home.get("/api/chats", headers=headers).status_code == 200
    book.revoke(book.devices()[0]["id"])
    assert home.get("/api/chats", headers=headers).status_code == 401


def test_the_gateway_is_off_until_turned_on_and_remembers_its_choice(tmp_path):
    started = []

    def fake_runner(gateway, app, port, ready):
        started.append(port)
        ready.set()
        gateway._stop_flag = threading.Event()
        gateway._server = type("S", (), {"should_exit": False})()
        while not gateway._server.should_exit:
            threading.Event().wait(0.01)

    gateway = pg.Gateway(state_path=tmp_path / "gw.json", runner=fake_runner)
    assert gateway.saved() == {"enabled": False, "port": pg.DEFAULT_PORT}
    gateway.start_if_enabled()
    assert started == [] and not gateway.running                 # nothing runs unless the owner turned it on
    assert gateway.start(9123)["running"] is True and started == [9123]
    assert gateway.saved() == {"enabled": True, "port": 9123}
    assert gateway.stop()["running"] is False and gateway.saved()["enabled"] is False


def test_a_port_that_is_taken_is_reported_not_raised(tmp_path):
    def busy_runner(gateway, app, port, ready):
        raise OSError("address already in use")

    gateway = pg.Gateway(state_path=tmp_path / "gw.json", runner=busy_runner)
    status = gateway.start(9124)
    gateway._thread.join(2)
    assert "could not start" in gateway.status()["error"] and status["enabled"] is True
