"""API authorisation boundaries (ROADMAP AA6, V1).

The point of these is the negative cases. Anyone can write a test showing an
owner can reach an admin route; what matters is that nobody else can.

The API has two modes, chosen automatically: **unclaimed** (no owner account —
a fresh local install, so chat works without a login) and **claimed** (an owner
exists, so a session is required). Privileged routes are refused in both.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import server
import server_auth
from auth import AuthStore, Role

OWNER = "shagnikpal@gmail.com"
PASSWORD = "a-long-enough-passphrase"
OTHER_PASSWORD = "another-long-passphrase"


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Swap in an isolated auth store for both the module and the routes."""
    fresh = AuthStore(tmp_path / "auth.json")
    monkeypatch.setattr(server_auth, "AUTH_STORE", fresh)
    monkeypatch.setattr(server, "AUTH_STORE", fresh)
    return fresh


@pytest.fixture
def client(store):
    return TestClient(server.app)


def _claim(store) -> None:
    store.bootstrap_owner(OWNER)
    store.set_password(OWNER, PASSWORD)


def _login(client, email=OWNER, password=PASSWORD) -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- mode detection -------------------------------------------------------------

def test_health_reports_unclaimed_on_a_fresh_install(client):
    assert client.get("/api/health").json()["claimed"] is False


def test_health_reports_claimed_once_the_owner_exists(client, store):
    _claim(store)
    assert client.get("/api/health").json()["claimed"] is True


# --- privileged routes are refused even while unclaimed --------------------------
#
# An unclaimed instance must never be MORE powerful than a claimed one.

@pytest.mark.parametrize("method,path", [
    ("get", "/api/admin/users"),
    ("get", "/api/admin/invites"),
    ("post", "/api/admin/invites"),
    ("post", "/api/admin/grant"),
])
def test_admin_routes_refuse_anonymous_callers_when_unclaimed(client, method, path):
    call = getattr(client, method)
    response = call(path, json={}) if method == "post" else call(path)
    assert response.status_code in (401, 403), f"{path} was reachable anonymously"


@pytest.mark.parametrize("method,path", [
    ("get", "/api/admin/users"),
    ("get", "/api/admin/invites"),
    ("post", "/api/admin/invites"),
    ("post", "/api/admin/grant"),
])
def test_admin_routes_refuse_anonymous_callers_when_claimed(client, store, method, path):
    _claim(store)
    call = getattr(client, method)
    response = call(path, json={}) if method == "post" else call(path)
    assert response.status_code in (401, 403), f"{path} was reachable anonymously"


def test_admin_routes_refuse_a_forged_token(client, store):
    _claim(store)
    response = client.get("/api/admin/users", headers=_auth("not-a-real-token"))
    assert response.status_code in (401, 403)


# --- chat gating ------------------------------------------------------------------

def test_chat_is_open_on_an_unclaimed_local_install(client):
    """A fresh local install must work without forcing an account."""
    response = client.post("/api/chat", json={"message": ""})
    # 400 (empty message) proves the auth layer let it through to validation.
    assert response.status_code == 400


def test_chat_requires_a_session_once_claimed(client, store):
    _claim(store)
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 401


# --- login ------------------------------------------------------------------------

def test_login_succeeds_with_the_right_password(client, store):
    _claim(store)
    body = client.post("/api/auth/login", json={"email": OWNER, "password": PASSWORD}).json()
    assert body["token"]
    assert body["user"]["role"] == "owner"


def test_login_rejects_a_wrong_password(client, store):
    _claim(store)
    response = client.post("/api/auth/login", json={"email": OWNER, "password": "wrong-one-here"})
    assert response.status_code == 401


def test_login_response_never_contains_a_secret(client, store):
    _claim(store)
    body = client.post("/api/auth/login", json={"email": OWNER, "password": PASSWORD}).text
    assert PASSWORD not in body
    assert "password_hash" not in body
    assert "password_salt" not in body


def test_login_does_not_reveal_whether_an_account_exists(client, store):
    _claim(store)
    unknown = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
    wrong = client.post("/api/auth/login", json={"email": OWNER, "password": "wrong-one-here"})
    assert unknown.json()["detail"] == wrong.json()["detail"]


# --- owner can actually do the things ---------------------------------------------

