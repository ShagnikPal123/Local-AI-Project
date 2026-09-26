"""Adding a connector by telling Nyx what you want (Plan Null N32/N33).

Owner, 2026-09-22: "a chat to tell the ai what to add … it will check and add it for you if you give it what it needs.
Like if it needs an Api and model but only model is given it can make it and say to give a api and the user can then
send it to then add that connector."

So: words in, a **draft** out. The draft says which connector this is, which fields it needs, which of them the words
already contained, and what is still missing — in a sentence the owner can answer. When the missing pieces arrive the
same draft is added for real.

Two rules this module exists to keep:

* **A secret never travels further than it has to.** Keys, tokens and passwords are pulled out of the text *here*, on
  this computer, before anything is sent to a model and before the draft is shown; the model only ever sees
  ``<the API key>``. They are held in memory with the draft and written only to ``secret_store`` when the owner adds
  the connector. Nothing writes them into a chat transcript, a log or this file.
* **A proposed connector is data, never code** (AGENTS.md §4.2). A model may suggest a name, an https address, an auth
  kind and a list of fields; every one of those is validated here and stored as a row.

The catalogue of ready-made connectors lives in ``connectors/catalog.py``; this module fills in and connects one of
those when the words match it, and keeps its own store for the ones the owner invents.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from paths import data_path

_LOG = logging.getLogger("nyx.connector_builder")

KINDS = ("rest", "mcp", "model")
AUTH_TYPES = ("bearer", "header", "query", "basic", "none", "app_password", "oauth")
_DRAFT_TTL = 3600.0
_MAX_DRAFTS = 30

_lock = threading.Lock()
_drafts: Dict[str, Dict[str, Any]] = {}


class BuilderError(ValueError):
    """Something the owner can fix, said in a sentence."""


# ---------------------------------------------------------------------------
# Reading the owner's words without keeping their secrets
# ---------------------------------------------------------------------------

#: Tokens whose shape alone says "this is a credential".
KEY_SHAPES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"), "anthropic"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"), "openai"),
    (re.compile(r"\bgsk_[A-Za-z0-9]{20,}"), "groq"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "github"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "github"),
    (re.compile(r"\bxox[baprse]-[A-Za-z0-9\-]{10,}"), "slack"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"), "google"),
    (re.compile(r"\bhf_[A-Za-z0-9]{20,}"), "huggingface"),
    (re.compile(r"\b(?:ntn_|secret_)[A-Za-z0-9]{20,}"), "notion"),
    (re.compile(r"\bnvapi-[A-Za-z0-9_\-]{20,}"), "nvidia"),
    (re.compile(r"\br8_[A-Za-z0-9]{20,}"), "replicate"),
    (re.compile(r"\bdop_v1_[A-Za-z0-9]{20,}"), "digitalocean"),
    (re.compile(r"\bey[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), "jwt"),
]

#: "api key: abc123", "token is abc123", "password = hunter2" — the shape is ordinary, the words give it away.
KEY_IN_WORDS = re.compile(
    r"(?P<label>api[\s_-]?key|access[\s_-]?token|auth[\s_-]?token|token|secret|password|passcode|app[\s_-]?password|key)"
    r"\s*(?:is|=|:|->)\s*[\"'`]?(?P<value>[A-Za-z0-9_\-./+]{8,})[\"'`]?", re.I)

URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.I)
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
USER_RE = re.compile(r"(?:user(?:name)?|account|login)\s*(?:is|=|:)\s*[\"']?([\w.@-]{2,60})[\"']?", re.I)
MODEL_RE = re.compile(r"(?:model|using|with)\s+[\"'`]?([A-Za-z0-9][\w.:/-]{2,60})[\"'`]?", re.I)


def strip_secrets(text: str) -> Tuple[str, List[Dict[str, str]]]:
    """Take every credential out of ``text``. Returns the safe text and what was found.

    The safe text is what a model may see; the values stay with the caller.
    """
    found: List[Dict[str, str]] = []
    safe = text or ""

    def hold(value: str, kind: str, label: str = "") -> str:
        value = value.strip().strip("\"'`,;")
        if len(value) < 8:
            return value
        for item in found:
            if item["value"] == value:
                return item["placeholder"]
        placeholder = f"<{label or 'the key'} {len(found) + 1}>"
        found.append({"value": value, "kind": kind, "label": label or "API key", "placeholder": placeholder})
        return placeholder

    for pattern, kind in KEY_SHAPES:
        safe = pattern.sub(lambda m: hold(m.group(0), kind), safe)
    def by_words(match: re.Match) -> str:
        label = re.sub(r"[\s_-]+", " ", match.group("label")).lower()
        value = match.group("value")
        if value.lower().startswith(("http", "<")) or "." in value and "/" in value:
            return match.group(0)
        return match.group(0).replace(value, hold(value, "named", "password" if "pass" in label else label))
    safe = KEY_IN_WORDS.sub(by_words, safe)
    return safe, found


def read_words(text: str) -> Dict[str, Any]:
    """What the owner's message offers: a safe copy of it, the secrets, and the plain values."""
    safe, secrets = strip_secrets(text)
    urls = [u.rstrip(".,);") for u in URL_RE.findall(safe)]
    model = ""
    match = MODEL_RE.search(safe)
    if match and not match.group(1).lower().startswith("http"):
        model = match.group(1)
    if not model:
        slashed = re.search(r"\b([A-Za-z0-9][\w.-]*/[\w.:-]{2,60})\b", safe)
        if slashed and not slashed.group(1).lower().startswith("http"):
            model = slashed.group(1)
    user = USER_RE.search(safe)
    emails = EMAIL_RE.findall(safe)
    return {"safe_text": safe, "secrets": secrets, "urls": urls, "model": model,
            "username": user.group(1) if user else (emails[0] if emails else ""), "emails": emails}


