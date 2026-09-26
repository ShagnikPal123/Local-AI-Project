"""Command Zone: one line to the whole team, and one place to see what the AIs want from the owner.

Owner request (2026-09-16), with a screenshot of Claude's usage card: a tab "so users know what
they use, what tabs they use, what tabs the AI wants to generate for them, what the AI wants approval
for, if the AI was sent to work on something and finds an idea the user can approve here … where you
can send a simple prompt, a small message, and see what AI are doing. It auto prompts everything so
sub agents, normal agents, and the tabs needed are contacted."

Three parts, each built on something Nyx already records:

* **Usage** — daily rollups of ``learning/turns.jsonl``. That file rotates at 5,000 lines, so the
  rollup is what keeps "All" true after months of use. No provider reports token counts here, so
  tokens are an estimate from the text (about four characters a token) and are labelled as one.
* **Inbox** — ideas and tab suggestions that agents file with ``propose_idea`` / ``suggest_tab``
  while they work, plus Nyx's own "a tab you'd use" prediction. Nothing in it runs until the owner
  approves it (generative-ai.md › Keep people in control).
* **Dispatch** — the Command Zone chat. Every message there carries a routing brief and takes the
  full pipeline, so the Manager hands the work to agents and tabs instead of answering alone.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from paths import atomic_replace, data_path

CHAT_TITLE = "Command Zone"
BRIEF_PREFIX = "[Command Zone]"

#: Characters per token for the estimate. English prose runs 3.5–4.5 with the tokenizers Nyx uses.
CHARS_PER_TOKEN = 4

#: The activity grid always spans this many days, so switching the range never reflows it.
GRID_DAYS = 26 * 7

RANGES = {"all": None, "30d": 30, "7d": 7}

_MAX_PENDING = 50
_MAX_RESOLVED = 60
_TITLE_LIMIT = 120
_DETAIL_LIMIT = 1500

#: Book lengths in estimated tokens (words × 1.3), smallest first, for "that's about N× …".
BOOKS = [
    ("The Old Man and the Sea", 35_000),
    ("The Hobbit", 124_000),
    ("Pride and Prejudice", 159_000),
    ("Moby-Dick", 273_000),
    ("War and Peace", 763_000),
    ("the whole Harry Potter series", 1_404_000),
]

DISPATCH_BRIEF = (
    f"{BRIEF_PREFIX}\n"
    "The owner sent this from the Command Zone: a short instruction for the whole team, not a chat. "
    "Get it moving instead of answering it alone:\n"
    "- Hand each part to the agents who fit with delegate_task, or delegate_parallel when several can work "
    "at once. Make a sub-agent with create_agent only when nobody on the team fits.\n"
    "- If the owner asked for a tab, make or open it. If a new tab would help but they did not ask for one, "
    "file it with suggest_tab — they approve new tabs in the Command Zone.\n"
    "- Worthwhile ideas you or an agent notice beyond the request go to propose_idea, not into the work.\n"
    "- Actions that need permission ask the owner as usual.\n"
    "Reply in two to four short lines: who is doing what, and what (if anything) is waiting for the owner."
)


def _publish(event_type: str, **payload: Any) -> None:
    try:
        from agent_events import publish_ui

        publish_ui(event_type, **payload)
    except Exception:
        pass


def _clean(text: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def _day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------


def provider_label(provider: str, model: str = "") -> str:
    try:
        from provider_specs import BUILTIN_PROVIDERS

        name = BUILTIN_PROVIDERS.get(provider, {}).get("label") or provider
    except Exception:
        name = provider
    name = name or "Unknown"
    return f"{name} · {model}" if model else name


def compare_to_books(tokens: int) -> str:
    """A sense of scale for a big number, the way the owner's screenshot does it."""
    if tokens <= 0:
        return ""
    shortest_name, shortest = BOOKS[0]
    if tokens < shortest:
        return f"That's about {max(1, round(tokens / shortest * 100))}% of {shortest_name}."
    name, size = max((b for b in BOOKS if b[1] <= tokens), key=lambda b: b[1])
    times = tokens / size
    amount = f"{times:.1f}".rstrip("0").rstrip(".") if times < 10 else f"{round(times):,}"
    return f"That's about {amount}× the length of {name}."


