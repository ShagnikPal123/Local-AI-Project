"""Tests for routes_access.py.

Mirrors the isolation pattern of tests/test_claim_flow.py (a loopback
TestClient exercises the "unclaimed install" path) and tests/test_server_auth.py
(a claimed store exercises the normal session gate). access_keys' own stores
are redirected into tmp_path exactly like tests/test_access_keys.py, so this
suite never touches the real secret store or access_public_keys.json.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import access_keys
import server
import server_auth
from auth import AuthStore, Role

OWNER = "shagnikpal@gmail.com"
PASSWORD = "a-long-enough-passphrase"
OTHER_PASSWORD = "another-long-passphrase"


@pytest.fixture(autouse=True)
def isolated_access_stores(tmp_path, monkeypatch):
    """Redirect every access_keys store into tmp_path (never the real files)."""
    monkeypatch.setattr(access_keys, "data_path", lambda name: tmp_path / name)
    monkeypatch.setattr(access_keys, "project_path", lambda name: tmp_path / name)
    (tmp_path / "access_public_keys.json").write_text(json.dumps({"keys": []}), encoding="utf-8")

    fake_secrets: dict[str, list[str]] = {}
    monkeypatch.setattr(access_keys.secret_store, "get_keys", lambda name: list(fake_secrets.get(name, [])))

    def fake_set_keys(name, keys):
        values = [k for k in keys if k]
        fake_secrets[name] = values
        return values

    monkeypatch.setattr(access_keys.secret_store, "set_keys", fake_set_keys)
    return tmp_path


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A fresh AuthStore, swapped into both server_auth and server."""
    fresh = AuthStore(path=tmp_path / "auth.json")
    monkeypatch.setattr(server_auth, "AUTH_STORE", fresh)
    monkeypatch.setattr(server, "AUTH_STORE", fresh)
    return fresh


@pytest.fixture
def client(store):
    """Default TestClient: reports host "testclient" - not loopback."""
    return TestClient(server.app)


@pytest.fixture
def loopback_client(store):
    """Reports a real loopback address, for the unclaimed-install admin path."""
    return TestClient(server.app, client=("127.0.0.1", 51234))


def _claim(store) -> None:
    store.bootstrap_owner(OWNER)
    store.set_password(OWNER, PASSWORD)


def _login(client, email=OWNER, password=PASSWORD) -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- status / redeem: open on unclaimed, session-gated once claimed --------


def test_status_is_reachable_on_an_unclaimed_install(client):
    body = client.get("/api/access/status").json()
    assert body["level"] == "owner"  # nobody local is anybody but the owner
    assert body["signing_ready"] is False


def test_status_requires_a_session_once_claimed(client, store):
    _claim(store)
    assert client.get("/api/access/status").status_code == 401


def test_status_reachable_by_a_signed_in_user(client, store):
    _claim(store)
    response = client.get("/api/access/status", headers=_auth(_login(client)))
    assert response.status_code == 200
    assert response.json()["level"] == "owner"


def test_redeem_with_a_bad_key_is_a_400_with_the_reason(client):
    response = client.post("/api/access/redeem", json={"key": "not-a-key"})
    assert response.status_code == 400
    assert response.json()["detail"]


def test_redeem_a_valid_key_is_recorded_and_valid(client, store):
    _claim(store)
    token = _login(client)
    minted = access_keys.mint("beta", "Tester")
    response = client.post("/api/access/redeem", json={"key": minted["key"]}, headers=_auth(token))
    assert response.status_code == 200
    body = response.json()
    # The signed-in caller is the owner, so level stays "owner" regardless -
    # but the key must show up as valid in the keys list.
    assert any(k["id"] == minted["id"] and k["valid"] for k in body["keys"])


def test_redeem_a_valid_key_raises_a_non_owner_to_that_role(client, store):
    _claim(store)
    owner_token = _login(client)
    invite = client.post(
        "/api/admin/invites", json={"role": "beta"}, headers=_auth(owner_token)
    ).json()
    client.post("/api/auth/join", json={
        "invite": invite["token"], "email": "tester2@example.com", "password": OTHER_PASSWORD,
    })
    tester_token = _login(client, "tester2@example.com", OTHER_PASSWORD)

    minted = access_keys.mint("dev", "Dev Tester")
    response = client.post(
        "/api/access/redeem", json={"key": minted["key"]}, headers=_auth(tester_token)
    )
    assert response.status_code == 200
    assert response.json()["level"] == "dev"


def test_redeem_requires_a_session_once_claimed(client, store):
    _claim(store)
    assert client.post("/api/access/redeem", json={"key": "x"}).status_code == 401


# --- admin routes: refused anonymously once claimed -------------------------


