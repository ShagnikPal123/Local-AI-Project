"""Email helpers: sort new mail, queue drafts, send only on the owner's yes. No mail server, no Google, no model."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import email_client
import email_helpers
from tools import ToolRegistry
from tests.test_email_client import FakeIMAP, FakeSMTP, SECRET, mailbox, servers  # noqa: F401  (fixtures)


@pytest.fixture()
def helpers(tmp_path, monkeypatch, mailbox, servers):  # noqa: F811
    monkeypatch.setattr(email_helpers, "data_path", lambda name: tmp_path / name)
    email_client.add_account("me@gmail.com", SECRET)
    return mailbox


def _item(**kw):
    return {"id": "1", "from": "Ana <ana@example.com>", "subject": "Lunch?", "snippet": "Are you free at noon?", **kw}


def test_a_question_needs_a_draft_and_plain_news_only_a_mention():
    assert email_helpers.classify(_item())["action"] == "draft"
    assert email_helpers.classify(_item(subject="Receipt", snippet="Your order shipped."))["action"] == "notify"


def test_obvious_spam_is_labelled_spam():
    spam = _item(subject="You have won a prize", snippet="Claim your reward now, act now")
    assert email_helpers.classify(spam)["action"] == "spam"


def test_the_owners_rule_beats_the_guess(helpers):
    email_helpers.add_rule("@example.com", "ignore")
    result = email_helpers.classify(_item())
    assert result["action"] == "ignore" and "@example.com" in result["why"]


def test_rules_cannot_send_by_themselves(helpers):
    with pytest.raises(email_helpers.HelperError, match="not offered"):
        email_helpers.add_rule("ana@example.com", "send")
    with pytest.raises(email_helpers.HelperError):
        email_helpers.add_rule("a", "draft")


def test_check_new_labels_unread_mail_once_and_drops_spam_text(helpers, monkeypatch):
    mail = [_item(id="7"), _item(id="9", subject="You have won", snippet="Claim your reward, act now")]
    monkeypatch.setattr(email_client, "list_emails", lambda *a, **k: [dict(m) for m in mail])
    first = email_helpers.check_new()
    assert [i["action"] for i in first["new"]] == ["draft", "spam"] and first["new"][1]["snippet"] == ""
    again = email_helpers.check_new()
    assert again["new"] == [] and again["already_seen"] == 2
    assert "DRAFT" in email_helpers.summarize(first) and "nothing is sent" in email_helpers.summarize(first)


def test_a_draft_waits_and_nothing_is_sent(helpers, servers):
    draft = email_helpers.save_draft("Yes, noon works.", message_id="9")
    assert draft["status"] == "pending" and draft["subject"] == "Re: Lunch?" and "ana@example.com" in draft["to"]
    assert servers == [] and email_helpers.list_drafts()[0]["id"] == draft["id"]
    assert "NOT been sent" in email_helpers.tool_email_draft_reply(message_id="9", body="Sure.")
    assert servers == []


def test_sending_a_draft_replies_in_the_thread_and_only_once(helpers, servers):
    draft = email_helpers.save_draft("Yes, noon works.", message_id="9")
    email_helpers.edit_draft(draft["id"], "Yes, noon works for me.")
    email_helpers.send_draft(draft["id"])
    assert servers[0]["message"]["In-Reply-To"] == "<m1@example.com>" and "noon works for me" in servers[0]["message"].get_content()
    with pytest.raises(email_helpers.HelperError, match="already handled"):
        email_helpers.send_draft(draft["id"])
    assert len(servers) == 1 and email_helpers.list_drafts() == []


def test_a_rejected_draft_cannot_be_sent(helpers, servers):
    draft = email_helpers.save_draft("Hello", to="bo@example.com", subject="Hi")
    email_helpers.reject_draft(draft["id"])
    with pytest.raises(email_helpers.HelperError):
        email_helpers.send_draft(draft["id"])
    assert servers == []


def test_the_send_tool_asks_the_owner_first(helpers, servers, monkeypatch):
    import permissions

    asked = []
    monkeypatch.setattr(permissions, "ask", lambda category, summary, detail="": asked.append((category, summary, detail)))
    draft = email_helpers.save_draft("Hello there", to="bo@example.com", subject="Hi")
    result = email_helpers.tool_email_send_draft(draft["id"])
    assert result.startswith("Sent to bo@example.com")
    assert asked[0][0] == "email.send" and "Hello there" in asked[0][2] and "bo@example.com" in asked[0][1]


def test_a_no_from_the_owner_means_nothing_is_sent(helpers, servers, monkeypatch):
    import permissions

    def refuse(category, summary, detail=""):
        raise permissions.PermissionDenied("The owner said no.")

    monkeypatch.setattr(permissions, "ask", refuse)
    draft = email_helpers.save_draft("Hello there", to="bo@example.com", subject="Hi")
    assert email_helpers.tool_email_send_draft(draft["id"]).startswith("NOT SENT")
    assert servers == [] and email_helpers.list_drafts()[0]["status"] == "pending"


def test_the_owner_can_switch_the_asking_off_but_it_starts_on(helpers, servers, monkeypatch):
    import permissions

    monkeypatch.setattr(permissions, "ask", lambda *a, **k: pytest.fail("should not ask once switched off"))
    assert email_helpers.settings() == {"send_without_asking": False}
    email_helpers.set_send_without_asking(True)
    draft = email_helpers.save_draft("Hi", to="bo@example.com", subject="Hi")
    assert email_helpers.tool_email_send_draft(draft["id"]).startswith("Sent")


def test_tools_register_with_safe_categories():
    registry = ToolRegistry()
    email_helpers.register_email_helper_tools(registry)
    categories = {t.name: t.category for t in registry.list_tools()}
    assert categories == {"email_check_new": "email.read", "email_draft_reply": "email.read", "email_drafts": "general",
                          "email_send_draft": "email.send", "email_rules": "general"}


def test_routes_are_owner_only_and_send_is_one_click(helpers, servers):
    import server

    local = TestClient(server.app, client=("127.0.0.1", 50041))
    remote = TestClient(server.app, client=("203.0.113.5", 50042))
    rule = local.post("/api/email/helpers/rules", json={"match": "@school.edu", "action": "notify"}).json()["rule"]
    assert local.post("/api/email/helpers/rules", json={"match": "@x.com", "action": "send"}).status_code == 400
    assert remote.post("/api/email/helpers/rules", json={"match": "@school.edu", "action": "ignore"}).status_code == 403
    draft = email_helpers.save_draft("Yes.", message_id="9")
    assert remote.post(f"/api/email/helpers/drafts/{draft['id']}/send").status_code == 403 and servers == []
    overview = local.get("/api/email/helpers").json()
    assert overview["rules"][0]["id"] == rule["id"] and overview["drafts"][0]["id"] == draft["id"]
    assert local.post(f"/api/email/helpers/drafts/{draft['id']}/send").json() == {"ok": True} and len(servers) == 1
    assert local.post(f"/api/email/helpers/drafts/{draft['id']}/send").status_code == 400
    assert local.delete(f"/api/email/helpers/rules/{rule['id']}").json() == {"ok": True}


def test_a_draft_written_in_chat_tells_the_open_panel(helpers, monkeypatch):
    import agent_events

    published = []
    monkeypatch.setattr(agent_events, "publish_ui", lambda kind, **data: published.append(kind))
    email_helpers.save_draft("Hello", to="bo@example.com", subject="Hi")
    assert published == ["email.drafts.changed"]
