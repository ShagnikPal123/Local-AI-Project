"""Email helpers that draft and ask: sort new mail, write a reply, wait for the owner before anything is sent.

"An avatar or simple chat reads each new email as it arrives … optional auto-reply … blocks spam … rules per sender."
The owner's rule for now is *draft and ask first, until he says otherwise*, so nothing in this module sends on its
own:

* ``check_new`` looks at unread mail once and labels each message ``draft`` (needs a reply), ``notify`` (worth a
  mention), ``spam`` or ``ignore``. It only reads headers and a short snippet; it never opens a link, an attachment
  or a message flagged as spam, and it never deletes or moves anything.
* ``save_draft`` stores a reply the assistant wrote. It stays ``pending`` in a queue the owner sees.
* ``send_draft`` is the only way out, and callers gate it: the owner's click on a route, or the ``email_send_draft``
  tool, which shows an approval card with the full text unless the owner switched ``send_without_asking`` on.
* Per-sender rules are changed by the owner only (routes), never by a tool, because a rule written while reading a
  stranger's email could be an instruction hidden in that email.

Rules can only say draft / notify / ignore / spam. A "send by itself" action is deliberately not offered.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from paths import data_path

RULE_ACTIONS = ("draft", "notify", "ignore", "spam")
FILE = "email_helpers.json"
_SEEN_LIMIT = 500
_lock = threading.Lock()


class HelperError(RuntimeError):
    """Something the owner can act on, in plain words."""


def _load() -> Dict[str, Any]:
    try:
        data = json.loads(data_path(FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: Dict[str, Any]) -> None:
    data_path(FILE).write_text(json.dumps(data, indent=1), encoding="utf-8")


# --- settings -----------------------------------------------------------------------------------------------


def settings() -> Dict[str, Any]:
    return {"send_without_asking": bool(_load().get("send_without_asking", False))}


def set_send_without_asking(on: bool) -> Dict[str, Any]:
    """The owner's switch for "stop asking me". Off until he turns it on; the outside-content gate still applies."""
    with _lock:
        data = _load()
        data["send_without_asking"] = bool(on)
        _save(data)
    return settings()


# --- per-sender rules ---------------------------------------------------------------------------------------


def list_rules() -> List[Dict[str, Any]]:
    return [r for r in _load().get("rules", []) if isinstance(r, dict)]


def add_rule(match: str, action: str, note: str = "") -> Dict[str, Any]:
    """``match`` is an address, a domain such as ``@school.edu``, or a name fragment, compared without case."""
    match, action = (match or "").strip().lower(), (action or "").strip().lower()
    if len(match) < 3:
        raise HelperError("A sender rule needs at least 3 characters: an address, a domain like @school.edu, or part of a name.")
    if action not in RULE_ACTIONS:
        raise HelperError(f"A rule can only say {', '.join(RULE_ACTIONS)}. Sending on its own is not offered yet.")
    with _lock:
        data = _load()
        rules = [r for r in data.get("rules", []) if r.get("match") != match]
        rule = {"id": uuid.uuid4().hex[:8], "match": match, "action": action, "note": (note or "")[:200]}
        rules.append(rule)
        data["rules"] = rules
        _save(data)
    return rule


def remove_rule(rule_id: str) -> bool:
    with _lock:
        data = _load()
        kept = [r for r in data.get("rules", []) if r.get("id") != rule_id]
        if len(kept) == len(data.get("rules", [])):
            return False
        data["rules"] = kept
        _save(data)
    return True


def rule_for(sender: str) -> Optional[Dict[str, Any]]:
    lowered = (sender or "").lower()
    return next((r for r in list_rules() if r.get("match") and r["match"] in lowered), None)


# --- sorting new mail ---------------------------------------------------------------------------------------

_SPAM = re.compile(
    r"(?i)\b(you(?:'ve| have) won|claim your (?:prize|reward)|act now|limited[- ]time offer|100% free|no cost to you|"
    r"crypto giveaway|double your|wire transfer|verify your account (?:now|immediately)|your account (?:will be|has been) "
    r"(?:suspended|locked)|unsubscribe now|viagra|casino|lottery|click here to claim)\b")
_ASKS = re.compile(r"(?i)(\?|\b(?:please (?:reply|respond|confirm|send|let me know)|can you|could you|would you|let me know|"
                   r"are you (?:free|available)|rsvp|deadline|by (?:monday|tuesday|wednesday|thursday|friday|tomorrow|tonight))\b)")


def looks_like_spam(item: Dict[str, Any]) -> bool:
    """A cheap smell test on the subject and snippet. It only labels; the message is never deleted."""
    text = f"{item.get('subject', '')} {item.get('snippet', '')}"
    shouting = sum(1 for c in item.get("subject", "") if c.isupper()) > 12 and item.get("subject", "").isupper()
    return bool(_SPAM.search(text)) or shouting


