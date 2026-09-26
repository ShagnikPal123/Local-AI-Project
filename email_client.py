"""Email that works: send, read, search and reply — or a ready-to-send draft.

Before this, asked to email someone, Nyx answered that it had "no email tool or
API integration", which was true. Now there are three ways, tried in order:

1. **An account the owner added** (address + app password): real IMAP to read and
   search, real SMTP to send and reply. Gmail, iCloud, Yahoo and most IMAP mail
   work with an *app password*; the Keys panel links to where to make one.
2. **Outlook on this PC** (classic desktop Outlook), driven through COM — sends
   from whatever accounts Outlook already has, no password needed here.
3. **A pre-filled compose window** in Gmail or Outlook on the web (by the
   address's domain) or the default mail app — everything written, the owner
   presses Send. Honest about it: the result says the mail was *not* sent yet.

Passwords live only in ``secret_store`` and are never returned, logged, or put in
a tool result. Every send is category ``email.send``, so the owner can set it to
"ask" and approve each one.
"""

from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import json
import mimetypes
import re
import smtplib
import ssl
import subprocess
import threading
import time
import urllib.parse
import uuid
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from paths import data_path

_TIMEOUT = 30
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

#: Server settings by domain, and where each provider's app passwords are made.
PRESETS: Dict[str, Dict[str, Any]] = {
    "gmail": {"domains": ["gmail.com", "googlemail.com"], "imap": ("imap.gmail.com", 993), "smtp": ("smtp.gmail.com", 465),
              "app_password_url": "https://myaccount.google.com/apppasswords",
              "compose": "https://mail.google.com/mail/?view=cm&fs=1&to={to}&su={subject}&body={body}&cc={cc}&bcc={bcc}"},
    "outlook": {"domains": ["outlook.com", "hotmail.com", "live.com", "msn.com"], "imap": ("outlook.office365.com", 993),
                "smtp": ("smtp-mail.outlook.com", 587), "app_password_url": "https://account.live.com/proofs/AppPassword",
                "compose": "https://outlook.live.com/mail/0/deeplink/compose?to={to}&subject={subject}&body={body}&cc={cc}&bcc={bcc}"},
    "office365": {"domains": [], "imap": ("outlook.office365.com", 993), "smtp": ("smtp.office365.com", 587),
                  "app_password_url": "https://mysignins.microsoft.com/security-info",
                  "compose": "https://outlook.office.com/mail/deeplink/compose?to={to}&subject={subject}&body={body}&cc={cc}&bcc={bcc}"},
    "yahoo": {"domains": ["yahoo.com", "ymail.com"], "imap": ("imap.mail.yahoo.com", 993), "smtp": ("smtp.mail.yahoo.com", 465),
              "app_password_url": "https://login.yahoo.com/myaccount/security/app-password"},
    "icloud": {"domains": ["icloud.com", "me.com", "mac.com"], "imap": ("imap.mail.me.com", 993), "smtp": ("smtp.mail.me.com", 587),
               "app_password_url": "https://account.apple.com/account/manage"},
}

#: School and work domains that run on Microsoft 365 (compose there, not Gmail).
_M365_HINTS = (".edu", "tamu.edu")


class EmailError(RuntimeError):
    """Something the owner can fix, in words they can act on."""


_lock = threading.Lock()


def _accounts_path() -> Path:
    return data_path("email_accounts.json")


def _secret_name(account_id: str) -> str:
    return f"EMAIL_APP_PASSWORD_{account_id.upper()}"


def _read_accounts() -> List[Dict[str, Any]]:
    try:
        data = json.loads(_accounts_path().read_text(encoding="utf-8"))
        return [a for a in data.get("accounts", []) if isinstance(a, dict) and a.get("address")]
    except (OSError, ValueError):
        return []


def _write_accounts(accounts: List[Dict[str, Any]]) -> None:
    path = _accounts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"accounts": accounts}, indent=2), encoding="utf-8")


def _password(account: Dict[str, Any]) -> str:
    try:
        from secret_store import get_keys

        keys = get_keys(_secret_name(account["id"]))
        return keys[0] if keys else ""
    except Exception:
        return ""


