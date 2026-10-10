"""Design research: study how other apps and sites look, keep what is good as compact notes, and design with them.

The owner (2026-10-09): "a new design feature which we will train separately which will be the design research I
said before. This will be a good thing to learn for Claude and my AI." It is the Research log of
``DESIGN_MASTERPLAN.md`` (the outer folder) made into a Nyx feature: each entry has a source, what's good, a prompt
that reproduces it, and where to use it — the same fields, so an entry can be copied into the masterplan for Claude
sessions to read.

How a study works (``study``):
1. The page and up to three of its stylesheets are fetched with ``absorb_sources.fetch`` (public hosts only, capped).
2. **Tokens are measured offline**: the colours used most, fonts, corner radii, type sizes, spacing, CSS custom
   properties, layout (grid / flex), and whether the page is dark or light. Arithmetic, no model.
3. A model reads only those tokens plus the page's title and headings — never the page text — and writes what's good,
   a reproduce prompt and the principles in play.
4. The entry is kept in ``design_research/entries.json`` (≤ 300). Nothing of the page itself is stored, so this is a
   library of notes about design, not a copy of anyone's site, and not training data: "train separately" stays the
   owner's later step (the Safe-mix rule — web pages are for lookup).

``design_sense`` reads the entries relevant to a request, so tabs Nyx designs draw on what was studied.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from paths import data_path

STORE = "design_research/entries.json"
MAX_ENTRIES = 300
MAX_SHEETS = 3
_HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_RGB = re.compile(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})")
_FONT = re.compile(r"font-family\s*:\s*([^;}{]+)", re.I)
_RADIUS = re.compile(r"border-radius\s*:\s*([0-9.]+(?:px|rem|em|%))", re.I)
_SIZE = re.compile(r"font-size\s*:\s*([0-9.]+(?:px|rem|em))", re.I)
_SPACE = re.compile(r"(?:padding|margin|gap)\s*:\s*([0-9.]+(?:px|rem|em))", re.I)
_VAR = re.compile(r"(--[a-zA-Z0-9-]{2,40})\s*:\s*([^;}{]{1,60})")
_LOCK = threading.RLock()


class ResearchError(RuntimeError):
    """Something the owner can act on."""


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------


def _norm_hex(value: str) -> str:
    value = value.lower()
    if len(value) == 4:
        value = "#" + "".join(ch * 2 for ch in value[1:])
    return value


def _luminance(hex_colour: str) -> float:
    r, g, b = (int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def measure(html: str, css: str) -> Dict[str, Any]:
    """The design tokens a page uses, from its markup and styles. Pure, so it is tested without the web."""
    text = f"{html}\n{css}"
    colours = Counter(_norm_hex(h) for h in _HEX.findall(text))
    for r, g, b in _RGB.findall(text):
        if max(int(r), int(g), int(b)) <= 255:
            colours["#%02x%02x%02x" % (int(r), int(g), int(b))] += 1
    fonts = Counter()
    for stack in _FONT.findall(text):
        first = stack.split(",")[0].strip().strip("'\"")
        if first and not first.startswith("var(") and len(first) < 40:
            fonts[first] += 1
    variables = {}
    for name, value in _VAR.findall(text)[:400]:
        if name not in variables:
            variables[name] = value.strip()
    top_colours = [c for c, _n in colours.most_common(10)]
    background = next((c for c in top_colours if _luminance(c) < 0.2 or _luminance(c) > 0.9), "")
    return {
        "colours": top_colours,
        "fonts": [f for f, _n in fonts.most_common(4)],
        "radii": [r for r, _n in Counter(_RADIUS.findall(text)).most_common(5)],
        "type_sizes": [s for s, _n in Counter(_SIZE.findall(text)).most_common(6)],
        "spacing": [s for s, _n in Counter(_SPACE.findall(text)).most_common(6)],
        "variables": dict(list(variables.items())[:20]),
        "layout": {"grid": len(re.findall(r"display\s*:\s*grid", text, re.I)),
                   "flex": len(re.findall(r"display\s*:\s*flex", text, re.I))},
        "theme": ("dark" if background and _luminance(background) < 0.2 else "light") if background else "unknown",
    }


def _outline(html: str) -> Dict[str, Any]:
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    heads = [re.sub(r"<[^>]+>|\s+", " ", h).strip() for h in re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", html, re.S | re.I)]
    return {"title": re.sub(r"\s+", " ", title.group(1)).strip()[:120] if title else "",
            "headings": [h[:80] for h in heads if h][:12]}


def _sheets(html: str, base: str) -> List[str]:
    import urllib.parse

    links = re.findall(r"<link[^>]+rel=[\"']?stylesheet[\"']?[^>]*>", html, re.I)
    hrefs = []
    for tag in links:
        href = re.search(r"href=[\"']([^\"']+)[\"']", tag, re.I)
        if href:
            hrefs.append(urllib.parse.urljoin(base, href.group(1)))
    return hrefs[:MAX_SHEETS]


# ---------------------------------------------------------------------------
# Studying
# ---------------------------------------------------------------------------


def _write_up(name: str, url: str, tokens: Dict[str, Any], outline: Dict[str, Any], focus: str) -> Dict[str, Any]:
    """What's good, a reproduce prompt, principles — written by a model from the tokens only."""
    from model_roles import MODEL_ROLES

    prompt = (
        f"You are a design researcher. Study the design system of {name} ({url}) from these measured tokens and its "
        f"page outline, and say what is good about it.{' Focus on: ' + focus if focus else ''}\n\n"
        f"Tokens: {json.dumps(tokens)}\nOutline: {json.dumps(outline)}\n\n"
        'Answer with JSON only: {"good": "1-3 short lines on what works and why", '
        '"reproduce": "a prompt another AI could follow to design in this style, with the key tokens", '
        '"principles": ["3-5 short design principles this shows"], "use_for": "what kind of screens this suits"}')
    run = MODEL_ROLES.run("fast_chat", prompt, max_tokens=700)
    text = re.sub(r"<think>.*?</think>", "", run.text or "", flags=re.S)
    match = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(match.group(0)) if match else {}
    except ValueError:
        data = {}
    return {"good": str(data.get("good") or "")[:500], "reproduce": str(data.get("reproduce") or "")[:900],
            "principles": [str(p)[:120] for p in (data.get("principles") or [])][:5],
            "use_for": str(data.get("use_for") or "")[:200], "model": run.label}


