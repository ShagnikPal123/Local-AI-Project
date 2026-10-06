"""HTTP routes for the owner's email accounts (contract §4.4).

Accounts are an address plus an app password; the password goes straight into
``secret_store`` and no response ever contains it. Reads use the chat gate; adding,
removing and testing accounts need the owner, like ``/api/keys``.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from server_auth import RequireChat

router = APIRouter()


def _owner(request: Request) -> Any:
    from server import require_local_owner

    return require_local_owner(request, request.headers.get("authorization"))


def _changed() -> None:
    try:
        from agent_events import publish_ui

        publish_ui("email.accounts.changed")
    except Exception:
        pass


@router.get("/api/email/accounts")
def get_accounts(_user=RequireChat) -> Dict[str, Any]:
    import email_client

    return {"accounts": email_client.list_accounts(), "outlook_app_available": email_client.outlook_available(),
            "providers": {name: {"app_password_url": preset.get("app_password_url", ""), "domains": preset.get("domains", [])}
                          for name, preset in email_client.PRESETS.items()}}


class AccountIn(BaseModel):
    address: str
    app_password: str = ""
    imap_host: str = ""
    imap_port: int = 0
    smtp_host: str = ""
    smtp_port: int = 0


@router.post("/api/email/accounts")
def post_account(body: AccountIn, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import email_client

    try:
        account = email_client.add_account(body.address, body.app_password, body.imap_host, body.imap_port,
                                           body.smtp_host, body.smtp_port)
    except email_client.EmailError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    _changed()
    return {"ok": True, "account": account}


@router.delete("/api/email/accounts/{account_id}")
def delete_account(account_id: str, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import email_client

    if not email_client.remove_account(account_id):
        raise HTTPException(status_code=404, detail="No such account.")
    _changed()
    return {"ok": True}


@router.post("/api/email/test/{account_id}")
def test_account(account_id: str, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    """Log in over IMAP and count unread mail. Sends nothing."""
    import email_client

    try:
        account = email_client._pick_account(account_id)
        client = email_client._login_imap(account)
        try:
            client.select("INBOX", readonly=True)
            status, data = client.uid("SEARCH", None, "UNSEEN")
            unread = len((data[0] or b"").split()) if status == "OK" else 0
        finally:
            client.logout()
        return {"ok": True, "detail": f"Signed in to {account['address']} — {unread} unread in the inbox."}
    except email_client.EmailError as error:
        return {"ok": False, "detail": str(error)}



# --- Google sign-in instead of an app password (Request H7) ---------------------------------


class GoogleClientIn(BaseModel):
    client_id: str
    client_secret: str


class GoogleStartIn(BaseModel):
    login_hint: str = ""
    #: Which Google apps to ask permission for (Connectors, U24); empty keeps the original Gmail-only sign-in.
    products: List[str] = []


def _redirect_uri(request: Request) -> str:
    port = request.url.port or 8000
    return f"http://127.0.0.1:{port}/api/google/oauth/callback"


@router.get("/api/google/oauth/status")
def google_status(request: Request, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import google_oauth

    accounts = dict.fromkeys([*google_oauth.connected(), *google_oauth._read_granted()])
    return {"client_configured": google_oauth.client_configured(), "connected": google_oauth.connected(),
            "redirect_uri": _redirect_uri(request), "scopes": list(google_oauth.SCOPES),
            "products": {address: google_oauth.products_of(address) for address in accounts
                         if google_oauth.products_of(address)}}


@router.post("/api/google/oauth/client")
def google_client(body: GoogleClientIn, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import google_oauth

    try:
        google_oauth.save_client(body.client_id, body.client_secret)
    except google_oauth.OAuthError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"client_configured": True}


@router.post("/api/google/oauth/start")
def google_start(body: GoogleStartIn, request: Request, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import google_oauth

    unknown = [p for p in body.products if p not in google_oauth.PRODUCT_SCOPES]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown Google app: {', '.join(unknown)}.")
    try:
        return {"auth_url": google_oauth.start(_redirect_uri(request), body.login_hint.strip(), body.products)}
    except google_oauth.OAuthError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/api/google/oauth/callback")
def google_callback(request: Request, state: str = "", code: str = "", error: str = ""):
    """Where Google sends the browser back. Public (the browser carries no Nyx session here), but only a
    ``state`` created moments ago by the owner's own Sign In click is accepted, from this computer."""
    from fastapi.responses import HTMLResponse
    import html

    import google_oauth

    def page(title: str, text: str, ok: bool) -> HTMLResponse:
        color = "#5EE08F" if ok else "#FF9A92"
        return HTMLResponse(
            "<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Nyx · Google</title><body style='margin:0;min-height:100vh;display:grid;place-items:center;"
            "background:#000;color:#f5f5f7;font:16px system-ui,sans-serif'><main style='max-width:420px;padding:24px;"
            f"text-align:center'><div style='font-size:34px;color:{color}'>{'✓' if ok else '▲'}</div>"
            f"<h1 style='font-size:22px'>{html.escape(title)}</h1><p style='color:#c7c7cc;line-height:1.5'>{html.escape(text)}</p>"
            "</main></body>", status_code=200 if ok else 400)

    host = (request.client.host if request.client else "") or ""
    if host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        return page("Open this on the PC running Nyx", "Google sign-in finishes on the computer where Nyx runs.", False)
    if error:
        return page("Google sign-in was cancelled", f"Google said: {error}. Nothing was connected.", False)
    try:
        address = google_oauth.complete(state, code)
    except google_oauth.OAuthError as failure:
        return page("Not connected", str(failure), False)
    _changed()
    try:
        from agent_events import publish_ui

        publish_ui("connectors.changed", id="google")
    except Exception:
        pass
    apps = google_oauth.products_of(address)
    if apps == ["gmail"]:
        text = "Nyx can now read and send this Gmail without an app password. You can close this tab."
    else:
        names = {"gmail": "Gmail", "calendar": "Calendar", "drive": "Drive", "docs": "Docs", "sheets": "Sheets",
                 "slides": "Slides", "tasks": "Tasks"}
        text = f"Nyx can now use {', '.join(names.get(a, a) for a in apps)} for this account. You can close this tab."
    return page(f"Connected {address}", text, True)