def test_owner_can_list_accounts(client, store):
    _claim(store)
    response = client.get("/api/admin/users", headers=_auth(_login(client)))
    assert response.status_code == 200
    assert response.json()["users"][0]["email"] == OWNER


def test_owner_can_mint_an_invite_link(client, store):
    _claim(store)
    response = client.post(
        "/api/admin/invites",
        json={"role": "beta", "email": "tester@example.com"},
        headers=_auth(_login(client)),
    )
    assert response.status_code == 200
    assert "/join?invite=" in response.json()["link"]


def test_an_invite_can_be_redeemed_then_used(client, store):
    _claim(store)
    invite = client.post(
        "/api/admin/invites", json={"role": "beta"}, headers=_auth(_login(client))
    ).json()

    joined = client.post("/api/auth/join", json={
        "invite": invite["token"], "email": "tester@example.com", "password": OTHER_PASSWORD,
    })
    assert joined.status_code == 200
    assert joined.json()["user"]["role"] == "beta"
    assert _login(client, "tester@example.com", OTHER_PASSWORD)


def test_a_used_invite_cannot_be_redeemed_again(client, store):
    _claim(store)
    invite = client.post(
        "/api/admin/invites", json={"role": "beta"}, headers=_auth(_login(client))
    ).json()
    client.post("/api/auth/join", json={
        "invite": invite["token"], "email": "first@example.com", "password": OTHER_PASSWORD})
    second = client.post("/api/auth/join", json={
        "invite": invite["token"], "email": "second@example.com", "password": OTHER_PASSWORD})
    assert second.status_code == 400


# --- a beta tester is properly boxed in --------------------------------------------

@pytest.fixture
def beta_token(client, store):
    _claim(store)
    invite = client.post(
        "/api/admin/invites", json={"role": "beta"}, headers=_auth(_login(client))
    ).json()
    client.post("/api/auth/join", json={
        "invite": invite["token"], "email": "tester@example.com", "password": OTHER_PASSWORD})
    return _login(client, "tester@example.com", OTHER_PASSWORD)


def test_a_beta_tester_can_chat(client, beta_token):
    response = client.post("/api/chat", json={"message": ""}, headers=_auth(beta_token))
    assert response.status_code == 400  # reached validation, so auth passed


@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/admin/users", None),
    ("get", "/api/admin/invites", None),
    ("post", "/api/admin/invites", {"role": "beta"}),
    ("post", "/api/admin/grant", {"email": "x@example.com", "role": "admin"}),
])
def test_a_beta_tester_cannot_reach_admin_routes(client, beta_token, method, path, body):
    call = getattr(client, method)
    response = call(path, json=body, headers=_auth(beta_token)) if body else call(path, headers=_auth(beta_token))
    assert response.status_code == 403, f"beta tester reached {path}"


def test_a_beta_tester_cannot_promote_themselves(client, beta_token):
    response = client.post(
        "/api/admin/grant",
        json={"email": "tester@example.com", "role": "owner"},
        headers=_auth(beta_token),
    )
    assert response.status_code == 403


def test_the_owner_role_cannot_be_reassigned_over_http(client, store):
    _claim(store)
    response = client.post(
        "/api/admin/grant",
        json={"email": OWNER, "role": "user"},
        headers=_auth(_login(client)),
    )
    assert response.status_code == 403


# --- speed mode override (ROADMAP W3, BB9) -----------------------------------------

def test_speed_defaults_to_auto(client):
    """Auto is the default; no setting change should be needed for good latency."""
    assert client.get("/api/speed").json()["mode"] == "auto"


def test_speed_lists_every_mode_with_a_description(client):
    modes = client.get("/api/speed").json()["modes"]
    assert {m["id"] for m in modes} == {"auto", "fast", "full"}
    assert all(m["description"].strip() for m in modes)


def test_speed_can_be_overridden_and_restored(client):
    assert client.post("/api/speed", json={"mode": "fast"}).json()["mode"] == "fast"
    assert client.get("/api/speed").json()["mode"] == "fast"
    assert client.post("/api/speed", json={"mode": "auto"}).json()["mode"] == "auto"


def test_unknown_speed_mode_is_rejected(client):
    assert client.post("/api/speed", json={"mode": "turbo"}).status_code == 400


