"""Sign in to Microsoft 365 (Outlook, Excel, Word, OneDrive, Teams, OneNote) with the device-code flow.

The owner asked for "microsoft apps like excel and word" in Connectors (Update 1, U24). Microsoft Graph needs an
OAuth sign-in, and the device-code flow is the one that fits a local app: Nyx asks Microsoft for a short code, the
owner types it at microsoft.com/devicelogin in any browser and approves, and Nyx collects the tokens. No redirect
address, no public callback route and no client secret — only the owner's own app registration's client ID (Entra
admin centre → App registrations → "Allow public client flows"), because Nyx must not borrow another publisher's.

Like ``google_oauth``: the refresh token lives in ``secret_store`` under the account, access tokens are fetched on
demand and cached in memory, and nothing secret reaches a response or a log. Each app asks only for its own Graph
permissions; a later sign-in for another app adds to what the account already granted.

There is no background thread: the Connectors sheet polls ``poll()`` while the owner finishes signing in, which
keeps ``NYX_NO_BACKGROUND`` honest and makes the flow testable step by step.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any, Dict, List, Optional

AUTHORITY = "https://login.microsoftonline.com"
GRAPH = "https://graph.microsoft.com/v1.0"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
BASE_SCOPES = ("offline_access", "User.Read")
#: Delegated Graph permissions per app. None of these needs an administrator's consent on a personal account.
PRODUCT_SCOPES: Dict[str, tuple] = {
    "outlook": ("Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite"),
    "excel": ("Files.ReadWrite",),
    "word": ("Files.ReadWrite",),
    "onedrive": ("Files.ReadWrite",),
    "teams": ("Team.ReadBasic.All", "Channel.ReadBasic.All", "Chat.Read", "ChatMessage.Send"),
    "onenote": ("Notes.Read",),
}
_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_TENANT = re.compile(r"^(common|organizations|consumers|[0-9a-fA-F-]{36}|[A-Za-z0-9.-]+\.[A-Za-z]{2,})$")
_TIMEOUT = 20

_lock = threading.Lock()
_pending: Dict[str, Any] = {}
_tokens: Dict[str, Dict[str, Any]] = {}


class MicrosoftError(RuntimeError):
    """Something the owner can act on, with no secret in it."""


def _path():
    from paths import data_path

    return data_path("connectors/microsoft.json")


def _read() -> Dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data: Dict[str, Any]) -> None:
    _path().parent.mkdir(parents=True, exist_ok=True)
    _path().write_text(json.dumps(data, indent=1), encoding="utf-8")


def _refresh_key(account: str) -> str:
    return f"MS_GRAPH_REFRESH:{account.strip().lower()}"


def _secret(name: str) -> str:
    from secret_store import get_keys

    values = get_keys(name)
    return values[0] if values else ""


def _set_secret(name: str, value: str) -> None:
    from secret_store import set_keys

    set_keys(name, [value] if value else [])


def _http():
    import requests

    return requests


def settings() -> Dict[str, Any]:
    data = _read()
    return {"client_id": str(data.get("client_id") or ""), "tenant": str(data.get("tenant") or "common")}


def client_configured() -> bool:
    return bool(settings()["client_id"])


def save_client(client_id: str, tenant: str = "common") -> Dict[str, Any]:
    """The owner's app registration. A client ID is an identifier, not a secret, so it is kept in plain JSON."""
    client_id, tenant = (client_id or "").strip(), (tenant or "common").strip() or "common"
    if not _GUID.match(client_id):
        raise MicrosoftError("Paste the Application (client) ID from your app registration — it looks like "
                             "1b2c3d4e-0000-1111-2222-333344445555.")
    if not _TENANT.match(tenant):
        raise MicrosoftError("Tenant should be common, organizations, consumers, a tenant ID or a domain.")
    data = _read()
    data.update(client_id=client_id, tenant=tenant)
    _write(data)
    return settings()


