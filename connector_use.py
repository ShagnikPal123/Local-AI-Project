"""Using connectors inside a chat turn (Plan Null N34/N35).

Owner, 2026-09-22: "in all chats and tabs add auto connector access as well as in settings so the ai can both auto
apply and predict which connectors are needed if user doesn't say and if the user does say let's have connectors be
called while typing &(connector name)".

Three jobs:

* **Pick.** ``plan_turn`` decides which connected connectors this message needs — the ones the owner picked in the
  chat bar, the ones written as ``&name``, or, on Auto, the ones predicted from the words. What it decides becomes one
  system note the model reads, listing what each connector can do. A connector the message clearly wants but that is
  not connected is named too, so Nyx can offer to add it instead of guessing.
* **Run.** ``use_connector`` calls a connected app: a declared REST action (HTTPS, only the connector's own host, auth
  filled in from the secret store) or a tool on a remote MCP server. Anything that changes something in another
  person's account needs the owner's yes first, in the chat, before it runs.
* **Say what exists.** ``connector_actions`` / ``connectors_available`` so the model never invents an action.

The catalogue of connectors (what exists, which fields each needs) belongs to ``connectors/catalog.py``. This module
never writes a credential: it reads saved values through the catalogue and puts them straight into a request header.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from paths import data_path

_LOG = logging.getLogger("nyx.connector_use")

NOTE_PREFIX = "[Connectors for this turn]"
MENTION = re.compile(r"(?<![\w&])&([A-Za-z][\w.-]{1,40})")
AUTO, OFF = "auto", "off"

#: Hard ceilings for one connector call.
TIMEOUT = 20
MAX_CHARS = 12000
_MCP_CACHE_TTL = 300.0

_lock = threading.Lock()
_mcp_tools: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
#: Write actions the owner said yes to, per turn: (turn id, connector, action) seen once.
_confirmed: Dict[str, float] = {}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

DEFAULTS = {
    "auto": True,              # predict connectors when the owner doesn't name one
    "confirm_writes": True,    # a change in someone's account needs a yes in the chat first
    "max_per_turn": 4,
}


def _settings_path():
    return data_path("connectors/use.json")


def settings() -> Dict[str, Any]:
    try:
        saved = json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    out = dict(DEFAULTS)
    if isinstance(saved, dict):
        if "auto" in saved:
            out["auto"] = bool(saved["auto"])
        if "confirm_writes" in saved:
            out["confirm_writes"] = bool(saved["confirm_writes"])
        try:
            out["max_per_turn"] = max(1, min(8, int(saved.get("max_per_turn", out["max_per_turn"]))))
        except (TypeError, ValueError):
            pass
    return out


def save_settings(**changes: Any) -> Dict[str, Any]:
    current = settings()
    for key in ("auto", "confirm_writes"):
        if key in changes and changes[key] is not None:
            current[key] = bool(changes[key])
    if changes.get("max_per_turn") is not None:
        try:
            current["max_per_turn"] = max(1, min(8, int(changes["max_per_turn"])))
        except (TypeError, ValueError):
            pass
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=1), encoding="utf-8")
    return current


# ---------------------------------------------------------------------------
# The catalogue (connectors/catalog.py) with a small stand-in until it lands
# ---------------------------------------------------------------------------

#: Only used when connectors/catalog.py is not importable, so this module (and its tests) work on their own.
_FALLBACK: List[Dict[str, Any]] = [
    {"id": "github", "name": "GitHub", "category": "developer", "kind": "rest", "popular": 95,
     "description": "Repositories, issues and pull requests.", "keywords": ["repo", "issue", "pull request", "commit", "code"],
     "base_url": "https://api.github.com", "auth": {"type": "bearer"}, "writes": True,
     "can": ["search repositories", "read and create issues"],
     "fields": [{"key": "token", "label": "Personal access token", "secret": True, "required": True,
                 "help_url": "https://github.com/settings/tokens", "kind": "password"}]},
    {"id": "notion", "name": "Notion", "category": "productivity", "kind": "rest", "popular": 90,
     "description": "Pages and databases in a Notion workspace.", "keywords": ["notes", "wiki", "page", "database"],
     "base_url": "https://api.notion.com/v1", "auth": {"type": "bearer", "extra_headers": {"Notion-Version": "2022-06-28"}},
     "writes": True, "can": ["search pages", "read a page", "add a page"],
     "fields": [{"key": "token", "label": "Integration token", "secret": True, "required": True,
                 "help_url": "https://www.notion.so/my-integrations", "kind": "password"}]},
    {"id": "openweather", "name": "OpenWeather", "category": "data", "kind": "rest", "popular": 60,
     "description": "Current weather and forecasts.", "keywords": ["weather", "forecast", "temperature", "rain"],
     "base_url": "https://api.openweathermap.org/data/2.5", "auth": {"type": "query", "param": "appid"}, "writes": False,
     "can": ["current weather for a place"],
     "fields": [{"key": "api_key", "label": "API key", "secret": True, "required": True,
                 "help_url": "https://home.openweathermap.org/api_keys", "kind": "password"}]},
]


def _catalog():
    try:
        from connectors import catalog  # type: ignore

        return catalog
    except Exception:  # pragma: no cover - until connectors/catalog.py lands
        return None


def entries(include_custom: bool = True) -> List[Dict[str, Any]]:
    """Every connector the owner could use, from the catalogue (plus custom ones)."""
    catalog = _catalog()
    if catalog is not None:
        try:
            listed = catalog.list_catalog(include_custom=include_custom)
            if isinstance(listed, list):
                return [e for e in listed if isinstance(e, dict) and e.get("id")]
        except Exception:  # pragma: no cover - a broken catalogue must not break a turn
            _LOG.debug("catalog listing failed", exc_info=True)
    out = list(_FALLBACK)
    if include_custom:
        try:
            import connector_builder

            out += [e for e in connector_builder.custom_connectors() if isinstance(e, dict) and e.get("id")]
        except Exception:  # pragma: no cover
            pass
    return out


def entry(connector_id: str) -> Optional[Dict[str, Any]]:
    wanted = str(connector_id or "").strip().lower()
    if not wanted:
        return None
    catalog = _catalog()
    if catalog is not None:
        try:
            found = catalog.get(wanted)
            if isinstance(found, dict):
                return found
        except Exception:  # pragma: no cover
            pass
    for item in entries():
        if str(item.get("id", "")).lower() == wanted:
            return item
    return None


def is_connected(connector_id: str) -> bool:
    catalog = _catalog()
    if catalog is not None:
        try:
            return bool(catalog.is_connected(connector_id))
        except Exception:  # pragma: no cover
            pass
    try:
        import connector_builder

        return connector_builder.is_connected(connector_id)
    except Exception:  # pragma: no cover
        return False


def _values(connector_id: str) -> Dict[str, Any]:
    """The saved field values for a connector, secrets included. Never leaves this process."""
    catalog = _catalog()
    if catalog is not None:
        try:
            saved = catalog.connection_values(connector_id)
            if isinstance(saved, dict) and saved:
                return saved
        except Exception:  # pragma: no cover
            pass
    try:
        import connector_builder

        return connector_builder.connection_values(connector_id)
    except Exception:  # pragma: no cover
        return {}


def connected() -> List[Dict[str, Any]]:
    return [e for e in entries() if is_connected(e["id"])]


# ---------------------------------------------------------------------------
# What each connector can do
# ---------------------------------------------------------------------------

#: Declared REST actions for the connectors worth shipping ready to use, keyed by catalogue id.
#: Anything not listed here can still be called with a path, and MCP connectors bring their own tool list.
ACTIONS: Dict[str, List[Dict[str, Any]]] = {
    "github": [
        {"id": "my_repos", "method": "GET", "path": "/user/repos", "description": "The owner's repositories",
         "params": {"sort": "updated|created|pushed", "per_page": "how many (max 50)"}},
        {"id": "search_repos", "method": "GET", "path": "/search/repositories", "description": "Search repositories",
         "params": {"q": "search words"}},
        {"id": "issues", "method": "GET", "path": "/repos/{owner}/{repo}/issues", "description": "Issues in a repository",
         "params": {"owner": "account", "repo": "repository", "state": "open|closed|all"}},
        {"id": "create_issue", "method": "POST", "path": "/repos/{owner}/{repo}/issues", "write": True,
         "description": "Open an issue", "params": {"owner": "account", "repo": "repository", "title": "title", "body": "text"}},
    ],
    "notion": [
        {"id": "search", "method": "POST", "path": "/search", "description": "Search pages and databases",
         "params": {"query": "search words"}},
        {"id": "page", "method": "GET", "path": "/pages/{page_id}", "description": "Read one page's properties",
         "params": {"page_id": "page id"}},
        {"id": "blocks", "method": "GET", "path": "/blocks/{page_id}/children", "description": "The text on a page",
         "params": {"page_id": "page id"}},
    ],
    "openweather": [
        {"id": "weather", "method": "GET", "path": "/weather", "description": "Current weather for a place",
         "params": {"q": "city name", "units": "metric|imperial"}},
        {"id": "forecast", "method": "GET", "path": "/forecast", "description": "Five-day forecast",
         "params": {"q": "city name", "units": "metric|imperial"}},
    ],
    "vercel": [
        {"id": "projects", "method": "GET", "path": "/v9/projects", "description": "Projects on the account", "params": {}},
        {"id": "deployments", "method": "GET", "path": "/v6/deployments", "description": "Recent deployments",
         "params": {"limit": "how many"}},
    ],
    "huggingface": [
        {"id": "models", "method": "GET", "path": "/api/models", "description": "Search models",
         "params": {"search": "words", "limit": "how many"}},
        {"id": "datasets", "method": "GET", "path": "/api/datasets", "description": "Search datasets",
         "params": {"search": "words", "limit": "how many"}},
    ],
    "linear": [
        {"id": "my_issues", "method": "POST", "path": "/graphql", "description": "Issues assigned to the owner",
         "params": {}, "body": {"query": "{ viewer { assignedIssues(first: 20) { nodes { identifier title state { name } } } } }"}},
    ],
    "slack": [
        {"id": "channels", "method": "GET", "path": "/conversations.list", "description": "Channels in the workspace",
         "params": {"limit": "how many"}},
        {"id": "history", "method": "GET", "path": "/conversations.history", "description": "Recent messages in a channel",
         "params": {"channel": "channel id", "limit": "how many"}},
        {"id": "post", "method": "POST", "path": "/chat.postMessage", "write": True, "description": "Post a message",
         "params": {"channel": "channel id", "text": "what to say"}},
    ],
}


def actions_for(connector_id: str) -> List[Dict[str, Any]]:
    """Declared actions (REST) or the live tool list (MCP). Never raises."""
    item = entry(connector_id)
    if item is None:
        return []
    if str(item.get("kind")) == "mcp":
        return _mcp_tool_list(item)
    declared = item.get("actions")
    if isinstance(declared, list) and declared:
        return [a for a in declared if isinstance(a, dict) and a.get("id")]
    return list(ACTIONS.get(str(item["id"]).lower(), []))


def summary(item: Dict[str, Any]) -> str:
    """One line: what this connector is for."""
    can = item.get("can")
    if isinstance(can, list) and can:
        return ", ".join(str(c) for c in can[:4])
    listed = actions_for(str(item.get("id", "")))
    if listed:
        return ", ".join(str(a.get("description") or a.get("id")) for a in listed[:4])
    return str(item.get("description") or "")[:120]


# ---------------------------------------------------------------------------
# Picking connectors for one turn
# ---------------------------------------------------------------------------

def mentions(text: str) -> List[str]:
    """``&notion`` written anywhere in the message. Returns catalogue ids (unknown names are dropped)."""
    out: List[str] = []
    for token in MENTION.findall(text or ""):
        found = resolve(token)
        if found and found not in out:
            out.append(found)
    return out


def resolve(name: str) -> str:
    """A written name → a catalogue id: exact id, the name with any punctuation removed, or a unique prefix."""
    wanted = re.sub(r"[^a-z0-9]", "", str(name or "").lower())
    if not wanted:
        return ""
    listed = entries()
    for item in listed:
        if re.sub(r"[^a-z0-9]", "", str(item.get("id", "")).lower()) == wanted:
            return str(item["id"])
    for item in listed:
        if re.sub(r"[^a-z0-9]", "", str(item.get("name", "")).lower()) == wanted:
            return str(item["id"])
    starts = [item for item in listed
              if re.sub(r"[^a-z0-9]", "", str(item.get("name", "")).lower()).startswith(wanted)]
    return str(starts[0]["id"]) if len(starts) == 1 else ""


_WORD = re.compile(r"[a-z0-9]+")


def predict(text: str, limit: int = 3, only_connected: bool = False) -> List[Dict[str, Any]]:
    """Which connectors this message is about, scored offline (no model call, so every turn can afford it)."""
    words = set(_WORD.findall((text or "").lower()))
    if not words:
        return []
    scored: List[Dict[str, Any]] = []
    for item in entries():
        name = str(item.get("name", ""))
        hits: List[str] = []
        score = 0
        if re.sub(r"[^a-z0-9]", "", name.lower()) in {re.sub(r"[^a-z0-9]", "", w) for w in words}:
            score += 6
            hits.append(name)
        for keyword in list(item.get("keywords") or [])[:24]:
            key = str(keyword).lower().strip()
            if not key:
                continue
            if (" " in key and key in (text or "").lower()) or (" " not in key and key in words):
                score += 2
                hits.append(key)
        for phrase in list(item.get("can") or [])[:8]:
            parts = [p for p in _WORD.findall(str(phrase).lower()) if len(p) > 3]
            if parts and sum(1 for p in parts if p in words) >= max(2, len(parts) - 1):
                score += 2
                hits.append(str(phrase))
        if score <= 0:
            continue
        live = is_connected(str(item["id"]))
        if only_connected and not live:
            continue
        scored.append({"id": str(item["id"]), "name": name, "score": score + (3 if live else 0),
                       "connected": live, "why": ", ".join(dict.fromkeys(hits))[:120]})
    scored.sort(key=lambda s: -s["score"])
    return [s for s in scored if s["score"] >= 5][:limit]


def plan_turn(text: str, choice: Any = AUTO, *, surface: str = "chat") -> Dict[str, Any]:
    """What this turn may use. ``choice`` is "auto", "off" or a list of catalogue ids from the chat bar."""
    prefs = settings()
    named = mentions(text)
    picked: List[str] = []
    how = "auto"
    if isinstance(choice, list):
        picked = [resolve(c) or str(c) for c in choice]
        how = "picked"
    elif choice == OFF and not named:
        return {"ids": [], "note": "", "missing": [], "used": [], "how": "off", "explicit": False}
    for connector_id in named:
        if connector_id not in picked:
            picked.append(connector_id)
    if named:
        how = "mentioned" if how == "auto" else how

    missing: List[Dict[str, str]] = []
    usable: List[Dict[str, Any]] = []
    for connector_id in picked:
        item = entry(connector_id)
        if item is None:
            missing.append({"id": connector_id, "name": connector_id, "known": False})
        elif not is_connected(connector_id):
            missing.append({"id": str(item["id"]), "name": str(item.get("name", connector_id)), "known": True})
        else:
            usable.append(item)

    if not picked and choice == AUTO and prefs["auto"]:
        for guess in predict(text, limit=prefs["max_per_turn"]):
            item = entry(guess["id"])
            if item is None:
                continue
            if guess["connected"]:
                usable.append(item)
            elif guess["score"] >= 8:
                missing.append({"id": guess["id"], "name": guess["name"], "known": True})

    usable = usable[:prefs["max_per_turn"]]
    note = _note(usable, missing, how, named, prefs)
    return {"ids": [str(i["id"]) for i in usable], "note": note, "missing": missing,
            "used": [{"id": str(i["id"]), "name": str(i.get("name", i["id"]))} for i in usable],
            "how": how, "explicit": bool(picked)}


def _note(usable: List[Dict[str, Any]], missing: List[Dict[str, str]], how: str, named: List[str],
          prefs: Dict[str, Any]) -> str:
    if not usable and not missing:
        return ""
    lines = [NOTE_PREFIX]
    if usable:
        lines.append("These of the owner's connected apps are available right now. Use the use_connector tool to reach "
                     "them — ask connector_actions for an action list before inventing one, and say which app an answer "
                     "came from:")
        for item in usable:
            lines.append(f"- {item['id']} ({item.get('name', item['id'])}): {summary(item)}")
        if prefs["confirm_writes"]:
            lines.append("Anything that writes, sends, posts or deletes in one of these accounts needs the owner to say "
                         "yes in this chat first; ask, then call it again with confirm=true.")
    if how == "mentioned" and named:
        lines.append("The owner wrote " + ", ".join(f"&{n}" for n in named) + ", so use those.")
    elif how == "picked":
        lines.append("The owner picked these in the chat bar, so prefer them over anything else.")
    elif usable:
        lines.append("Nyx picked these from the words of the message. If they turn out not to fit, just answer normally.")
    for item in missing:
        if item.get("known"):
            lines.append(f"- {item['name']} is NOT connected. If the answer needs it, say so and offer to add it: the "
                         "owner can press + in Connectors, or say \"add " + str(item["name"]) + "\" and Nyx will ask for "
                         "what it needs.")
        else:
            lines.append(f"- There is no connector called {item['id']!r}. Tell the owner, and offer to add one.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Calling a connector
# ---------------------------------------------------------------------------

class ConnectorCallError(RuntimeError):
    """A call that cannot be made (not connected, unknown action, refused host)."""


def _requests():
    import requests

    return requests


def _https(url: str) -> str:
    parsed = urlparse(url or "")
    if parsed.scheme != "https" or not parsed.netloc:
        raise ConnectorCallError("Connectors may only talk to https addresses.")
    return url


def _fill(template: str, values: Dict[str, Any], params: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """``/repos/{owner}/{repo}/issues`` → a real path, taking each name from the call or the saved fields."""
    used: List[str] = []

    def take(match: re.Match) -> str:
        key = match.group(1)
        value = params.get(key, values.get(key, ""))
        if value in (None, ""):
            raise ConnectorCallError(f"This action needs {key!r}.")
        used.append(key)
        return re.sub(r"[^\w.@:-]", "", str(value))[:120]

    path = re.sub(r"\{(\w+)}", take, template or "")
    return path, {k: v for k, v in params.items() if k not in used}


def _auth(item: Dict[str, Any], values: Dict[str, Any], headers: Dict[str, str], query: Dict[str, Any]) -> None:
    auth = item.get("auth") if isinstance(item.get("auth"), dict) else {}
    kind = str(auth.get("type") or "bearer").lower()
    token = ""
    for key in (auth.get("token_field"), "token", "api_key", "key", "access_token", "secret"):
        if key and str(values.get(key, "")).strip():
            token = str(values[key]).strip()
            break
    for key, value in (auth.get("extra_headers") or {}).items():
        headers[str(key)] = str(value)
    if kind == "none":
        return
    if kind in ("bearer", "oauth"):
        headers["Authorization"] = f"{auth.get('prefix') or 'Bearer '}{token}".strip()
    elif kind == "header":
        headers[str(auth.get("header") or "Authorization")] = f"{auth.get('prefix') or ''}{token}"
    elif kind == "query":
        query[str(auth.get("param") or "key")] = token
    elif kind == "basic":
        import base64

        user = str(values.get(auth.get("username_field") or "username", ""))
        secret = str(values.get(auth.get("password_field") or "password", token))
        headers["Authorization"] = "Basic " + base64.b64encode(f"{user}:{secret}".encode()).decode()


def call(connector_id: str, action: str = "", *, params: Optional[Dict[str, Any]] = None, method: str = "",
         path: str = "", body: Optional[Dict[str, Any]] = None, timeout: int = TIMEOUT) -> Dict[str, Any]:
    """One connector call. Returns ``{"ok", "status", "data"|"text", "action", "writes"}``."""
    item = entry(connector_id)
    if item is None:
        raise ConnectorCallError(f"There is no connector called {connector_id!r}.")
    if not is_connected(str(item["id"])):
        raise ConnectorCallError(f"{item.get('name', connector_id)} is not connected yet.")
    params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    if str(item.get("kind")) == "mcp":
        return _mcp_call(item, action, params, timeout=timeout)

    spec = next((a for a in actions_for(str(item["id"])) if str(a.get("id")) == str(action)), None)
    if spec is None and not path:
        listed = ", ".join(str(a.get("id")) for a in actions_for(str(item["id"]))) or "none are declared"
        raise ConnectorCallError(f"{item.get('name')} has no action {action!r}. Known actions: {listed}.")
    values = _values(str(item["id"]))
    base = str(item.get("base_url") or "").rstrip("/")
    if not base:
        raise ConnectorCallError(f"{item.get('name')} has no address to call.")
    base, _ = _fill(base, values, {})
    template = str(spec["path"]) if spec else str(path)
    verb = (method or (spec.get("method") if spec else "") or "GET").upper()
    if verb not in ("GET", "POST", "PATCH", "PUT", "DELETE"):
        raise ConnectorCallError("Only GET, POST, PATCH, PUT and DELETE are allowed.")
    filled, left = _fill(template if template.startswith("/") else "/" + template, values, params)
    url = _https(base + filled)
    headers: Dict[str, str] = {"Accept": "application/json", "User-Agent": "NyxIchos/1.0"}
    query: Dict[str, Any] = {}
    _auth(item, values, headers, query)
    payload = dict(body or (spec.get("body") if spec else None) or {})
    if verb == "GET":
        query.update(left)
    else:
        payload.update({k: v for k, v in left.items() if k not in payload})
    try:
        response = _requests().request(verb, url, headers=headers, params=query or None,
                                       json=payload if verb != "GET" and payload else None, timeout=timeout)
    except Exception as error:  # noqa: BLE001 - network problems are answers, not crashes
        raise ConnectorCallError(f"{item.get('name')} could not be reached: {type(error).__name__}") from None
    return _result(item, spec, response)


def _result(item: Dict[str, Any], spec: Optional[Dict[str, Any]], response: Any) -> Dict[str, Any]:
    text = (response.text or "")[:MAX_CHARS]
    out: Dict[str, Any] = {"ok": response.status_code < 400, "status": response.status_code,
                           "connector": str(item["id"]), "action": str((spec or {}).get("id") or ""),
                           "writes": bool((spec or {}).get("write"))}
    try:
        out["data"] = json.loads(text) if text.strip().startswith(("{", "[")) else text
    except ValueError:
        out["data"] = text
    if not out["ok"]:
        out["error"] = f"{item.get('name')} answered {response.status_code}: {str(out['data'])[:300]}"
    return out


# --- remote MCP servers -----------------------------------------------------

def _mcp_post(url: str, token: str, payload: Dict[str, Any], session: str = "", timeout: int = TIMEOUT) -> Tuple[Dict[str, Any], str]:
    """One JSON-RPC message over streamable HTTP. Handles a plain JSON or an SSE answer."""
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
               "User-Agent": "NyxIchos/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if session:
        headers["Mcp-Session-Id"] = session
    response = _requests().post(_https(url), headers=headers, json=payload, timeout=timeout)
    session = response.headers.get("Mcp-Session-Id", session)
    text = (response.text or "")[:MAX_CHARS * 2]
    if response.status_code >= 400:
        raise ConnectorCallError(f"The MCP server answered {response.status_code}: {text[:200]}")
    if "text/event-stream" in response.headers.get("Content-Type", ""):
        for line in text.splitlines():
            if line.startswith("data:"):
                try:
                    message = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if isinstance(message, dict) and ("result" in message or "error" in message):
                    return message, session
        return {}, session
    try:
        return json.loads(text) if text.strip() else {}, session
    except ValueError:
        raise ConnectorCallError("The MCP server did not answer with JSON.") from None


def _mcp_session(item: Dict[str, Any], timeout: int = TIMEOUT) -> Tuple[str, str, str]:
    url = _https(str(item.get("mcp_url") or item.get("base_url") or ""))
    values = _values(str(item["id"]))
    token = str(values.get("token") or values.get("api_key") or values.get("access_token") or "").strip()
    message, session = _mcp_post(url, token, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "Nyx Ichos", "version": "1.0"}}}, timeout=timeout)
    if message.get("error"):
        raise ConnectorCallError(f"The MCP server refused the connection: {str(message['error'])[:200]}")
    try:
        _mcp_post(url, token, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session, timeout=timeout)
    except ConnectorCallError:
        pass
    return url, token, session


def _mcp_tool_list(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    key = str(item["id"])
    with _lock:
        cached = _mcp_tools.get(key)
    if cached and time.time() - cached[0] < _MCP_CACHE_TTL:
        return cached[1]
    if not is_connected(key):
        return []
    try:
        url, token, session = _mcp_session(item)
        message, _ = _mcp_post(url, token, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, session)
    except Exception:  # noqa: BLE001 - an unreachable server means no tools, not a failed turn
        _LOG.debug("mcp tools/list failed for %s", key, exc_info=True)
        return []
    tools = []
    for tool in (message.get("result") or {}).get("tools", [])[:60]:
        if isinstance(tool, dict) and tool.get("name"):
            schema = tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {}
            tools.append({"id": str(tool["name"]), "description": str(tool.get("description") or "")[:200],
                          "params": {k: str((v or {}).get("description", "")) [:80]
                                     for k, v in (schema.get("properties") or {}).items()},
                          "write": bool(tool.get("annotations", {}).get("destructiveHint")
                                        or not tool.get("annotations", {}).get("readOnlyHint", False)
                                        and re.search(r"create|update|delete|send|post|write", str(tool["name"]), re.I))})
    with _lock:
        _mcp_tools[key] = (time.time(), tools)
    return tools


def _mcp_call(item: Dict[str, Any], action: str, params: Dict[str, Any], timeout: int = TIMEOUT) -> Dict[str, Any]:
    if not action:
        raise ConnectorCallError("Say which tool on the MCP server to call.")
    url, token, session = _mcp_session(item, timeout=timeout)
    message, _ = _mcp_post(url, token, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                        "params": {"name": action, "arguments": params}}, session, timeout=timeout)
    if message.get("error"):
        return {"ok": False, "status": 0, "connector": str(item["id"]), "action": action,
                "error": str(message["error"])[:400]}
    result = message.get("result") or {}
    parts = []
    for block in result.get("content", []) if isinstance(result.get("content"), list) else []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    data = "\n".join(parts)[:MAX_CHARS] or result.get("structuredContent") or result
    return {"ok": not result.get("isError"), "status": 200, "connector": str(item["id"]), "action": action,
            "data": data, "writes": False}


# ---------------------------------------------------------------------------
# Tools the model calls
# ---------------------------------------------------------------------------

def _is_write(item: Dict[str, Any], action: str) -> bool:
    spec = next((a for a in actions_for(str(item["id"])) if str(a.get("id")) == str(action)), None)
    if spec is None:
        return bool(item.get("writes"))
    return bool(spec.get("write")) or str(spec.get("method", "GET")).upper() != "GET"


def _turn_key(connector_id: str, action: str) -> str:
    try:
        from tool_context import current

        turn = getattr(current(), "turn_id", "") or ""
    except Exception:  # pragma: no cover
        turn = ""
    return f"{turn}:{connector_id}:{action}"


def tool_use_connector(connector: str = "", action: str = "", params: Any = None, confirm: bool = False,
                       path: str = "", method: str = "") -> str:
    """Call one of the owner's connected apps."""
    connector_id = resolve(connector) or str(connector or "").strip()
    item = entry(connector_id)
    if item is None:
        names = ", ".join(str(c["id"]) for c in connected()[:20]) or "none yet"
        return (f"There is no connector called {connector!r}. Connected right now: {names}. "
                "The owner can add one in Connectors with +, or by saying what to add.")
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except ValueError:
            params = {}
    params = params if isinstance(params, dict) else {}
    if not is_connected(connector_id):
        fields = ", ".join(str(f.get("label") or f.get("key")) for f in (item.get("fields") or []) if f.get("required"))
        return (f"{item.get('name')} is not connected yet, so I can't use it. It needs: {fields or 'its account details'}. "
                "Ask the owner whether to add it — they can press + in Connectors, or paste what it needs here.")
    if _is_write(item, action) and settings()["confirm_writes"] and not confirm:
        key = _turn_key(connector_id, action)
        with _lock:
            _confirmed[key] = time.time()
        return (f"'{action}' would change something in the owner's {item.get('name')} account. Ask them in plain words "
                "whether to do it, with exactly what will happen, and only if they say yes call use_connector again "
                "with confirm=true.")
    try:
        result = call(connector_id, action, params=params, path=path, method=method)
    except ConnectorCallError as error:
        return f"Could not use {item.get('name')}: {error}"
    except Exception as error:  # noqa: BLE001
        _LOG.debug("connector call failed", exc_info=True)
        return f"Could not use {item.get('name')}: {type(error).__name__}"
    if not result.get("ok"):
        return str(result.get("error") or f"{item.get('name')} answered {result.get('status')}.")
    data = result.get("data")
    text = json.dumps(data, indent=1)[:MAX_CHARS] if not isinstance(data, str) else data[:MAX_CHARS]
    return f"{item.get('name')} · {action or path}:\n{text}"