def test_speed_requires_a_session_once_claimed(client, store):
    _claim(store)
    assert client.get("/api/speed").status_code == 401
    assert client.post("/api/speed", json={"mode": "fast"}).status_code == 401


# --- deny-by-default middleware (ROADMAP V1) ---------------------------------------
#
# The first pass gated routes one at a time and missed /api/memory, /api/chats,
# and /api/connectors — all of which expose personal data or what the agent can
# reach. A path-based gate protects new routes automatically.

DATA_ROUTES = [
    "/api/status",
    "/api/memory",
    "/api/memory/rag",
    "/api/chats",
    "/api/chat-trash",
    "/api/models",
    "/api/connectors",
    "/api/personalities",
    "/api/knowledge",
    "/api/speed",
    "/api/command-zone",
]


@pytest.mark.parametrize("path", DATA_ROUTES)
def test_data_routes_are_open_on_an_unclaimed_install(client, path):
    """A fresh local install must not demand an account to be useful."""
    assert client.get(path).status_code != 401


@pytest.mark.parametrize("path", DATA_ROUTES)
def test_data_routes_require_a_session_once_claimed(client, store, path):
    _claim(store)
    assert client.get(path).status_code == 401, f"{path} leaked data anonymously"


@pytest.mark.parametrize("path", DATA_ROUTES)
def test_data_routes_are_reachable_by_a_signed_in_user(client, store, path):
    _claim(store)
    response = client.get(path, headers=_auth(_login(client)))
    assert response.status_code != 401


def test_public_paths_stay_reachable_when_claimed(client, store):
    """Without these the client could never discover it needs to log in."""
    _claim(store)
    assert client.get("/api/health").status_code == 200
    assert client.post(
        "/api/auth/login", json={"email": OWNER, "password": PASSWORD}
    ).status_code == 200


def test_an_unknown_api_route_is_denied_rather_than_defaulting_open(client, store):
    """Deny-by-default: a route nobody remembered to gate must still be gated."""
    _claim(store)
    assert client.get("/api/some-future-endpoint").status_code == 401


# --- agent team endpoints (ROADMAP B1, B4, BB6) ------------------------------------

def test_agents_endpoint_provides_a_master_by_default(client):
    body = client.get("/api/agents").json()
    assert any(a["role"] == "master" for a in body["agents"])


def test_three_agents_can_be_spawned_in_one_call(client):
    """The exact shape requested: two goals plus one manager.

    Asserts on the agents actually created rather than on a total. GET
    /api/agents now calls ensure_default_subagents(), which seeds the four
    standing roles (Manager, Site/Web Dev, Coder, Checker), so the team is never
    empty and a bare `total == 3` measured the defaults rather than this call.
    """
    before = client.get("/api/agents").json()["total"]
    body = client.post("/api/agents", json={"agents": [
        {"name": "research", "goal": "find current sources"},
        {"name": "builder", "goal": "implement and test the change"},
        {"name": "lead", "goal": "manage the other two", "role": "master"},
    ]}).json()
    team = body["team"]

    assert team["total"] == before + 3
    spawned = {a["name"]: a for a in team["agents"]}
    assert {"research", "builder", "lead"} <= set(spawned)
    assert spawned["lead"]["role"] == "master"
    # The master is listed first so the panel can show who is coordinating.
    assert team["agents"][0]["role"] == "master"


def test_an_unknown_role_is_rejected(client):
    response = client.post("/api/agents", json={"agents": [
        {"name": "x", "goal": "y", "role": "overlord"},
    ]})
    assert response.status_code == 400


def test_agent_routes_require_a_session_once_claimed(client, store):
    _claim(store)
    assert client.get("/api/agents").status_code == 401
    assert client.post("/api/agents", json={"agents": []}).status_code == 401


# --- power modes (ROADMAP EE1-EE9) --------------------------------------------------

def test_power_defaults_to_auto(client):
    assert client.get("/api/power").json()["current"] == "auto"


def test_power_lists_every_mode_with_its_effect_here(client):
    body = client.get("/api/power").json()
    ids = {m["id"] for m in body["modes"]}
    assert ids == {"low", "medium", "high", "max", "auto", "auto_task"}
    assert body["hardware_budget"] >= 1


def test_power_mode_can_be_selected(client):
    body = client.post("/api/power", json={"mode": "low"}).json()
    assert body["current"] == "low"
    assert body["ceiling"]["max_workers"] >= 1