def provider_for(address: str) -> str:
    domain = (address or "").rsplit("@", 1)[-1].lower().strip()
    for name, preset in PRESETS.items():
        if domain in preset.get("domains", []):
            return name
    if domain.endswith(_M365_HINTS):
        return "office365"
    return "imap"


def _is_oauth(account: Dict[str, Any]) -> bool:
    return account.get("auth") == "oauth"


def add_oauth_account(address: str) -> Dict[str, Any]:
    """A Gmail account connected with Google sign-in (google_oauth.py, Request H7): no app password."""
    preset = PRESETS.get("gmail", {})
    with _lock:
        accounts = _read_accounts()
        existing = next((a for a in accounts if a["address"].lower() == address.lower()), None)
        account = existing or {"id": uuid.uuid4().hex[:10], "address": address}
        account.update(provider="gmail", auth="oauth",
                       imap_host=(preset.get("imap") or ("imap.gmail.com", 993))[0], imap_port=993,
                       smtp_host=(preset.get("smtp") or ("smtp.gmail.com", 465))[0], smtp_port=465,
                       added_at=account.get("added_at") or time.time())
        if existing is None:
            accounts.append(account)
        _write_accounts(accounts)
    return public_account(account)


def public_account(account: Dict[str, Any]) -> Dict[str, Any]:
    has_password = bool(_password(account)) or (_is_oauth(account) and _oauth_ready(account))
    preset = PRESETS.get(account.get("provider", ""), {})
    return {
        "id": account["id"],
        "address": account["address"],
        "provider": account.get("provider", "imap"),
        "imap_host": account.get("imap_host"),
        "smtp_host": account.get("smtp_host"),
        "configured": has_password,
        "send": "smtp" if has_password else ("outlook_app" if outlook_available() else "compose"),
        "read": "imap" if has_password else "none",
        "app_password_url": preset.get("app_password_url", ""),
        "auth": "google_sign_in" if _is_oauth(account) else "app_password",
    }


def _oauth_ready(account: Dict[str, Any]) -> bool:
    try:
        from secret_store import get_keys

        return bool(get_keys(f"GOOGLE_OAUTH_REFRESH:{account['address'].strip().lower()}"))
    except Exception:
        return False


def list_accounts() -> List[Dict[str, Any]]:
    return [public_account(a) for a in _read_accounts()]


def add_account(address: str, app_password: str = "", imap_host: str = "", imap_port: int = 0,
                smtp_host: str = "", smtp_port: int = 0, verify: bool = True) -> Dict[str, Any]:
    clean = (address or "").strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", clean):
        raise EmailError("That does not look like an email address.")
    provider = provider_for(clean)
    preset = PRESETS.get(provider, {})
    imap = (imap_host or (preset.get("imap") or ("", 0))[0], int(imap_port or (preset.get("imap") or ("", 993))[1] or 993))
    smtp = (smtp_host or (preset.get("smtp") or ("", 0))[0], int(smtp_port or (preset.get("smtp") or ("", 465))[1] or 465))
    if app_password and not (imap[0] and smtp[0]):
        raise EmailError("For this address, enter the IMAP and SMTP server names from your mail provider's help page.")
    with _lock:
        accounts = _read_accounts()
        existing = next((a for a in accounts if a["address"].lower() == clean.lower()), None)
        account = existing or {"id": uuid.uuid4().hex[:10], "address": clean}
        account.update(provider=provider, imap_host=imap[0], imap_port=imap[1], smtp_host=smtp[0], smtp_port=smtp[1],
                       added_at=account.get("added_at") or time.time())
        if app_password:
            if verify:
                _login_imap(account, app_password.replace(" ", "")).logout()
            from secret_store import set_keys

            set_keys(_secret_name(account["id"]), [app_password.replace(" ", "")])
        if existing is None:
            accounts.append(account)
        _write_accounts(accounts)
    return public_account(account)


def remove_account(account_id: str) -> bool:
    removed = next((a for a in _read_accounts() if a["id"] == account_id), None)
    if removed is not None and _is_oauth(removed):
        try:
            import google_oauth

            google_oauth.disconnect(removed["address"])
        except Exception:
            pass
    with _lock:
        accounts = _read_accounts()
        kept = [a for a in accounts if a["id"] != account_id]
        if len(kept) == len(accounts):
            return False
        _write_accounts(kept)
    try:
        from secret_store import set_keys

        set_keys(_secret_name(account_id), [])
    except Exception:
        pass
    return True