def scopes_for(products: Any) -> List[str]:
    wanted = [p for p in (products or []) if p in PRODUCT_SCOPES] or ["outlook"]
    out = list(BASE_SCOPES)
    for product in wanted:
        out += [s for s in PRODUCT_SCOPES[product] if s not in out]
    return out


def _post(url: str, data: Dict[str, str], http: Any = None) -> Dict[str, Any]:
    response = (http or _http()).post(url, data=data, timeout=_TIMEOUT)
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code >= 400 and not body.get("error"):
        body = {"error": f"http_{response.status_code}", "error_description": f"Microsoft answered {response.status_code}."}
    return body


def start(products: Any, http: Any = None) -> Dict[str, Any]:
    """Ask Microsoft for a sign-in code for these apps. Returns what the owner needs to see: code and address."""
    conf = settings()
    if not conf["client_id"]:
        raise MicrosoftError("Add your app registration's client ID first.")
    scopes = scopes_for(products)
    body = _post(f"{AUTHORITY}/{conf['tenant']}/oauth2/v2.0/devicecode",
                 {"client_id": conf["client_id"], "scope": " ".join(scopes)}, http)
    if body.get("error") or not body.get("device_code"):
        raise MicrosoftError(f"Microsoft refused to start the sign-in: {_reason(body)}")
    now = time.time()
    with _lock:
        _pending.clear()
        _pending.update(device_code=body["device_code"], interval=max(1, int(body.get("interval", 5))),
                        expires=now + int(body.get("expires_in", 900)), next=now, scopes=scopes,
                        products=[p for p in (products or []) if p in PRODUCT_SCOPES] or ["outlook"],
                        user_code=str(body.get("user_code", "")),
                        verification_uri=str(body.get("verification_uri") or "https://microsoft.com/devicelogin"))
    return pending() or {}


def pending() -> Optional[Dict[str, Any]]:
    """The sign-in in progress, as the owner sees it (never the device code itself)."""
    with _lock:
        if not _pending:
            return None
        left = int(_pending["expires"] - time.time())
        if left <= 0:
            _pending.clear()
            return None
        return {"user_code": _pending["user_code"], "verification_uri": _pending["verification_uri"],
                "expires_in": left, "products": list(_pending["products"])}


def _reason(body: Dict[str, Any]) -> str:
    text = str(body.get("error_description") or body.get("error") or "no answer")
    return text.split("\r\n")[0].split(" Trace ID")[0][:240]


def poll(http: Any = None) -> Dict[str, Any]:
    """One check on the sign-in in progress. ``{"state": "waiting"|"connected"|"expired"|"declined"|"idle", …}``."""
    with _lock:
        flow = dict(_pending)
    if not flow:
        return {"state": "idle"}
    now = time.time()
    if now > flow["expires"]:
        with _lock:
            _pending.clear()
        return {"state": "expired", "detail": "The code expired before the sign-in finished. Start again."}
    if now < flow["next"]:
        return {"state": "waiting", **(pending() or {})}
    conf = settings()
    body = _post(f"{AUTHORITY}/{conf['tenant']}/oauth2/v2.0/token",
                 {"grant_type": DEVICE_GRANT, "client_id": conf["client_id"], "device_code": flow["device_code"]}, http)
    error = str(body.get("error") or "")
    if error in ("authorization_pending", "slow_down"):
        with _lock:
            if _pending:
                _pending["interval"] += 5 if error == "slow_down" else 0
                _pending["next"] = time.time() + _pending["interval"]
        return {"state": "waiting", **(pending() or {})}
    with _lock:
        _pending.clear()
    if error:
        state = "declined" if error in ("authorization_declined", "access_denied") else "expired" \
            if error == "expired_token" else "failed"
        return {"state": state, "detail": _reason(body)}
    account = _account_of(body.get("access_token", ""), http)
    _store_tokens(account, body, flow["scopes"], flow["products"])
    return {"state": "connected", "account": account, "products": products_of(account)}