class UsageRollup:
    """Per-day totals folded in from the learner's turn log, kept after that log rotates."""

    def __init__(self, path: Optional[Path] = None, turns_path: Optional[Path] = None,
                 clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self._turns_path = turns_path
        self.clock = clock
        self._lock = threading.RLock()
        self._data: Optional[Dict[str, Any]] = None
        self._seen: tuple = ()

    def _file(self) -> Path:
        return self._path or data_path("command_zone_usage.json")

    def _turns(self) -> Path:
        return self._turns_path or data_path("learning/turns.jsonl")

    def _load(self) -> Dict[str, Any]:
        if self._data is None:
            try:
                raw = json.loads(self._file().read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raw = {}
            self._data = {"last_ts": float(raw.get("last_ts") or 0), "days": dict(raw.get("days") or {})}
        return self._data

    def _save(self) -> None:
        target = self._file()
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data), encoding="utf-8")
        atomic_replace(tmp, target)

    def ingest(self) -> int:
        """Fold in turns newer than the last one seen. Returns how many were added."""
        path = self._turns()
        try:
            stat = path.stat()
        except OSError:
            return 0
        signature = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            if signature == self._seen:
                return 0
            data = self._load()
            added = 0
            newest = data["last_ts"]
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                return 0
            for line in lines:
                try:
                    record = json.loads(line)
                    ts = float(record.get("ts") or 0)
                except (ValueError, TypeError, AttributeError):
                    continue
                if ts <= data["last_ts"]:
                    continue
                self._add(data["days"], record, ts)
                newest = max(newest, ts)
                added += 1
            data["last_ts"] = newest
            self._seen = signature
            if added:
                self._save()
            return added

    @staticmethod
    def _add(days: Dict[str, Any], record: Dict[str, Any], ts: float) -> None:
        day = days.setdefault(_day(ts), {"messages": 0, "tokens": 0, "chats": [], "hours": [0] * 24,
                                         "models": {}, "agents": {}})
        day["messages"] += 1
        chars = len(str(record.get("message") or "")) + int(record.get("reply_chars") or 0)
        day["tokens"] += max(1, round(chars / CHARS_PER_TOKEN))
        chat = str(record.get("chat_id") or "")
        if chat and chat not in day["chats"]:
            day["chats"].append(chat)
        day["hours"][time.localtime(ts).tm_hour] += 1
        provider = str(record.get("provider") or "")
        agents = [str(a) for a in (record.get("agents") or []) if a]
        if provider.startswith("agent:"):
            agents.append(provider[len("agent:"):])
        elif provider:
            key = f"{provider}::{record.get('model') or ''}"
            day["models"][key] = day["models"].get(key, 0) + 1
        for agent in set(agents):
            day["agents"][agent] = day["agents"].get(agent, 0) + 1

    def summary(self, range_key: str = "all") -> Dict[str, Any]:
        self.ingest()
        range_key = range_key if range_key in RANGES else "all"
        span = RANGES[range_key]
        now = self.clock()
        with self._lock:
            days = json.loads(json.dumps(self._load()["days"]))
        cutoff = _day(now - (span - 1) * 86400) if span else ""
        picked = {d: v for d, v in days.items() if not cutoff or d >= cutoff}

        messages = sum(v["messages"] for v in picked.values())
        tokens = sum(v["tokens"] for v in picked.values())
        chats = {c for v in picked.values() for c in v["chats"]}
        hours = [sum(v["hours"][h] for v in picked.values()) for h in range(24)]
        models: Counter = Counter()
        agents: Counter = Counter()
        for v in picked.values():
            models.update(v["models"])
            agents.update(v["agents"])

        model_rows = []
        for key, count in models.most_common():
            provider, _, model = key.partition("::")
            model_rows.append({"provider": provider, "model": model, "label": provider_label(provider, model),
                               "messages": count, "share": round(count / messages, 3) if messages else 0})
        grid_start = _day(now - (GRID_DAYS - 1) * 86400)
        return {
            "range": range_key,
            "since": min(days) if days else None,
            "sessions": len(chats),
            "messages": messages,
            "tokens": tokens,
            "tokens_estimated": True,
            "active_days": sum(1 for v in picked.values() if v["messages"]),
            "peak_hour": max(range(24), key=lambda h: hours[h]) if messages else None,
            "favorite_model": model_rows[0] if model_rows else None,
            "models": model_rows[:12],
            "agents": [{"name": name, "messages": count} for name, count in agents.most_common(12)],
            "daily": {d: v["messages"] for d, v in days.items() if d >= grid_start},
            "range_start": cutoff or None,
            "today": _day(now),
            "comparison": compare_to_books(tokens),
        }


# ---------------------------------------------------------------------------
# Inbox: ideas and tabs waiting for the owner
# ---------------------------------------------------------------------------