def _pick_account(account: str = "") -> Optional[Dict[str, Any]]:
    accounts = _read_accounts()
    wanted = (account or "").strip().lower()
    if wanted:
        for item in accounts:
            if wanted in (item["id"].lower(), item["address"].lower()):
                return item
        raise EmailError(f"No email account {account!r} is set up. Accounts: {', '.join(a['address'] for a in accounts) or 'none'}.")
    with_password = [a for a in accounts if _password(a) or (_is_oauth(a) and _oauth_ready(a))]
    return (with_password or accounts or [None])[0]


# ---------------------------------------------------------------------------
# IMAP
# ---------------------------------------------------------------------------


def _login_imap(account: Dict[str, Any], password: str = "") -> imaplib.IMAP4_SSL:
    if _is_oauth(account) and not password:
        import google_oauth

        try:
            auth = google_oauth.xoauth2(account["address"])
            client = imaplib.IMAP4_SSL(account["imap_host"], int(account.get("imap_port") or 993),
                                       ssl_context=ssl.create_default_context(), timeout=_TIMEOUT)
            client.authenticate("XOAUTH2", lambda _challenge: auth.encode())
            return client
        except google_oauth.OAuthError as error:
            raise EmailError(str(error)) from error
        except imaplib.IMAP4.error as error:
            raise EmailError(f"Gmail refused the Google sign-in for {account['address']}. Sign in again from Keys & Models.") from error
        except OSError as error:
            raise EmailError(f"Could not reach {account['imap_host']}: {error}") from error
    secret = password or _password(account)
    if not secret:
        raise EmailError(f"{account['address']} has no app password saved, so its mail cannot be read here.")
    try:
        client = imaplib.IMAP4_SSL(account["imap_host"], int(account.get("imap_port") or 993),
                                   ssl_context=ssl.create_default_context(), timeout=_TIMEOUT)
        client.login(account["address"], secret)
        return client
    except imaplib.IMAP4.error as error:
        detail = str(error).replace(secret, "[REDACTED]")
        hint = PRESETS.get(account.get("provider", ""), {}).get("app_password_url", "")
        raise EmailError(f"{account['address']} refused the login ({detail[:160]}). Use an app password"
                         + (f" from {hint}" if hint else "") + ", not your normal password.") from error
    except OSError as error:
        raise EmailError(f"Could not reach {account['imap_host']}: {error}") from error


