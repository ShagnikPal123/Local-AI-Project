"""Collab: beta testers send their changes to GitHub for review, and everyone sees them (Request K).

The owner (2026-09-16): "a second website for beta testers where they can apply changes to github, have a special
page for collaboration where they send and show all changes and it auto uploads those changes to that tab."

Two halves:

* **The website** (``site/collab/`` + the Vercel functions in ``site/api/collab``) holds the owner's GitHub token,
  verifies a tester's Nyx access key, turns a change into a ``beta/…`` branch and a pull request (feedback into an
  issue), and lists everything on the collaboration page, which refreshes itself. Nothing merges on its own.
* **This module** is the tester's Nyx: it gathers what they changed on their own install — code changes Nyx
  applied (Improve, the Code tab inside this project), tabs, skills and agents they made — scans it for secrets
  with the same patterns ``build_release.py`` uses, and sends the chosen pieces with their access key. The same
  feed shows in Nyx's Collab tab.

Nothing leaves the PC until the tester presses Send, and personal data (chats, memory, keys, uploads) is never a
candidate. The site checks paths and secrets again on its side.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from paths import PROJECT_DIR, data_path

DEFAULT_SITE = "https://nyx-ichos.vercel.app"
KINDS = ("code", "tab", "skill", "agent", "design", "feedback")
_MAX_FILE_BYTES = 300_000
_LOCK = threading.Lock()
_FEED_CACHE: Dict[str, Any] = {"at": 0.0, "data": None}


class CollabError(RuntimeError):
    """Why something could not be sent, in words for the tester."""


# ---------------------------------------------------------------------------
# Settings and identity
# ---------------------------------------------------------------------------


def _config_path() -> Path:
    return data_path("collab.json")


def config() -> Dict[str, Any]:
    try:
        data = json.loads(_config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    site = str(data.get("site_url") or DEFAULT_SITE).rstrip("/")
    return {"site_url": site, "sent": list(data.get("sent", []))[-50:]}


def save_config(**changes: Any) -> Dict[str, Any]:
    with _LOCK:
        current = config()
        if "site_url" in changes:
            url = str(changes["site_url"] or "").strip().rstrip("/")
            if url and not re.match(r"^https://[a-z0-9.-]+(:\d+)?(/[\w./-]*)?$", url, re.I) and not url.startswith("http://localhost"):
                raise CollabError("The site address must start with https://")
            current["site_url"] = url or DEFAULT_SITE
        if "sent" in changes:
            current["sent"] = list(changes["sent"])[-50:]
        _config_path().write_text(json.dumps(current, indent=1), encoding="utf-8")
    return current


def identity() -> Dict[str, Any]:
    """The newest valid access key on this install (name and role only — the key itself stays here)."""
    try:
        import access_keys

        records = access_keys._read_access().get("keys", [])
    except Exception:  # noqa: BLE001
        records = []
    best: Optional[Dict[str, Any]] = None
    for record in sorted(records, key=lambda r: -float(r.get("redeemed_at") or 0)):
        try:
            access_keys.verify(record.get("key", ""))
        except Exception:  # noqa: BLE001 - expired, revoked or from another signer
            continue
        best = record
        break
    if best is None:
        return {"has_key": False}
    return {"has_key": True, "name": best.get("name", ""), "role": best.get("role", ""), "exp": best.get("exp", 0),
            "id": best.get("id", "")}


def _key() -> str:
    import access_keys

    for record in sorted(access_keys._read_access().get("keys", []), key=lambda r: -float(r.get("redeemed_at") or 0)):
        try:
            access_keys.verify(record.get("key", ""))
            return str(record["key"])
        except Exception:  # noqa: BLE001
            continue
    raise CollabError("Redeem your access key first (Settings → Access), then send changes.")


def vercel_env() -> str:
    """The public signing keys as the site's NYX_ACCESS_PUBLIC_KEYS value — public keys only, never the seed."""
    try:
        data = json.loads((PROJECT_DIR / "access_public_keys.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    keys = {str(k.get("kid")): str(k.get("public_key")) for k in data.get("keys", []) if k.get("kid") and k.get("public_key")}
    return json.dumps(keys, separators=(",", ":"))


# ---------------------------------------------------------------------------
# What a tester can send
# ---------------------------------------------------------------------------


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:48] or "item"


def _relative(path: str) -> Optional[str]:
    try:
        resolved = Path(path).resolve()
        return resolved.relative_to(PROJECT_DIR.resolve()).as_posix()
    except (ValueError, OSError):
        return None


def candidates() -> List[Dict[str, Any]]:
    """Local changes worth sharing, newest first. Contents are read only when sending."""
    items: List[Dict[str, Any]] = []
    try:
        import self_patch

        for change_id, record in self_patch.applied_changes().items():
            if record.get("rolled_back_at"):
                continue
            items.append({"id": f"improve:{change_id}", "kind": "code", "title": record.get("summary") or f"Improvement {change_id}",
                          "detail": f"Applied by Improve to {record.get('file')}", "files": [record.get("file")],
                          "at": float(record.get("applied_at") or 0)})
    except Exception:  # noqa: BLE001
        pass
    try:
        import code_workspace

        for proposal in code_workspace.proposals():
            if proposal.get("status") not in ("applied", "applied_in_editor"):
                continue
            paths = [_relative(proposal.get("path", ""))] if proposal.get("kind") != "create" else [
                _relative(str(Path(proposal.get("path", "")) / f.get("relative", ""))) for f in proposal.get("files") or []]
            paths = [p for p in paths if p]
            if not paths:
                continue  # an edit in the tester's own project, not in Nyx
            items.append({"id": f"code:{proposal['id']}", "kind": "code", "title": proposal.get("instruction", "")[:100] or "Code change",
                          "detail": f"Code tab edit to {', '.join(paths[:3])}", "files": paths, "at": float(proposal.get("created_at") or 0)})
    except Exception:  # noqa: BLE001
        pass
    try:
        from dynamic_tabs import TAB_STORE

        for tab in TAB_STORE.list_tabs():
            items.append({"id": f"tab:{tab['id']}", "kind": "tab", "title": f"Tab: {tab['label']}",
                          "detail": tab.get("description", "")[:140] or f"{len(tab.get('blocks', []))} blocks",
                          "files": [f"community/tabs/{_slug(tab['label'])}.json"], "at": float(tab.get("updated_at") or 0)})
    except Exception:  # noqa: BLE001
        pass
    try:
        from skills import SKILL_STORE

        for skill in SKILL_STORE.list_skills():
            if skill.get("source") in ("builtin", "library"):
                continue
            items.append({"id": f"skill:{skill['id']}", "kind": "skill", "title": f"Skill: {skill.get('name', '')}",
                          "detail": str(skill.get("description", ""))[:140], "files": [f"community/skills/{_slug(skill.get('name', ''))}.json"],
                          "at": float(skill.get("created_at") or 0)})
    except Exception:  # noqa: BLE001
        pass
    try:
        from agent_runtime import load_roster

        for agent in load_roster():
            if agent.get("origin", "roster") == "roster" or agent.get("role") == "master":
                continue
            items.append({"id": f"agent:{_slug(agent['name'])}", "kind": "agent", "title": f"Agent: {agent['name']}",
                          "detail": str(agent.get("goal", ""))[:140], "files": [f"community/agents/{_slug(agent['name'])}.json"],
                          "at": float(agent.get("created_at") or 0)})
    except Exception:  # noqa: BLE001
        pass
    items.sort(key=lambda i: -i["at"])
    return items


def _files_for(candidate_id: str) -> List[Dict[str, str]]:
    kind, _, ident = candidate_id.partition(":")
    if kind == "improve":
        import self_patch

        record = self_patch.applied_changes().get(ident)
        if not record:
            raise CollabError("That improvement is no longer applied.")
        return [_project_file(record["file"])]
    if kind == "code":
        import code_workspace

        proposal = code_workspace.get_proposal(ident, include_text=False)
        if proposal.get("kind") == "create":
            paths = [_relative(str(Path(proposal["path"]) / f.get("relative", ""))) for f in proposal.get("files") or []]
        else:
            paths = [_relative(proposal["path"])]
        return [_project_file(p) for p in paths if p]
    if kind == "tab":
        from dynamic_tabs import TAB_STORE

        spec = TAB_STORE.get(ident)
        if spec is None:
            raise CollabError("That tab no longer exists.")
        data = spec.as_dict()
        data.pop("edits", None)
        if str((data.get("background") or {}).get("image", "")).startswith("/api/uploads/"):
            data["background"] = {k: v for k, v in data["background"].items() if k != "image"}  # uploads stay on this PC
        return [{"path": f"community/tabs/{_slug(data['label'])}.json", "content": json.dumps(data, indent=2)}]
    if kind == "skill":
        from skills import SKILL_STORE

        skill = SKILL_STORE.get(ident)
        if skill is None:
            raise CollabError("That skill no longer exists.")
        data = {k: v for k, v in skill.as_dict().items() if k in ("name", "description", "instructions", "triggers", "tools")}
        return [{"path": f"community/skills/{_slug(data.get('name', ident))}.json", "content": json.dumps(data, indent=2)}]
    if kind == "agent":
        from agent_runtime import load_roster

        agent = next((a for a in load_roster() if _slug(a["name"]) == ident), None)
        if agent is None:
            raise CollabError("That agent no longer exists.")
        data = {k: agent.get(k) for k in ("name", "emoji", "color", "goal", "purpose", "instructions", "expertise", "tools",
                                         "consult", "consult_models") if agent.get(k) not in (None, "", [])}
        return [{"path": f"community/agents/{ident}.json", "content": json.dumps(data, indent=2)}]
    raise CollabError(f"Unknown item {candidate_id!r}.")


def _project_file(relative: str) -> Dict[str, str]:
    path = (PROJECT_DIR / relative).resolve()
    if not path.is_file() or not path.is_relative_to(PROJECT_DIR.resolve()):
        raise CollabError(f"{relative} is not a file in Nyx.")
    if path.stat().st_size > _MAX_FILE_BYTES:
        raise CollabError(f"{relative} is too large to send ({path.stat().st_size // 1000} KB).")
    return {"path": Path(relative).as_posix(), "content": path.read_text(encoding="utf-8", errors="replace")}


def scan_texts(files: List[Dict[str, str]]) -> List[str]:
    """Secrets inside file contents, with the patterns build_release.py refuses to ship."""
    from build_release import _RAW_TOKEN_RES, _SECRET_RE, _placeholder

    findings: List[str] = []
    for file in files:
        text = file.get("content", "")
        for match in _SECRET_RE.finditer(text):
            value = match.group(1)
            if value.isupper() or _placeholder(value) or value.startswith("test") or ("_" in value and value.islower()):
                continue
            findings.append(f"{file['path']}: …{value[-4:]}")
        for pattern in _RAW_TOKEN_RES:
            for match in pattern.finditer(text):
                if not _placeholder(match.group(0)):
                    findings.append(f"{file['path']}: a token …{match.group(0)[-4:]}")
        if "NYX1-" in text:
            findings.append(f"{file['path']}: an access key")
    return findings


# ---------------------------------------------------------------------------
# Talking to the site
# ---------------------------------------------------------------------------


def _post(path: str, body: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
    import requests

    url = config()["site_url"] + path
    try:
        response = requests.post(url, json=body, timeout=timeout)
    except requests.RequestException as error:
        raise CollabError(f"Could not reach the Collab site ({type(error).__name__}).") from error
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code != 200 or not data.get("ok", True):
        raise CollabError(str(data.get("error") or f"The Collab site answered {response.status_code}."))
    return data


def preview(ids: List[str]) -> Dict[str, Any]:
    files: List[Dict[str, str]] = []
    for candidate_id in ids[:30]:
        for file in _files_for(candidate_id):
            if not any(f["path"] == file["path"] for f in files):
                files.append(file)
    return {"files": [{"path": f["path"], "bytes": len(f["content"].encode("utf-8")),
                       "sha": hashlib.sha256(f["content"].encode("utf-8")).hexdigest()[:10]} for f in files],
            "secrets": scan_texts(files), "_files": files}


def send(ids: List[str], title: str, description: str = "", kind: str = "") -> Dict[str, Any]:
    if not ids:
        raise CollabError("Pick at least one change to send, or send feedback.")
    packed = preview(ids)
    if packed["secrets"]:
        raise CollabError("Not sent — a secret is inside: " + "; ".join(packed["secrets"][:3]) + ". Remove it first.")
    kinds = {candidate_id.partition(":")[0] for candidate_id in ids}
    chosen = kind if kind in KINDS else ("code" if kinds & {"improve", "code"} else next(iter(kinds)) if len(kinds) == 1 else "code")
    result = _post("/api/collab/submit", {"key": _key(), "title": title.strip()[:120], "description": description.strip()[:6000],
                                          "kind": chosen, "files": packed["_files"]})
    _remember(result, title)
    return result


def send_feedback(title: str, description: str) -> Dict[str, Any]:
    result = _post("/api/collab/submit", {"key": _key(), "title": title.strip()[:120], "description": description.strip()[:6000],
                                          "kind": "feedback", "files": []})
    _remember(result, title)
    return result


def _remember(result: Dict[str, Any], title: str) -> None:
    sent = config()["sent"] + [{"title": title[:120], "number": result.get("number"), "url": result.get("url"),
                                "kind": result.get("kind"), "at": time.time()}]
    save_config(sent=sent)
    _FEED_CACHE["at"] = 0.0


def feed(force: bool = False) -> Dict[str, Any]:
    import requests

    if not force and _FEED_CACHE["data"] is not None and time.time() - _FEED_CACHE["at"] < 15:
        return _FEED_CACHE["data"]
    url = config()["site_url"] + "/api/collab/feed"
    try:
        response = requests.get(url, timeout=20)
        data = response.json()
    except (requests.RequestException, ValueError) as error:
        raise CollabError(f"Could not reach the Collab site ({type(error).__name__}).") from error
    if response.status_code != 200:
        raise CollabError(str(data.get("error") or f"The Collab site answered {response.status_code}."))
    _FEED_CACHE.update(at=time.time(), data=data)
    return data


if __name__ == "__main__":  # pragma: no cover - owner helper
    import sys

    if "--vercel-env" in sys.argv:
        print("NYX_ACCESS_PUBLIC_KEYS=" + vercel_env())
