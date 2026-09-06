"""First-run ownership claim over HTTP, and the grant refactor behind it.

Claiming used to be CLI-only (`python admin_setup.py claim <email>`), so a user
with no terminal had no way to secure their install. The route that replaces it
runs before any account exists, which means it cannot be protected by a session
- it is guarded by being loopback-only and by refusing once an owner exists.
Those two guards are the whole security of the endpoint, so they are what these
tests pin down.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server
import server_auth
from auth import AuthStore, Role

OWNER = "owner@example.com"
PASSWORD = "a-sufficiently-long-password"


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A fresh, unclaimed AuthStore for each test."""
    fresh = AuthStore(path=tmp_path / "auth.json")
    monkeypatch.setattr(server_auth, "AUTH_STORE", fresh)
    monkeypatch.setattr(server, "AUTH_STORE", fresh)
    return fresh


@pytest.fixture
def client(store):
    """A client that presents a loopback address.

    TestClient reports the host as "testclient" by default, which the route
    correctly refuses. Setting a real loopback address exercises the happy path
    without weakening the guard; test_a_non_loopback_caller_cannot_claim covers
    the other side.
    """
    return TestClient(server.app, client=("127.0.0.1", 51234))


def test_a_fresh_install_can_be_claimed(client, store):
    response = client.post("/api/auth/claim", json={"email": OWNER, "password": PASSWORD})
    assert response.status_code == 200, response.text

    body = response.json()
    # The owner lands signed in rather than being bounced to a login screen for
    # the password they just chose.
    assert body["token"]
    assert body["user"]["role"] == Role.OWNER.value
    assert store.get_user(OWNER) is not None


def test_the_returned_token_is_a_working_session(client):
    token = client.post(
        "/api/auth/claim", json={"email": OWNER, "password": PASSWORD}
    ).json()["token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    assert me.json()["user"]["email"] == OWNER


def test_a_second_claim_is_refused(client):
    client.post("/api/auth/claim", json={"email": OWNER, "password": PASSWORD})

    second = client.post(
        "/api/auth/claim", json={"email": "someone@else.com", "password": PASSWORD}
    )
    assert second.status_code == 409
    assert "already has an owner" in second.json()["detail"]


def test_a_weak_password_is_refused_and_claims_nothing(client, store):
    response = client.post("/api/auth/claim", json={"email": OWNER, "password": "short"})
    assert response.status_code == 400

    # A rejected claim must not leave a half-made owner behind, or the install
    # would be permanently unclaimable.
    assert store.get_user(OWNER) is None


def test_a_non_loopback_caller_cannot_claim(store):
    """Over a network, "whoever asks first owns it" is a land-grab."""
    remote = TestClient(server.app, client=("203.0.113.9", 51234))
    response = remote.post("/api/auth/claim", json={"email": OWNER, "password": PASSWORD})

    assert response.status_code == 403
    assert "machine running Nyx" in response.json()["detail"]
    assert store.get_user(OWNER) is None


def test_claim_is_in_the_public_allowlist():
    """It runs before any account exists, so the session gate must not catch it."""
    assert "/api/auth/claim" in server_auth.PUBLIC_PATHS


def test_claim_does_not_exist_in_hosted_mode(monkeypatch):
    """A hosted install is provisioned deliberately, never claimed."""
    import deploy_mode

    assert "/api/auth/claim" in deploy_mode.HOSTED_BLOCKED_PREFIXES
    monkeypatch.setattr(deploy_mode, "is_hosted", lambda: True)
    assert not deploy_mode.is_route_available("/api/auth/claim")