def _account_of(access_token: str, http: Any = None) -> str:
    response = (http or _http()).get(f"{GRAPH}/me", headers={"Authorization": f"Bearer {access_token}"},
                                     timeout=_TIMEOUT)
    try:
        me = response.json() if response.status_code == 200 else {}
    except ValueError:
        me = {}
    account = str(me.get("mail") or me.get("userPrincipalName") or "").strip()
    if not account:
        raise MicrosoftError("Microsoft did not say which account signed in.")
    return account


def _store_tokens(account: str, body: Dict[str, Any], scopes: List[str], products: List[str]) -> None:
    refresh = str(body.get("refresh_token") or "")
    if not refresh:
        raise MicrosoftError("Microsoft did not return a refresh token (offline_access was refused).")
    _set_secret(_refresh_key(account), refresh)
    granted = str(body.get("scope") or "").split() or scopes
    with _lock:
        _tokens[account.lower()] = {"access": str(body.get("access_token") or ""),
                                    "expires": time.time() + int(body.get("expires_in", 3600)) - 60}
        data = _read()
        accounts = data.setdefault("accounts", {})
        record = accounts.setdefault(account.lower(), {"account": account, "scopes": []})
        record["scopes"] = sorted(set(record.get("scopes") or []) | {s.split("/")[-1] for s in granted})
        record["connected_at"] = record.get("connected_at") or time.time()
        _write(data)


def products_of(account: str) -> List[str]:
    record = (_read().get("accounts") or {}).get(account.lower()) or {}
    if not _secret(_refresh_key(account)):
        return []
    granted = {s.lower() for s in record.get("scopes") or []}
    return [p for p, needed in PRODUCT_SCOPES.items() if {s.lower() for s in needed} <= granted]


def accounts() -> List[str]:
    return [str(r.get("account") or k) for k, r in (_read().get("accounts") or {}).items()]


def accounts_for(product: str) -> List[str]:
    return [a for a in accounts() if product in products_of(a)]


def access_token(account: str, http: Any = None) -> str:
    key = account.strip().lower()
    with _lock:
        cached = _tokens.get(key)
        if cached and cached["access"] and cached["expires"] > time.time():
            return cached["access"]
    refresh = _secret(_refresh_key(account))
    if not refresh:
        raise MicrosoftError(f"{account} is not signed in to Microsoft any more. Sign in again from Connectors.")
    conf = settings()
    record = (_read().get("accounts") or {}).get(key) or {}
    identity = {"openid", "profile", "email", *(s.lower() for s in BASE_SCOPES)}
    scopes = list(BASE_SCOPES) + [s for s in record.get("scopes") or [] if s.lower() not in identity]
    body = _post(f"{AUTHORITY}/{conf['tenant']}/oauth2/v2.0/token",
                 {"grant_type": "refresh_token", "client_id": conf["client_id"], "refresh_token": refresh,
                  "scope": " ".join(scopes)}, http)
    if body.get("error") or not body.get("access_token"):
        raise MicrosoftError(f"Microsoft refused to renew the sign-in: {_reason(body)}")
    if body.get("refresh_token"):
        _set_secret(_refresh_key(account), str(body["refresh_token"]))  # Microsoft rotates them
    with _lock:
        _tokens[key] = {"access": str(body["access_token"]), "expires": time.time() + int(body.get("expires_in", 3600)) - 60}
    return str(body["access_token"])


def disconnect(account: str) -> None:
    """Forget the account here. Revoking the app's access is done at account.microsoft.com → Privacy → Apps."""
    _set_secret(_refresh_key(account), "")
    with _lock:
        _tokens.pop(account.strip().lower(), None)
        data = _read()
        (data.get("accounts") or {}).pop(account.strip().lower(), None)
        _write(data)


def status() -> Dict[str, Any]:
    conf = settings()
    return {"client_configured": bool(conf["client_id"]), "tenant": conf["tenant"],
            "accounts": {a: products_of(a) for a in accounts() if products_of(a)}, "pending": pending(),
            "products": list(PRODUCT_SCOPES)}