def study(url: str, name: str = "", focus: str = "", *, fetch: Any = None, write_up: Any = None) -> Dict[str, Any]:
    """Study one site: measure its tokens, write it up, keep the entry."""
    import absorb_sources

    get = fetch or (lambda u: absorb_sources.fetch(u, max_bytes=1_500_000))
    target = (url or "").strip()
    if not re.match(r"^https?://", target):
        raise ResearchError("Give the page's address, starting with https://")
    try:
        body, _type, final = get(target)
    except Exception as error:  # noqa: BLE001 - said plainly
        raise ResearchError(f"Could not read {target}: {error}") from error
    html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)
    css_parts = re.findall(r"<style[^>]*>(.*?)</style>", html, re.S | re.I)
    for sheet in _sheets(html, final or target):
        try:
            data, _t, _f = get(sheet)
            css_parts.append(data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data))
        except Exception:  # noqa: BLE001 - one stylesheet missing is fine
            continue
    tokens = measure(html, "\n".join(css_parts))
    outline = _outline(html)
    label = (name or outline["title"] or re.sub(r"^https?://(www\.)?", "", target).split("/")[0])[:80]
    try:
        notes = (write_up or _write_up)(label, target, tokens, outline, focus)
    except Exception as error:  # noqa: BLE001 - the tokens are still worth keeping
        notes = {"good": "", "reproduce": "", "principles": [], "use_for": "", "model": f"no model ({type(error).__name__})"}
    entry = {"id": "dr-" + uuid.uuid4().hex[:8], "name": label, "url": target, "at": time.time(), "focus": focus[:200],
             "tokens": tokens, "outline": outline, **notes}
    with _LOCK:
        entries = _load()
        entries.append(entry)
        _save(entries[-MAX_ENTRIES:])
    return entry


