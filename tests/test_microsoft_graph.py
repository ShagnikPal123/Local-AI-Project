"""Microsoft 365 in Connectors (Update 1 U24): device-code sign-in, per-app permissions, tokens kept secret."""

from __future__ import annotations

import json

import pytest

from connectors import microsoft_graph as ms

CLIENT = "1b2c3d4e-0000-1111-2222-333344445555"


class _Response:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class _Microsoft:
    """Answers like login.microsoftonline.com and graph.microsoft.com, scripted per test."""

    def __init__(self, token_answers):
        self.token_answers = list(token_answers)
        self.posts = []

    def post(self, url, data=None, timeout=0):
        self.posts.append((url, dict(data or {})))
        if url.endswith("/devicecode"):
            return _Response(200, {"device_code": "DEVICE-CODE", "user_code": "ABCD-EFGH", "interval": 5,
                                   "expires_in": 900, "verification_uri": "https://microsoft.com/devicelogin"})
        answer = self.token_answers.pop(0)
        return _Response(400 if "error" in answer else 200, answer)

    def get(self, url, headers=None, timeout=0):
        assert headers["Authorization"].startswith("Bearer ")
        return _Response(200, {"userPrincipalName": "owner@outlook.com"})


@pytest.fixture()
def secrets(tmp_path, monkeypatch):
    store = {}
    import secret_store

    monkeypatch.setattr(secret_store, "get_keys", lambda name: list(store.get(name, [])))
    monkeypatch.setattr(secret_store, "set_keys",
                        lambda name, values: store.__setitem__(name, [v for v in values if v]) or list(values))
    monkeypatch.setattr(ms, "_path", lambda: tmp_path / "microsoft.json")
    ms._pending.clear()
    ms._tokens.clear()
    return store


def test_the_client_id_must_be_a_guid(secrets):
    with pytest.raises(ms.MicrosoftError):
        ms.save_client("my-app")
    with pytest.raises(ms.MicrosoftError):
        ms.save_client(CLIENT, "not a tenant!")
    assert ms.save_client(CLIENT)["tenant"] == "common" and ms.client_configured()


def test_device_sign_in_connects_only_the_apps_asked_for(secrets, monkeypatch):
    ms.save_client(CLIENT)
    fake = _Microsoft([{"error": "authorization_pending"},
                       {"access_token": "eyJ.access", "refresh_token": "M.refresh", "expires_in": 3600,
                        "scope": "https://graph.microsoft.com/Files.ReadWrite https://graph.microsoft.com/User.Read"}])
    shown = ms.start(["excel"], http=fake)
    assert shown["user_code"] == "ABCD-EFGH" and "device_code" not in json.dumps(shown)
    assert "Files.ReadWrite" in fake.posts[0][1]["scope"] and "offline_access" in fake.posts[0][1]["scope"]

    assert ms.poll(http=fake)["state"] == "waiting"
    monkeypatch.setitem(ms._pending, "next", 0)  # skip the polite wait between checks
    done = ms.poll(http=fake)
    assert done["state"] == "connected" and done["account"] == "owner@outlook.com"
    assert set(done["products"]) == {"excel", "word", "onedrive"}
    assert ms.accounts_for("excel") == ["owner@outlook.com"] and ms.accounts_for("outlook") == []
    assert secrets["MS_GRAPH_REFRESH:owner@outlook.com"] == ["M.refresh"]
    assert "M.refresh" not in (ms._path()).read_text(encoding="utf-8")
    assert ms.pending() is None


def test_slow_down_and_decline_are_reported(secrets, monkeypatch):
    ms.save_client(CLIENT)
    fake = _Microsoft([{"error": "slow_down"}, {"error": "authorization_declined", "error_description": "No"}])
    ms.start(["outlook"], http=fake)
    before = ms._pending["interval"]
    assert ms.poll(http=fake)["state"] == "waiting" and ms._pending["interval"] == before + 5
    monkeypatch.setitem(ms._pending, "next", 0)
    assert ms.poll(http=fake)["state"] == "declined"


def test_access_tokens_refresh_and_rotate(secrets):
    ms.save_client(CLIENT)
    ms._store_tokens("owner@outlook.com", {"access_token": "old", "refresh_token": "R1", "expires_in": 0},
                     ["offline_access", "User.Read", "Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite"], ["outlook"])
    fake = _Microsoft([{"access_token": "new", "refresh_token": "R2", "expires_in": 3600}])
    assert ms.access_token("owner@outlook.com", http=fake) == "new"
    assert secrets["MS_GRAPH_REFRESH:owner@outlook.com"] == ["R2"]
    sent = fake.posts[-1][1]
    assert sent["grant_type"] == "refresh_token" and "Mail.Send" in sent["scope"]
    assert ms.access_token("owner@outlook.com", http=fake) == "new"  # cached: no second request
    ms.disconnect("owner@outlook.com")
    assert ms.accounts_for("outlook") == [] and secrets["MS_GRAPH_REFRESH:owner@outlook.com"] == []


def test_graph_calls_go_out_with_the_sign_in_token(secrets, monkeypatch, tmp_path):
    import connector_use
    from connectors import catalog

    monkeypatch.setattr(ms, "access_token", lambda account, http=None: "graph-token")
    monkeypatch.setattr(ms, "accounts_for", lambda product: ["owner@outlook.com"] if product == "excel" else [])
    calls = []

    class _Http:
        def request(self, method, url, headers=None, params=None, data=None, timeout=0):
            calls.append((method, url, headers, data))
            return type("R", (), {"status_code": 200, "text": '{"value": []}', "headers": {}})()

    monkeypatch.setattr(connector_use, "_requests", lambda: _Http())
    assert catalog.is_connected("excel") and not catalog.is_connected("teams")
    connector_use.call("excel", "range", params={"item_id": "01ABC", "sheet": "Q3 budget", "address": "A1:C4"})
    method, url, headers, _ = calls[-1]
    assert url == ("https://graph.microsoft.com/v1.0/me/drive/items/01ABC/workbook/worksheets/Q3%20budget/"
                   "range(address='A1:C4')")
    assert headers["Authorization"] == "Bearer graph-token"


def test_the_status_route_never_shows_a_device_code(secrets, monkeypatch):
    from fastapi.testclient import TestClient

    import server

    client = TestClient(server.app, client=("127.0.0.1", 50040))
    assert client.post("/api/connectors/microsoft/client", json={"client_id": "nope"}).status_code == 400
    assert client.post("/api/connectors/microsoft/client", json={"client_id": CLIENT}).json()["client_configured"]
    monkeypatch.setattr(ms, "_http", lambda: _Microsoft([{"error": "authorization_pending"}]))
    started = client.post("/api/connectors/microsoft/start", json={"products": ["word"]}).json()["pending"]
    assert started["user_code"] == "ABCD-EFGH"
    status = client.get("/api/connectors/microsoft/status").json()
    assert status["pending"]["user_code"] == "ABCD-EFGH" and "DEVICE-CODE" not in json.dumps(status)
    assert client.post("/api/connectors/microsoft/start", json={"products": ["minesweeper"]}).status_code == 400
