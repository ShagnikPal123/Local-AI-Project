"""ID0 + All — Big Kahuna as a companion (Request S21, S22).

The owner: "it uses active collaboration, thinks in background, knows and predicts, has its own chat
which is where the thinking occurs and can talk to the user even when the main chat is open … I can
say in the voice to open gmail and type this email and it can open gmail before I say what to type
then types extremely fast."

So, while the mode is on:

* **Its own chat** (``kahuna/companion.jsonl``): Big Kahuna's thoughts after each main-chat answer
  (who led, what it predicts next, what it learned) and the owner's direct questions to it.
* **Voice intents on partial speech.** ``intent`` reads the words *while they are still being said*.
  Safe, reversible actions — opening a site or a tab — are marked ``early`` and happen at once;
  anything else waits for the full sentence. An email becomes a Gmail draft that opens already
  filled in. Nothing here ever sends, buys, deletes or posts: the owner presses Send.
* ``act`` runs an action on this PC (the default browser), owner-only and loopback-only at the route.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import webbrowser
from typing import Any, Dict, List, Optional

import identity0
from identity0 import state

FILE = "companion.jsonl"
_MAX_LINES = 500
_lock = threading.Lock()
_last_thought = 0.0

GMAIL_INBOX = "https://mail.google.com/mail/u/0/#inbox"
GMAIL_COMPOSE = "https://mail.google.com/mail/?view=cm&fs=1"

#: Spoken names of places the owner opens, and where they are. Only these (and Google searches) open.
SITES: Dict[str, str] = {
    "gmail": GMAIL_INBOX, "google mail": GMAIL_INBOX, "my email": GMAIL_INBOX, "my mail": GMAIL_INBOX,
    "youtube": "https://www.youtube.com", "google": "https://www.google.com", "github": "https://github.com",
    "calendar": "https://calendar.google.com", "google calendar": "https://calendar.google.com",
    "drive": "https://drive.google.com", "google drive": "https://drive.google.com",
    "docs": "https://docs.google.com", "google docs": "https://docs.google.com",
    "sheets": "https://sheets.google.com", "google sheets": "https://sheets.google.com",
    "maps": "https://maps.google.com", "google maps": "https://maps.google.com",
    "outlook": "https://outlook.live.com/mail/", "spotify": "https://open.spotify.com",
    "netflix": "https://www.netflix.com", "amazon": "https://www.amazon.com", "reddit": "https://www.reddit.com",
    "twitter": "https://x.com", "linkedin": "https://www.linkedin.com", "wikipedia": "https://en.wikipedia.org",
    "news": "https://news.google.com", "google news": "https://news.google.com", "weather": "https://weather.com",
    "tradingview": "https://www.tradingview.com", "yahoo finance": "https://finance.yahoo.com",
    "robinhood": "https://robinhood.com", "discord": "https://discord.com/app", "whatsapp": "https://web.whatsapp.com",
    "instagram": "https://www.instagram.com", "facebook": "https://www.facebook.com", "twitch": "https://www.twitch.tv",
    "notion": "https://www.notion.so", "canva": "https://www.canva.com", "figma": "https://www.figma.com",
    "chatgpt": "https://chatgpt.com", "claude": "https://claude.ai", "translate": "https://translate.google.com",
}

_OPEN = re.compile(r"\b(?:open|launch|pull up|bring up|go to|show me|switch to|take me to)\s+(?:up\s+)?(?:the\s+|my\s+)?"
                   r"(?P<target>[a-z0-9 .'-]{2,40}?)(?:\s+(?:tab|page|app|website|site))?(?=$|[.,!?]|\s+(?:and|then|so)\b)", re.I)
_EMAIL = re.compile(r"\b(?:write|send|compose|draft|type|start)\s+(?:an?\s+|this\s+|the\s+)?(?:e-?mail|mail|message)"
                    r"(?:\s+to\s+(?P<to>[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}|[^,.:]+?))?(?:\s*(?:,|:|\bsaying\b|\bthat says\b|\babout\b|\bsay(?:ing)?\b|\basking\b|"
                    r"\btelling\b|\bletting\b)\s*(?P<body>.+))?$", re.I)
_SEARCH = re.compile(r"\b(?:search(?: google)?(?: for)?|google|look up)\s+(?P<q>.{2,120})$", re.I)
_ADDRESS = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def enabled() -> bool:
    return bool(state.get_settings().get("id0_all", False))


# --- its own chat ------------------------------------------------------------------------------


def history(limit: int = 80) -> List[Dict[str, Any]]:
    try:
        lines = state.path(FILE).read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def say(role: str, text: str, kind: str = "message", **extra: Any) -> Dict[str, Any]:
    """Append to the companion chat and tell the UI (``kahuna.companion`` event)."""
    entry = {"ts": time.time(), "role": role, "kind": kind, "text": (text or "").strip()[:4000], **extra}
    target = state.path(FILE)
    with _lock:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        try:
            lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
            if len(lines) > _MAX_LINES:
                target.write_text("".join(lines[-_MAX_LINES:]), encoding="utf-8")
        except OSError:
            pass
    try:
        from agent_events import publish_ui

        publish_ui("kahuna.companion", message=entry)
    except Exception:  # noqa: BLE001
        pass
    return entry


def clear() -> None:
    with _lock:
        try:
            state.path(FILE).unlink()
        except OSError:
            pass


def after_answer(record: Dict[str, Any], plan: Any) -> Optional[Dict[str, Any]]:
    """Think in the background after a main-chat answer: who led, what comes next (offline, throttled)."""
    global _last_thought
    if not enabled() or time.time() - _last_thought < 20:
        return None
    _last_thought = time.time()
    lead = (record.get("lead") or {})
    parts = [f"{lead.get('member', '?')} led ({plan.domain}, {round(lead.get('ms', 0) / 1000, 1)} s)."]
    if plan.helpers:
        parts.append(f"I asked {', '.join(h.id for h in plan.helpers)} first.")
    if plan.shadow is not None:
        parts.append(f"{plan.shadow.id} is answering too, so I can compare them.")
    try:
        from identity0 import predict

        guess = predict.everything(record.get("prompt", ""))
        if guess.get("next_tab"):
            parts.append(f"Next you'll probably want the {guess['next_tab'].get('tab')} tab.")
        if guess.get("agents"):
            parts.append(f"{guess['agents'][0]['name']} fits this kind of work.")
    except Exception:  # noqa: BLE001
        pass
    return say("kahuna", " ".join(parts), kind="thought", domain=plan.domain)


def ask(text: str, router: Any) -> Dict[str, Any]:
    """The owner talks to Big Kahuna directly, in its own chat, while the main chat carries on."""
    say("owner", text)
    recent = [r for r in history(16) if r.get("kind") in ("message", "thought")]
    try:
        from identity0 import supercore

        persona = supercore.system_note() + "\n"
    except Exception:  # noqa: BLE001
        persona = ""
    messages: List[Dict[str, Any]] = [{"role": "system", "content": persona + (
        f"You are {identity0.NAME} (second name {identity0.CODENAME}), the owner's companion inside the Nyx app. "
        "You run in the background next to the main chat: you pick which AI models answer, compare them, learn, "
        "and predict what the owner needs. Answer briefly and warmly, like a sharp friend. If they ask you to open "
        "something or write an email, say you're on it; the app does the action.")}]
    for row in recent[:-1]:
        messages.append({"role": "user" if row.get("role") == "owner" else "assistant", "content": row.get("text", "")})
    messages.append({"role": "user", "content": text})
    provider = (getattr(router, "providers", {}) or {}).get(identity0.PROVIDER_ID)
    reply = ""
    try:
        reply = provider.chat(messages) if provider is not None and provider.is_available() else router.chat(messages)[0]
    except Exception as error:  # noqa: BLE001
        reply = f"I couldn't reach a model just now ({str(error)[:120]})."
    return say("kahuna", reply)


# --- voice intents ----------------------------------------------------------------------------


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _tab_for(target: str, tabs: List[Dict[str, str]]) -> Optional[str]:
    wanted = target.lower().strip()
    for tab in tabs:
        names = {str(tab.get("id", "")).lower(), str(tab.get("label", "")).lower()}
        if wanted in names or any(n and (wanted == n or wanted.rstrip("s") == n.rstrip("s")) for n in names):
            return str(tab.get("id"))
    return None


def intent(text: str, *, final: bool = False, tabs: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """Actions in what the owner is saying. ``early`` ones are safe to run before the sentence ends."""
    said = _clean(text)
    actions: List[Dict[str, Any]] = []
    email = _EMAIL.search(said)
    opens_mail = bool(re.search(r"\b(g ?mail|e-?mail|mail)\b", said, re.I))
    for match in _OPEN.finditer(said):
        target = match.group("target").strip().lower().rstrip(".")
        target = re.sub(r"^(the|my)\s+", "", target)
        tab = _tab_for(target, tabs or [])
        if tab:
            actions.append({"kind": "open_tab", "tab": tab, "label": target, "early": True, "key": f"tab:{tab}"})
        elif target in SITES:
            actions.append({"kind": "open_url", "url": SITES[target], "label": target, "early": True,
                            "key": f"url:{target}"})
    if email and opens_mail:
        to = _clean(email.group("to") or "")
        body = _clean(email.group("body") or "")
        address = _ADDRESS.search(to or body or "")
        if final:
            actions = [a for a in actions if a.get("label") not in ("gmail", "google mail", "my email", "my mail")]
            actions.append({"kind": "compose_email", "to": address.group(0) if address else to, "spoken": body or said,
                            "early": False, "key": "compose"})
        elif not any(a.get("key", "").startswith("url:") for a in actions):
            actions.append({"kind": "open_url", "url": GMAIL_INBOX, "label": "gmail", "early": True, "key": "url:gmail"})
    if not actions and final:
        search = _SEARCH.search(said)
        if search:
            query = search.group("q").strip()
            actions.append({"kind": "open_url", "label": f"search {query}", "early": False, "key": "search",
                            "url": "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)})
    return {"text": said, "final": final, "actions": actions, "handled": bool(actions) and final}


def draft_email(spoken: str, to: str = "", router: Any = None, budget_s: float = 6.0) -> Dict[str, str]:
    """Turn what was said into to/subject/body — the fastest member writes it, the words are the fallback."""
    draft = {"to": to, "subject": "", "body": _clean(spoken)}
    try:
        from identity0 import collab, members

        pool = members.available(router) if router is not None else []
        local = [m for m in pool if m.local and m.provider != "self"] or pool
        if local:
            answer = collab.complete(local[0].id, [{"role": "user", "content": (
                "Write the email the owner just asked for, in their voice. Reply with ONLY JSON "
                '{"subject": "...", "body": "..."}. No sign-off name unless they said one.\n\nThey said: ' + spoken[:1500])}],
                max_tokens=400, temperature=0.4, timeout=budget_s, router=router)
            match = re.search(r"\{.*\}", answer.get("text", ""), re.S)
            if match:
                data = json.loads(match.group(0))
                draft["subject"] = _clean(str(data.get("subject", "")))[:150]
                draft["body"] = str(data.get("body", "")).strip()[:5000] or draft["body"]
    except Exception:  # noqa: BLE001 - the spoken words are always a usable draft
        pass
    if not draft["subject"]:
        draft["subject"] = " ".join(draft["body"].split()[:7])[:80]
    return draft


def compose_url(to: str, subject: str, body: str) -> str:
    query = urllib.parse.urlencode({"to": to or "", "su": subject or "", "body": body or ""}, quote_via=urllib.parse.quote)
    return f"{GMAIL_COMPOSE}&{query}"


def _safe_url(url: str) -> bool:
    return url.startswith("https://") and (url in SITES.values() or url.startswith("https://www.google.com/search?q=")
                                          or url.startswith(GMAIL_COMPOSE))


def act(action: Dict[str, Any], router: Any = None, opener: Any = None) -> Dict[str, Any]:
    """Run one action on this PC. Opening only; never sending, buying or deleting."""
    open_url = opener or (lambda url: webbrowser.open(url, new=2))
    kind = action.get("kind")
    if kind == "open_url":
        url = str(action.get("url", ""))
        if not _safe_url(url):
            return {"ok": False, "error": "That address is not one Big Kahuna opens by voice."}
        open_url(url)
        say("kahuna", f"Opened {action.get('label') or url}.", kind="action")
        return {"ok": True, "opened": url}
    if kind == "compose_email":
        draft = draft_email(str(action.get("spoken", "")), str(action.get("to", "")), router=router)
        url = compose_url(draft["to"], draft["subject"], draft["body"])
        open_url(url)
        say("kahuna", f"Your draft to {draft['to'] or 'someone'} is open in Gmail — check it and press Send.",
            kind="action", draft=draft)
        return {"ok": True, "opened": url, "draft": draft}
    return {"ok": False, "error": f"Unknown action: {kind}"}