def tool_connector_actions(connector: str = "") -> str:
    """What one connector can do."""
    connector_id = resolve(connector) or str(connector or "").strip()
    item = entry(connector_id)
    if item is None:
        return f"There is no connector called {connector!r}."
    listed = actions_for(connector_id)
    if not listed:
        return (f"{item.get('name')} has no declared actions. You can still call it with a path, for example "
                "use_connector(connector=\"" + connector_id + "\", path=\"/some/endpoint\").")
    lines = [f"{item.get('name')} ({connector_id}) — {'connected' if is_connected(connector_id) else 'NOT connected'}:"]
    for spec in listed[:40]:
        args = ", ".join(f"{k}: {v}" for k, v in (spec.get("params") or {}).items())
        lines.append(f"- {spec.get('id')}{' (changes things)' if spec.get('write') else ''}: "
                     f"{spec.get('description', '')}" + (f" — {args}" if args else ""))
    return "\n".join(lines)


def tool_connectors_available(query: str = "") -> str:
    """The owner's connected apps, and what else could be added."""
    live = connected()
    lines = []
    if live:
        lines.append("Connected now:")
        lines += [f"- {c['id']} ({c.get('name')}): {summary(c)}" for c in live[:30]]
    else:
        lines.append("Nothing is connected yet.")
    if query.strip():
        guesses = [e for e in entries() if query.strip().lower() in
                   (str(e.get("name", "")) + " " + " ".join(str(k) for k in e.get("keywords") or [])).lower()]
        if guesses:
            lines.append("\nNot connected, but available to add:")
            lines += [f"- {g.get('name')} ({g['id']}): {str(g.get('description', ''))[:100]}" for g in guesses[:10]]
    lines.append("\nTo add one, the owner presses + in Connectors, or tells you what to add and you check what it needs.")
    return "\n".join(lines)