class Inbox:
    def __init__(self, path: Optional[Path] = None, clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self.clock = clock
        self._lock = threading.RLock()
        self._data: Optional[Dict[str, Any]] = None

    def _file(self) -> Path:
        return self._path or data_path("command_zone.json")

    def _load(self) -> Dict[str, Any]:
        if self._data is None:
            try:
                raw = json.loads(self._file().read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raw = {}
            self._data = {"chat_id": str(raw.get("chat_id") or ""), "items": list(raw.get("items") or []),
                          "dismissed_tabs": list(raw.get("dismissed_tabs") or [])}
        return self._data

    def _save(self) -> None:
        target = self._file()
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=1), encoding="utf-8")
        atomic_replace(tmp, target)

    # --- filing ------------------------------------------------------------------

    def propose(self, kind: str, title: str, detail: str = "", agent: str = "") -> Dict[str, Any]:
        """File an idea or a tab suggestion. The same pending title is merged, not repeated."""
        kind = kind if kind in ("idea", "tab") else "idea"
        title = _clean(title, _TITLE_LIMIT)
        if not title:
            raise ValueError("Give the idea a short title.")
        detail = str(detail or "").strip()[:_DETAIL_LIMIT]
        agent = _clean(agent, 40) or "Nyx"
        with self._lock:
            data = self._load()
            for item in data["items"]:
                if item["status"] == "pending" and item["kind"] == kind and item["title"].lower() == title.lower():
                    if detail and detail not in item["detail"]:
                        item["detail"] = (item["detail"] + "\n\n" + detail).strip()[:_DETAIL_LIMIT]
                    self._save()
                    return dict(item)
            pending = [i for i in data["items"] if i["status"] == "pending"]
            if len(pending) >= _MAX_PENDING:
                raise ValueError(f"{_MAX_PENDING} items are already waiting for the owner. Keep this one for later.")
            item = {"id": uuid.uuid4().hex[:10], "kind": kind, "title": title, "detail": detail, "agent": agent,
                    "created_at": self.clock(), "status": "pending", "resolved_at": None, "outcome": "",
                    "turn_id": ""}
            data["items"].append(item)
            self._save()
        _publish("command_zone.changed", item_id=item["id"], action="proposed")
        return dict(item)

    def pending(self) -> List[Dict[str, Any]]:
        with self._lock:
            items = [dict(i) for i in self._load()["items"] if i["status"] == "pending"]
        return sorted(items, key=lambda i: -i["created_at"])

    def recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._lock:
            items = [dict(i) for i in self._load()["items"] if i["status"] != "pending"]
        return sorted(items, key=lambda i: -(i["resolved_at"] or 0))[:limit]

    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return next((dict(i) for i in self._load()["items"] if i["id"] == item_id), None)

    def update(self, item_id: str, **changes: Any) -> Optional[Dict[str, Any]]:
        with self._lock:
            data = self._load()
            item = next((i for i in data["items"] if i["id"] == item_id), None)
            if item is None:
                return None
            item.update(changes)
            resolved = sorted((i for i in data["items"] if i["status"] != "pending"),
                              key=lambda i: -(i["resolved_at"] or 0))
            drop = {i["id"] for i in resolved[_MAX_RESOLVED:]}
            data["items"] = [i for i in data["items"] if i["id"] not in drop]
            self._save()
            result = dict(item)
        _publish("command_zone.changed", item_id=item_id, action=result["status"])
        return result

    def dismiss_tab_topic(self, topic: str) -> None:
        with self._lock:
            data = self._load()
            lowered = topic.strip().lower()
            if lowered and lowered not in data["dismissed_tabs"]:
                data["dismissed_tabs"] = (data["dismissed_tabs"] + [lowered])[-100:]
                self._save()

    def restore_tab_topic(self, topic: str) -> None:
        with self._lock:
            data = self._load()
            data["dismissed_tabs"] = [t for t in data["dismissed_tabs"] if t != topic.strip().lower()]
            self._save()

    def dismissed_tabs(self) -> List[str]:
        with self._lock:
            return list(self._load()["dismissed_tabs"])

    # --- the Command Zone chat ---------------------------------------------------------

    @property
    def chat_id(self) -> str:
        with self._lock:
            return self._load()["chat_id"]

    def set_chat_id(self, chat_id: str) -> None:
        with self._lock:
            self._load()["chat_id"] = chat_id
            self._save()


INBOX = Inbox()
USAGE = UsageRollup()