def classify(item: Dict[str, Any]) -> Dict[str, str]:
    """What to do with one listed message: the owner's rule for the sender first, then a guess."""
    rule = rule_for(item.get("from", ""))
    if rule:
        return {"action": rule["action"], "why": f"your rule for “{rule['match']}”"}
    if looks_like_spam(item):
        return {"action": "spam", "why": "it reads like spam"}
    if _ASKS.search(f"{item.get('subject', '')} {item.get('snippet', '')}"):
        return {"action": "draft", "why": "it asks something"}
    return {"action": "notify", "why": "new mail, nothing asked"}


def check_new(account: str = "", limit: int = 20) -> Dict[str, Any]:
    """Look at unread mail not seen before, label it, remember it. Reads headers and a snippet only."""
    import email_client

    picked = email_client._pick_account(account)
    key = (picked or {}).get("address", account or "").lower()
    items = email_client.list_emails(account, unread_only=True, limit=limit)
    with _lock:
        data = _load()
        seen = list(data.get("seen", {}).get(key, []))
        fresh = [i for i in items if i["id"] not in seen]
        data.setdefault("seen", {})[key] = (seen + [i["id"] for i in fresh])[-_SEEN_LIMIT:]
        _save(data)
    labelled = [{**i, **classify(i)} for i in fresh]
    for item in labelled:
        if item["action"] == "spam":
            item["snippet"] = ""             # nothing from a spam message is passed on to the model
    return {"account": key, "new": labelled, "already_seen": len(items) - len(fresh)}


def summarize(result: Dict[str, Any]) -> str:
    """Plain text for the chat, a text message or an email to the owner."""
    new = result.get("new", [])
    if not new:
        return "No new mail."
    order = {"draft": 0, "notify": 1, "spam": 2, "ignore": 3}
    lines = [f"{len(new)} new message(s):"]
    for item in sorted(new, key=lambda i: order.get(i["action"], 9)):
        lines.append(f"- [{item['id']}] {item['action'].upper()} — {item['from']} — {item['subject']} ({item['why']})")
    drafts = sum(1 for i in new if i["action"] == "draft")
    if drafts:
        lines.append(f"{drafts} look like they need a reply. I can draft each one; nothing is sent until you approve it.")
    return "\n".join(lines)


# --- the draft queue ----------------------------------------------------------------------------------------


def list_drafts(status: str = "pending") -> List[Dict[str, Any]]:
    drafts = [d for d in _load().get("drafts", []) if isinstance(d, dict)]
    return [d for d in drafts if not status or d.get("status") == status]


def _get(draft_id: str) -> Dict[str, Any]:
    draft = next((d for d in list_drafts("") if d.get("id") == draft_id), None)
    if draft is None:
        raise HelperError(f"No draft {draft_id!r}.")
    return draft


def _update(draft_id: str, **changes: Any) -> Dict[str, Any]:
    with _lock:
        data = _load()
        for draft in data.get("drafts", []):
            if draft.get("id") == draft_id:
                draft.update(changes)
                _save(data)
                return dict(draft)
    raise HelperError(f"No draft {draft_id!r}.")


def save_draft(body: str, message_id: str = "", to: str = "", subject: str = "", account: str = "",
               reply_all: bool = False, note: str = "") -> Dict[str, Any]:
    """Queue a reply (give ``message_id``) or a new message (give ``to``). Nothing is sent."""
    import email_client

    body = (body or "").strip()
    if not body:
        raise HelperError("A draft needs some text.")
    record: Dict[str, Any] = {"id": uuid.uuid4().hex[:8], "status": "pending", "created": time.time(), "body": body,
                              "account": account, "reply_all": bool(reply_all), "note": (note or "")[:200]}
    if message_id:
        try:
            original = email_client.read_email(message_id, account)
        except email_client.EmailError as error:
            raise HelperError(str(error)) from error
        reply_subject = original["subject"] if original["subject"].lower().startswith("re:") else f"Re: {original['subject']}"
        record.update(kind="reply", message_id=str(message_id), to=original["from"], subject=reply_subject,
                      original=original["body"][:300])
    elif to:
        record.update(kind="new", to=to, subject=subject or "(no subject)", message_id="")
    else:
        raise HelperError("Say which email this answers (message_id) or who it goes to (to).")
    with _lock:
        data = _load()
        data.setdefault("drafts", []).append(record)
        data["drafts"] = data["drafts"][-200:]
        _save(data)
    return record


def edit_draft(draft_id: str, body: str) -> Dict[str, Any]:
    draft = _get(draft_id)
    if draft["status"] != "pending":
        raise HelperError("Only a pending draft can be edited.")
    if not (body or "").strip():
        raise HelperError("A draft needs some text.")
    return _update(draft_id, body=body.strip())