def register_connector_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        name="use_connector",
        description=("Use one of the owner's connected apps (GitHub, Notion, Gmail, Slack, an MCP server…). Call "
                     "connector_actions first when you are unsure what it can do. Anything that writes needs the "
                     "owner's yes in the chat and confirm=true."),
        parameters=[
            ToolParam("connector", "string", "The connector id, e.g. github", required=True),
            ToolParam("action", "string", "Which action (or MCP tool) to run", required=False),
            ToolParam("params", "object", "The action's arguments", required=False),
            ToolParam("confirm", "boolean", "True only after the owner agreed to a change", required=False),
            ToolParam("path", "string", "An API path, when no declared action fits", required=False),
            ToolParam("method", "string", "GET, POST, PATCH, PUT or DELETE (with path)", required=False),
        ],
        handler=tool_use_connector,
        category="connectors",
        label=lambda a: f"Using {a.get('connector', 'a connector')}" + (f" · {a.get('action')}" if a.get("action") else ""),
    )
    registry.register(
        name="connector_actions",
        description="List what one connected app can do, with the arguments each action takes.",
        parameters=[ToolParam("connector", "string", "The connector id", required=True)],
        handler=tool_connector_actions,
        category="connectors",
        label=lambda a: f"Checking what {a.get('connector', 'it')} can do",
    )
    registry.register(
        name="connectors_available",
        description="Which apps the owner has connected, and what else could be added.",
        parameters=[ToolParam("query", "string", "Look for connectors matching these words", required=False)],
        handler=tool_connectors_available,
        category="connectors",
        label=lambda a: "Checking the connectors",
    )