def _decode(value: Any) -> str:
    if not value:
        return ""
    parts = []
    for text, charset in email.header.decode_header(str(value)):
        if isinstance(text, bytes):
            parts.append(text.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(text)
    return "".join(parts).strip()


def _body_text(message: email.message.Message, limit: int = 20_000) -> str:
    plain, html = "", ""
    for part in message.walk() if message.is_multipart() else [message]:
        if part.get_content_maintype() == "multipart" or part.get("Content-Disposition", "").startswith("attachment"):
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            continue
        if part.get_content_type() == "text/plain" and not plain:
            plain = text
        elif part.get_content_type() == "text/html" and not html:
            html = text
    if not plain and html:
        plain = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
        plain = re.sub(r"(?s)<br\s*/?>|</p>", "\n", plain)
        plain = re.sub(r"(?s)<[^>]+>", "", plain)
        plain = re.sub(r"&nbsp;", " ", plain)
    plain = re.sub(r"\n{3,}", "\n\n", plain).strip()
    return plain[:limit]


def _attachments_of(message: email.message.Message) -> List[str]:
    return [_decode(part.get_filename()) for part in message.walk() if part.get_filename()]


def list_emails(account: str = "", folder: str = "INBOX", query: str = "", unread_only: bool = False, limit: int = 10) -> List[Dict[str, Any]]:
    picked = _pick_account(account)
    if picked is None:
        raise EmailError("No email account is set up yet. Add one (address + app password) in Keys → Email.")
    client = _login_imap(picked)
    try:
        status, _ = client.select(f'"{folder}"' if " " in folder else folder, readonly=True)
        if status != "OK":
            raise EmailError(f"No folder called {folder!r}.")
        criteria: List[str] = ["UNSEEN"] if unread_only else ["ALL"]
        if query.strip():
            q = query.strip().replace('"', "")
            criteria = (["UNSEEN"] if unread_only else []) + ["OR", "OR", "FROM", f'"{q}"', "SUBJECT", f'"{q}"', "BODY", f'"{q}"']
        status, data = client.uid("SEARCH", None, *criteria)
        uids = (data[0] or b"").split() if status == "OK" else []
        results = []
        for uid in reversed(uids[-max(1, min(int(limit or 10), 50)):]):
            status, parts = client.uid("FETCH", uid, "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE)] BODY.PEEK[TEXT]<0.400>)")
            if status != "OK" or not parts:
                continue
            header_bytes, snippet_bytes, flags = b"", b"", ""
            for item in parts:
                # Servers put FLAGS before or after the literals, so read every descriptor.
                descriptor = (item[0] if isinstance(item, tuple) else item or b"").decode(errors="replace")
                flags += descriptor
                if isinstance(item, tuple):
                    if "HEADER" in descriptor:
                        header_bytes = item[1]
                    else:
                        snippet_bytes = item[1]
            headers = email.message_from_bytes(header_bytes)
            snippet_text = snippet_bytes.decode("utf-8", errors="replace")
            snippet_text = "\n".join(line for line in snippet_text.splitlines()
                                     if not line.startswith(("--", "Content-")) and not re.fullmatch(r"[A-Za-z0-9+/=]{60,}", line))
            snippet = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", snippet_text)).strip()[:200]
            results.append({"id": uid.decode(), "from": _decode(headers.get("From")), "subject": _decode(headers.get("Subject")),
                            "date": _decode(headers.get("Date")), "unread": "\\Seen" not in flags, "snippet": snippet})
        return results
    finally:
        try:
            client.logout()
        except Exception:
            pass


def read_email(message_id: str, account: str = "", folder: str = "INBOX") -> Dict[str, Any]:
    picked = _pick_account(account)
    if picked is None:
        raise EmailError("No email account is set up yet.")
    client = _login_imap(picked)
    try:
        client.select(folder, readonly=True)
        status, parts = client.uid("FETCH", str(message_id).encode(), "(RFC822)")
        raw = next((p[1] for p in parts or [] if isinstance(p, tuple)), None)
        if status != "OK" or not raw:
            raise EmailError(f"No message {message_id} in {folder}.")
        message = email.message_from_bytes(raw)
        return {"id": str(message_id), "from": _decode(message.get("From")), "to": _decode(message.get("To")),
                "cc": _decode(message.get("Cc")), "subject": _decode(message.get("Subject")),
                "date": _decode(message.get("Date")), "message_id": message.get("Message-ID", ""),
                "references": message.get("References", ""), "body": _body_text(message),
                "attachments": _attachments_of(message)}
    finally:
        try:
            client.logout()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------


def _split(addresses: Any) -> List[str]:
    if isinstance(addresses, (list, tuple)):
        items = [str(a) for a in addresses]
    else:
        items = re.split(r"[;,]", str(addresses or ""))
    return [a.strip() for a in items if a and a.strip()]


def _build_message(sender: str, to: List[str], subject: str, body: str, cc: List[str], bcc: List[str],
                   attachments: List[str], reply_to: Optional[Dict[str, Any]] = None) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    message["Subject"] = subject or "(no subject)"
    message["Date"] = email.utils.formatdate(localtime=True)
    message["Message-ID"] = email.utils.make_msgid(domain=sender.rsplit("@", 1)[-1])
    if reply_to and reply_to.get("message_id"):
        message["In-Reply-To"] = reply_to["message_id"]
        message["References"] = (reply_to.get("references", "") + " " + reply_to["message_id"]).strip()
    message.set_content(body or "")
    for item in attachments:
        path = Path(item).expanduser()
        if not path.is_file():
            raise EmailError(f"Attachment not found: {path}")
        mime, _ = mimetypes.guess_type(path.name)
        main, sub = (mime or "application/octet-stream").split("/", 1)
        message.add_attachment(path.read_bytes(), maintype=main, subtype=sub, filename=path.name)
    return message


def _smtp_send(account: Dict[str, Any], message: EmailMessage, recipients: List[str]) -> None:
    host, port = account["smtp_host"], int(account.get("smtp_port") or 465)
    if _is_oauth(account):
        import google_oauth

        try:
            auth = google_oauth.xoauth2(account["address"])
            with smtplib.SMTP_SSL(host, 465, context=ssl.create_default_context(), timeout=_TIMEOUT) as client:
                client.ehlo()
                client.auth("XOAUTH2", lambda challenge=None: auth)
                client.send_message(message, to_addrs=recipients)
            return
        except google_oauth.OAuthError as error:
            raise EmailError(str(error)) from error
        except smtplib.SMTPAuthenticationError as error:
            raise EmailError(f"Gmail refused the Google sign-in for sending from {account['address']}. Sign in again.") from error
        except (smtplib.SMTPException, OSError) as error:
            raise EmailError(f"Sending through {host} failed: {str(error)[:200]}") from error
    secret = _password(account)
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=_TIMEOUT) as client:
                client.login(account["address"], secret)
                client.send_message(message, to_addrs=recipients)
        else:
            with smtplib.SMTP(host, port, timeout=_TIMEOUT) as client:
                client.starttls(context=ssl.create_default_context())
                client.login(account["address"], secret)
                client.send_message(message, to_addrs=recipients)
    except smtplib.SMTPAuthenticationError as error:
        raise EmailError(f"{account['address']} refused the login for sending. Use an app password.") from error
    except (smtplib.SMTPException, OSError) as error:
        raise EmailError(f"Sending through {host} failed: {str(error).replace(secret, '[REDACTED]')[:200]}") from error