# ---------------------------------------------------------------------------
# Which connector the owner means
# ---------------------------------------------------------------------------

def _catalog_entries() -> List[Dict[str, Any]]:
    import connector_use

    return connector_use.entries(include_custom=False)


def match_catalog(text: str) -> Optional[Dict[str, Any]]:
    """The catalogue entry the words are about, if one clearly is."""
    lowered = f" {re.sub(r'[^a-z0-9 ]+', ' ', (text or '').lower())} "
    best, best_score = None, 0
    for item in _catalog_entries():
        name = re.sub(r"[^a-z0-9 ]+", " ", str(item.get("name", "")).lower()).strip()
        if not name:
            continue
        score = 0
        if f" {name} " in lowered:
            score = 10 + len(name)
        elif f" {str(item.get('id', '')).lower()} " in lowered:
            score = 8
        if score > best_score:
            best, best_score = item, score
    return best


def _model_companies() -> Dict[str, Dict[str, str]]:
    try:
        from routes_key_pool import COMPANIES

        return dict(COMPANIES)
    except Exception:  # pragma: no cover - the table lives with the Keys routes
        return {"openai": {"label": "OpenAI", "url": "https://api.openai.com/v1/chat/completions", "example": "gpt-4.1-mini",
                           "signup": "https://platform.openai.com/api-keys"}}


def match_model_company(text: str) -> Optional[Tuple[str, Dict[str, str]]]:
    """"add groq with llama-3.3-70b" → the Groq row from the Keys table."""
    lowered = f" {re.sub(r'[^a-z0-9 ]+', ' ', (text or '').lower())} "
    for key, row in _model_companies().items():
        if key == "other":
            continue
        label = re.sub(r"[^a-z0-9 ]+", " ", str(row.get("label", "")).lower()).split("(")[0].strip()
        if f" {key} " in lowered or (label and f" {label} " in lowered):
            return key, row
    return None


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------