def reject_draft(draft_id: str) -> Dict[str, Any]:
    draft = _get(draft_id)
    if draft["status"] != "pending":
        raise HelperError("That draft was already handled.")
    return _update(draft_id, status="rejected")


def send_draft(draft_id: str) -> Dict[str, Any]:
    """Actually send one pending draft. Callers must already have the owner's yes (see the module docstring)."""
    import email_client

    draft = _get(draft_id)
    if draft["status"] != "pending":
        raise HelperError("That draft was already handled, so it was not sent again.")
    try:
        if draft["kind"] == "reply":
            outcome = email_client.reply_email(draft["message_id"], draft["body"], draft.get("account", ""),
                                               bool(draft.get("reply_all")))
        else:
            outcome = email_client.send_email(draft["to"], draft["subject"], draft["body"], account=draft.get("account", ""),
                                              allow_compose=False)
    except email_client.EmailError as error:
        raise HelperError(str(error)) from error
    _update(draft_id, status="sent", sent_at=time.time())
    return outcome


# --- tools --------------------------------------------------------------------------------------------------


def _tool(fn, *args, **kwargs) -> str:
    import email_client

    try:
        return fn(*args, **kwargs)
    except (HelperError, email_client.EmailError) as error:
        return f"Error: {error}"


def tool_email_check_new(account: str = "", limit: int = 20) -> str:
    return _tool(lambda: summarize(check_new(account, int(limit or 20))))


def tool_email_draft_reply(message_id: str = "", body: str = "", to: str = "", subject: str = "", account: str = "",
                           reply_all: bool = False) -> str:
    def run() -> str:
        draft = save_draft(body, message_id, to, subject, account, reply_all)
        return (f"Draft {draft['id']} saved for {draft['to']} — “{draft['subject']}”. It has NOT been sent. "
                "Show the user the text and ask whether to send it; send only with email_send_draft after they say yes.")
    return _tool(run)


def tool_email_drafts() -> str:
    drafts = list_drafts("pending")
    if not drafts:
        return "No drafts are waiting."
    return "\n".join(f"- [{d['id']}] to {d['to']} — “{d['subject']}”\n  {d['body'][:160]}" for d in drafts)


def tool_email_send_draft(draft_id: str) -> str:
    def run() -> str:
        draft = _get(draft_id)
        if not settings()["send_without_asking"]:
            from permissions import ask

            ask("email.send", f"Send this email to {draft['to']}?",
                detail=f"To: {draft['to']}\nSubject: {draft['subject']}\n\n{draft['body'][:1200]}")
        outcome = send_draft(draft_id)
        return f"Sent to {', '.join(outcome.get('to') or [draft['to']])} — “{draft['subject']}”."
    from permissions import PermissionDenied

    try:
        return _tool(run)
    except PermissionDenied as error:        # the owner said no, or nobody was there to answer: say so, plainly
        return f"NOT SENT. {error}"


def tool_email_rules() -> str:
    rules = list_rules()
    if not rules:
        return "No sender rules. The default is: draft a reply when something is asked, and ask the user before sending."
    return "\n".join(f"- {r['match']} → {r['action']}" + (f" ({r['note']})" if r.get("note") else "") for r in rules)


def register_email_helper_tools(registry: Any) -> None:
    from tools import ToolParam as P

    registry.register("email_check_new", "Look at new unread email once and label each: draft (needs a reply), notify, spam or "
                      "ignore, using the user's sender rules. Reads only headers and a snippet.",
                      [P("account", "string", "Account address (default: the first)", required=False),
                       P("limit", "number", "How many unread to look at (default 20)", required=False)],
                      tool_email_check_new, category="email.read", label="Checking new email")
    registry.register("email_draft_reply", "Write a reply to an email (give message_id) or a new email (give to) as a DRAFT. "
                      "Nothing is sent. Then show the user the text and ask.",
                      [P("body", "string", "The text of the reply"), P("message_id", "string", "Id from email_list", required=False),
                       P("to", "string", "Recipient, for a new email", required=False),
                       P("subject", "string", "Subject, for a new email", required=False),
                       P("account", "string", "Account to use", required=False),
                       P("reply_all", "boolean", "Reply to everyone", required=False)],
                      tool_email_draft_reply, category="email.read", label="Drafting an email reply")
    registry.register("email_drafts", "List the email drafts waiting for the user's approval.", [],
                      tool_email_drafts, category="general", label="Checking email drafts")
    registry.register("email_send_draft", "Send one saved draft. The user is shown the full text and must approve it first.",
                      [P("draft_id", "string", "Id from email_drafts")],
                      tool_email_send_draft, category="email.send", label="Sending an approved email draft")
    registry.register("email_rules", "Which senders have a rule (draft, notify, ignore or spam). Read-only: only the user "
                      "changes rules.", [], tool_email_rules, category="general", label="Checking email rules")
