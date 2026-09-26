"""Email: real send/read through fakes — nothing here touches a mail server."""

from __future__ import annotations

import json
from email.message import EmailMessage

import pytest
from fastapi.testclient import TestClient

import email_client
from tools import ToolRegistry

SECRET = "abcd efgh ijkl mnop"


@pytest.fixture()
def mailbox(tmp_path, monkeypatch):
    """Accounts file in tmp, an in-memory secret store, no Outlook, no browser."""
    secrets = {}
    monkeypatch.setattr(email_client, "_accounts_path", lambda: tmp_path / "email_accounts.json")
    monkeypatch.setattr("secret_store.get_keys", lambda name: list(secrets.get(name, [])))
    monkeypatch.setattr("secret_store.set_keys", lambda name, values: secrets.__setitem__(name, [v for v in values if v]))
    monkeypatch.setattr(email_client, "outlook_available", lambda: False)
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url, *a, **k: opened.append(url))
    return {"secrets": secrets, "opened": opened}


def _raw(subject="Lunch?", sender="Ana <ana@example.com>", body="Are you free at noon?") -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "me@gmail.com"
    message["Cc"] = "bo@example.com"
    message["Subject"] = subject
    message["Date"] = "Mon, 14 Sep 2026 10:00:00 -0500"
    message["Message-ID"] = "<m1@example.com>"
    message.set_content(body)
    return message.as_bytes()


class FakeIMAP:
    instances = []
    fail_login = False

    def __init__(self, host, port, ssl_context=None, timeout=None):
        self.host, self.port = host, port
        FakeIMAP.instances.append(self)

    def login(self, user, password):
        if FakeIMAP.fail_login:
            raise email_client.imaplib.IMAP4.error(f"[AUTHENTICATIONFAILED] bad {password}")
        self.user, self.password = user, password

    def select(self, folder, readonly=False):
        return "OK", [b"2"]

    def uid(self, command, *args):
        if command == "SEARCH":
            self.criteria = args[1:]
            return "OK", [b"7 9"]
        if command == "FETCH":
            if args[1] == "(RFC822)":
                return "OK", [(b"9 (RFC822 {100}", _raw())]
            uid = args[0].decode()
            flags = "\\Seen" if uid == "7" else ""
            return "OK", [(f"{uid} (FLAGS ({flags}) BODY[HEADER.FIELDS (FROM TO SUBJECT DATE)] {{50}}".encode(),
                           _raw(subject=f"Note {uid}")), (b" BODY[TEXT]<0> {20}", b"Are you free at noon?"), b")"]
        return "NO", []

    def logout(self):
        pass


