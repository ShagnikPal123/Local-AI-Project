"""The owner's admin access server (OVERHAUL_CONTRACTS.md section 4.6).

Nyx itself (server.py) is the product; this is a second, small FastAPI app the
owner runs to mint and manage beta/dev access keys, review applications from
the public beta site, and see who has which role. It is deliberately separate
from server.py rather than a router mounted onto it:

* it binds to its own host/port (default 127.0.0.1:8765, `NYX_ADMIN_HOST` /
  `NYX_ADMIN_PORT`) so it can be turned off entirely, or exposed slightly wider
  than the main app, without touching the product surface a tester's install
  serves;
* its one unauthenticated route (`POST /apply`) needs CORS for the public beta
  site's origin - a policy that has no business anywhere near the main app's
  `/api/*` surface (AGENTS.md section 7: "never widen the CORS policy globally
  to fix one endpoint").

Auth model: loopback-only by default (see `_require_admin`). Once the install
is claimed (an owner account exists - `server_auth.is_claimed()`), a caller
must present a valid admin/owner session via an HttpOnly, SameSite=Strict
cookie obtained from `POST /login`; until then, whoever is at the keyboard
(loopback) is trusted, mirroring `server.require_local_owner`'s reasoning -
an unclaimed install has no account that *could* hold the permission, and a
useful instance cannot be deployed without claiming it first.

`start_in_thread()` lets the tray launcher run this alongside the main engine
without a second console window; `python admin_server.py` runs it standalone
for local development.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import access_keys

_SESSION_COOKIE = "nyx_admin_session"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_SESSION_MAX_AGE = 60 * 60 * 12  # matches auth.AuthStore's own session TTL

_RATE_LIMIT_WINDOW_SECONDS = 3600.0
_RATE_LIMIT_MAX_PER_WINDOW = 5

app = FastAPI(title="Nyx Ichos — Admin", docs_url=None, redoc_url=None, openapi_url=None)

# In-memory only, per the contract - a restart resetting the counters is an
# acceptable trade for not needing a persistent store for something this
# cheap to abuse into a spam problem otherwise.
_rate_lock = threading.Lock()
_rate_buckets: Dict[str, List[float]] = {}


class AdminCaller:
    """Who is making an admin-console request, resolved by `_require_admin`.

    `token` is the raw session token (empty on an unclaimed loopback install,
    where there is no session at all) - callers that need to delegate to
    `AuthStore`'s token-authorising methods (invites, grants) pass it straight
    through rather than this module reaching into `AuthStore`'s private state.
    """

    __slots__ = ("user", "token", "label")

    def __init__(self, user: Any, token: str, label: str) -> None:
        self.user = user
        self.token = token
        self.label = label


def _client_host(request: Request) -> str:
    return request.client.host if request.client else ""


def _require_admin(request: Request) -> AdminCaller:
    """Loopback-only pre-claim; a valid admin/owner cookie session after."""
    from server_auth import AUTH_STORE, is_claimed

    if not is_claimed():
        host = _client_host(request)
        if host in _LOOPBACK_HOSTS:
            return AdminCaller(user=None, token="", label=f"owner@{host or 'local'}")
        raise HTTPException(
            status_code=403,
            detail="This admin console can only be reached from this computer until Nyx is claimed.",
        )

    from auth import Permission, has_permission

    token = request.cookies.get(_SESSION_COOKIE, "") or ""
    user = AUTH_STORE.resolve_session(token) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in required.")
    if not has_permission(user.role, Permission.VIEW_ADMIN):
        raise HTTPException(status_code=403, detail="Admin access required.")
    return AdminCaller(user=user, token=token, label=user.email)


# ---------------------------------------------------------------------------
# Login / logout / health
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: str = ""
    password: str = ""


@app.post("/login")
def login(body: LoginRequest, response: Response) -> Dict[str, Any]:
    from auth import AuthError, Permission, has_permission
    from server_auth import AUTH_STORE, is_claimed

    if not is_claimed():
        raise HTTPException(
            status_code=400,
            detail="Nyx has not been claimed yet - open this console from the machine running Nyx.",
        )
    try:
        token = AUTH_STORE.authenticate(body.email, body.password)
    except AuthError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error

    user = AUTH_STORE.resolve_session(token)
    if user is None or not has_permission(user.role, Permission.VIEW_ADMIN):
        AUTH_STORE.logout(token)
        raise HTTPException(status_code=403, detail="Admin access required.")

    # HttpOnly + SameSite=Strict: the cookie is invisible to page JS and is
    # never attached to a cross-site request, so a malicious page cannot ride
    # the owner's session to mint keys or change roles. `secure` is left off
    # by default because this console is meant for http://127.0.0.1; set
    # NYX_ADMIN_HTTPS=1 when it is actually served over TLS.
    response.set_cookie(
        _SESSION_COOKIE, token, httponly=True, samesite="strict",
        secure=bool(os.getenv("NYX_ADMIN_HTTPS")), max_age=_SESSION_MAX_AGE,
    )
    access_keys.audit(user.email, "login", user.email, "")
    return {"ok": True, "email": user.email, "role": user.role.value}


@app.post("/logout")
def logout(request: Request, response: Response) -> Dict[str, Any]:
    from server_auth import AUTH_STORE

    token = request.cookies.get(_SESSION_COOKIE, "")
    if token:
        AUTH_STORE.logout(token)
    response.delete_cookie(_SESSION_COOKIE)
    return {"ok": True}


@app.get("/health")
def health() -> Dict[str, Any]:
    from server_auth import is_claimed

    return {"status": "ok", "claimed": is_claimed()}


# ---------------------------------------------------------------------------
# Users & roles, invites - thin wrappers over auth.AuthStore
# ---------------------------------------------------------------------------


@app.get("/admin/api/users")
def list_users(_caller: AdminCaller = Depends(_require_admin)) -> Dict[str, Any]:
    from server_auth import AUTH_STORE

    # `.public()` already strips password hash/salt and tokens (auth.py's
    # own contract) - nothing further to redact here.
    return {"users": [u.public() for u in AUTH_STORE.users.values()]}


class GrantRoleRequest(BaseModel):
    email: str
    role: str


@app.post("/admin/api/users/grant")
def grant_role(body: GrantRoleRequest, caller: AdminCaller = Depends(_require_admin)) -> Dict[str, Any]:
    from auth import AuthError
    from auth import Role as RoleEnum
    from server_auth import AUTH_STORE

    try:
        role = RoleEnum(body.role)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=f"Unknown role {body.role!r}.") from error
    try:
        user = AUTH_STORE.grant_role_as(caller.user, body.email, role)
    except AuthError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    access_keys.audit(caller.label, "grant_role", body.email, role.value)
    return {"user": user.public()}


@app.get("/admin/api/invites")
def list_invites(caller: AdminCaller = Depends(_require_admin)) -> Dict[str, Any]:
    if not caller.token:
        return {"invites": []}  # nobody to invite yet on an unclaimed install
    from auth import AuthError
    from server_auth import AUTH_STORE

    try:
        return {"invites": AUTH_STORE.list_invites(caller.token)}
    except AuthError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


class InviteRequest(BaseModel):
    role: str = "beta"
    email: str = ""


@app.post("/admin/api/invites")
def create_invite(body: InviteRequest, caller: AdminCaller = Depends(_require_admin)) -> Dict[str, Any]:
    if not caller.token:
        raise HTTPException(status_code=400, detail="Claim this install before inviting anyone.")
    from auth import AuthError
    from auth import Role as RoleEnum
    from server_auth import AUTH_STORE

    try:
        role = RoleEnum(body.role)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=f"Unknown role {body.role!r}.") from error
    try:
        invite = AUTH_STORE.create_invite(caller.token, role, body.email)
    except AuthError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    access_keys.audit(caller.label, "create_invite", invite.token, role.value)
    return {
        "token": invite.token, "role": invite.role.value,
        "email": invite.email, "expires_at": invite.expires_at,
    }


@app.post("/admin/api/invites/{token}/revoke")
def revoke_invite(token: str, caller: AdminCaller = Depends(_require_admin)) -> Dict[str, Any]:
    if not caller.token:
        raise HTTPException(status_code=400, detail="Claim this install before managing invites.")
    from auth import AuthError
    from server_auth import AUTH_STORE

    try:
        AUTH_STORE.revoke_invite(caller.token, token)
    except AuthError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    access_keys.audit(caller.label, "revoke_invite", token, "")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Access keys, applications, flags, audit - straight to access_keys.py
# ---------------------------------------------------------------------------


class MintRequest(BaseModel):
    role: str
    name: str = ""
    email: str = ""
    days: int = 90
    features: Optional[List[str]] = None
    notes: str = ""


@app.post("/admin/api/mint")
def admin_mint(body: MintRequest, caller: AdminCaller = Depends(_require_admin)) -> Dict[str, Any]:
    try:
        return access_keys.mint(
            body.role, body.name, email=body.email, days=body.days,
            features=body.features, notes=body.notes, actor=caller.label,
        )
    except access_keys.AccessKeyError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/admin/api/minted")
def admin_minted(_caller: AdminCaller = Depends(_require_admin)) -> Dict[str, Any]:
    return access_keys.list_minted()


@app.post("/admin/api/revoke/{key_id}")
def admin_revoke(key_id: str, caller: AdminCaller = Depends(_require_admin)) -> Dict[str, Any]:
    return access_keys.revoke(key_id, actor=caller.label)


@app.get("/admin/api/applications")
def admin_applications(_caller: AdminCaller = Depends(_require_admin)) -> Dict[str, Any]:
    return access_keys.list_applications()


class DecisionRequest(BaseModel):
    approve: bool
    days: int = 90


@app.post("/admin/api/applications/{app_id}/decision")
def admin_decision(
    app_id: str, body: DecisionRequest, caller: AdminCaller = Depends(_require_admin)
) -> Dict[str, Any]:
    try:
        return access_keys.decide_application(app_id, body.approve, actor=caller.label, days=body.days)
    except access_keys.AccessKeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/admin/api/flags")
def admin_get_flags(_caller: AdminCaller = Depends(_require_admin)) -> Dict[str, Any]:
    return {"flags": access_keys.get_flags()}


class FlagsRequest(BaseModel):
    flags: Dict[str, bool] = {}


@app.post("/admin/api/flags")
def admin_set_flags(body: FlagsRequest, caller: AdminCaller = Depends(_require_admin)) -> Dict[str, Any]:
    return {"flags": access_keys.set_flags(body.flags, actor=caller.label)}


@app.get("/admin/api/audit")
def admin_audit(limit: int = 200, _caller: AdminCaller = Depends(_require_admin)) -> Dict[str, Any]:
    return {"audit": access_keys.read_audit(limit)}


@app.get("/admin/api/overview")
def admin_overview(_caller: AdminCaller = Depends(_require_admin)) -> Dict[str, Any]:
    """Counts for the console's landing panel.

    "Redemptions last 7 days" can only ever reflect what this install can
    observe. Nyx has no telemetry and no phone-home (AGENTS.md), and every
    tester runs their own copy - so a key minted here that gets redeemed on
    someone else's machine is invisible to the owner's install by design.
    The only redemptions this count can see are ones recorded against this
    install's own minted registry (access_keys.redeem() does that whenever a
    key it verifies also happens to be one this install minted).
    """
    from server_auth import AUTH_STORE

    users_by_role: Dict[str, int] = {}
    for user in AUTH_STORE.users.values():
        users_by_role[user.role.value] = users_by_role.get(user.role.value, 0) + 1

    minted = access_keys.list_minted()["keys"]
    now = time.time()
    cutoff = now - 7 * 86400
    keys_by_role: Dict[str, int] = {}
    active = revoked = expired = 0
    redemptions_7d = 0
    for record in minted:
        role = record.get("role", "unknown")
        keys_by_role[role] = keys_by_role.get(role, 0) + 1
        if record.get("revoked"):
            revoked += 1
        elif record.get("exp") and record["exp"] < now:
            expired += 1
        else:
            active += 1
        for redemption in record.get("redemptions", []) or []:
            if redemption.get("redeemed_at", 0) >= cutoff:
                redemptions_7d += 1

    applications = access_keys.list_applications()["applications"]
    pending = sum(1 for application in applications if application.get("status") == "pending")

    return {
        "users_by_role": users_by_role,
        "keys": {
            "by_role": keys_by_role, "active": active, "revoked": revoked,
            "expired": expired, "total": len(minted),
        },
        "applications_pending": pending,
        "redemptions_last_7_days": redemptions_7d,
    }


# ---------------------------------------------------------------------------
# Public intake - the one unauthenticated write in this app
# ---------------------------------------------------------------------------


def _allowed_apply_origins() -> set:
    """Read fresh on every request (not cached at import) so ops can change
    NYX_BETA_SITE_ORIGINS without a restart, and tests can monkeypatch it."""
    raw = os.getenv("NYX_BETA_SITE_ORIGINS", "")
    origins = {origin.strip() for origin in raw.split(",") if origin.strip()}
    # "null" is the Origin a page opened via file:// sends; the localhost
    # entries are for testing the beta site against a local admin server.
    origins.update({"null", "http://localhost", "http://127.0.0.1"})
    return origins


@app.middleware("http")
async def _apply_cors(request: Request, call_next):
    """CORS, scoped to exactly one route.

    FastAPI's CORSMiddleware bakes its allow-list in at construction time, so
    it cannot see an env var read later (or changed by a test). This computes
    the allow-list per request instead, and only touches responses for
    `/apply` - every other route in this app is same-origin (this app serves
    its own admin console) and must not get a permissive CORS header.
    """
    if request.url.path != "/apply":
        return await call_next(request)

    origin = request.headers.get("origin", "")
    allowed = bool(origin) and origin in _allowed_apply_origins()

    if request.method == "OPTIONS":
        response = Response(status_code=200)
    else:
        response = await call_next(request)

    if allowed:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


def _rate_limited(ip: str) -> bool:
    now = time.time()
    with _rate_lock:
        recent = [t for t in _rate_buckets.get(ip, []) if now - t < _RATE_LIMIT_WINDOW_SECONDS]
        if len(recent) >= _RATE_LIMIT_MAX_PER_WINDOW:
            _rate_buckets[ip] = recent
            return True
        recent.append(now)
        _rate_buckets[ip] = recent
        return False


class ApplyRequest(BaseModel):
    name: str = ""
    email: str = ""
    role: str = "beta"
    reason: str = ""
    links: str = ""
    website: str = ""  # honeypot: a real visitor never fills this in


@app.post("/apply")
def apply(body: ApplyRequest, request: Request) -> Dict[str, Any]:
    if body.website.strip():
        # Tripped honeypot: report success (so a bot has no signal to react
        # to and adapt around) without creating anything.
        return {"ok": True}

    ip = _client_host(request) or "unknown"
    if _rate_limited(ip):
        raise HTTPException(
            status_code=429, detail="Too many applications from this address - try again later."
        )

    try:
        record = access_keys.submit_application(
            body.name, body.email, body.role, reason=body.reason, links=body.links, source_ip=ip,
        )
    except access_keys.AccessKeyError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"ok": True, "id": record["id"]}


# ---------------------------------------------------------------------------
# The console itself - one static page, inline JS, no build step.
#
# Semantic markup with class names rather than decoration: the owner plans to
# restyle this later (OVERHAUL_CONTRACTS.md), so the HTML should describe what
# each piece *is* (a table of applications, a mint form) rather than how it
# looks.
# ---------------------------------------------------------------------------

_CONSOLE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nyx Ichos — Admin</title>
<style>
  :root{ --bg:#161826; --surface:#232532; --nav:#12141f; --text:#e9e9ed;
    --accent:#9184d9; --n400:#b2b6ca; --n500:#9397ab; --n600:#75798c;
    --ok:#5ac08a; --warn:#e0b45a; --bad:#e07a7a; --divider:#33364a; }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
    line-height:1.5}
  header{padding:18px 24px;border-bottom:1px solid var(--divider);display:flex;align-items:center;justify-content:space-between}
  header h1{font-size:16px;margin:0}
  header .status{font-size:12px;color:var(--n500)}
  nav.tabs{display:flex;gap:4px;padding:12px 24px 0;border-bottom:1px solid var(--divider)}
  nav.tabs button{background:none;border:0;color:var(--n500);padding:10px 14px;font-size:13px;cursor:pointer;border-bottom:2px solid transparent}
  nav.tabs button[aria-selected="true"]{color:var(--text);border-bottom-color:var(--accent)}
  main{padding:20px 24px;max-width:1100px;margin:0 auto}
  section[data-panel]{display:none}
  section[data-panel].active{display:block}
  h2{font-size:15px;margin:0 0 12px}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-bottom:20px}
  .card{background:var(--surface);border-radius:8px;padding:14px}
  .card b{display:block;font-size:22px}
  .card span{font-size:12px;color:var(--n500)}
  table{width:100%;border-collapse:collapse;font-size:13px;background:var(--surface);border-radius:8px;overflow:hidden}
  th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--divider)}
  th{color:var(--n500);font-weight:500;font-size:11px;text-transform:uppercase}
  tr:last-child td{border-bottom:0}
  form.inline{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px;align-items:flex-end}
  form.inline label{display:flex;flex-direction:column;font-size:11px;color:var(--n500);gap:4px}
  input,select,textarea{background:var(--nav);border:1px solid var(--divider);color:var(--text);
    border-radius:6px;padding:7px 9px;font-size:13px;font-family:inherit}
  textarea{width:100%;min-height:60px}
  button.action{background:var(--accent);color:#14121f;border:0;border-radius:6px;padding:8px 14px;font-size:13px;cursor:pointer}
  button.action.secondary{background:var(--nav);color:var(--text);box-shadow:inset 0 0 0 1px var(--divider)}
  button.action.danger{background:var(--bad);color:#2a1414}
  button.small{font-size:12px;padding:5px 9px}
  .pill{display:inline-block;padding:2px 8px;border-radius:99px;font-size:11px}
  .pill.ok{background:rgba(90,192,138,.18);color:var(--ok)}
  .pill.bad{background:rgba(224,122,122,.18);color:var(--bad)}
  .pill.warn{background:rgba(224,180,90,.18);color:var(--warn)}
  .msg{font-size:12px;color:var(--n500);margin:8px 0}
  code{font-family:"JetBrains Mono",Consolas,monospace;font-size:12px;background:var(--nav);padding:2px 5px;border-radius:4px;word-break:break-all}
  #login-gate{max-width:320px;margin:80px auto;padding:24px;background:var(--surface);border-radius:10px}
  #login-gate h2{margin-top:0}
  #login-gate label{display:block;font-size:12px;color:var(--n500);margin:10px 0 4px}
  #login-gate input{width:100%}
  .hidden{display:none !important}
</style>
</head>
<body>

<div id="login-gate" class="hidden">
  <h2>Sign in</h2>
  <p class="msg">This console needs an owner or admin session once Nyx has been claimed.</p>
  <label>Email<input id="login-email" type="email" autocomplete="username"></label>
  <label>Password<input id="login-password" type="password" autocomplete="current-password"></label>
  <p class="msg" id="login-error"></p>
  <button class="action" id="login-submit" style="width:100%;margin-top:6px">Sign in</button>
</div>

<div id="app" class="hidden">
  <header>
    <h1>Nyx Ichos — Admin</h1>
    <span class="status" id="claim-status"></span>
  </header>
  <nav class="tabs">
    <button data-tab="overview" aria-selected="true">Overview</button>
    <button data-tab="applications">Applications</button>
    <button data-tab="mint">Mint</button>
    <button data-tab="keys">Keys</button>
    <button data-tab="users">Users</button>
    <button data-tab="flags">Flags</button>
    <button data-tab="audit">Audit</button>
  </nav>
  <main>

    <section data-panel="overview" class="active">
      <h2>Overview</h2>
      <div class="cards" id="overview-cards"></div>
    </section>

    <section data-panel="applications">
      <h2>Applications</h2>
      <table>
        <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Reason</th><th>Status</th><th></th></tr></thead>
        <tbody id="applications-body"></tbody>
      </table>
    </section>

    <section data-panel="mint">
      <h2>Mint a key</h2>
      <form class="inline" id="mint-form">
        <label>Role
          <select name="role"><option value="beta">beta</option><option value="dev">dev</option></select>
        </label>
        <label>Name<input name="name" required></label>
        <label>Email<input name="email" type="email"></label>
        <label>Days (0 = never expires)<input name="days" type="number" value="90"></label>
        <button class="action" type="submit">Mint</button>
      </form>
      <div id="mint-result"></div>
    </section>

    <section data-panel="keys">
      <h2>Minted keys</h2>
      <table>
        <thead><tr><th>Name</th><th>Role</th><th>Email</th><th>Expires</th><th>Status</th><th></th></tr></thead>
        <tbody id="keys-body"></tbody>
      </table>
    </section>

    <section data-panel="users">
      <h2>Users</h2>
      <table>
        <thead><tr><th>Email</th><th>Role</th><th>Change role</th></tr></thead>
        <tbody id="users-body"></tbody>
      </table>
    </section>

    <section data-panel="flags">
      <h2>Feature flags</h2>
      <form class="inline" id="flag-form">
        <label>Flag name<input name="name" required></label>
        <label>Value
          <select name="value"><option value="true">on</option><option value="false">off</option></select>
        </label>
        <button class="action" type="submit">Set</button>
      </form>
      <table><thead><tr><th>Flag</th><th>Value</th></tr></thead><tbody id="flags-body"></tbody></table>
    </section>

    <section data-panel="audit">
      <h2>Audit log</h2>
      <table>
        <thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Target</th><th>Detail</th></tr></thead>
        <tbody id="audit-body"></tbody>
      </table>
    </section>

  </main>
</div>

<script>
"use strict";

async function api(path, opts) {
  const response = await fetch(path, Object.assign({ credentials: "same-origin" }, opts || {}));
  if (response.status === 401) { showLoginGate(); throw new Error("Sign in required."); }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || ("Request failed (" + response.status + ")"));
  return body;
}

function el(tag, attrs, children) {
  const node = document.createElement(tag);
  Object.entries(attrs || {}).forEach(([key, value]) => {
    if (key === "text") node.textContent = value; else node.setAttribute(key, value);
  });
  (children || []).forEach((child) => node.appendChild(child));
  return node;
}

function showLoginGate() {
  document.getElementById("login-gate").classList.remove("hidden");
  document.getElementById("app").classList.add("hidden");
}

function showApp() {
  document.getElementById("login-gate").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");
}

// --- tabs --------------------------------------------------------------

document.querySelectorAll("nav.tabs button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("nav.tabs button").forEach((b) => b.setAttribute("aria-selected", "false"));
    button.setAttribute("aria-selected", "true");
    document.querySelectorAll("section[data-panel]").forEach((s) => s.classList.remove("active"));
    document.querySelector('section[data-panel="' + button.dataset.tab + '"]').classList.add("active");
    loadPanel(button.dataset.tab);
  });
});

// --- login ---------------------------------------------------------------

document.getElementById("login-submit").addEventListener("click", async () => {
  const email = document.getElementById("login-email").value;
  const password = document.getElementById("login-password").value;
  const errorEl = document.getElementById("login-error");
  errorEl.textContent = "";
  try {
    await api("/login", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }) });
    showApp();
    loadPanel("overview");
  } catch (error) {
    errorEl.textContent = error.message;
  }
});

// --- panels ----------------------------------------------------------------

async function loadOverview() {
  const body = await api("/admin/api/overview");
  const cards = document.getElementById("overview-cards");
  cards.innerHTML = "";
  const entries = [
    ["Pending applications", body.applications_pending],
    ["Active keys", body.keys.active],
    ["Revoked keys", body.keys.revoked],
    ["Expired keys", body.keys.expired],
    ["Redemptions (7d, this install)", body.redemptions_last_7_days],
  ];
  entries.forEach(([label, value]) => {
    cards.appendChild(el("div", { class: "card" }, [
      el("b", { text: String(value) }), el("span", { text: label }),
    ]));
  });
}

async function loadApplications() {
  const body = await api("/admin/api/applications");
  const tbody = document.getElementById("applications-body");
  tbody.innerHTML = "";
  body.applications.forEach((application) => {
    const row = el("tr", {}, [
      el("td", { text: application.name }), el("td", { text: application.email }),
      el("td", { text: application.role }), el("td", { text: application.reason || "" }),
      el("td", {}, [el("span", { class: "pill " + (application.status === "pending" ? "warn" : application.status === "approved" ? "ok" : "bad"), text: application.status })]),
    ]);
    const actions = el("td", {});
    if (application.status === "pending") {
      const approve = el("button", { class: "action small", text: "Approve" });
      approve.addEventListener("click", async () => {
        await api("/admin/api/applications/" + application.id + "/decision", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approve: true, days: 90 }),
        });
        loadApplications(); loadOverview();
      });
      const reject = el("button", { class: "action small secondary", text: "Reject" });
      reject.addEventListener("click", async () => {
        await api("/admin/api/applications/" + application.id + "/decision", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approve: false }),
        });
        loadApplications(); loadOverview();
      });
      actions.appendChild(approve); actions.appendChild(reject);
    }
    row.appendChild(actions);
    tbody.appendChild(row);
  });
}

async function loadKeys() {
  const body = await api("/admin/api/minted");
  const tbody = document.getElementById("keys-body");
  tbody.innerHTML = "";
  body.keys.forEach((key) => {
    const status = key.revoked ? "bad" : (key.exp && key.exp < Date.now() / 1000 ? "warn" : "ok");
    const statusText = key.revoked ? "revoked" : (key.exp && key.exp < Date.now() / 1000 ? "expired" : "active");
    const row = el("tr", {}, [
      el("td", { text: key.name }), el("td", { text: key.role }), el("td", { text: key.email || "" }),
      el("td", { text: key.exp ? new Date(key.exp * 1000).toLocaleDateString() : "never" }),
      el("td", {}, [el("span", { class: "pill " + status, text: statusText })]),
    ]);
    const actions = el("td", {});
    const copy = el("button", { class: "action small secondary", text: "Copy invite" });
    copy.addEventListener("click", () => {
      const link = "nyx://redeem?key=" + key.key;
      navigator.clipboard?.writeText(key.key + "\\n\\n" + link).catch(() => {});
    });
    actions.appendChild(copy);
    if (!key.revoked) {
      const revoke = el("button", { class: "action small danger", text: "Revoke" });
      revoke.addEventListener("click", async () => {
        await api("/admin/api/revoke/" + key.id, { method: "POST" });
        loadKeys(); loadOverview();
      });
      actions.appendChild(revoke);
    }
    row.appendChild(actions);
    tbody.appendChild(row);
  });
}

async function loadUsers() {
  const body = await api("/admin/api/users");
  const tbody = document.getElementById("users-body");
  tbody.innerHTML = "";
  body.users.forEach((user) => {
    const select = el("select", {}, ["owner", "admin", "beta", "user"].map((role) => {
      const option = el("option", { value: role, text: role });
      if (role === user.role) option.setAttribute("selected", "selected");
      return option;
    }));
    select.addEventListener("change", async () => {
      await api("/admin/api/users/grant", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: user.email, role: select.value }),
      });
      loadUsers();
    });
    tbody.appendChild(el("tr", {}, [
      el("td", { text: user.email }), el("td", { text: user.role }), el("td", {}, [select]),
    ]));
  });
}

async function loadFlags() {
  const body = await api("/admin/api/flags");
  const tbody = document.getElementById("flags-body");
  tbody.innerHTML = "";
  Object.entries(body.flags).forEach(([name, value]) => {
    tbody.appendChild(el("tr", {}, [el("td", { text: name }), el("td", { text: String(value) })]));
  });
}

async function loadAudit() {
  const body = await api("/admin/api/audit");
  const tbody = document.getElementById("audit-body");
  tbody.innerHTML = "";
  body.audit.forEach((entry) => {
    tbody.appendChild(el("tr", {}, [
      el("td", { text: new Date(entry.ts * 1000).toLocaleString() }),
      el("td", { text: entry.actor }), el("td", { text: entry.action }),
      el("td", { text: entry.target || "" }), el("td", { text: entry.detail || "" }),
    ]));
  });
}

function loadPanel(name) {
  const loaders = {
    overview: loadOverview, applications: loadApplications, keys: loadKeys,
    users: loadUsers, flags: loadFlags, audit: loadAudit, mint: () => {},
  };
  (loaders[name] || (() => {}))().catch((error) => console.error(error));
}

document.getElementById("mint-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    const result = await api("/admin/api/mint", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        role: form.get("role"), name: form.get("name"), email: form.get("email"),
        days: Number(form.get("days") || 90),
      }),
    });
    document.getElementById("mint-result").innerHTML = "";
    document.getElementById("mint-result").appendChild(el("div", { class: "msg" }, [
      document.createTextNode("Key minted. "), el("code", { text: result.key }),
    ]));
    loadOverview();
  } catch (error) {
    document.getElementById("mint-result").textContent = error.message;
  }
});

document.getElementById("flag-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const flags = {};
  flags[form.get("name")] = form.get("value") === "true";
  await api("/admin/api/flags", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ flags }),
  });
  loadFlags();
});

// --- boot --------------------------------------------------------------

(async () => {
  try {
    const health = await fetch("/health").then((r) => r.json());
    document.getElementById("claim-status").textContent = health.claimed ? "claimed" : "unclaimed (local owner)";
    await api("/admin/api/overview");
    showApp();
    loadPanel("overview");
  } catch (error) {
    showLoginGate();
  }
})();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def console() -> str:
    return _CONSOLE_HTML


# ---------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------


def start_in_thread(port: Optional[int] = None):
    """Start this app on a background thread; returns (uvicorn.Server, port).

    Used by the tray launcher to run the admin console alongside the main
    engine without a second console window. Call `.should_exit = True` on the
    returned server to stop it (the standard uvicorn.Server shutdown signal).
    """
    import uvicorn

    host = os.getenv("NYX_ADMIN_HOST", "127.0.0.1")
    resolved_port = port if port else int(os.getenv("NYX_ADMIN_PORT", "8765"))
    config = uvicorn.Config(app, host=host, port=resolved_port, log_level="warning")
    server_instance = uvicorn.Server(config)
    thread = threading.Thread(target=server_instance.run, name="nyx-admin-server", daemon=True)
    thread.start()
    return server_instance, resolved_port


if __name__ == "__main__":
    import uvicorn

    _host = os.getenv("NYX_ADMIN_HOST", "127.0.0.1")
    _port = int(os.getenv("NYX_ADMIN_PORT", "8765"))
    print(f"Nyx Ichos — Admin console: http://{_host}:{_port}/")
    uvicorn.run(app, host=_host, port=_port)