def predicted_tab() -> Optional[Dict[str, Any]]:
    """Nyx's own suggestion — the topic the owner keeps coming back to that no tab covers yet."""
    try:
        from predictor import SCHEDULER

        topic, why = SCHEDULER.needed_tab()
    except Exception:
        return None
    if not topic or topic.lower() in INBOX.dismissed_tabs():
        return None
    if any(i["kind"] == "tab" and i["title"].lower() == topic.lower() for i in INBOX.pending()):
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:40]
    return {"id": f"predicted-{slug}", "kind": "tab", "title": topic, "detail": f"Because {why}.",
            "agent": "Nyx", "created_at": None, "status": "pending", "predicted": True}


def ensure_chat(store: Any) -> str:
    """The chat every Command Zone message goes to. Made on first use, and again if it was deleted."""
    chat_id = INBOX.chat_id
    if chat_id and chat_id in store.data.get("chats", {}):
        return chat_id
    chat_id = store.create(CHAT_TITLE, activate=False)
    INBOX.set_chat_id(chat_id)
    return chat_id


def brief_for_chat(chat_id: str) -> str:
    """The routing brief when a turn runs in the Command Zone chat, else nothing."""
    return DISPATCH_BRIEF if chat_id and chat_id == INBOX.chat_id else ""


def idea_message(item: Dict[str, Any]) -> str:
    source = f" ({item['agent']} suggested it)" if item.get("agent") and item["agent"] != "Nyx" else ""
    detail = f"\n\n{item['detail']}" if item.get("detail") else ""
    return f"Go ahead with this idea{source}: {item['title']}{detail}"


def resolve(item_id: str, approve: bool, *, dispatch: Callable[[str], Dict[str, Any]],
            make_tab: Optional[Callable[[str, str], str]] = None) -> Dict[str, Any]:
    """Approve or dismiss one inbox item.

    An approved idea is sent to the Command Zone chat, so the team picks it up the same way as a
    typed command. An approved tab is built in the background — designing it can take a model call.
    """
    now = time.time()
    if item_id.startswith("predicted-"):
        suggestion = predicted_tab()
        if suggestion is None or suggestion["id"] != item_id:
            raise KeyError(item_id)
        if not approve:
            INBOX.dismiss_tab_topic(suggestion["title"])
            item = INBOX.propose("tab", suggestion["title"], suggestion["detail"], "Nyx")
            return INBOX.update(item["id"], status="dismissed", resolved_at=now, outcome="Dismissed") or item
        item = INBOX.propose("tab", suggestion["title"], suggestion["detail"], "Nyx")
        item_id = item["id"]

    item = INBOX.get(item_id)
    if item is None:
        raise KeyError(item_id)
    if item["status"] != "pending":
        raise ValueError("That has already been answered.")
    if not approve:
        if item["kind"] == "tab":
            INBOX.dismiss_tab_topic(item["title"])
        return INBOX.update(item_id, status="dismissed", resolved_at=now, outcome="Dismissed") or item

    if item["kind"] == "idea":
        started = dispatch(idea_message(item))
        return INBOX.update(item_id, status="approved", resolved_at=now, turn_id=started.get("turn_id", ""),
                            outcome="Sent to the team") or item

    maker = make_tab or _make_tab
    INBOX.update(item_id, status="approved", resolved_at=now, outcome="Making the tab…")

    def build() -> None:
        try:
            result = maker(item["title"], item["detail"])
        except Exception as error:  # noqa: BLE001 - shown on the item, never raised into a thread
            result = f"Error: {error}"
        outcome = result[:200] if result.startswith("Error") else f"Made the “{item['title']}” tab"
        INBOX.update(item_id, outcome=outcome)

    threading.Thread(target=build, name=f"nyx-zone-tab-{item_id}", daemon=True).start()
    return INBOX.get(item_id) or item


def restore(item_id: str) -> Dict[str, Any]:
    """Put a dismissed item back — the undo for Dismiss."""
    item = INBOX.get(item_id)
    if item is None:
        raise KeyError(item_id)
    if item["status"] != "dismissed":
        raise ValueError("Only dismissed items can be put back.")
    if item["kind"] == "tab":
        INBOX.restore_tab_topic(item["title"])
    return INBOX.update(item_id, status="pending", resolved_at=None, outcome="") or item


def _make_tab(title: str, detail: str) -> str:
    from landscape_tools import tool_ui_create_tab

    return tool_ui_create_tab(title, description=f"A workspace for {title}, approved in the Command Zone. {detail}".strip())