# ---------------------------------------------------------------------------
# The library
# ---------------------------------------------------------------------------


def _path() -> Path:
    return data_path(STORE)


def _load() -> List[Dict[str, Any]]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(entries: List[Dict[str, Any]]) -> None:
    target = _path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(entries, indent=1, ensure_ascii=False), encoding="utf-8")
    temp.replace(target)


def entries() -> List[Dict[str, Any]]:
    return list(reversed(_load()))


def remove(entry_id: str) -> bool:
    with _LOCK:
        kept = [e for e in _load() if e.get("id") != entry_id]
        changed = len(kept) != len(_load())
        _save(kept)
    return changed


def relevant(request: str, limit: int = 3) -> List[Dict[str, Any]]:
    """Entries whose words overlap the request most; the newest when nothing overlaps. For design_sense."""
    words = set(re.findall(r"[a-z]{4,}", (request or "").lower()))
    scored = []
    for entry in _load():
        text = " ".join([entry.get("name", ""), entry.get("good", ""), entry.get("use_for", ""),
                         " ".join(entry.get("principles") or []), entry.get("focus", "")]).lower()
        scored.append((len(words & set(re.findall(r"[a-z]{4,}", text))), entry.get("at", 0), entry))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [entry for _score, _at, entry in scored[:limit]]


def as_masterplan(entry: Dict[str, Any]) -> str:
    """The entry in DESIGN_MASTERPLAN.md's Research-log format, ready to paste or append."""
    day = time.strftime("%Y-%m-%d", time.localtime(entry.get("at") or time.time()))
    t = entry.get("tokens") or {}
    lines = [f"### {entry.get('name')} — {day}", f"- **Source:** {entry.get('url')}"]
    if entry.get("good"):
        lines.append(f"- **What's good:** {entry['good']}")
    tokens = f"colours {', '.join((t.get('colours') or [])[:5])}; fonts {', '.join(t.get('fonts') or []) or '—'}; " \
             f"radii {', '.join(t.get('radii') or []) or '—'}; {t.get('theme', 'unknown')} theme"
    lines.append(f"- **Tokens:** {tokens}")
    if entry.get("reproduce"):
        lines.append(f"- **Reproduce:** \"{entry['reproduce']}\"")
    if entry.get("use_for"):
        lines.append(f"- **Use it for:** {entry['use_for']}")
    return "\n".join(lines)


def masterplan_path() -> Path:
    from paths import PROJECT_DIR

    return Path(PROJECT_DIR).parent / "DESIGN_MASTERPLAN.md"


def add_to_masterplan(entry_id: str) -> Dict[str, Any]:
    """Append one entry to the owner's DESIGN_MASTERPLAN.md (outer folder) — only from the owner's button."""
    entry = next((e for e in _load() if e.get("id") == entry_id), None)
    if entry is None:
        raise ResearchError("That entry is gone.")
    target = masterplan_path()
    if not target.is_file():
        raise ResearchError(f"There is no DESIGN_MASTERPLAN.md at {target}.")
    current = target.read_text(encoding="utf-8")
    block = as_masterplan(entry)
    if block.splitlines()[0] in current:
        return {"added": False, "path": str(target), "why": "Already in the masterplan."}
    target.write_text(current.rstrip() + "\n\n" + block + "\n", encoding="utf-8")
    return {"added": True, "path": str(target)}


def tool_study(url: str, focus: str = "") -> str:
    try:
        entry = study(url, focus=focus)
    except ResearchError as error:
        return f"Not studied: {error}"
    return as_masterplan(entry)


def register_research_tools(registry: Any) -> None:
    from tools import ToolParam as P

    registry.register("design_study", "Study how a website looks — its colours, fonts, spacing, corners and layout — and "
                      "keep what is good as a design research note Nyx designs with later. Use when the owner says "
                      "'study this site's design', 'design research on …', or wants a look like some site.",
                      [P("url", "string", "The page, https://…"), P("focus", "string", "What to look at", required=False)],
                      tool_study, category="web", label=lambda a: f"Studying the design of {a.get('url', '')[:50]}")