def _field(key: str, label: str, *, secret: bool = False, required: bool = True, value: str = "",
           help_url: str = "", kind: str = "text", placeholder: str = "") -> Dict[str, Any]:
    return {"key": key, "label": label, "secret": bool(secret), "required": bool(required),
            "value": value, "filled": bool(str(value).strip()), "help_url": help_url,
            "kind": kind or ("password" if secret else "text"), "placeholder": placeholder}


def draft(text: str, *, propose: Optional[Any] = None) -> Dict[str, Any]:
    """Words → what Nyx would add, what it already has, and what it still needs."""
    words = (text or "").strip()
    if len(words) < 3:
        raise BuilderError("Say what to add, for example \"add Notion\" or \"add Groq with llama-3.3-70b\".")
    read = read_words(words)
    entry = match_catalog(words)
    if entry is not None:
        spec, source = _from_catalog(entry), "catalog"
    else:
        company = match_model_company(words)
        if company is not None:
            spec, source = _from_model_company(company[0], company[1], read), "model"
        else:
            spec, source = _proposed(read, propose), "proposed"
    fields = _fill(spec, read)
    missing = [f for f in fields if f["required"] and not f["filled"]]
    record = {
        "draft_id": uuid.uuid4().hex[:10],
        "catalog_id": spec.get("catalog_id", ""),
        "id": spec.get("id", ""),
        "name": spec.get("name", ""),
        "kind": spec.get("kind", "rest"),
        "description": spec.get("description", ""),
        "help_url": spec.get("help_url", ""),
        "source": source,
        "fields": fields,
        "missing": [f["label"] for f in missing],
        "ready": not missing,
        "spec": spec,
    }
    record["message"] = _message(record)
    _remember(record)
    return _public(record)