_outlook_cache: Dict[str, Any] = {}


def outlook_available() -> bool:
    """Classic desktop Outlook registered for COM *with a mail profile* (cached).

    Office often installs classic Outlook next to "new Outlook" without anyone
    signing in; driving it then opens the first-run wizard instead of sending.
    """
    if "value" in _outlook_cache:
        return bool(_outlook_cache["value"])
    found = False
    try:
        import winreg

        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Outlook.Application\CLSID"))
        for version in ("16.0", "15.0"):
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\Office\{version}\Outlook\Profiles")
            except OSError:
                continue
            try:
                found = winreg.QueryInfoKey(key)[0] > 0
            finally:
                winreg.CloseKey(key)
            if found:
                break
    except Exception:
        found = False
    _outlook_cache["value"] = found
    return found


def _outlook_send(to: List[str], subject: str, body: str, cc: List[str], bcc: List[str], attachments: List[str]) -> None:
    script = (
        "$o = New-Object -ComObject Outlook.Application; $m = $o.CreateItem(0); "
        "$m.To = $env:NYX_TO; $m.CC = $env:NYX_CC; $m.BCC = $env:NYX_BCC; $m.Subject = $env:NYX_SUBJECT; $m.Body = $env:NYX_BODY; "
        "if ($env:NYX_ATTACH) { foreach ($a in $env:NYX_ATTACH.Split('|')) { if ($a) { [void]$m.Attachments.Add($a) } } }; "
        "$m.Send()"
    )
    import os

    env = {**os.environ, "NYX_TO": "; ".join(to), "NYX_CC": "; ".join(cc), "NYX_BCC": "; ".join(bcc),
           "NYX_SUBJECT": subject or "", "NYX_BODY": body or "", "NYX_ATTACH": "|".join(attachments)}
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                            text=True, timeout=90, env=env, creationflags=_NO_WINDOW)
    if result.returncode != 0:
        raise EmailError(f"Outlook could not send it: {(result.stderr or '').strip()[:240]}")


def compose_link(to: List[str], subject: str, body: str, cc: List[str], bcc: List[str], sender: str = "") -> str:
    provider = provider_for(sender) if sender else "gmail"
    template = PRESETS.get(provider, {}).get("compose")
    quote = lambda value: urllib.parse.quote(value or "", safe="")  # noqa: E731
    if not template:
        params = urllib.parse.urlencode({"subject": subject or "", "body": body or "", "cc": ",".join(cc), "bcc": ",".join(bcc)},
                                        quote_via=urllib.parse.quote)
        return f"mailto:{quote(','.join(to))}?{params}"
    return template.format(to=quote(",".join(to)), subject=quote(subject), body=quote(body),
                           cc=quote(",".join(cc)), bcc=quote(",".join(bcc)))