def test_unknown_power_mode_is_rejected(client):
    assert client.post("/api/power", json={"mode": "ludicrous"}).status_code == 400


def test_power_requires_a_session_once_claimed(client, store):
    _claim(store)
    assert client.get("/api/power").status_code == 401
    assert client.post("/api/power", json={"mode": "low"}).status_code == 401


# --- strands endpoint (ROADMAP DD1, DD2) --------------------------------------------

def test_strands_endpoint_returns_a_graph(client):
    body = client.get("/api/strands").json()
    assert "nodes" in body and "links" in body and "counts" in body


def test_strands_requires_a_session_once_claimed(client, store):
    _claim(store)
    assert client.get("/api/strands").status_code == 401


def test_strands_reflects_real_agents(client):
    client.post("/api/agents", json={"agents": [
        {"name": "research", "goal": "improve recency ranking for search freshness"},
    ]})
    body = client.get("/api/strands").json()
    labels = [n["label"] for n in body["nodes"]]
    assert "research" in labels


# --- HUD widgets and event log (ROADMAP DD6-DD12) -----------------------------------

def test_widgets_endpoint_returns_a_layout_and_the_addable_types(client):
    body = client.get("/api/widgets").json()
    assert body["widgets"]
    assert {"tab", "prompt"} <= {t["type"] for t in body["available"]}


def test_a_bound_widget_without_a_target_is_rejected(client):
    """A widget bound to nothing is a blank box, not a feature."""
    assert client.post("/api/widgets", json={"type": "tab"}).status_code == 400


def test_an_unknown_widget_type_is_rejected(client):
    assert client.post("/api/widgets", json={"type": "hologram"}).status_code == 400


def test_widgets_can_be_added_reordered_and_removed(client):
    added = client.post("/api/widgets", json={
        "type": "tab", "title": "Models", "config": {"target": "models"},
    })
    assert added.status_code == 200
    widget_id = added.json()["widget"]["id"]

    ids = [w["id"] for w in client.get("/api/widgets").json()["widgets"]]
    reordered = client.post("/api/widgets/order", json={"order": list(reversed(ids))}).json()
    assert [w["id"] for w in reordered["widgets"]] == list(reversed(ids))

    assert client.delete(f"/api/widgets/{widget_id}").status_code == 200
    assert widget_id not in [w["id"] for w in client.get("/api/widgets").json()["widgets"]]


def test_removing_an_unknown_widget_is_a_404(client):
    assert client.delete("/api/widgets/nope").status_code == 404


def test_events_endpoint_returns_real_activity(client):
    client.post("/api/widgets", json={"type": "finance"})
    body = client.get("/api/events").json()
    assert any("Widget added" in e["message"] for e in body["events"])


def test_widget_and_event_routes_require_a_session_once_claimed(client, store):
    _claim(store)
    assert client.get("/api/widgets").status_code == 401
    assert client.get("/api/events").status_code == 401


# --- change review API (ROADMAP AA7-AA11) -------------------------------------------

@pytest.fixture
def change_log(tmp_path, monkeypatch):
    """Isolate the change log so tests never touch the real history."""
    import change_review
    fresh = change_review.ChangeLog(tmp_path / "changes.json")
    monkeypatch.setattr(change_review, "CHANGE_LOG", fresh)
    return fresh


@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/changes", None),
    ("post", "/api/changes", {"title": "x", "target": "settings"}),
    ("post", "/api/changes/abc/approve", {}),
    ("post", "/api/changes/abc/publish", {}),
    ("post", "/api/changes/abc/rollback", {}),
])
def test_change_routes_refuse_anonymous_callers(client, store, change_log, method, path, body):
    _claim(store)
    call = getattr(client, method)
    response = call(path, json=body) if body is not None else call(path)
    assert response.status_code in (401, 403), f"{path} was reachable anonymously"


@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/changes", None),
    ("post", "/api/changes", {"title": "x", "target": "settings"}),
    ("post", "/api/changes/abc/publish", {}),
])
def test_a_beta_tester_cannot_touch_changes(client, beta_token, change_log, method, path, body):
    call = getattr(client, method)
    response = (
        call(path, json=body, headers=_auth(beta_token)) if body is not None
        else call(path, headers=_auth(beta_token))
    )
    assert response.status_code == 403, f"beta tester reached {path}"