ADMIN_ROUTES = [
    ("get", "/api/access/minted"),
    ("get", "/api/access/applications"),
    ("get", "/api/access/flags"),
    ("get", "/api/access/audit"),
    ("post", "/api/access/signing-key"),
    ("post", "/api/access/mint"),
    ("post", "/api/access/revoke/abc"),
    ("post", "/api/access/applications/abc/decision"),
    ("post", "/api/access/flags"),
]


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
def test_admin_routes_refuse_anonymous_callers_when_claimed(client, store, method, path):
    _claim(store)
    call = getattr(client, method)
    response = call(path, json={}) if method == "post" else call(path)
    assert response.status_code in (401, 403), f"{path} was reachable anonymously"


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
def test_admin_routes_refuse_a_non_loopback_caller_when_unclaimed(client, method, path):
    """TestClient's default host is "testclient" - not loopback."""
    call = getattr(client, method)
    response = call(path, json={}) if method == "post" else call(path)
    assert response.status_code in (401, 403), f"{path} was reachable over a fake remote host"


def test_admin_routes_allow_the_loopback_caller_when_unclaimed(loopback_client):
    assert loopback_client.get("/api/access/minted").status_code == 200
    assert loopback_client.get("/api/access/applications").status_code == 200
    assert loopback_client.get("/api/access/flags").status_code == 200
    assert loopback_client.post("/api/access/signing-key").status_code == 200


def test_admin_routes_work_for_a_signed_in_owner_when_claimed(client, store):
    _claim(store)
    token = _login(client)
    assert client.get("/api/access/minted", headers=_auth(token)).status_code == 200
    assert client.post("/api/access/signing-key", headers=_auth(token)).status_code == 200


def test_a_beta_tester_cannot_reach_admin_routes(client, store):
    _claim(store)
    owner_token = _login(client)
    invite = client.post(
        "/api/admin/invites", json={"role": "beta"}, headers=_auth(owner_token)
    ).json()
    client.post("/api/auth/join", json={
        "invite": invite["token"], "email": "tester@example.com", "password": OTHER_PASSWORD,
    })
    beta_token = _login(client, "tester@example.com", OTHER_PASSWORD)
    assert client.get("/api/access/minted", headers=_auth(beta_token)).status_code == 403


# --- mint / list / revoke happy path -----------------------------------------


def test_owner_can_mint_list_and_revoke_a_key(loopback_client):
    minted = loopback_client.post("/api/access/mint", json={
        "role": "dev", "name": "Dev Tester", "days": 30,
    }).json()
    assert minted["key"].startswith("NYX1-")
    assert "nyx://redeem?key=" in minted["redeem_link"]

    listed = loopback_client.get("/api/access/minted").json()
    assert any(k["id"] == minted["id"] for k in listed["keys"])

    revoked = loopback_client.post(f"/api/access/revoke/{minted['id']}").json()
    assert revoked["revoked"] is True

    audited = loopback_client.get("/api/access/audit").json()["audit"]
    assert any(a["action"] == "revoke" and a["target"] == minted["id"] for a in audited)


def test_mint_with_a_bad_role_is_a_400(loopback_client):
    response = loopback_client.post("/api/access/mint", json={"role": "superuser", "name": "X"})
    assert response.status_code == 400


# --- applications end-to-end -------------------------------------------------


def test_application_decision_flow(loopback_client):
    access_keys.submit_application("Grace", "grace@example.com", "beta", reason="curious")
    listed = loopback_client.get("/api/access/applications").json()["applications"]
    app_id = listed[0]["id"]

    decision = loopback_client.post(
        f"/api/access/applications/{app_id}/decision", json={"approve": True, "days": 14}
    ).json()
    assert decision["application"]["status"] == "approved"
    assert decision["mint"]["key"].startswith("NYX1-")


def test_deciding_an_unknown_application_is_a_404(loopback_client):
    response = loopback_client.post(
        "/api/access/applications/nope/decision", json={"approve": True}
    )
    assert response.status_code == 404


# --- flags --------------------------------------------------------------------


def test_flags_get_and_set(loopback_client):
    assert loopback_client.get("/api/access/flags").json()["flags"] == {}
    updated = loopback_client.post("/api/access/flags", json={"flags": {"labs_v2": True}}).json()
    assert updated["flags"] == {"labs_v2": True}
    assert loopback_client.get("/api/access/flags").json()["flags"] == {"labs_v2": True}


# --- the signing seed must never leak into a response ------------------------


def test_no_response_ever_contains_the_signing_seed(loopback_client):
    loopback_client.post("/api/access/signing-key")
    seed_hex = access_keys.secret_store.get_keys(access_keys._SIGNING_KEY_NAME)[0]

    minted = loopback_client.post("/api/access/mint", json={"role": "beta", "name": "X"})
    assert seed_hex not in minted.text

    status_resp = loopback_client.get("/api/access/status")
    assert seed_hex not in status_resp.text

    minted_resp = loopback_client.get("/api/access/minted")
    assert seed_hex not in minted_resp.text

    audit_resp = loopback_client.get("/api/access/audit")
    assert seed_hex not in audit_resp.text