def send_email(to: Any, subject: str, body: str, cc: Any = "", bcc: Any = "", account: str = "",
               attachments: Optional[List[str]] = None, allow_compose: bool = True) -> Dict[str, Any]:
    """Send (or, with no way to send, open a ready draft). Returns what actually happened."""
    recipients = _split(to)
    if not recipients:
        raise EmailError("Who should it go to?")
    cc_list, bcc_list, files = _split(cc), _split(bcc), [str(a) for a in (attachments or [])]
    picked = _pick_account(account)
    if picked is not None and _password(picked):
        message = _build_message(picked["address"], recipients, subject, body, cc_list, bcc_list, files)
        _smtp_send(picked, message, recipients + cc_list + bcc_list)
        return {"sent": True, "via": "smtp", "from": picked["address"], "to": recipients}
    outlook_problem = ""
    if outlook_available():
        try:
            _outlook_send(recipients, subject, body, cc_list, bcc_list, files)
            return {"sent": True, "via": "outlook", "from": "Outlook's default account", "to": recipients}
        except (EmailError, subprocess.TimeoutExpired) as error:
            outlook_problem = f" (Outlook could not send: {str(error)[:120]})"
    if not allow_compose:
        raise EmailError("No way to send: add an email account with an app password, or set up Outlook." + outlook_problem)
    link = compose_link(recipients, subject, body, cc_list, bcc_list, picked["address"] if picked else "")
    import webbrowser

    webbrowser.open(link)
    note = " Attachments must be added in the compose window." if files else ""
    return {"sent": False, "via": "compose", "link_opened": link.split("?")[0], "to": recipients,
            "note": "A ready-to-send draft is open in the browser — press Send there." + note + outlook_problem}


def reply_email(message_id: str, body: str, account: str = "", reply_all: bool = False) -> Dict[str, Any]:
    original = read_email(message_id, account)
    picked = _pick_account(account)
    to = [email.utils.parseaddr(original["from"])[1]]
    cc: List[str] = []
    if reply_all:
        own = (picked or {}).get("address", "").lower()
        cc = [addr for _name, addr in email.utils.getaddresses([original.get("to", ""), original.get("cc", "")])
              if addr and addr.lower() != own]
    subject = original["subject"] if original["subject"].lower().startswith("re:") else f"Re: {original['subject']}"
    quoted = "\n".join(f"> {line}" for line in original["body"].splitlines()[:40])
    full_body = f"{body}\n\nOn {original['date']}, {original['from']} wrote:\n{quoted}"
    if picked is None or not _password(picked):
        raise EmailError("Replying needs the account's app password (it has to read the original).")
    message = _build_message(picked["address"], to, subject, full_body, cc, [], [], reply_to=original)
    _smtp_send(picked, message, to + cc)
    return {"sent": True, "via": "smtp", "to": to, "cc": cc, "subject": subject}


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def _tool(fn, *args, **kwargs) -> str:
    try:
        return fn(*args, **kwargs)
    except EmailError as error:
        return f"Error: {error}"


def tool_email_send(to: str, subject: str, body: str, cc: str = "", bcc: str = "", account: str = "",
                    attachments: Any = None) -> str:
    def run() -> str:
        files = attachments if isinstance(attachments, list) else _split(attachments) if attachments else []
        outcome = send_email(to, subject, body, cc=cc, bcc=bcc, account=account, attachments=files)
        if outcome["sent"]:
            return f"Sent to {', '.join(outcome['to'])} via {outcome['via']} from {outcome['from']}."
        return f"NOT SENT YET. {outcome['note']} (Tell the user plainly; to send directly next time they can add an app password in Keys → Email.)"
    return _tool(run)


def tool_email_list(account: str = "", folder: str = "INBOX", query: str = "", unread_only: bool = False, limit: int = 10) -> str:
    def run() -> str:
        items = list_emails(account, folder, query, unread_only, limit)
        if not items:
            return "No messages matched."
        lines = [f"{len(items)} message(s) in {folder}:"]
        for item in items:
            lines.append(f"- [{item['id']}] {'● ' if item['unread'] else ''}{item['date'][:25]} — {item['from']} — "
                         f"{item['subject']}\n  {item['snippet'][:140]}")
        return "\n".join(lines)
    return _tool(run)


