"""Google sign-in for Gmail instead of an app password (Request H7)."""

from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, urlsplit

import pytest

import google_oauth


class _Response:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class _Google:
    def __init__(self):
        self.posts = []

    def post(self, url, data=None, timeout=0):
        self.posts.append((url, dict(data or {})))
        if data.get("grant_type") == "authorization_code":
            claims = base64.urlsafe_b64encode(json.dumps({"email": "owner@gmail.com"}).encode()).decode().rstrip("=")
            return _Response(200, {"access_token": "ya29.access", "refresh_token": "1//refresh", "expires_in": 3599,
                                   "id_token": f"h.{claims}.s"})
        if data.get("grant_type") == "refresh_token":
            return _Response(200, {"access_token": "ya29.fresh", "expires_in": 3599})
        return _Response(200, {})


@pytest.fixture()
def secrets_and_mail(tmp_path, monkeypatch):
    store = {}
    import email_client
    import secret_store

    monkeypatch.setattr(secret_store, "get_keys", lambda name: list(store.get(name, [])))
    monkeypatch.setattr(secret_store, "set_keys", lambda name, values: store.__setitem__(name, [v for v in values if v]) or list(values))
    monkeypatch.setattr(email_client, "_accounts_path", lambda: tmp_path / "email_accounts.json")
    google_oauth._pending.clear()
    google_oauth._tokens.clear()
    return store


def test_the_client_must_look_like_a_google_client(secrets_and_mail):
    with pytest.raises(google_oauth.OAuthError):
        google_oauth.save_client("my-client", "secret-value-123")
    google_oauth.save_client("123-abc.apps.googleusercontent.com", "GOCSPX-secret-value")
    assert google_oauth.client_configured()


def test_sign_in_connects_gmail_with_a_refresh_token_and_no_password(secrets_and_mail):
    import email_client

    store = secrets_and_mail
    google_oauth.save_client("123-abc.apps.googleusercontent.com", "GOCSPX-secret-value")
    url = google_oauth.start("http://127.0.0.1:8000/api/google/oauth/callback")
    query = parse_qs(urlsplit(url).query)
    assert query["code_challenge_method"] == ["S256"] and "https://mail.google.com/" in query["scope"][0]
    state = query["state"][0]

    google = _Google()
    assert google_oauth.complete(state, "auth-code", http=google) == "owner@gmail.com"
    assert store["GOOGLE_OAUTH_REFRESH:owner@gmail.com"] == ["1//refresh"]
    exchange = google.posts[0][1]
    assert exchange["code_verifier"] and exchange["redirect_uri"].endswith("/api/google/oauth/callback")

    account = email_client.list_accounts()[0]
    assert account["auth"] == "google_sign_in" and account["configured"] and account["read"] == "imap"
    assert "1//refresh" not in json.dumps(account)
    assert google_oauth.xoauth2("owner@gmail.com", http=google) == "user=owner@gmail.com\x01auth=Bearer ya29.access\x01\x01"

    with pytest.raises(google_oauth.OAuthError):
        google_oauth.complete(state, "auth-code", http=google)  # a state works once


def test_the_callback_is_public_but_refuses_an_unknown_state(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import server
    import server_auth
    from auth import AuthStore

    fresh = AuthStore(path=tmp_path / "auth.json")
    monkeypatch.setattr(server_auth, "AUTH_STORE", fresh)
    monkeypatch.setattr(server, "AUTH_STORE", fresh)
    fresh.bootstrap_owner("owner@example.com")
    fresh.set_password("owner@example.com", "a-long-password-123")
    client = TestClient(server.app, client=("127.0.0.1", 50000))

    response = client.get("/api/google/oauth/callback?state=forged&code=x")
    assert response.status_code == 400 and "expired" in response.text
    assert client.get("/api/google/oauth/status").status_code == 401
    assert client.post("/api/google/oauth/start", json={}).status_code == 401