class FakeSMTP:
    sent = []

    def __init__(self, host, port, context=None, timeout=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.tls = True

    def login(self, user, password):
        self.user = user

    def send_message(self, message, to_addrs=None):
        FakeSMTP.sent.append({"host": self.host, "port": self.port, "message": message, "to": to_addrs})


@pytest.fixture()
def servers(monkeypatch):
    FakeIMAP.instances, FakeIMAP.fail_login, FakeSMTP.sent = [], False, []
    monkeypatch.setattr(email_client.imaplib, "IMAP4_SSL", FakeIMAP)
    monkeypatch.setattr(email_client.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(email_client.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP.sent


def test_provider_presets_by_domain():
    assert email_client.provider_for("x@gmail.com") == "gmail"
    assert email_client.provider_for("x@hotmail.com") == "outlook"
    assert email_client.provider_for("x@tamu.edu") == "office365"
    assert email_client.provider_for("x@icloud.com") == "icloud"
    assert email_client.provider_for("x@fastmail.com") == "imap"


def test_adding_an_account_verifies_login_and_never_returns_the_password(mailbox, servers):
    account = email_client.add_account("me@gmail.com", SECRET)
    assert account["configured"] and account["send"] == "smtp" and account["read"] == "imap"
    assert FakeIMAP.instances[0].host == "imap.gmail.com" and FakeIMAP.instances[0].password == SECRET.replace(" ", "")
    stored = (email_client._accounts_path()).read_text()
    assert SECRET.replace(" ", "") not in stored and SECRET.replace(" ", "") not in json.dumps(email_client.list_accounts())


def test_a_wrong_password_is_explained_and_redacted(mailbox, servers):
    FakeIMAP.fail_login = True
    with pytest.raises(email_client.EmailError) as error:
        email_client.add_account("me@gmail.com", "wrongpass123")
    assert "app password" in str(error.value) and "wrongpass123" not in str(error.value)
    assert "myaccount.google.com/apppasswords" in str(error.value)
    assert email_client.list_accounts() == []


def test_unknown_domains_need_server_names(mailbox, servers):
    with pytest.raises(email_client.EmailError):
        email_client.add_account("me@fastmail.com", "pw123456")
    account = email_client.add_account("me@fastmail.com", "pw123456", imap_host="imap.fastmail.com",
                                       smtp_host="smtp.fastmail.com", smtp_port=587)
    assert account["imap_host"] == "imap.fastmail.com"


def test_send_uses_smtp_with_cc_bcc_and_attachments(mailbox, servers, tmp_path):
    email_client.add_account("me@gmail.com", SECRET)
    report = tmp_path / "report.txt"
    report.write_text("numbers")
    outcome = email_client.send_email("a@x.com, b@x.com", "Report", "Attached.", cc="c@x.com", bcc="d@x.com",
                                      attachments=[str(report)])
    assert outcome == {"sent": True, "via": "smtp", "from": "me@gmail.com", "to": ["a@x.com", "b@x.com"]}
    sent = servers[0]
    assert sent["host"] == "smtp.gmail.com" and sent["to"] == ["a@x.com", "b@x.com", "c@x.com", "d@x.com"]
    assert sent["message"]["Cc"] == "c@x.com" and "Bcc" not in sent["message"]
    assert [p.get_filename() for p in sent["message"].iter_attachments()] == ["report.txt"]


def test_starttls_port_is_used_for_outlook(mailbox, servers):
    email_client.add_account("me@outlook.com", SECRET)
    email_client.send_email("a@x.com", "Hi", "Body")
    assert servers[0]["port"] == 587


def test_without_any_account_it_opens_a_draft_and_says_not_sent(mailbox, servers):
    result = email_client.tool_email_send("prof@tamu.edu", "Extension", "Could I have two more days?")
    assert result.startswith("NOT SENT YET")
    assert servers == []
    assert mailbox["opened"][0].startswith("https://mail.google.com/mail/?view=cm")
    assert "Extension" in mailbox["opened"][0]


def test_compose_link_follows_the_sender_domain():
    link = email_client.compose_link(["a@x.com"], "Hi there", "Line 1\nLine 2", [], [], sender="me@tamu.edu")
    assert link.startswith("https://outlook.office.com/mail/deeplink/compose?to=a%40x.com")
    assert "Hi%20there" in link and "Line%201%0ALine%202" in link
    assert email_client.compose_link(["a@x.com"], "S", "B", [], [], sender="me@fastmail.com").startswith("mailto:a%40x.com?")


def test_outlook_desktop_is_used_when_there_is_no_password(mailbox, servers, monkeypatch):
    monkeypatch.setattr(email_client, "outlook_available", lambda: True)
    calls = []
    monkeypatch.setattr(email_client.subprocess, "run",
                        lambda argv, **k: calls.append(k["env"]) or type("R", (), {"returncode": 0, "stderr": ""})())
    outcome = email_client.send_email("a@x.com", "Subj", "Body")
    assert outcome["via"] == "outlook" and calls[0]["NYX_TO"] == "a@x.com" and calls[0]["NYX_SUBJECT"] == "Subj"
    assert servers == [] and mailbox["opened"] == []


def test_a_failing_outlook_falls_back_to_a_draft(mailbox, servers, monkeypatch):
    monkeypatch.setattr(email_client, "outlook_available", lambda: True)
    monkeypatch.setattr(email_client.subprocess, "run",
                        lambda argv, **k: type("R", (), {"returncode": 1, "stderr": "profile missing"})())
    outcome = email_client.send_email("a@x.com", "Subj", "Body")
    assert outcome["sent"] is False and "profile missing" in outcome["note"] and len(mailbox["opened"]) == 1


def test_list_and_read_emails(mailbox, servers):
    email_client.add_account("me@gmail.com", SECRET)
    listing = email_client.tool_email_list(query="noon", limit=5)
    assert "[9] ● " in listing and "[7] " in listing and "Note 9" in listing
    assert '"noon"' in FakeIMAP.instances[-1].criteria
    full = email_client.tool_email_read("9")
    assert "Subject: Lunch?" in full and "Are you free at noon?" in full


def test_reply_keeps_the_thread_and_reply_all_skips_yourself(mailbox, servers):
    email_client.add_account("me@gmail.com", SECRET)
    result = email_client.tool_email_reply("9", "Yes, see you then.", reply_all=True)
    assert "ana@example.com" in result and "bo@example.com" in result
    message = servers[0]["message"]
    assert message["Subject"] == "Re: Lunch?" and message["In-Reply-To"] == "<m1@example.com>"
    assert "me@gmail.com" not in servers[0]["to"]
    assert "> Are you free at noon?" in message.get_content()


def test_tools_register_with_the_contract_categories():
    registry = ToolRegistry()
    email_client.register_email_tools(registry)
    categories = {tool.name: tool.category for tool in registry.list_tools()}
    assert categories == {"email_send": "email.send", "email_list": "email.read", "email_read": "email.read",
                          "email_reply": "email.send", "email_compose": "apps", "email_accounts": "general"}


def test_routes_hide_passwords_and_refuse_remote_writes(mailbox, servers):
    import server

    local = TestClient(server.app, client=("127.0.0.1", 50021))
    added = local.post("/api/email/accounts", json={"address": "me@gmail.com", "app_password": SECRET})
    assert added.status_code == 200 and SECRET.replace(" ", "") not in added.text
    listing = local.get("/api/email/accounts").json()
    assert listing["accounts"][0]["address"] == "me@gmail.com" and listing["outlook_app_available"] is False
    account_id = listing["accounts"][0]["id"]
    assert local.post(f"/api/email/test/{account_id}").json()["ok"] is True
    assert local.post("/api/email/accounts", json={"address": "nope"}).status_code == 400
    remote = TestClient(server.app, client=("203.0.113.5", 50022))
    assert remote.post("/api/email/accounts", json={"address": "x@gmail.com"}).status_code == 403
    assert remote.delete(f"/api/email/accounts/{account_id}").status_code == 403
    assert local.delete(f"/api/email/accounts/{account_id}").json() == {"ok": True}
    assert mailbox["secrets"].get(email_client._secret_name(account_id)) == []
