"""Diagrams and pictures Nyx can put on screen, from chat or from voice (Request R14).

The owner (2026-09-17): "in both the text and the voice modes I can ask it to say make a diagram and a new tab opens as
an overlay and it can draw or pull from an image which [it] choos[es]. It can search and show an image … A command
example is to show me a diagram of how you, the ai works and it shows me a diagram of its base agents, the other agents
it uses and uses design tricks and skills and tech to make it. Make sure this uses multiple agents at times for best
experience yet least power use so it stays efficient and doesn't force a crash."

A diagram is a **spec, never code** (AGENTS.md invariant 2): nodes, edges and groups that the overlay draws as SVG, so
nothing a model writes is executed. Three ways one is made:

* **About Nyx itself** — ``self_portrait()`` reads the real roster, tools, skills, model roles and tabs, so "how do you
  work" is answered from what is actually installed, not from what a model imagines.
* **From a model** — one call for a simple request. For a complicated one, two small calls run side by side (one lays
  out the structure, one checks and labels it) and the better answer wins: that is the "multiple agents" the owner
  asked for, bounded to two so a laptop never grinds.
* **A picture instead** — ``find_image()`` searches Openverse and Wikimedia Commons (both free, both give a licence and
  a source), and ``generate_image`` draws one when nothing found fits.

Diagrams are saved as small JSON files so the overlay can reopen and keep drawing on them.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from paths import data_path

_LOG = logging.getLogger("nyx.diagram")

KINDS = ("flow", "map", "stack", "timeline", "comparison")
SHAPES = ("box", "round", "circle", "diamond", "note")
MAX_NODES = 44
MAX_EDGES = 90
MAX_GROUPS = 8
KEEP = 60
#: Two small calls at most — the owner asked for several agents, but never at the cost of the machine.
MAX_HELPERS = 2

_SELF_WORDS = re.compile(r"\b(you|your|yourself|nyx|this ai|the ai|itself|its own)\b", re.I)
_SELF_TOPIC = re.compile(r"\b(work|works|working|architecture|inside|structure|agents?|brain|system|setup|built|pipeline|tools?)\b", re.I)
_IMAGE_WORDS = re.compile(r"\b(photo|photograph|picture of|image of|painting|drawing of|what does .* look like|show me a picture)\b", re.I)


class DiagramError(RuntimeError):
    """Why a diagram could not be made, in words for the overlay."""


# ---------------------------------------------------------------------------
# The spec
# ---------------------------------------------------------------------------


def _text(value: Any, limit: int) -> str:
    if isinstance(value, (list, tuple, set)):
        # An agent's expertise is a list; show it as words, not as Python's list spelling.
        value = ", ".join(str(item) for item in value if item)
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _level(value: Any) -> Optional[int]:
    """The column a box asks for. 0 is a real answer, so it must not be read as "none"."""
    text = str(value).strip()
    return max(0, min(12, int(text))) if text.lstrip("-").isdigit() else None


def clean_spec(data: Any, *, request: str = "", source: str = "model") -> Dict[str, Any]:
    """Validate whatever came back into a drawable diagram. Raises DiagramError when there is nothing to draw."""
    if not isinstance(data, dict):
        raise DiagramError("The model did not describe a diagram.")
    kind = str(data.get("kind") or "flow").lower()
    nodes: List[Dict[str, Any]] = []
    seen: Dict[str, str] = {}
    for index, raw in enumerate((data.get("nodes") or [])[:MAX_NODES]):
        if isinstance(raw, str):
            raw = {"label": raw}
        if not isinstance(raw, dict):
            continue
        label = _text(raw.get("label") or raw.get("name") or raw.get("id"), 60)
        if not label:
            continue
        node_id = re.sub(r"[^a-z0-9_-]+", "-", str(raw.get("id") or label).lower()).strip("-")[:40] or f"n{index}"
        while node_id in seen:
            node_id = f"{node_id}-{index}"
        seen[node_id] = label
        shape = str(raw.get("shape") or "box").lower()
        nodes.append({"id": node_id, "label": label, "sub": _text(raw.get("sub") or raw.get("detail"), 90),
                      "group": _text(raw.get("group"), 40), "shape": shape if shape in SHAPES else "box",
                      "level": _level(raw.get("level"))})
    if not nodes:
        raise DiagramError("A diagram needs at least one labelled box.")
    ids = {n["id"] for n in nodes}
    by_label = {n["label"].lower(): n["id"] for n in nodes}

    def resolve(value: Any) -> str:
        key = re.sub(r"[^a-z0-9_-]+", "-", str(value or "").lower()).strip("-")
        if key in ids:
            return key
        return by_label.get(_text(value, 60).lower(), "")

    edges = []
    for raw in (data.get("edges") or data.get("links") or [])[:MAX_EDGES]:
        if not isinstance(raw, dict):
            continue
        start, end = resolve(raw.get("from") or raw.get("source")), resolve(raw.get("to") or raw.get("target"))
        if not start or not end or start == end:
            continue
        style = str(raw.get("style") or "solid").lower()
        edges.append({"from": start, "to": end, "label": _text(raw.get("label"), 40),
                      "style": style if style in ("solid", "dashed", "thick") else "solid"})
    groups = []
    for index, raw in enumerate((data.get("groups") or [])[:MAX_GROUPS]):
        if isinstance(raw, str):
            raw = {"label": raw}
        if not isinstance(raw, dict):
            continue
        label = _text(raw.get("label") or raw.get("name"), 40)
        if label:
            groups.append({"id": re.sub(r"[^a-z0-9_-]+", "-", label.lower())[:30] or f"g{index}", "label": label, "color": index})
    known = {g["label"].lower() for g in groups}
    for node in nodes:
        if node["group"] and node["group"].lower() not in known and len(groups) < MAX_GROUPS:
            groups.append({"id": re.sub(r"[^a-z0-9_-]+", "-", node["group"].lower())[:30], "label": node["group"], "color": len(groups)})
            known.add(node["group"].lower())
    return {
        "id": uuid.uuid4().hex[:10], "title": _text(data.get("title") or request, 90) or "Diagram",
        "caption": _text(data.get("caption") or data.get("summary"), 300), "kind": kind if kind in KINDS else "flow",
        "nodes": nodes, "edges": edges, "groups": groups,
        "notes": [_text(n, 160) for n in (data.get("notes") or [])][:6],
        "image": None, "strokes": [], "request": _text(request, 300), "source": source, "created_at": time.time(),
    }


# ---------------------------------------------------------------------------
# Nyx's own picture, from what is really installed
# ---------------------------------------------------------------------------


def _roster() -> List[Dict[str, Any]]:
    try:
        import agent_runtime

        return agent_runtime.load_roster()
    except Exception:  # noqa: BLE001
        return []


def self_portrait() -> Dict[str, Any]:
    """How Nyx actually works right now: its agents, the models behind them, its tools, skills and memory.

    Laid out as a map: You above the turn runner, then the Manager and its specialists, then tools, model roles and
    knowledge. At most eight boxes a column, so it reads at a glance; the rest is counted in the notes."""
    nodes: List[Dict[str, Any]] = [
        {"id": "owner", "label": "You", "sub": "type or speak", "group": "Front", "shape": "round", "level": 0},
        {"id": "turn", "label": "Turn runner", "sub": "plans, calls tools, streams the answer", "group": "Front",
         "shape": "box", "level": 0}]
    edges: List[Dict[str, Any]] = [{"from": "owner", "to": "turn", "label": "asks", "style": "solid"}]
    notes: List[str] = []

    roster = _roster()
    manager = next((a for a in roster if str(a.get("role")) == "master"), None)
    if manager:
        nodes.append({"id": "manager", "label": manager.get("name", "Manager"), "sub": _text(manager.get("goal"), 70),
                      "group": "Agents", "shape": "round", "level": 0})
        edges.append({"from": "turn", "to": "manager", "label": "hands work to", "style": "solid"})
    workers = [a for a in roster if a is not manager]
    shown = workers if len(workers) <= 8 else workers[:7]
    for agent in shown:
        node_id = re.sub(r"[^a-z0-9]+", "-", str(agent.get("name", "agent")).lower())[:30] or "agent"
        made_by = str(agent.get("made_by") or "")
        nodes.append({"id": node_id, "label": str(agent.get("name", "Agent"))[:40],
                      "sub": _text(agent.get("expertise") or agent.get("goal"), 70) + (" · made by Nyx" if made_by == "nyx" else ""),
                      "group": "Agents", "shape": "box", "level": 1})
        edges.append({"from": "manager" if manager else "turn", "to": node_id, "style": "solid"})
    if len(workers) > len(shown):
        rest = workers[len(shown):]
        nodes.append({"id": "more-agents", "label": f"{len(rest)} more agents",
                      "sub": _text(", ".join(str(a.get("name", "")) for a in rest), 90), "group": "Agents", "shape": "note",
                      "level": 1})
        edges.append({"from": "manager" if manager else "turn", "to": "more-agents", "style": "solid"})

    try:
        from tools import TOOL_REGISTRY

        categories: Dict[str, int] = {}
        for tool in TOOL_REGISTRY.tools.values():
            name = str(getattr(tool, "category", "other") or "other").split(".")[0]
            categories[name] = categories.get(name, 0) + 1
        biggest = sorted(categories.items(), key=lambda kv: -kv[1])[:6]
        for name, count in biggest:
            node_id = f"tools-{re.sub(r'[^a-z0-9]+', '-', name.lower())}"[:30]
            nodes.append({"id": node_id, "label": name.replace("_", " ").title(), "sub": f"{count} tools", "group": "Tools",
                          "shape": "note", "level": 0})
            edges.append({"from": "turn", "to": node_id, "style": "dashed"})
        if len(categories) > len(biggest):
            notes.append(f"{sum(categories.values())} tools in {len(categories)} kinds; the {len(biggest)} biggest kinds are drawn.")
    except Exception:  # noqa: BLE001
        pass

    try:
        from model_roles import MODEL_ROLES

        roles = list(MODEL_ROLES.list_all().items())
        for role, entry in roles[:6]:
            node_id = f"model-{re.sub(r'[^a-z0-9]+', '-', role)}"[:30]
            nodes.append({"id": node_id, "label": _text(entry.get("title") or role, 40), "sub": _text(entry.get("label"), 60),
                          "group": "Models", "shape": "round", "level": 0})
            edges.append({"from": "turn", "to": node_id, "style": "dashed"})
        if len(roles) > 6:
            notes.append(f"{len(roles)} model roles; the first six are drawn (Models tab has them all).")
    except Exception:  # noqa: BLE001
        pass

    try:
        from skills import SKILL_STORE

        skills = [s for s in SKILL_STORE.list_skills() if s.get("enabled")]
        nodes.append({"id": "skills", "label": "Skills", "sub": f"{len(skills)} it can follow", "group": "Knowledge",
                      "shape": "note", "level": 0})
        edges.append({"from": "turn", "to": "skills", "style": "dashed"})
    except Exception:  # noqa: BLE001
        pass
    try:
        import super_brain

        counts = super_brain.BRAIN.counts(cached=True)
        nodes.append({"id": "brain", "label": "Super brain",
                      "sub": f"{counts.get('memories', 0):,} memories · {counts.get('concepts', 0):,} concepts",
                      "group": "Knowledge", "shape": "circle", "level": 0})
        edges.append({"from": "turn", "to": "brain", "label": "remembers in", "style": "solid"})
    except Exception:  # noqa: BLE001
        pass
    try:
        import nyx_core

        snapshot = nyx_core.CORE.snapshot()
        nodes.append({"id": "core", "label": f"Nyx Core · level {snapshot.get('level', 0)}",
                      "sub": f"{snapshot.get('parameters', 0):,} learned parameters", "group": "Knowledge", "shape": "circle",
                      "level": 0})
        edges.append({"from": "brain", "to": "core", "label": "trains", "style": "solid"})
    except Exception:  # noqa: BLE001
        pass

    caption = ("What Nyx is made of on this PC right now: the turn runner takes what you say, the Manager hands work to the "
               "specialists, tools reach the machine and the web, model roles decide who thinks about what, and everything "
               "read or said lands in the super brain that trains Nyx Core.")
    notes.insert(0, "Built from this install: agents, tools, model roles, skills and memory counts as they are now.")
    return clean_spec({"title": "How Nyx works", "kind": "map", "caption": caption, "nodes": nodes, "edges": edges,
                       "groups": [{"label": "Front"}, {"label": "Agents"}, {"label": "Tools"}, {"label": "Models"}, {"label": "Knowledge"}],
                       "notes": notes},
                      request="how Nyx works", source="itself")


# ---------------------------------------------------------------------------
# Making one
# ---------------------------------------------------------------------------


def is_self_request(request: str) -> bool:
    text = str(request or "")
    return bool(_SELF_WORDS.search(text) and _SELF_TOPIC.search(text))


def wants_picture(request: str) -> bool:
    return bool(_IMAGE_WORDS.search(str(request or "")))


def _model(prompt: str, *, system: str, max_tokens: int = 1200, role: str = "data_absorption") -> str:
    from model_roles import MODEL_ROLES

    return MODEL_ROLES.run(role, prompt, system="detailed thinking off\n" + system, max_tokens=max_tokens).text


_PROMPT = (
    "Draw this as a diagram: {request}\n\n"
    "Reply with JSON only, no reasoning:\n"
    '{{"title": "short title", "kind": "flow|map|stack|timeline|comparison", "caption": "one sentence a reader sees under it", '
    '"groups": [{{"label": "a band or column"}}], "nodes": [{{"id": "short-id", "label": "what it is", "sub": "a few words more", '
    '"group": "which group", "shape": "box|round|circle|diamond|note"}}], "edges": [{{"from": "id", "to": "id", "label": "verb", '
    '"style": "solid|dashed|thick"}}], "notes": ["anything the reader should know"]}}\n'
    "Between 4 and 20 nodes. Labels are short. Every edge points from one node id to another."
)
_CHECK = (
    "Here is a diagram someone drew for the request: {request}\n{spec}\n\n"
    "Improve it: fix wrong or missing links, tighten the labels, add what is obviously missing, drop anything that does not "
    "belong. Keep the same JSON shape and reply with JSON only, no reasoning."
)


def make(request: str, *, model_fn: Optional[Callable[..., str]] = None, helpers: Optional[int] = None) -> Dict[str, Any]:
    """A diagram for this request. One model call for something simple, two in parallel for something complex."""
    clean = str(request or "").strip()
    if len(clean) < 3:
        raise DiagramError("Say what the diagram should show.")
    if is_self_request(clean):
        return self_portrait()
    ask = model_fn or _model
    from absorb_engine import json_from

    complex_request = helpers if helpers is not None else (len(clean) > 120 or bool(re.search(
        r"\b(compare|versus| vs |timeline|pipeline|architecture|end to end|everything|full|detailed|stack)\b", clean, re.I)))
    first = None
    try:
        first = clean_spec(json_from(ask(_PROMPT.format(request=clean),
                                         system="You turn requests into diagram JSON. Reply with JSON only.")), request=clean)
    except Exception as error:  # noqa: BLE001 - the second pass or the offline fallback may still answer
        _LOG.info("diagram first pass failed: %s", error)
    if complex_request and first is not None:
        # The second helper only ever *improves* what the first drew, so a failure costs nothing.
        try:
            with ThreadPoolExecutor(max_workers=MAX_HELPERS) as pool:
                job = pool.submit(ask, _CHECK.format(request=clean, spec=json.dumps(_for_model(first))[:4000]),
                                  system="You improve diagram JSON. Reply with JSON only.")
                better = clean_spec(json_from(job.result(timeout=90)), request=clean, source="model+check")
            if len(better["nodes"]) >= max(3, len(first["nodes"]) - 2):
                better["helpers"] = 2
                return better
        except Exception as error:  # noqa: BLE001
            _LOG.info("diagram check pass failed: %s", error)
    if first is not None:
        first["helpers"] = 1
        return first
    return offline_spec(clean)


def _for_model(spec: Dict[str, Any]) -> Dict[str, Any]:
    return {k: spec[k] for k in ("title", "kind", "caption", "nodes", "edges", "groups", "notes") if k in spec}


def offline_spec(request: str) -> Dict[str, Any]:
    """No model answered: a plain map of what the request is about, so the overlay still opens with something real."""
    import absorb_text

    phrases = absorb_text.keyphrases(request, limit=8) or absorb_text.content_words(request)[:6] or [request[:40]]
    nodes = [{"id": "topic", "label": request[:60], "shape": "round", "group": "Asked for"}]
    edges = []
    for index, phrase in enumerate(phrases[:8]):
        node_id = f"p{index}"
        nodes.append({"id": node_id, "label": phrase[:50], "shape": "box", "group": "Parts"})
        edges.append({"from": "topic", "to": node_id, "style": "solid"})
    return clean_spec({"title": request[:60], "kind": "map", "nodes": nodes, "edges": edges,
                       "caption": "No model was reachable, so this is the shape of what you asked for — edit it or draw on it.",
                       "notes": ["Ask again when a model is reachable for a full diagram."]}, request=request, source="offline")


# ---------------------------------------------------------------------------
# Pictures
# ---------------------------------------------------------------------------


def find_image(query: str, limit: int = 6, get: Optional[Callable[..., Any]] = None) -> List[Dict[str, Any]]:
    """Real pictures with a licence and a source: Openverse first, then Wikimedia Commons. Neither needs a key."""
    import requests

    http = get or requests.get
    headers = {"User-Agent": "NyxIchos/1.0 (local assistant)"}
    found: List[Dict[str, Any]] = []
    try:
        response = http("https://api.openverse.org/v1/images/", params={"q": query, "page_size": limit, "license_type": "all"},
                        headers=headers, timeout=15)
        if response.status_code == 200:
            for item in response.json().get("results", [])[:limit]:
                found.append({"url": item.get("url", ""), "thumb": item.get("thumbnail") or item.get("url", ""),
                              "title": _text(item.get("title"), 90), "source": item.get("foreign_landing_url", ""),
                              "licence": _text(item.get("license") or "", 30).upper(), "by": _text(item.get("creator"), 60),
                              "where": "Openverse"})
    except Exception as error:  # noqa: BLE001 - Wikimedia is the fallback
        _LOG.info("openverse failed: %s", error)
    if len(found) < limit:
        try:
            response = http("https://commons.wikimedia.org/w/api.php", headers=headers, timeout=15, params={
                "action": "query", "generator": "search", "gsrnamespace": 6, "gsrsearch": query, "gsrlimit": limit,
                "prop": "imageinfo", "iiprop": "url|extmetadata", "format": "json"})
            pages = (response.json().get("query", {}) or {}).get("pages", {}) if response.status_code == 200 else {}
            for page in list(pages.values())[:limit]:
                info = (page.get("imageinfo") or [{}])[0]
                meta = info.get("extmetadata") or {}
                url = info.get("url", "")
                if not url.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                    continue
                found.append({"url": url, "thumb": url, "title": _text(page.get("title", "").replace("File:", ""), 90),
                              "source": info.get("descriptionurl", ""), "licence": _text((meta.get("LicenseShortName") or {}).get("value"), 30),
                              "by": re.sub(r"<[^>]+>", "", str((meta.get("Artist") or {}).get("value", "")))[:60], "where": "Wikimedia Commons"})
        except Exception as error:  # noqa: BLE001
            _LOG.info("commons failed: %s", error)
    return found[:limit]


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def _dir() -> Path:
    path = data_path("diagrams")
    path.mkdir(parents=True, exist_ok=True)
    return path


def save(spec: Dict[str, Any]) -> Dict[str, Any]:
    path = _dir() / f"{spec['id']}.json"
    path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    files = sorted(_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[KEEP:]:
        try:
            old.unlink()
        except OSError:
            pass
    return spec


def load(diagram_id: str) -> Dict[str, Any]:
    path = _dir() / f"{re.sub(r'[^a-z0-9]+', '', str(diagram_id).lower())[:32]}.json"
    if not path.exists():
        raise DiagramError("That diagram is gone.")
    return json.loads(path.read_text(encoding="utf-8"))


def recent(limit: int = 20) -> List[Dict[str, Any]]:
    out = []
    for path in sorted(_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"id": spec.get("id"), "title": spec.get("title"), "kind": spec.get("kind"),
                    "created_at": spec.get("created_at", 0), "nodes": len(spec.get("nodes") or []),
                    "has_image": bool(spec.get("image")), "request": spec.get("request", "")})
    return out


def update(diagram_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
    """Save what the owner drew or renamed on top of a diagram."""
    spec = load(diagram_id)
    if isinstance(changes.get("strokes"), list):
        spec["strokes"] = changes["strokes"][:4000]
    if changes.get("title"):
        spec["title"] = _text(changes["title"], 90)
    if isinstance(changes.get("image"), dict) or changes.get("image") is None and "image" in changes:
        spec["image"] = changes.get("image")
    if isinstance(changes.get("nodes"), list) or isinstance(changes.get("edges"), list):
        merged = clean_spec({**_for_model(spec), **{k: v for k, v in changes.items() if k in ("nodes", "edges", "groups", "kind", "caption")}},
                            request=spec.get("request", ""), source=spec.get("source", "model"))
        spec = {**spec, **{k: merged[k] for k in ("nodes", "edges", "groups", "kind", "caption")}}
    spec["updated_at"] = time.time()
    return save(spec)


# ---------------------------------------------------------------------------
# Chat tools
# ---------------------------------------------------------------------------


def _publish(spec: Dict[str, Any]) -> None:
    try:
        from agent_events import publish_ui

        publish_ui("diagram.open", diagram={"id": spec["id"], "title": spec["title"]})
    except Exception:  # noqa: BLE001
        pass


def tool_show_diagram(request: str, with_picture: bool = False) -> str:
    """Chat/voice: "make a diagram of …" — the overlay opens with it."""
    try:
        spec = make(request)
    except DiagramError as error:
        return f"Could not draw that: {error}"
    if with_picture or wants_picture(request):
        images = find_image(request, limit=3)
        if images:
            spec["image"] = images[0]
            spec["image_choices"] = images
    save(spec)
    _publish(spec)
    where = "from this install" if spec["source"] == "itself" else ("offline" if spec["source"] == "offline"
                                                                    else f"{spec.get('helpers', 1)} model pass(es)")
    return (f"Opened a diagram: “{spec['title']}” — {len(spec['nodes'])} boxes, {len(spec['edges'])} links ({where}). "
            "It is on screen in the diagram overlay, where it can be drawn on, saved as a picture or a PDF, and put in the chat. "
            f"[diagram:{spec['id']}]")


def tool_show_image(query: str, generate: bool = False) -> str:
    """Chat/voice: find a real picture (with its licence and source) or draw one."""
    if not generate:
        images = find_image(query, limit=4)
        if images:
            spec = clean_spec({"title": _text(query, 60) or "Picture", "kind": "map",
                               "nodes": [{"id": "picture", "label": _text(query, 50) or "Picture", "shape": "note"}],
                               "caption": f"{images[0]['title']} — {images[0]['where']}"
                                          + (f", {images[0]['licence']}" if images[0].get("licence") else "")},
                              request=query, source="image")
            spec["image"] = images[0]
            spec["image_choices"] = images
            save(spec)
            _publish(spec)
            return (f"Found a picture for “{query}”: {images[0]['title']} ({images[0]['where']}"
                    + (f", {images[0]['licence']}" if images[0].get("licence") else "") + "). It is open in the overlay with "
                    f"{len(images)} choices. [diagram:{spec['id']}]")
    from image_gen import generate_image

    result = generate_image(query)
    if not result.ok:
        return f"No picture found or drawn: {result.error}"
    spec = clean_spec({"title": _text(query, 60) or "Picture", "kind": "map",
                       "nodes": [{"id": "picture", "label": _text(query, 50) or "Picture", "shape": "note"}],
                       "caption": f"Drawn by {result.label}"}, request=query, source="generated")
    spec["image"] = {"url": result.url, "thumb": result.url, "title": _text(query, 90), "source": "", "licence": "",
                     "by": result.label, "where": "Nyx drew it"}
    save(spec)
    _publish(spec)
    return f"Drew a picture for “{query}” with {result.label} and opened it. ![{query[:60]}]({result.url}) [diagram:{spec['id']}]"


def register_diagram_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        name="show_diagram",
        description=("Draw a diagram and open it on screen for the owner (works in text and in voice): how something works, an "
                     "architecture, a flow, a comparison, a timeline. Asking about Nyx itself draws the real install — its "
                     "agents, tools, model roles, skills and memory."),
        parameters=[ToolParam("request", "string", "What the diagram should show, in the owner's words"),
                    ToolParam("with_picture", "boolean", "Also find a real photo to sit beside it", required=False)],
        handler=tool_show_diagram,
        category="ui",
        label=lambda a: f"Drawing {str(a.get('request', ''))[:40]}",
    )
    registry.register(
        name="show_image",
        description=("Find a real picture on the free image libraries (Openverse, Wikimedia Commons) and show it with its "
                     "licence and source, or draw one when nothing fits. Opens in the same overlay."),
        parameters=[ToolParam("query", "string", "What the picture should show"),
                    ToolParam("generate", "boolean", "Draw it instead of searching", required=False)],
        handler=tool_show_image,
        category="ui",
        label=lambda a: f"Finding a picture of {str(a.get('query', ''))[:40]}",
    )