def test_the_owner_can_propose_and_publish_a_change(client, store, change_log):
    _claim(store)
    token = _login(client)

    proposed = client.post("/api/changes", json={
        "title": "Tweak the settings tab",
        "description": "smaller padding",
        "target": "settings",
        "content": "new",
        "previous_content": "old",
    }, headers=_auth(token))
    assert proposed.status_code == 200
    change_id = proposed.json()["change"]["id"]
    assert proposed.json()["change"]["status"] == "draft"

    # A draft must not be publishable.
    assert client.post(f"/api/changes/{change_id}/publish",
                       headers=_auth(token)).status_code == 400

    change_log.submit_for_review(change_id)
    assert client.post(f"/api/changes/{change_id}/approve",
                       headers=_auth(token)).status_code == 200
    published = client.post(f"/api/changes/{change_id}/publish", headers=_auth(token))
    assert published.status_code == 200
    assert published.json()["change"]["status"] == "published"


def test_only_the_owner_may_target_the_base_ai(client, store, change_log):
    """Admins can review and publish; rewriting the base AI is owner-only."""
    _claim(store)
    owner_token = _login(client)

    invite = client.post("/api/admin/invites", json={"role": "admin"},
                         headers=_auth(owner_token)).json()
    client.post("/api/auth/join", json={
        "invite": invite["token"], "email": "admin@example.com", "password": OTHER_PASSWORD})
    admin_token = _login(client, "admin@example.com", OTHER_PASSWORD)

    body = {"title": "Rewrite the core", "target": "base_ai", "content": "x"}
    assert client.post("/api/changes", json=body,
                       headers=_auth(admin_token)).status_code == 403
    assert client.post("/api/changes", json=body,
                       headers=_auth(owner_token)).status_code == 200


def test_a_change_without_a_target_is_rejected(client, store, change_log):
    _claim(store)
    response = client.post("/api/changes", json={"title": "x", "target": "  "},
                           headers=_auth(_login(client)))
    assert response.status_code == 400


# --- automatic self-revival on publish (ROADMAP F3) ---------------------------------

@pytest.fixture
def isolated_overlay(tmp_path, monkeypatch):
    import overlay as overlay_mod
    fresh = overlay_mod.OverlayStore(tmp_path / "overlay.json")
    monkeypatch.setattr(overlay_mod, "OVERLAY", fresh)
    return fresh


def _approved_change(client, change_log, token, target="settings"):
    change_id = client.post("/api/changes", json={
        "title": "A change", "target": target,
        "content": "new", "previous_content": "old",
    }, headers=_auth(token)).json()["change"]["id"]
    change_log.submit_for_review(change_id)
    client.post(f"/api/changes/{change_id}/approve", headers=_auth(token))
    return change_id


def test_publishing_applies_to_the_overlay(client, store, change_log, isolated_overlay):
    _claim(store)
    token = _login(client)
    change_id = _approved_change(client, change_log, token)

    published = client.post(f"/api/changes/{change_id}/publish", headers=_auth(token))
    assert published.status_code == 200
    assert isolated_overlay.get("settings") == "new"


def test_a_change_that_breaks_the_app_is_auto_reverted(client, store, change_log, isolated_overlay):
    """The core of F3: a bad change is undone inside the request that made it."""
    _claim(store)
    token = _login(client)
    change_id = _approved_change(client, change_log, token)

    with patch("health_check.run_health_check", return_value={
        "healthy": False, "failed": ["core_imports"], "results": [], "total_ms": 1.0,
    }):
        response = client.post(f"/api/changes/{change_id}/publish", headers=_auth(token))

    assert response.status_code == 409
    assert "core_imports" in response.json()["detail"]["failed"]
    # And crucially, the overlay is clean again.
    assert isolated_overlay.get("settings") is None


def test_an_auto_reverted_change_is_not_marked_published(client, store, change_log, isolated_overlay):
    """The record must not claim something is live when it was rolled back."""
    _claim(store)
    token = _login(client)
    change_id = _approved_change(client, change_log, token)

    with patch("health_check.run_health_check", return_value={
        "healthy": False, "failed": ["auth"], "results": [], "total_ms": 1.0,
    }):
        client.post(f"/api/changes/{change_id}/publish", headers=_auth(token))

    assert change_log.get(change_id).status.value == "approved"