def _from_catalog(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {"catalog_id": str(entry.get("id", "")), "id": str(entry.get("id", "")), "name": str(entry.get("name", "")),
            "kind": str(entry.get("kind") or "rest"), "description": str(entry.get("description", ""))[:300],
            "help_url": str(entry.get("help_url") or entry.get("docs_url") or ""),
            "fields": list(entry.get("fields") or []), "base_url": entry.get("base_url"),
            "mcp_url": entry.get("mcp_url"), "auth": entry.get("auth") or {"type": "bearer"},
            "keywords": list(entry.get("keywords") or []), "can": list(entry.get("can") or [])}


def _from_model_company(company_id: str, row: Dict[str, str], read: Dict[str, Any]) -> Dict[str, Any]:
    """An AI model provider: exactly the owner's example — a model without its key."""
    return {
        "catalog_id": "", "id": f"model-{company_id}", "name": str(row.get("label", company_id)), "kind": "model",
        "company": company_id, "chat_url": str(row.get("url", "")), "help_url": str(row.get("signup", "")),
        "description": f"An AI model from {row.get('label', company_id)} that Nyx can answer with.",
        "fields": [
            {"key": "model", "label": "Model", "secret": False, "required": True,
             "placeholder": str(row.get("example", "")), "kind": "text"},
            {"key": "api_key", "label": "API key", "secret": True, "required": not _is_local(str(row.get("url", ""))),
             "help_url": str(row.get("signup", "")), "kind": "password"},
            {"key": "chat_url", "label": "API address", "secret": False, "required": not str(row.get("url", "")),
             "placeholder": str(row.get("url", "")), "kind": "url"},
        ],
    }


def _is_local(url: str) -> bool:
    return bool(re.search(r"//(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1])", url or ""))


def _proposed(read: Dict[str, Any], propose: Optional[Any]) -> Dict[str, Any]:
    """Nothing in the catalogue matched: ask a model for a spec, then validate every part of it."""
    raw: Dict[str, Any] = {}
    try:
        reply = (propose or _ask_model)(read["safe_text"])
        raw = _json_object(reply)
    except Exception:  # noqa: BLE001 - no model, no problem: fall back to what the words gave
        _LOG.debug("connector proposal failed", exc_info=True)
    name = str(raw.get("name") or "").strip()[:40]
    kind = str(raw.get("kind") or "rest").lower()
    if kind not in KINDS:
        kind = "rest"
    base_url = _https(str(raw.get("base_url") or "")) or _https(next((u for u in read["urls"]), ""))
    mcp_url = _https(str(raw.get("mcp_url") or ""))
    if mcp_url and not base_url:
        kind = "mcp"
    if not name:
        host = re.sub(r"^www\.", "", (re.search(r"//([^/]+)", base_url or mcp_url or "") or ["", ""])[1] if (base_url or mcp_url) else "")
        name = (host.split(".")[0].title() if host else "New connector")
    auth = raw.get("auth") if isinstance(raw.get("auth"), dict) else {}
    auth_type = str(auth.get("type") or "bearer").lower()
    if auth_type not in AUTH_TYPES:
        auth_type = "bearer"
    fields = []
    for item in (raw.get("fields") if isinstance(raw.get("fields"), list) else [])[:8]:
        if not isinstance(item, dict) or not item.get("key"):
            continue
        key = re.sub(r"[^a-z0-9_]", "", str(item["key"]).lower())[:32]
        if not key:
            continue
        fields.append({"key": key, "label": str(item.get("label") or key.replace("_", " ").title())[:60],
                       "secret": bool(item.get("secret", key in ("api_key", "token", "password", "secret"))),
                       "required": bool(item.get("required", True)),
                       "help_url": _https(str(item.get("help_url") or "")), "kind": str(item.get("kind") or "text")})
    if not fields:
        fields = [{"key": "token", "label": "API key or token", "secret": True, "required": True, "kind": "password"}]
    if not base_url and not mcp_url:
        fields.insert(0, {"key": "base_url", "label": "API address (https)", "secret": False, "required": True,
                          "kind": "url", "placeholder": "https://api.example.com/v1"})
    return {"catalog_id": "", "id": _slug(name), "name": name, "kind": kind, "base_url": base_url, "mcp_url": mcp_url,
            "description": str(raw.get("description") or "")[:300],
            "help_url": _https(str(raw.get("help_url") or raw.get("docs_url") or "")),
            "auth": {"type": auth_type, **({"header": str(auth["header"])[:60]} if auth.get("header") else {}),
                     **({"param": str(auth["param"])[:40]} if auth.get("param") else {})},
            "fields": fields, "keywords": [str(k)[:30] for k in (raw.get("keywords") or [])][:12],
            "can": [str(c)[:60] for c in (raw.get("can") or [])][:6]}


def _ask_model(safe_text: str) -> str:
    from model_roles import MODEL_ROLES

    system = ("detailed thinking off\nYou describe how to connect to an app's public API. Reply with JSON only. Never "
              "invent a credential; only say which fields the owner must paste.")
    prompt = ("The owner wants to connect this to their assistant:\n\"\"\"\n" + safe_text[:1500] + "\n\"\"\"\n\n"
              "Reply with JSON: {\"name\": \"\", \"kind\": \"rest|mcp|model\", \"base_url\": \"https://…\", "
              "\"mcp_url\": \"\", \"description\": \"one line\", \"help_url\": \"page where the owner gets a key\", "
              "\"auth\": {\"type\": \"bearer|header|query|basic|none\", \"header\": \"\", \"param\": \"\"}, "
              "\"fields\": [{\"key\": \"api_key\", \"label\": \"API key\", \"secret\": true, \"required\": true, "
              "\"help_url\": \"\"}], \"keywords\": [], \"can\": [\"what it can do\"]}. Use the real public API address "
              "if you know it, https only. If you do not know it, leave base_url empty.")
    return MODEL_ROLES.run("fast_chat", prompt, system=system, max_tokens=700).text


def _json_object(text: str) -> Dict[str, Any]:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        value = json.loads(text[start:end + 1])
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _https(url: str) -> str:
    url = (url or "").strip().strip("\"'")
    return url if url.lower().startswith("https://") and " " not in url else ""


def _slug(text: str) -> str:
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-"))[:40] or "connector"


def _fill(spec: Dict[str, Any], read: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Put what the words gave into the fields the connector needs."""
    secrets = list(read["secrets"])
    fields: List[Dict[str, Any]] = []
    for raw in spec.get("fields") or []:
        item = _field(str(raw.get("key")), str(raw.get("label") or raw.get("key")),
                      secret=bool(raw.get("secret")), required=bool(raw.get("required", True)),
                      help_url=str(raw.get("help_url") or ""), kind=str(raw.get("kind") or ""),
                      placeholder=str(raw.get("placeholder") or ""))
        key = item["key"]
        if item["secret"] and secrets:
            item.update(value=secrets.pop(0)["value"], filled=True)
        elif key in ("model", "model_id") and read["model"]:
            item.update(value=read["model"], filled=True)
        elif key in ("base_url", "chat_url", "url", "mcp_url", "server_url") and read["urls"]:
            item.update(value=read["urls"][0], filled=True)
        elif key in ("username", "user", "login", "email", "address") and read["username"]:
            item.update(value=read["username"], filled=True)
        fields.append(item)
    return fields


def _message(record: Dict[str, Any]) -> str:
    name = record["name"]
    have = [f["label"].lower() for f in record["fields"] if f["filled"] and not f["secret"]]
    have += ["the key" for f in record["fields"] if f["filled"] and f["secret"]]
    missing = record["missing"]
    where = ""
    help_url = record.get("help_url") or next((f["help_url"] for f in record["fields"] if f.get("help_url")), "")
    if missing and help_url:
        where = f" You can get it at {help_url}."
    if record["ready"]:
        return f"I can add {name} now — everything it needs is here. Press Add and I'll connect it."
    got = f" I already have {', '.join(have)}." if have else ""
    need = missing[0] if len(missing) == 1 else ", ".join(missing[:-1]) + " and " + missing[-1]
    return (f"I can add {name}.{got} I still need the {need.lower()} — paste it in the box below and I'll add it."
            f"{where}")


def _remember(record: Dict[str, Any]) -> None:
    now = time.time()
    with _lock:
        for key in [k for k, v in _drafts.items() if now - v["at"] > _DRAFT_TTL]:
            _drafts.pop(key, None)
        while len(_drafts) >= _MAX_DRAFTS:
            _drafts.pop(next(iter(_drafts)))
        _drafts[record["draft_id"]] = {"at": now, "record": record}


def _public(record: Dict[str, Any]) -> Dict[str, Any]:
    """The draft as the UI sees it: a secret the owner pasted is shown masked, never in full."""
    fields = []
    for item in record["fields"]:
        shown = dict(item)
        if item["secret"] and item["filled"]:
            shown["value"] = ""
            shown["masked"] = "•" * 8 + str(item["value"])[-4:]
        fields.append(shown)
    out = {k: v for k, v in record.items() if k != "spec"}
    out["fields"] = fields
    return out


def get_draft(draft_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        held = _drafts.get(str(draft_id or ""))
    return held["record"] if held else None


# ---------------------------------------------------------------------------
# Adding it for real
# ---------------------------------------------------------------------------

def _custom_path():
    return data_path("connectors/custom.json")


def _store_path():
    return data_path("connectors/custom_connections.json")


def _read(path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")


def custom_connectors() -> List[Dict[str, Any]]:
    """The owner's own connectors, in the catalogue's entry shape (no secrets)."""
    saved = _read(_custom_path()).get("connectors", [])
    out = []
    for spec in saved if isinstance(saved, list) else []:
        if isinstance(spec, dict) and spec.get("id"):
            out.append({**{k: v for k, v in spec.items() if k not in ("values",)}, "origin": "custom",
                        "category": spec.get("category", "custom"), "popular": 0})
    return out


def is_connected(connector_id: str) -> bool:
    return bool(_read(_store_path()).get(str(connector_id or "").lower()))


def connection_values(connector_id: str) -> Dict[str, Any]:
    """Saved values for one of the owner's own connectors, secrets included. Server-side only."""
    key = str(connector_id or "").lower()
    saved = _read(_store_path()).get(key)
    if not isinstance(saved, dict):
        return {}
    values = dict(saved.get("fields") or {})
    try:
        from secret_store import get_keys

        for name in saved.get("secret_fields") or []:
            keys = get_keys(f"connector:{key}:{name}")
            if keys:
                values[name] = keys[0]
    except Exception:  # pragma: no cover
        pass
    return values


def disconnect(connector_id: str) -> bool:
    key = str(connector_id or "").lower()
    store = _read(_store_path())
    saved = store.pop(key, None)
    if saved is None:
        return False
    _write(_store_path(), store)
    try:
        from secret_store import set_keys

        for name in saved.get("secret_fields") or []:
            set_keys(f"connector:{key}:{name}", [])
    except Exception:  # pragma: no cover
        pass
    custom = _read(_custom_path())
    listed = [s for s in custom.get("connectors", []) if str(s.get("id", "")).lower() != key]
    if len(listed) != len(custom.get("connectors", [])):
        _write(_custom_path(), {"connectors": listed})
    return True


def connect(connector_id: str, fields: Dict[str, Any], spec: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Save one of the owner's own connectors: plain values in the store, secrets in ``secret_store``."""
    key = str(connector_id or "").lower()
    if not key:
        raise BuilderError("The connector needs a name.")
    known = {str(f.get("key")): f for f in (spec or {}).get("fields", [])} if spec else {}
    plain: Dict[str, Any] = {}
    secret_names: List[str] = []
    for name, value in (fields or {}).items():
        text = str(value or "").strip()
        if not text:
            continue
        if known.get(name, {}).get("secret") or name in ("api_key", "token", "password", "secret", "access_token"):
            try:
                from secret_store import set_keys

                set_keys(f"connector:{key}:{name}", [text])
                secret_names.append(name)
            except Exception as error:  # pragma: no cover
                raise BuilderError(f"Could not store the {name}: {type(error).__name__}") from None
        else:
            plain[name] = text[:500]
    store = _read(_store_path())
    store[key] = {"fields": plain, "secret_fields": secret_names, "connected_at": time.time()}
    _write(_store_path(), store)
    if spec:
        custom = _read(_custom_path())
        listed = [s for s in custom.get("connectors", []) if str(s.get("id", "")).lower() != key]
        listed.append({k: v for k, v in spec.items() if k in (
            "id", "name", "kind", "description", "base_url", "mcp_url", "auth", "fields", "keywords", "can",
            "help_url", "category", "logo", "color", "writes")})
        _write(_custom_path(), {"connectors": listed})
    return {"id": key, "connected": True, "fields": {k: "•" * 8 for k in secret_names} | {k: v for k, v in plain.items()}}


def add(draft_id: str = "", *, fields: Optional[Dict[str, Any]] = None, catalog_id: str = "",
        spec: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Add the connector a draft described, once the owner has filled in what was missing."""
    record = get_draft(draft_id) if draft_id else None
    if record is None and not (catalog_id or spec):
        raise BuilderError("That draft has expired — say again what to add.")
    working = dict(record["spec"]) if record else (dict(spec) if spec else {})
    if catalog_id:
        import connector_use

        entry = connector_use.entry(catalog_id)
        if entry is None:
            raise BuilderError(f"There is no connector called {catalog_id!r}.")
        working = _from_catalog(entry)
    values: Dict[str, Any] = {}
    if record:
        values = {f["key"]: f["value"] for f in record["fields"] if f["filled"]}
    values.update({k: str(v) for k, v in (fields or {}).items() if str(v or "").strip()})
    required = [f for f in working.get("fields", []) if f.get("required")]
    missing = [str(f.get("label") or f.get("key")) for f in required if not str(values.get(str(f.get("key")), "")).strip()]
    if missing:
        raise BuilderError("Still missing: " + ", ".join(missing) + ".")

    if working.get("kind") == "model":
        return _add_model(working, values)
    target = working.get("catalog_id") or ""
    if target:
        try:
            from connectors import catalog  # type: ignore

            result = catalog.connect(target, values)
            return {"ok": True, "id": target, "name": working.get("name", target),
                    "connected": bool(result.get("connected", True)), "kind": working.get("kind", "rest"),
                    "message": f"{working.get('name', target)} is connected."}
        except ImportError:
            pass  # the catalogue is not there yet: keep it in this module's own store
        except ValueError as error:
            raise BuilderError(str(error)) from None
    connector_id = target or working.get("id") or _slug(str(working.get("name", "")))
    working["id"] = connector_id
    connect(connector_id, values, working)
    return {"ok": True, "id": connector_id, "name": working.get("name", connector_id), "connected": True,
            "kind": working.get("kind", "rest"), "message": f"{working.get('name', connector_id)} is connected."}


def _add_model(spec: Dict[str, Any], values: Dict[str, Any]) -> Dict[str, Any]:
    """A model provider joins the model menu and the failover chain, exactly like Keys → Add a model."""
    from provider_specs import BUILTIN_NAMES, PROVIDER_SPECS, ProviderSpecError, build_spec
    from secret_store import add_key

    company = str(spec.get("company") or "other")
    row = _model_companies().get(company, {})
    try:
        from routes_key_pool import normalize_chat_url

        url = normalize_chat_url(str(values.get("chat_url") or spec.get("chat_url") or row.get("url", "")))
    except Exception:  # pragma: no cover
        url = str(values.get("chat_url") or spec.get("chat_url") or row.get("url", ""))
    if not url:
        raise BuilderError("That company needs its API address (https://…/v1).")
    name = _slug(str(spec.get("name") or company))
    if name in BUILTIN_NAMES:
        name = f"{name}-custom"
    key = str(values.get("api_key") or "").strip()
    local = _is_local(url)
    key_name = f"CUSTOM_{name.upper().replace('-', '_')}_API_KEY" if (key or not local) else ""
    try:
        provider = build_spec(name=name, chat_url=url, model=str(values.get("model", "")).strip(),
                              api_key_name=key_name, label=f"{spec.get('name', name)}",
                              is_free=True, added_by="owner", signup_url=str(row.get("signup", "")),
                              notes="added from the connectors chat", allow_local=local)
        PROVIDER_SPECS.add(provider)
    except ProviderSpecError as error:
        raise BuilderError(str(error)) from None
    if key:
        add_key(key_name, key)
    try:
        from server import _refresh_router_cache  # type: ignore

        _refresh_router_cache()
    except Exception:  # pragma: no cover - the next engine start picks it up anyway
        pass
    return {"ok": True, "id": name, "name": str(spec.get("name", name)), "connected": True, "kind": "model",
            "message": f"{spec.get('name', name)} is ready — {values.get('model', 'its model')} can answer now."}


def test(connector_id: str) -> Dict[str, Any]:
    """A read-only call, to prove a connector works."""
    import connector_use

    entry = connector_use.entry(connector_id)
    if entry is None:
        raise BuilderError(f"There is no connector called {connector_id!r}.")
    actions = connector_use.actions_for(str(entry["id"]))
    read_only = next((a for a in actions if not a.get("write") and str(a.get("method", "GET")).upper() == "GET"), None)
    if read_only is None and str(entry.get("kind")) != "mcp":
        return {"ok": bool(connector_use.is_connected(str(entry["id"]))), "message": "Saved. Nothing to test with yet."}
    try:
        if str(entry.get("kind")) == "mcp":
            tools = connector_use.actions_for(str(entry["id"]))
            return {"ok": bool(tools), "message": f"{len(tools)} tools available." if tools else "The server did not answer."}
        result = connector_use.call(str(entry["id"]), str(read_only["id"]))
    except connector_use.ConnectorCallError as error:
        return {"ok": False, "message": str(error)}
    return {"ok": bool(result.get("ok")), "message": ("It answered." if result.get("ok")
                                                      else str(result.get("error", "It did not answer."))[:200])}