def tool_email_read(message_id: str, account: str = "", folder: str = "INBOX") -> str:
    def run() -> str:
        item = read_email(message_id, account, folder)
        attachments = f"\nAttachments: {', '.join(item['attachments'])}" if item["attachments"] else ""
        return (f"From: {item['from']}\nTo: {item['to']}\nDate: {item['date']}\nSubject: {item['subject']}{attachments}\n\n"
                f"{item['body']}")
    return _tool(run)


def tool_email_reply(message_id: str, body: str, account: str = "", reply_all: bool = False) -> str:
    def run() -> str:
        outcome = reply_email(message_id, body, account, reply_all)
        return f"Replied to {', '.join(outcome['to'])}" + (f" (cc {', '.join(outcome['cc'])})" if outcome["cc"] else "") + \
            f" — subject “{outcome['subject']}”."
    return _tool(run)


def tool_email_compose(to: str, subject: str = "", body: str = "", cc: str = "", account: str = "") -> str:
    picked = None
    try:
        picked = _pick_account(account)
    except EmailError:
        pass
    link = compose_link(_split(to), subject, body, _split(cc), [], picked["address"] if picked else "")
    import webbrowser

    webbrowser.open(link)
    return "Opened a pre-filled draft in the browser for the user to review and send. It has NOT been sent."


def tool_email_accounts() -> str:
    accounts = list_accounts()
    if not accounts:
        return ("No email accounts are set up. Sending still works by opening a ready draft; to send and read directly, "
                "the user adds their address and an app password in Keys → Email" +
                (" (Outlook desktop is installed, so sending through it works now)." if outlook_available() else "."))
    return "\n".join(f"- {a['address']} ({a['provider']}): send via {a['send']}, read via {a['read']}" for a in accounts)


def register_email_tools(registry: Any) -> None:
    from tools import ToolParam as P

    registry.register("email_send", "Send an email. Uses the user's added account (app password) or Outlook; if neither "
                      "exists it opens a ready draft and the result says NOT SENT YET — report that honestly.",
                      [P("to", "string", "Recipient address(es), comma-separated"), P("subject", "string", "Subject"),
                       P("body", "string", "Plain-text body"), P("cc", "string", "CC addresses", required=False),
                       P("bcc", "string", "BCC addresses", required=False),
                       P("account", "string", "Which of the user's accounts to send from", required=False),
                       P("attachments", "array", "File paths to attach", required=False)],
                      tool_email_send, category="email.send", label=lambda a: f"Emailing {str(a.get('to', ''))[:50]}")
    registry.register("email_list", "List or search recent emails (needs an account with an app password).",
                      [P("account", "string", "Account address (default: the first)", required=False),
                       P("folder", "string", "Folder, default INBOX", required=False),
                       P("query", "string", "Search sender, subject and body", required=False),
                       P("unread_only", "boolean", "Only unread", required=False),
                       P("limit", "number", "How many (default 10)", required=False)],
                      tool_email_list, category="email.read", label=lambda a: f"Checking email{': ' + str(a['query'])[:40] if a.get('query') else ''}")
    registry.register("email_read", "Read one email in full by its id from email_list.",
                      [P("message_id", "string", "Id from email_list"), P("account", "string", "Account", required=False),
                       P("folder", "string", "Folder, default INBOX", required=False)],
                      tool_email_read, category="email.read", label="Reading an email")
    registry.register("email_reply", "Reply to an email by id (quotes the original, keeps the thread).",
                      [P("message_id", "string", "Id from email_list"), P("body", "string", "Your reply"),
                       P("account", "string", "Account", required=False),
                       P("reply_all", "boolean", "Reply to everyone", required=False)],
                      tool_email_reply, category="email.send", label="Replying to an email")
    registry.register("email_compose", "Open a pre-filled email draft for the user to review and send themselves.",
                      [P("to", "string", "Recipient(s)"), P("subject", "string", "Subject", required=False),
                       P("body", "string", "Body", required=False), P("cc", "string", "CC", required=False),
                       P("account", "string", "Sender account (picks Gmail/Outlook)", required=False)],
                      tool_email_compose, category="apps", label=lambda a: f"Drafting an email to {str(a.get('to', ''))[:40]}")
    registry.register("email_accounts", "Which email accounts are set up and how each can send and read.", [],
                      tool_email_accounts, category="general", label="Checking email accounts")
