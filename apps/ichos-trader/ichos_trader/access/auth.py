"""Logins: local, a passcode, or Google / GitHub, with owners and viewers.

Shagnik wants others to be able to *see* the setup but never use his keys or his account. So:

* **Owner** - may change anything. Only people named in ``ICHOS_OWNER_EMAILS`` (Google) or
  ``ICHOS_OWNER_GITHUB`` (GitHub), or anyone who knows ``ICHOS_PASSCODE``.
* **Viewer** - anyone else who signs in. Reads the dashboard; every change is refused.
* **Local** - with no login configured, the trader trusts only the PC it runs on (a request from
  127.0.0.1 is the owner) and refuses everyone else. That keeps the one-click local app simple
  without leaving a cloud copy open by mistake.

A session is a signed cookie (HMAC-SHA256) holding the name, the role and an expiry. The signing
key comes from ``ICHOS_SESSION_SECRET`` or is made once and kept in the gitignored data folder.
The OAuth requests go through an injectable ``requests`` session so tests never touch the network.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets as token_maker
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests

from . import secrets

COOKIE = "ichos_session"
STATE_COOKIE = "ichos_oauth_state"
SESSION_DAYS = 14
LOOPBACK = {"127.0.0.1", "::1", "localhost"}

PROVIDERS = {
    "google": {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "user": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
    },
    "github": {
        "authorize": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "user": "https://api.github.com/user",
        "scope": "read:user user:email",
    },
}


class AuthError(Exception):
    """A login that failed, with a sentence the person can read."""


def _list(name: str) -> List[str]:
    return [x.strip().lower() for x in os.environ.get(name, "").split(",") if x.strip()]


def providers() -> List[str]:
    return [p for p in PROVIDERS if secrets.get(f"{p}_client_id") and secrets.get(f"{p}_client_secret")]


def mode() -> str:
    """"google"/"github" when OAuth is set up, else "passcode" when one is set, else "local"."""
    found = providers()
    if found:
        return found[0]
    return "passcode" if secrets.get("passcode") else "local"


def _key() -> bytes:
    key = secrets.get("session_secret")
    if not key:
        key = token_maker.token_urlsafe(32)
        secrets.put("session_secret", key)
    return key.encode()


def sign(data: Dict[str, Any]) -> str:
    body = base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode().rstrip("=")
    mac = hmac.new(_key(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{mac}"


def unsign(token: Optional[str]) -> Optional[Dict[str, Any]]:
    if not token or "." not in token:
        return None
    body, mac = token.rsplit(".", 1)
    if not hmac.compare_digest(mac, hmac.new(_key(), body.encode(), hashlib.sha256).hexdigest()):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (ValueError, json.JSONDecodeError):
        return None
    return data if float(data.get("exp", 0)) > time.time() else None


def session_for(name: str, role: str, email: str = "", login: str = "", provider: str = "") -> str:
    return sign({"name": name, "role": role, "email": email, "login": login, "provider": provider,
                 "exp": time.time() + SESSION_DAYS * 86_400})


def role_for(email: str = "", login: str = "") -> str:
    owners, github = _list("ICHOS_OWNER_EMAILS"), _list("ICHOS_OWNER_GITHUB")
    if email and email.lower() in owners:
        return "owner"
    if login and login.lower() in github:
        return "owner"
    return "viewer"


def current_user(cookie: Optional[str], client_host: str) -> Optional[Dict[str, Any]]:
    """The signed-in person, or the local owner, or None (not allowed in)."""
    user = unsign(cookie)
    if user:
        return user
    if mode() == "local" and client_host in LOOPBACK:
        return {"name": "Owner", "role": "owner", "email": "", "login": "", "provider": "local"}
    return None


def check_passcode(given: str) -> bool:
    real = secrets.get("passcode")
    return bool(real) and hmac.compare_digest(str(given or "").encode(), real.encode())


# --- OAuth ------------------------------------------------------------------------------------

def login_url(provider: str, redirect_uri: str) -> Dict[str, str]:
    """Where to send the browser, and the state value to keep in a cookie until it comes back."""
    if provider not in providers():
        raise AuthError(f"{provider.title()} login is not set up on this trader.")
    state = token_maker.token_urlsafe(24)
    query = {"client_id": secrets.get(f"{provider}_client_id"), "redirect_uri": redirect_uri,
             "scope": PROVIDERS[provider]["scope"], "state": state}
    if provider == "google":
        query.update(response_type="code", prompt="select_account")
    return {"url": PROVIDERS[provider]["authorize"] + "?" + urlencode(query), "state": state}


def finish_login(provider: str, code: str, redirect_uri: str, http: Optional[requests.Session] = None) -> str:
    """Swap the code for the person's name and address; returns a session cookie value."""
    if provider not in providers():
        raise AuthError(f"{provider.title()} login is not set up on this trader.")
    http = http or requests.Session()
    urls = PROVIDERS[provider]
    form = {"client_id": secrets.get(f"{provider}_client_id"), "client_secret": secrets.get(f"{provider}_client_secret"),
            "code": code, "redirect_uri": redirect_uri, "grant_type": "authorization_code"}
    try:
        token = http.post(urls["token_url"], data=form, headers={"Accept": "application/json"}, timeout=10).json()
        access = token.get("access_token")
        if not access:
            raise AuthError("The login was refused. Please try again.")
        headers = {"Authorization": f"Bearer {access}", "Accept": "application/json"}
        me = http.get(urls["user"], headers=headers, timeout=10).json()
        email, login = (me.get("email") or "").lower(), ""
        if provider == "google" and not me.get("email_verified", False):
            raise AuthError("That Google address is not verified.")
        if provider == "github":
            login = me.get("login", "")
            emails = http.get(urls["user"] + "/emails", headers=headers, timeout=10).json()
            verified = [e["email"].lower() for e in emails if isinstance(e, dict) and e.get("verified")]
            email = next((e["email"].lower() for e in emails if isinstance(e, dict) and e.get("primary")
                          and e.get("verified")), verified[0] if verified else "")
    except (requests.RequestException, ValueError) as error:
        raise AuthError(f"Could not reach {provider.title()} to finish the login.") from error
    name = me.get("name") or login or email or "Someone"
    return session_for(name, role_for(email, login), email, login, provider)
