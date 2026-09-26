"""Tabs Big Kahuna thinks the owner needs — proposed from real use, created on approval (Request S10, S18).

"Make it hyper intelligent, able to make tabs it thinks and knows the user needs … Predict and create
tabs automatically if user switches on in settings." Signals, all local and offline: what the owner has
been asking about lately (recent requests), which tabs they keep opening at which hours (the tab
predictor), and the tabs that already exist (never propose a duplicate). A proposal names a template
tab when one fits — those are tested, validated specs — and says why in plain words.

With ``auto_tabs`` off (the default) proposals wait in the Big Kahuna tab for a click. With it on, the
best new proposal is created by itself, at most one per day, and the owner is told.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from typing import Any, Dict, List, Optional

from identity0 import state

FILE = "tab_proposals.json"
_WORD = re.compile(r"[a-z][a-z0-9+#-]{2,30}")


class TabPlanError(ValueError):
    pass


def auto_enabled() -> bool:
    return bool(state.get_settings().get("auto_tabs", False))


def _load() -> Dict[str, Any]:
    data = state.read_json(FILE, {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("proposals", [])
    data.setdefault("last_auto", 0.0)
    return data


def _recent_requests(limit: int = 150) -> List[str]:
    try:
        from paths import data_path

        lines = data_path("learning/turns.jsonl").read_text(encoding="utf-8").splitlines()[-limit:]
        messages = [str(json.loads(line).get("message", "")) for line in lines if line.strip()]
    except (OSError, ValueError):
        messages = []
    if len(messages) < 10:
        try:
            from identity0.corpus.sources import owner_questions

            messages += owner_questions(limit)
        except Exception:  # noqa: BLE001
            pass
    return messages


def _existing_labels() -> List[str]:
    try:
        from dynamic_tabs import TAB_STORE

        return [str(t.get("label", "")).lower() for t in TAB_STORE.list_tabs()]
    except Exception:  # noqa: BLE001
        return []


def plan(messages: Optional[List[str]] = None, existing: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Ranked proposals: template tabs whose topic the owner keeps asking about and does not have yet."""
    from identity0.templates.catalog import TEMPLATES

    messages = _recent_requests() if messages is None else messages
    existing = _existing_labels() if existing is None else existing
    words: Counter = Counter()
    for message in messages:
        words.update(set(_WORD.findall(message.lower())))
    proposals = []
    for template in TEMPLATES:
        if template["kind"] != "tab":
            continue
        label = template["spec"]["label"].lower()
        if any(label in e or e in label for e in existing if e):
            continue
        hits = {tag: words[tag] + words.get(tag + "s", 0) for tag in template["tags"]}
        score = sum(hits.values())
        if score < 3:
            continue
        top = max(hits, key=hits.get)
        proposals.append({"id": template["id"], "template_id": template["id"], "title": template["spec"]["label"],
                          "why": f"you asked about {top} {hits[top]} times lately", "score": score})
    return sorted(proposals, key=lambda p: -p["score"])[:6]


def refresh() -> List[Dict[str, Any]]:
    data = _load()
    decided = {p["id"]: p for p in data["proposals"] if p.get("state") in ("approved", "dismissed")}
    fresh = [{**p, "state": "new", "at": time.time()} for p in plan() if p["id"] not in decided]
    data["proposals"] = list(decided.values()) + fresh
    if auto_enabled() and fresh and time.time() - float(data.get("last_auto", 0)) > 86400:
        best = fresh[0]
        try:
            _create(best)
            best["state"] = "approved"
            best["auto"] = True
            data["last_auto"] = time.time()
            _tell(f"I made a {best['title']} tab because {best['why']}.")
        except Exception as error:  # noqa: BLE001 - a proposal that fails stays a proposal
            best["error"] = str(error)[:160]
    state.write_json(FILE, data)
    return proposals()


def proposals() -> List[Dict[str, Any]]:
    return [p for p in _load()["proposals"] if p.get("state") == "new"]


def _create(proposal: Dict[str, Any]) -> Dict[str, Any]:
    from identity0 import templates

    return templates.instantiate(proposal["template_id"])


def _tell(text: str) -> None:
    try:
        from identity0 import companion

        companion.say("kahuna", text, kind="action")
    except Exception:  # noqa: BLE001
        pass


def decide(proposal_id: str, approve: bool) -> Dict[str, Any]:
    data = _load()
    proposal = next((p for p in data["proposals"] if p["id"] == proposal_id and p.get("state") == "new"), None)
    if proposal is None:
        raise TabPlanError("That suggestion is gone.")
    result: Dict[str, Any] = {}
    if approve:
        result = _create(proposal)
    proposal["state"] = "approved" if approve else "dismissed"
    state.write_json(FILE, data)
    return {"proposal": proposal, "result": result, "proposals": proposals()}


def best_topic() -> tuple:
    """For the tab predictor's idle maker: (title, why) of the best proposal, or ("", "")."""
    found = plan()
    return (found[0]["title"], found[0]["why"]) if found else ("", "")
