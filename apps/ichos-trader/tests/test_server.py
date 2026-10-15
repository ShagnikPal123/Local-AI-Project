"""The web API: deny by default, owners change things, viewers only look, keys never come back."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ichos_trader import server, settings
from ichos_trader.access import auth, secrets
from ichos_trader.connectors import catalog
from ichos_trader.engine import Engine
from ichos_trader.markets import SimulatedFeed
from ichos_trader.markets.hub import MarketHub

LOCAL = ("127.0.0.1", 50000)
REMOTE = ("203.0.113.9", 50000)
FAKE_SECRET = "k" * 12 + "-fake-LAST"


@pytest.fixture
def app():
    settings.save({"markets": {"crypto": True, "stocks": False, "fx": False}, "learn_first": False})
    sim = SimulatedFeed()
    hub = MarketHub(feeds={"crypto": sim, "stock": sim, "etf": sim, "fx": sim})
    return server.create_app(Engine(hub))


def client(app, where=LOCAL, role=None, header=True):
    c = TestClient(app, client=where, base_url="http://127.0.0.1:8100",
                   headers={server.CHANGE_HEADER: "1"} if header else {})
    if role:
        c.cookies.set(auth.COOKIE, auth.session_for("Guest", role))
    return c


def _api_routes(app):
    out = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/api/") and not path.startswith(server.PUBLIC):
            for method in sorted(route.methods - {"HEAD"}):
                out.append((method, path.replace("{cid}", "alpaca")))
    return out


def test_every_private_route_is_refused_to_a_stranger(app):
    stranger = client(app, REMOTE)
    routes = _api_routes(app)
    assert len(routes) >= 12
    for method, path in routes:
        assert stranger.request(method, path).status_code == 401, (method, path)
    assert stranger.get("/api/health").json()["ok"]
    assert stranger.get("/api/me").json()["signed_in"] is False


def test_a_viewer_can_look_but_every_change_is_refused(app):
    look = client(app, REMOTE, "viewer")
    assert look.get("/api/dashboard").status_code == 200
    assert look.get("/api/settings").status_code == 200
    for method, path in _api_routes(app):
        if method != "GET":
            assert look.request(method, path, json={}).status_code == 403, (method, path)


def test_the_local_owner_runs_a_cycle_and_reads_the_dashboard(app):
    me = client(app)
    assert me.get("/api/me").json()["user"]["role"] == "owner"
    assert me.post("/api/control/cycle").json()["ok"]
    dash = me.get("/api/dashboard").json()
    assert dash["money_kind"] == "practice" and dash["markets"] and dash["trades"]
    assert me.post("/api/control/start").json()["state"] in ("trading", "learning", "paused")
    assert me.post("/api/control/stop", json={}).json()["state"] == "off"
    assert me.post("/api/control/flatten").json()["sold"] >= 1


def test_tuning_pins_a_dial_and_running_cannot_be_set_behind_the_watchdog(app):
    me = client(app)
    body = me.put("/api/settings", json={"risk": 0.8, "running": True}).json()
    assert body["settings"]["pins"] == {"risk": 0.8} and body["settings"]["running"] is False
    assert me.put("/api/settings", json={"unpin": ["risk"]}).json()["settings"]["pins"] == {}
    assert me.put("/api/settings", json={"risk": "lots"}).status_code == 400


def test_speedtest_places_nothing(app):
    me = client(app)
    result = me.post("/api/speedtest").json()
    assert result["grade"] in ("fast", "ok", "slow") and result["markets"] > 0
    assert me.get("/api/dashboard").json()["trades"] == []


def test_paper_reset(app):
    me = client(app)
    assert me.post("/api/paper/reset", json={"cash": 2500}).json()["equity"] == 2500
    assert me.post("/api/paper/reset", json={"cash": "x"}).status_code == 400


def test_connector_keys_never_come_back(app, monkeypatch):
    monkeypatch.setattr(catalog.Alpaca, "test", lambda self: "Connected.")
    me = client(app)
    saved = me.post("/api/connectors/alpaca", json={"key_id": "PKFAKE", "secret_key": FAKE_SECRET})
    assert saved.status_code == 200 and FAKE_SECRET not in saved.text
    listed = me.get("/api/connectors")
    assert FAKE_SECRET not in listed.text and "…LAST" in listed.text
    viewer_text = client(app, REMOTE, "viewer").get("/api/connectors").text
    assert "LAST" not in viewer_text and "PKFAKE" not in viewer_text
    assert me.delete("/api/connectors/alpaca").json()["ok"] and secrets.get("alpaca_secret_key") is None
    assert me.post("/api/connectors/nope", json={}).status_code == 404


def test_claude_is_refused_while_off(app):
    assert client(app).post("/api/claude/ask", json={"question": "Why?"}).status_code == 400


def test_passcode_login_with_a_lockout(app):
    secrets.put("passcode", "correct horse battery")
    c = client(app, REMOTE)
    assert c.get("/api/dashboard").status_code == 401
    assert c.post("/api/auth/passcode", json={"passcode": "correct horse battery"}).status_code == 200
    assert c.get("/api/me").json()["user"]["role"] == "owner"
    other = client(app, REMOTE)
    for _ in range(5):
        assert other.post("/api/auth/passcode", json={"passcode": "nope"}).status_code == 401
    assert other.post("/api/auth/passcode", json={"passcode": "correct horse battery"}).status_code == 429


def test_oauth_callback_needs_the_state_it_was_sent_with(app):
    secrets.put("google_client_id", "client-id")
    secrets.put("google_client_secret", FAKE_SECRET)
    c = client(app, REMOTE)
    start = c.get("/api/auth/login/google", follow_redirects=False)
    assert start.status_code == 302 and start.headers["location"].startswith("https://accounts.google.com/")
    assert c.get("/api/auth/callback/google?code=x&state=wrong").status_code == 400
    assert c.get("/api/auth/login/github", follow_redirects=False).status_code == 404


def test_another_website_cannot_press_the_buttons(app):
    assert client(app, header=False).post("/api/control/cycle").status_code == 403
    assert client(app, header=False).get("/api/dashboard").status_code == 200
    rebound = TestClient(app, client=LOCAL, base_url="http://evil.example", headers={server.CHANGE_HEADER: "1"})
    assert rebound.get("/api/dashboard").status_code == 403


def test_unknown_api_paths_are_404_and_the_page_falls_back(app):
    me = client(app)
    assert me.get("/api/nope").status_code == 404
    assert "Ichos Trader" in me.get("/").text or "<div id=\"root\"" in me.get("/").text


def test_setup_sets_the_practice_money_in_one_go(app):
    owner = client(app, role="owner")
    assert owner.get("/api/setup").json()["done"] is False
    reply = owner.post("/api/setup", json={"amount": 2500, "currency": "EUR", "start": True})
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["done"] and body["start_cash"] == 2500 and body["currency"] == "EUR" and body["state"] != "off"
    assert owner.get("/api/dashboard").json()["money"]["currency"] == "EUR"
    assert owner.post("/api/setup", json={"amount": 0}).status_code == 400
    assert client(app, REMOTE, "viewer").post("/api/setup", json={"amount": 5}).status_code == 403
    owner.post("/api/control/stop")


def test_choosing_alpaca_before_its_keys_are_added_says_so(app):
    owner = client(app, role="owner")
    reply = owner.post("/api/setup", json={"amount": 1000, "broker": "alpaca", "start": True})
    assert reply.status_code == 400 and "not connected" in reply.json()["detail"]
    dash = owner.get("/api/dashboard")
    assert dash.status_code == 200 and dash.json()["broker"] == "Alpaca practice account"
    assert "not connected" in dash.json()["broker_error"]


def test_switching_to_real_money_and_back_in_setup(app, monkeypatch):
    import requests
    from ichos_trader import realmoney

    def offline(*_, **__):
        raise requests.ConnectionError("no network in tests")

    monkeypatch.setattr(requests.Session, "request", offline)
    owner = client(app, role="owner")
    refused = owner.post("/api/setup", json={"amount": 300, "money": "real", "confirmation": "ok"})
    assert refused.status_code == 400 and "type exactly" in refused.json()["detail"]
    secrets.put("alpaca_live_key_id", "AKFAKEFAKEFAKE")
    secrets.put("alpaca_live_secret_key", FAKE_SECRET)
    reply = owner.post("/api/setup", json={"amount": 300, "money": "real", "confirmation": realmoney.CONFIRMATION})
    assert reply.status_code == 200 and reply.json()["real_money"]["on"] and reply.json()["state"] == "off"
    dash = owner.get("/api/dashboard").json()
    assert dash["money_kind"] == "real" and dash["broker"] == "Alpaca real money" and dash["broker_error"]
    assert FAKE_SECRET not in owner.get("/api/setup").text
    assert owner.post("/api/real-money/off").json()["on"] is False
    assert owner.get("/api/dashboard").json()["money_kind"] == "practice"