def test_the_deep_health_endpoint_reports_the_real_system(client):
    body = client.get("/api/health/deep").json()
    assert body["healthy"] is True, body["failed"]
    assert any(r["name"] == "auth" for r in body["results"])


# --- the workspace is served by the API itself (ROADMAP BB12) ------------------------
#
# One process, one URL. Previously the UI needed a second terminal running Vite
# on :5173, so anything pointing a user at the app hit ERR_CONNECTION_REFUSED.

@pytest.mark.parametrize("path", ["/", "/app", "/app/", "/app/whatever"])
def test_the_workspace_is_served_at_the_root(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_the_workspace_html_is_the_built_app(client):
    assert '<div id="root">' in client.get("/").text


def test_serving_the_app_does_not_shadow_the_api(client):
    """The catch-all must never swallow an /api route."""
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/skills").status_code == 200


def test_the_built_assets_are_reachable(client):
    import re

    html = client.get("/").text
    assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
    assert assets, "the built page referenced no assets"
    for asset in assets:
        assert client.get(asset).status_code == 200


def test_health_still_answers_for_the_landing_page_probe(client):
    """The public site polls this to decide whether to enable its button."""
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert "claimed" in body


def test_google_sign_in_callback_is_the_only_public_google_route(client, store):
    """Request H7: Google redirects the browser back without a Nyx session, so the callback is public —
    guarded by a single-use state — while status/client/start stay owner-only."""
    _claim(store)
    assert "/api/google/oauth/callback" in server_auth.PUBLIC_PATHS
    assert client.get("/api/google/oauth/callback?state=nope&code=x").status_code != 401
    for method, path in (("get", "/api/google/oauth/status"), ("post", "/api/google/oauth/client"), ("post", "/api/google/oauth/start")):
        call = getattr(client, method)
        response = call(path, json={}) if method == "post" else call(path)
        assert response.status_code == 401, f"{path} was reachable anonymously"


# --- Request R: the tabs that see the screen, change Nyx, or let it act freely are the owner's --------------------

OWNER_ONLY_R_ROUTES = [
    ("get", "/api/screen", None),
    ("get", "/api/screen/frame", None),
    ("post", "/api/screen/start", {"source": {"kind": "screen", "index": 0}}),
    ("post", "/api/screen/ask", {"question": "what is this?"}),
    ("get", "/api/apply", None),
    ("post", "/api/apply", {"prompt": "add a tab"}),
    ("post", "/api/apply/rebuild", {}),
    ("get", "/api/freewill", None),
    ("post", "/api/freewill/decide", {"allow": True}),
    ("post", "/api/local-models/pull", {"name": "qwen3:8b"}),
    ("post", "/api/local-models/install", {}),
    ("post", "/api/absorb/start", {"mode": "auto"}),
]


@pytest.mark.parametrize("method,path,body", OWNER_ONLY_R_ROUTES)
def test_request_r_routes_refuse_anonymous_callers(client, store, method, path, body):
    _claim(store)
    call = getattr(client, method)
    response = call(path, json=body) if body is not None else call(path)
    assert response.status_code in (401, 403), f"{path} was reachable anonymously"


@pytest.mark.parametrize("method,path,body", OWNER_ONLY_R_ROUTES)
def test_a_beta_tester_cannot_reach_request_r_routes(client, beta_token, method, path, body):
    call = getattr(client, method)
    response = (call(path, json=body, headers=_auth(beta_token)) if body is not None
                else call(path, headers=_auth(beta_token)))
    assert response.status_code == 403, f"beta tester reached {path}"


def test_a_beta_tester_cannot_talk_to_free_will(client, beta_token):
    """The Free Will conversation goes through the ordinary chat stream, so the owner check lives there too."""
    response = client.post("/api/chat/stream", json={"message": "hi", "chat_id": "__freewill__", "use_rag": False},
                           headers=_auth(beta_token))
    assert response.status_code == 403


# --- Request S: Big Kahuna sees every answer and opens things on this PC — the owner's alone ------------------------

OWNER_ONLY_S_ROUTES = [
    ("get", "/api/identity0", None),
    ("get", "/api/identity0/settings", None),
    ("put", "/api/identity0/settings", {"changes": {"enabled": False}}),
    ("post", "/api/identity0/main", {}),
    ("get", "/api/identity0/competence", None),
    ("get", "/api/identity0/experiences", None),
    ("post", "/api/identity0/predict", {"text": "hi"}),
    ("get", "/api/identity0/companion", None),
    ("post", "/api/identity0/companion/ask", {"text": "hi"}),
    ("delete", "/api/identity0/companion", None),
    ("post", "/api/identity0/intent", {"text": "open gmail"}),
    ("post", "/api/identity0/warm", {}),
    ("post", "/api/identity0/act", {"action": {"kind": "open_url", "url": "https://www.youtube.com"}}),
    ("get", "/api/identity0/templates", None),
    ("get", "/api/identity0/templates/python-cli", None),
    ("post", "/api/identity0/templates/python-cli/use", {"folder": "C:/x"}),
    ("get", "/api/identity0/tabs", None),
    ("post", "/api/identity0/tabs/refresh", {}),
    ("post", "/api/identity0/tabs/abc/accept", {}),
    ("get", "/api/identity0/model", None),
    ("get", "/api/identity0/jobs", None),
    ("post", "/api/identity0/jobs", {"kind": "train_nano"}),
    ("post", "/api/identity0/jobs/train_nano-0000aaaa/cancel", {}),
    ("post", "/api/identity0/jobs/train_nano-0000aaaa/resume", {}),
    ("post", "/api/identity0/model/nano-v1/promote", {}),
    ("get", "/api/identity0/scoreboard", None),
    ("post", "/api/identity0/scoreboard/run", {"member": "ollama:qwen3.5:9b"}),
    ("get", "/api/identity0/constitution", None),
    ("put", "/api/identity0/constitution", {"changes": {"voice": "x"}}),
    ("post", "/api/identity0/constitution/abc/approve", {}),
]


@pytest.fixture
def admin_token(client, store):
    """An invited admin: allowed to run the engine, never allowed near Big Kahuna."""
    _claim(store)
    invite = client.post(
        "/api/admin/invites", json={"role": "admin"}, headers=_auth(_login(client))
    ).json()
    client.post("/api/auth/join", json={
        "invite": invite["token"], "email": "admin2@example.com", "password": OTHER_PASSWORD})
    return _login(client, "admin2@example.com", OTHER_PASSWORD)


@pytest.mark.parametrize("method,path,body", OWNER_ONLY_S_ROUTES)
def test_request_s_routes_refuse_anonymous_callers(client, store, method, path, body):
    _claim(store)
    call = getattr(client, method)
    response = call(path, json=body) if body is not None else call(path)
    assert response.status_code in (401, 403), f"{path} was reachable anonymously"


@pytest.mark.parametrize("method,path,body", OWNER_ONLY_S_ROUTES)
def test_a_beta_tester_cannot_reach_request_s_routes(client, beta_token, method, path, body):
    call = getattr(client, method)
    response = (call(path, json=body, headers=_auth(beta_token)) if body is not None
                else call(path, headers=_auth(beta_token)))
    assert response.status_code == 403, f"beta tester reached {path}"


@pytest.mark.parametrize("method,path,body", OWNER_ONLY_S_ROUTES)
def test_an_admin_cannot_reach_request_s_routes(client, admin_token, method, path, body):
    """Big Kahuna reads every answer and acts on this PC: it is the owner's, not any admin's."""
    call = getattr(client, method)
    response = (call(path, json=body, headers=_auth(admin_token)) if body is not None
                else call(path, headers=_auth(admin_token)))
    assert response.status_code == 403, f"an admin reached {path}"


def test_big_kahuna_routes_do_not_exist_on_a_hosted_build():
    import deploy_mode

    assert "/api/identity0" in deploy_mode.HOSTED_BLOCKED_PREFIXES


# --- Project Null N8: an office of agents spends the owner's keys and writes in their folders ----------------

OWNER_ONLY_OFFICE_ROUTES = [
    ("get", "/api/office", None),
    ("get", "/api/office/library", None),
    ("post", "/api/office/folders", {"name": "theirs"}),
    ("post", "/api/office/offices", {"name": "theirs"}),
    ("get", "/api/office/offices/ofc-nope", None),
    ("post", "/api/office/offices/ofc-nope/chat", {"text": "do something"}),
    ("post", "/api/office/offices/ofc-nope/say", {"text": "managers: hello"}),
    ("post", "/api/office/offices/ofc-nope/resolve", {"text": "managers"}),
    ("post", "/api/office/offices/ofc-nope/control", {"action": "halt"}),
    ("get", "/api/office/offices/ofc-nope/files", None),
    ("get", "/api/office/offices/ofc-nope/memory", None),
    ("post", "/api/office/items/fld-nope/reveal", None),
    ("get", "/api/office/focus", None),
    ("post", "/api/office/focus", {"action": "enter"}),
    ("get", "/api/office/settings", None),
    ("put", "/api/office/settings", {"changes": {"allow_web": False}}),
]


@pytest.mark.parametrize("method,path,body", OWNER_ONLY_OFFICE_ROUTES)
def test_office_routes_refuse_anonymous_callers(client, store, method, path, body):
    _claim(store)
    call = getattr(client, method)
    response = call(path, json=body) if body is not None else call(path)
    assert response.status_code in (401, 403), f"{path} was reachable anonymously"


@pytest.mark.parametrize("method,path,body", OWNER_ONLY_OFFICE_ROUTES)
def test_a_beta_tester_cannot_reach_the_office(client, beta_token, method, path, body):
    call = getattr(client, method)
    response = (call(path, json=body, headers=_auth(beta_token)) if body is not None
                else call(path, headers=_auth(beta_token)))
    assert response.status_code == 403, f"beta tester reached {path}"


def test_office_routes_do_not_exist_on_a_hosted_build():
    import deploy_mode

    assert "/api/office" in deploy_mode.HOSTED_BLOCKED_PREFIXES


# Proto Voice (Project Null N92): the microphone that may act on the computer.
OWNER_ONLY_PROTO_VOICE_ROUTES = [
    ("get", "/api/proto-voice", None),
    ("put", "/api/proto-voice", {"allowed": True}),
    ("post", "/api/proto-voice/act", {"text": "shut down the computer"}),
    ("post", "/api/proto-voice/confirm", {"token": "nope"}),
    ("post", "/api/proto-voice/simulate", {"text": "open notepad"}),
]


@pytest.mark.parametrize("method,path,body", OWNER_ONLY_PROTO_VOICE_ROUTES)
def test_proto_voice_routes_refuse_anonymous_callers(client, store, method, path, body):
    _claim(store)
    call = getattr(client, method)
    response = call(path, json=body) if body is not None else call(path)
    assert response.status_code in (401, 403), f"{path} was reachable anonymously"


@pytest.mark.parametrize("method,path,body", OWNER_ONLY_PROTO_VOICE_ROUTES)
def test_a_beta_tester_cannot_use_proto_voice(client, beta_token, method, path, body):
    call = getattr(client, method)
    response = (call(path, json=body, headers=_auth(beta_token)) if body is not None
                else call(path, headers=_auth(beta_token)))
    assert response.status_code == 403, f"beta tester reached {path}"


# The curiosity machine (N103) is the owner's own; the feature catalog is readable
# by any signed-in chat caller but only the owner may force a rescan (N100).
OWNER_ONLY_CURIOSITY_ROUTES = [
    ("get", "/api/curiosity", None),
    ("post", "/api/curiosity/ask", {"text": "what is this"}),
    ("post", "/api/curiosity/study", {"id": ""}),
    ("put", "/api/curiosity/settings", {"study_alone": True}),
    ("delete", "/api/curiosity/questions/nope", None),
    ("post", "/api/features/rescan", None),
]


@pytest.mark.parametrize("method,path,body", OWNER_ONLY_CURIOSITY_ROUTES)
def test_curiosity_routes_refuse_anonymous_callers(client, store, method, path, body):
    _claim(store)
    call = getattr(client, method)
    response = call(path, json=body) if body is not None else call(path)
    assert response.status_code in (401, 403), f"{path} was reachable anonymously"


@pytest.mark.parametrize("method,path,body", OWNER_ONLY_CURIOSITY_ROUTES)
def test_a_beta_tester_cannot_reach_the_third_mind(client, beta_token, method, path, body):
    call = getattr(client, method)
    response = (call(path, json=body, headers=_auth(beta_token)) if body is not None
                else call(path, headers=_auth(beta_token)))
    assert response.status_code == 403, f"beta tester reached {path}"
