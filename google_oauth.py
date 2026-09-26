"""Connect a Google account with Google's own sign-in instead of an app password (Request H7).

"For connecting my Google to the AI, the app passwords don't work." Google no longer offers app
passwords on many accounts (no 2-Step Verification, Advanced Protection, work or school accounts), so
Gmail refused the IMAP/SMTP login. This is the supported path: OAuth 2.0 for installed apps.

1. The owner makes a free OAuth client in Google Cloud (type **Desktop app**, Gmail API enabled, their
   own address added as a test user) and pastes its client ID and secret into Keys & Models once.
   Both are stored in ``secret_store``; neither ever appears in a response.
2. **Sign in with Google** opens Google's page (PKCE + a single-use ``state``, 10-minute expiry). Google
   sends the browser back to this engine's loopback callback, which trades the code for tokens.
3. The refresh token is kept in ``secret_store`` under the address; access tokens are fetched when
   needed and used for IMAP and SMTP with XOAUTH2, so every email tool works unchanged.

Nyx never sees the Google password.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
SCOPES = ("openid", "email", "https://mail.google.com/")
CLIENT_ID_KEY = "GOOGLE_OAUTH_CLIENT_ID"
CLIENT_SECRET_KEY = "GOOGLE_OAUTH_CLIENT_SECRET"
FLOW_TTL_SECONDS = 10 * 60

_pending: Dict[str, Dict[str, Any]] = {}
_tokens: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


class OAuthError(RuntimeError):
    """Something the owner can act on, with no secret in the message."""


def _refresh_key(address: str) -> str:
    return f"GOOGLE_OAUTH_REFRESH:{address.strip().lower()}"


def _get(name: str) -> str:
    from secret_store import get_keys

    values = get_keys(name)
    return values[0] if values else ""


def client_configured() -> bool:
    return bool(_get(CLIENT_ID_KEY) and _get(CLIENT_SECRET_KEY))


def save_client(client_id: str, client_secret: str) -> None:
    from secret_store import set_keys

    client_id, client_secret = (client_id or "").strip(), (client_secret or "").strip()
    if not client_id.endswith(".apps.googleusercontent.com"):
        raise OAuthError("A Google client ID ends with .apps.googleusercontent.com — copy it from Google Cloud → Credentials.")
    if len(client_secret) < 10:
        raise OAuthError("Paste the client secret shown next to that client ID.")
    set_keys(CLIENT_ID_KEY, [client_id])
    set_keys(CLIENT_SECRET_KEY, [client_secret])


def connected() -> List[str]:
    from email_client import _read_accounts

    return [a["address"] for a in _read_accounts() if a.get("auth") == "oauth" and _get(_refresh_key(a["address"]))]


def start(redirect_uri: str, login_hint: str = "") -> str:
    """The Google sign-in URL for a new, single-use flow."""
    if not client_configured():
        raise OAuthError("Add your Google OAuth client ID and secret first.")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    now = time.time()
    with _lock:
        for key in [k for k, v in _pending.items() if now - v["created"] > FLOW_TTL_SECONDS]:
            _pending.pop(key, None)
        _pending[state] = {"verifier": verifier, "redirect_uri": redirect_uri, "created": now}
    params = {
        "client_id": _get(CLIENT_ID_KEY), "redirect_uri": redirect_uri, "response_type": "code",
        "scope": " ".join(SCOPES), "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
        "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTH_URL}?{urlencode(params)}"


def _post(url: str, data: Dict[str, str], http: Any = None) -> Dict[str, Any]:
    import requests

    response = (http or requests).post(url, data=data, timeout=20)
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code != 200:
        reason = body.get("error_description") or body.get("error") or f"HTTP {response.status_code}"
        raise OAuthError(f"Google refused: {reason}")
    return body


def complete(state: str, code: str, http: Any = None) -> str:
    """Trade Google's code for tokens, store the refresh token, and connect the mailbox. Returns the address."""
    with _lock:
        flow = _pending.pop(state or "", None)
    if flow is None or time.time() - flow["created"] > FLOW_TTL_SECONDS:
        raise OAuthError("This sign-in link has expired or was already used. Start again from Keys & Models.")
    tokens = _post(TOKEN_URL, {
        "code": code, "client_id": _get(CLIENT_ID_KEY), "client_secret": _get(CLIENT_SECRET_KEY),
        "redirect_uri": flow["redirect_uri"], "grant_type": "authorization_code", "code_verifier": flow["verifier"],
    }, http)
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise OAuthError("Google did not return a refresh token. Remove Nyx at myaccount.google.com/permissions and sign in again.")
    address = _email_from(tokens, http)
    from secret_store import set_keys

    set_keys(_refresh_key(address), [refresh])
    with _lock:
        _tokens[address.lower()] = {"access": tokens.get("access_token", ""), "expires": time.time() + int(tokens.get("expires_in", 0)) - 60}
    import email_client

    email_client.add_oauth_account(address)
    return address


def _email_from(tokens: Dict[str, Any], http: Any = None) -> str:
    id_token = tokens.get("id_token") or ""
    if id_token.count(".") == 2:
        payload = id_token.split(".")[1]
        try:
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            if claims.get("email"):
                return str(claims["email"])
        except (ValueError, json.JSONDecodeError):
            pass
    import requests

    response = (http or requests).get(USERINFO_URL, headers={"Authorization": f"Bearer {tokens.get('access_token', '')}"}, timeout=20)
    email = (response.json() if response.status_code == 200 else {}).get("email")
    if not email:
        raise OAuthError("Google did not say which address signed in.")
    return str(email)


def access_token(address: str, http: Any = None) -> str:
    key = address.strip().lower()
    with _lock:
        cached = _tokens.get(key)
        if cached and cached["access"] and cached["expires"] > time.time():
            return cached["access"]
    refresh = _get(_refresh_key(address))
    if not refresh:
        raise OAuthError(f"{address} is not signed in with Google any more. Sign in again from Keys & Models.")
    tokens = _post(TOKEN_URL, {"client_id": _get(CLIENT_ID_KEY), "client_secret": _get(CLIENT_SECRET_KEY),
                               "refresh_token": refresh, "grant_type": "refresh_token"}, http)
    with _lock:
        _tokens[key] = {"access": tokens["access_token"], "expires": time.time() + int(tokens.get("expires_in", 3600)) - 60}
    return tokens["access_token"]


def xoauth2(address: str, http: Any = None) -> str:
    """The SASL XOAUTH2 string for IMAP and SMTP."""
    return f"user={address}\x01auth=Bearer {access_token(address, http)}\x01\x01"


def disconnect(address: str, http: Any = None) -> None:
    import requests

    refresh = _get(_refresh_key(address))
    if refresh:
        try:
            (http or requests).post(REVOKE_URL, data={"token": refresh}, timeout=10)
        except Exception:  # noqa: BLE001 - forgetting locally matters more than Google's answer
            pass
    from secret_store import set_keys

    set_keys(_refresh_key(address), [])
    with _lock:
        _tokens.pop(address.strip().lower(), None)