def elsewhere(owner: bool) -> List[Dict[str, Any]]:
    """Approvals that belong to another tab, counted here so none are missed. Details stay in their tab."""
    found: List[Dict[str, Any]] = []
    try:
        from trading import guard

        trades = guard.pending_approvals()
        if trades:
            found.append({"id": "trading", "tab": "trading", "count": len(trades),
                          "label": "Trades waiting for your OK", "detail": "Prices move — decide in Trading."})
    except Exception:
        pass
    try:
        from change_review import CHANGE_LOG

        summary = CHANGE_LOG.summary()
        count = int(summary.get("awaiting_review", 0)) + int(summary.get("ready_to_publish", 0))
        if count:
            found.append({"id": "changes", "tab": "improve", "count": count,
                          "label": "Improvements to review", "detail": "Changes Nyx wants to make to itself."})
    except Exception:
        pass
    if owner:
        try:
            import key_pool

            alerts = key_pool.alerts()
            if alerts:
                found.append({"id": "keys", "tab": "keys", "count": len(alerts),
                              "label": "API keys that keep failing", "detail": "Keep retrying them or remove them."})
        except Exception:
            pass
    return found


def tab_usage() -> Dict[str, Any]:
    """How often each tab is opened (all time), and where the owner usually goes next."""
    visits: Dict[str, int] = {}
    next_tab = None
    try:
        from predictor import PREDICTOR

        visits = PREDICTOR.visits()
        next_tab = PREDICTOR.next_tab()
    except Exception:
        pass
    user_labels: Dict[str, str] = {}
    try:
        from dynamic_tabs import TAB_STORE

        user_labels = {str(t.get("id")): str(t.get("label") or t.get("id")) for t in TAB_STORE.list_tabs()}
    except Exception:
        pass
    total = sum(visits.values())
    rows = []
    for tab, count in sorted(visits.items(), key=lambda kv: -kv[1]):
        if tab.startswith("user-") and tab not in user_labels:
            continue  # a tab that has since been deleted
        rows.append({"id": tab, "label": user_labels.get(tab, ""), "user": tab.startswith("user-"),
                     "visits": count, "share": round(count / total, 3) if total else 0})
    return {"tabs": rows, "total": total, "next": next_tab}


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def _calling_agent(agent: str) -> str:
    if agent:
        return agent
    try:
        from tool_context import current

        ctx = current()
        chat = getattr(ctx, "chat_id", "") if ctx else ""
        if chat.startswith("agent:"):
            return chat[len("agent:"):].title()
    except Exception:
        pass
    return "Nyx"


def tool_propose_idea(title: str, detail: str = "", agent: str = "") -> str:
    try:
        item = INBOX.propose("idea", title, detail, _calling_agent(agent))
    except ValueError as error:
        return f"Error: {error}"
    return f"Filed “{item['title']}” in the Command Zone. The owner decides; carry on with your task."


def tool_suggest_tab(label: str, why: str = "", agent: str = "") -> str:
    try:
        from dynamic_tabs import TAB_STORE

        if any(str(t.get("label", "")).lower() == _clean(label, 60).lower() for t in TAB_STORE.list_tabs()):
            return f"A tab called {label!r} already exists — open it instead."
    except Exception:
        pass
    try:
        item = INBOX.propose("tab", label, why, _calling_agent(agent))
    except ValueError as error:
        return f"Error: {error}"
    return f"Suggested the “{item['title']}” tab in the Command Zone. It is made only if the owner approves."


def register_command_zone_tools(registry: Any) -> None:
    from tools import ToolParam as P

    registry.register(
        "propose_idea",
        "File an idea for the owner to approve in the Command Zone. Use it when, while working, you notice "
        "something worth doing that is outside what you were asked (an improvement, a follow-up, a risk). "
        "Do not start the idea yourself.",
        [P("title", "string", "The idea in a few words"),
         P("detail", "string", "What it is, why it's worth it, and what doing it would take", required=False),
         P("agent", "string", "Your name, if you are an agent", required=False)],
        tool_propose_idea, category="general", label=lambda a: f"Filing an idea: {str(a.get('title', ''))[:40]}")
    registry.register(
        "suggest_tab",
        "Suggest a new tab for the owner to approve in the Command Zone, when a tab would help with something "
        "they keep doing and they did not ask for one. If they asked for a tab, make it with ui_create_tab instead.",
        [P("label", "string", "The tab's name"),
         P("why", "string", "What the owner would use it for", required=False),
         P("agent", "string", "Your name, if you are an agent", required=False)],
        tool_suggest_tab, category="general", label=lambda a: f"Suggesting a tab: {str(a.get('label', ''))[:40]}")
