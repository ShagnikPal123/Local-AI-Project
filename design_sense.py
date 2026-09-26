"""Front-end design sense: how Nyx should read a design request (Project Null N88).

The owner: "feel all ui, past ui decision, how ui updates, how apple and most
software companies design ui, how ai interpret prompts for front end design and
how it should respond. It should also have no default design. It should allow
for extremely free interpretation. It should have almost all permissions on so
it can search, look at other tabs, understand exactly what the user wants, and
use online ai models to design it."

The failure this is built against: an assistant asked for "a page for my runs"
produces the same centred card stack it produces for everything, because the
prompt gave it no design to make and the model fell back to its training
average. So the job here is not to supply a house style — it is to *remove the
default* by making the model decide, on the record, for this request:

* what is actually being made, for whom, and what it has to feel like;
* two or three genuinely different directions, one of which is chosen with a reason;
* the tokens that follow from that choice (palette, type, spacing, motion);
* the thing it will deliberately avoid, which is what stops the generic version.

What it draws on: the owner's own past UI decisions (kept in ``data/design/
decisions.jsonl`` and mined from their requests), the tabs that already exist and
the tokens this app is built from, the Apple guidelines shipped with Nyx, plus
web references and a model pass when they are available. All of it is *input to
a decision*, never a template to fill.

``build_brief`` is the whole interface; ``brief_for_prompt`` is the one-line form
for callers that just want text to paste into their own prompt, and never raises.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional, Sequence

from paths import data_path

MAX_DECISIONS = 400
#: How many past decisions the taste profile reads.
TASTE_WINDOW = 60


# ---------------------------------------------------------------------------
# What is known about designing things (written here, not copied from anywhere)
# ---------------------------------------------------------------------------

#: The parts of practice that actually change a decision, in the words that make
#: a model act on them. Deliberately short: a wall of theory gets skimmed.
PRINCIPLES: Dict[str, List[str]] = {
    "apple": [
        "Clarity: the content is the interface. Chrome earns its place or goes.",
        "Deference: nothing decorative competes with what the person came for.",
        "Depth: layering and motion say where things came from and where they went.",
        "One thing is obviously the most important on every screen; the rest recedes.",
        "Controls are large enough to hit without aiming (44pt), and say what they do in verbs.",
        "Respect the system: dark mode, reduced motion, text size, and the platform's own gestures.",
    ],
    "industry": [
        "Material: surfaces and elevation carry hierarchy; motion is a physical consequence, not decoration.",
        "Fluent: depth and materials, but quieter — content first, generous density control.",
        "Stripe/Linear school: restraint, one accent, tabular numbers, keyboard-first, fast.",
        "Consumer social: density and immediacy over polish; the thing you do is one tap from the top.",
        "A product's look is a set of decisions repeated, not a theme file: spacing scale, one accent, one type scale.",
    ],
    "how_ui_updates": [
        "Real redesigns are incremental: tokens change first, then components, then layouts.",
        "Ship behind a switch, keep the old look reachable, and let the person say which they prefer.",
        "Change what is measurably confusing; leave what people have muscle memory for.",
        "When a look is refreshed, the smallest units go first (colour, radius, type), so nothing is relearned.",
    ],
    "craft": [
        "Whitespace is the cheapest hierarchy there is; borders are the most expensive.",
        "One accent colour, used for the action you want taken — never for three different meanings.",
        "Numbers in columns are tabular and right-aligned. Money and time always carry their unit.",
        "Empty states do the teaching: what this is, one thing to press, no apology.",
        "Loading says what is happening, not that something is happening.",
        "Colour never carries meaning alone: add a word, a sign or a shape (WCAG 1.4.1).",
        "Text on its background is at least 4.5:1, 3:1 for large text, and focus is always visible.",
        "Motion under 200ms for state, under 400ms for entrances; honour prefers-reduced-motion.",
    ],
}

#: How to read a front-end request. This is the part that replaces the default design.
READING_A_PROMPT = [
    "Name the job first: what does the person do here, how often, and what do they want to be true when they leave?",
    "Read the adjectives as constraints, not decoration: “clean” means fewer borders and more air; “fun” means "
    "motion and colour earn their place; “serious” means density and precision.",
    "Notice what they did NOT say — those are the free choices, and free choices are where the design comes from.",
    "Look at what they already have (their other tabs, their past requests): match the family, or break from it "
    "deliberately and say why.",
    "When something is genuinely ambiguous and changes the whole design, ask one question with options. Otherwise "
    "choose, and state the assumption in a line.",
    "Never start from a layout you have used before. Start from the content: what is on screen, in what order of "
    "importance, and how much of it is there on a bad day (empty, one item, five hundred).",
]

#: What "no default design" means concretely, stated as the things not to do.
AVOID_BY_DEFAULT = [
    "the centred hero + three feature cards + footer, unless the content really is a marketing page",
    "a purple-to-blue gradient used as personality",
    "a card around everything; cards are for things you can act on separately",
    "icons that repeat the label next to them",
    "a modal for anything the page could show in place",
    "placeholder text standing in for labels",
    "the same layout as the last thing you made",
]


# ---------------------------------------------------------------------------
# The owner's own taste
# ---------------------------------------------------------------------------


def _decisions_path():
    folder = data_path("design")
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "decisions.jsonl"


def record_decision(kind: str, summary: str, detail: Optional[Dict[str, Any]] = None,
                    verdict: str = "applied") -> Dict[str, Any]:
    """Remember a UI decision and how it went, so the next one can learn from it.

    ``verdict`` is applied | undone | liked | disliked — an undone change is the
    most useful record there is, so it is kept as carefully as a kept one.
    """
    entry = {"at": time.time(), "kind": str(kind)[:40], "summary": str(summary)[:400],
             "verdict": verdict if verdict in ("applied", "undone", "liked", "disliked") else "applied",
             "detail": {k: str(v)[:200] for k, v in (detail or {}).items()}}
    path = _decisions_path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    except OSError:  # pragma: no cover
        lines = []
    lines.append(json.dumps(entry, ensure_ascii=False))
    try:
        path.write_text("\n".join(lines[-MAX_DECISIONS:]) + "\n", encoding="utf-8")
    except OSError:  # pragma: no cover - a full disk must not break a design
        pass
    return entry


def decisions(limit: int = TASTE_WINDOW) -> List[Dict[str, Any]]:
    try:
        lines = _decisions_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: List[Dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            out.append(entry)
    return out


#: Sentences in the owner's requests that are about how things look or feel.
_UI_WORDS = re.compile(
    r"\b(ui|design|look|theme|colou?r|dark|black|clean|aesthetic|layout|font|icon|animation|animate|"
    r"apple|glass|gradient|background|spacing|rounded|button|slider|tab bar|hover)\b", re.IGNORECASE)


def past_requests(limit: int = 14) -> List[str]:
    """What the owner has actually asked for about looks, in their own words.

    Mined from the handoff's goals file rather than guessed: it is the one place
    every request is kept verbatim.
    """
    try:
        from paths import PROJECT_DIR

        text = (PROJECT_DIR / "AI_HANDOFF" / "01_GOALS.md").read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - the brief is still useful without this
        return []
    found: List[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
        clean = sentence.strip(" -*#>").strip()
        if 25 <= len(clean) <= 260 and _UI_WORDS.search(clean) and not clean.startswith("|"):
            found.append(clean)
    # The most recent are the most relevant; keep them in the order written.
    return found[-limit:]


def taste() -> Dict[str, Any]:
    """The owner's design profile: what they asked for, what they kept, what they undid."""
    kept = [d for d in decisions() if d["verdict"] in ("applied", "liked")]
    undone = [d for d in decisions() if d["verdict"] in ("undone", "disliked")]
    return {
        "asked_for": past_requests(),
        "kept": [d["summary"] for d in kept[-12:]],
        "undone": [d["summary"] for d in undone[-8:]],
        "tokens": app_tokens(),
    }


# ---------------------------------------------------------------------------
# What this app already looks like
# ---------------------------------------------------------------------------


def app_tokens() -> Dict[str, str]:
    """The design tokens Nyx itself is built from, read from the stylesheet."""
    try:
        from paths import PROJECT_DIR

        css = (PROJECT_DIR / "frontend" / "nyx-pulse" / "src" / "theme.css").read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return {}
    tokens: Dict[str, str] = {}
    for name, value in re.findall(r"--([a-z0-9-]+):\s*([^;]+);", css):
        if name.startswith(("color-", "radius", "font", "space")) and len(tokens) < 40:
            tokens[name] = value.strip()[:60]
    return tokens


def other_tabs(exclude: Optional[str] = None, limit: int = 12) -> List[Dict[str, Any]]:
    """The tabs that already exist, so a new one can match the family or break from it on purpose."""
    out: List[Dict[str, Any]] = []
    try:
        import dynamic_tabs

        store = getattr(dynamic_tabs, "TAB_STORE", None)
        tabs = store.list_tabs() if store is not None else []
    except Exception:  # noqa: BLE001 - looking at the other tabs is a nicety
        tabs = []
    for tab in tabs:
        if exclude and str(tab.get("id")) == exclude:
            continue
        theme = tab.get("theme") or {}
        out.append({"id": tab.get("id"), "title": tab.get("title"), "accent": tab.get("accent"),
                    "surface": theme.get("surface"), "font": theme.get("font"),
                    "blocks": [b.get("type") for b in (tab.get("blocks") or [])][:8]})
        if len(out) >= limit:
            break
    return out


def apple_guidance(request: str, limit: int = 3) -> List[Dict[str, str]]:
    """The Apple pages that bear on this request, from the library shipped with Nyx."""
    try:
        from connectors.apple_design_connector import AppleDesignConnector

        connector = AppleDesignConnector()
        if not connector.is_available():
            return []
        hits = connector.lookup(request)[:limit]
    except Exception:  # noqa: BLE001
        return []
    out = []
    for hit in hits:
        name = str(hit.get("file") or hit.get("topic") or "")
        try:
            page = AppleDesignConnector().read_guideline(name)
            body = str(page.get("text") or page.get("content") or "")
        except Exception:  # noqa: BLE001
            body = str(hit.get("excerpt") or "")
        out.append({"topic": name, "text": body[:1200]})
    return out


def _research(request: str, limit: int = 4) -> List[Dict[str, str]]:
    """References from the web — the owner asked for the permissions to look."""
    try:
        from tools import TOOL_REGISTRY

        result = TOOL_REGISTRY.call_tool(
            "search_web", query=f"{request} interface design examples 2026", engine="all", freshness="year")
    except Exception as error:  # noqa: BLE001 - no internet is not an error here
        return [{"title": "No web references", "note": str(error)[:120]}]
    text = str(result)[:4000]
    found = []
    for line in text.splitlines():
        match = re.search(r"https?://\S+", line)
        if match and len(found) < limit:
            found.append({"title": line[:120].strip(), "url": match.group(0)[:200]})
    return found


# ---------------------------------------------------------------------------
# The brief
# ---------------------------------------------------------------------------


def _model_brief(request: str, context: str) -> Dict[str, Any]:
    """Ask the design model to make the decisions. Returns {} when no model answers."""
    from model_roles import MODEL_ROLES

    prompt = (
        "You are deciding how something should look and work. Do not describe a generic interface, and do not "
        "reuse a layout you have produced before — decide for THIS request, from its content.\n\n"
        f"The request:\n\"\"\"\n{request[:4000]}\n\"\"\"\n\n{context[:12000]}\n\n"
        "Reply with JSON only:\n"
        '{"intent": "what this is for, in one sentence", "audience": "who uses it and how often", '
        '"mood": ["three or four words it should feel like"], '
        '"assumptions": ["what you decided for them, and why, one line each"], '
        '"directions": [{"name": "…", "idea": "the one-line premise", "why_not": "what it costs"}], '
        '"chosen": {"name": "…", "because": "why this one for this person and this content"}, '
        '"tokens": {"palette": [{"role": "background|surface|text|accent|…", "value": "#hex", "note": "…"}], '
        '"type": "the typeface choice and the scale", "spacing": "the scale and the base unit", '
        '"radius": "…", "motion": "what moves, how long, and why", "surface": "flat|glass|layered"}, '
        '"layout": "what is where, in reading order, and what happens at a narrow width", '
        '"components": ["each piece on screen, in order of importance"], '
        '"states": {"empty": "…", "loading": "…", "error": "…", "a_lot_of_data": "…"}, '
        '"accessibility": ["contrast, focus, motion, hit sizes — the specific numbers you used"], '
        '"avoid": ["what you deliberately did not do here, and why"]}\n'
        "Two or three directions, genuinely different from each other. Every colour is a real hex value."
    )
    run = MODEL_ROLES.run("code_generation", prompt, max_tokens=2000)
    text = (run.text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        from tools import _loads_lenient

        data = _loads_lenient(text[start:end + 1])
    except Exception:  # noqa: BLE001
        try:
            data = json.loads(text[start:end + 1])
        except ValueError:
            return {}
    if isinstance(data, dict):
        data["model"] = run.label
        return data
    return {}


def _context_for(request: str, tab_id: Optional[str], sources: Optional[Sequence[Dict[str, Any]]],
                 research: bool) -> Dict[str, Any]:
    profile = taste()
    gathered = {
        "past_requests": profile["asked_for"],
        "kept": profile["kept"],
        "undone": profile["undone"],
        "app_tokens": profile["tokens"],
        "other_tabs": other_tabs(exclude=tab_id),
        "apple": apple_guidance(request),
        "references": _research(request) if research else [],
        "given": [{"kind": str(s.get("kind", "note")), "value": str(s.get("value", ""))[:300],
                   "label": str(s.get("label", ""))[:80]} for s in (sources or [])][:10],
    }
    return gathered


def _as_text(gathered: Dict[str, Any]) -> str:
    """The gathered context as the model reads it."""
    lines: List[str] = []
    if gathered["past_requests"]:
        lines.append("What this person has asked for about looks, in their own words:")
        lines += [f"- {line}" for line in gathered["past_requests"]]
    if gathered["kept"]:
        lines.append("\nDesign decisions they kept: " + "; ".join(gathered["kept"][:8]))
    if gathered["undone"]:
        lines.append("Decisions they undid (do not repeat these): " + "; ".join(gathered["undone"][:6]))
    if gathered["app_tokens"]:
        tokens = ", ".join(f"{k}={v}" for k, v in list(gathered["app_tokens"].items())[:14])
        lines.append(f"\nThe app this lives in is built from: {tokens}")
    if gathered["other_tabs"]:
        lines.append("Their other tabs: " + "; ".join(
            f"{t['title']} (accent {t.get('accent')}, {t.get('surface') or 'default'} surface)" for t in gathered["other_tabs"][:8]))
    if gathered["given"]:
        lines.append("\nWhat they gave you to look at: " + "; ".join(
            f"{g['label'] or g['kind']}: {g['value']}" for g in gathered["given"]))
    if gathered["apple"]:
        lines.append("\nApple's guidance that bears on this:")
        for page in gathered["apple"]:
            lines.append(f"- {page['topic']}: {page['text'][:400]}")
    if gathered["references"]:
        lines.append("\nReferences found on the web: " + "; ".join(
            f"{r.get('title', '')} {r.get('url', '')}".strip() for r in gathered["references"][:4]))

    lines.append("\nHow to read a request like this:")
    lines += [f"- {rule}" for rule in READING_A_PROMPT]
    lines.append("\nPractice worth following:")
    for group in ("apple", "craft", "industry", "how_ui_updates"):
        lines += [f"- {rule}" for rule in PRINCIPLES[group][:5]]
    lines.append("\nThere is no default design here. In particular, avoid: " + "; ".join(AVOID_BY_DEFAULT))
    return "\n".join(lines)


def build_brief(request: str, *, tab_id: Optional[str] = None, images: Optional[Sequence[str]] = None,
                sources: Optional[Sequence[Dict[str, Any]]] = None, research: bool = True,
                use_model: bool = True) -> Dict[str, Any]:
    """Everything needed to design this thing on purpose rather than by habit.

    Never raises: with no model and no internet it still returns the owner's
    taste, the surrounding tabs, the principles and the "avoid" list, which is
    most of what stops a generic result.
    """
    request = (request or "").strip()
    gathered = _context_for(request, tab_id, sources, research)
    if images:
        gathered["given"] = list(gathered["given"]) + [
            {"kind": "image", "value": str(uid), "label": "picture to read for layout"} for uid in list(images)[:6]]

    brief: Dict[str, Any] = {
        "request": request[:2000],
        "taste": {k: gathered[k] for k in ("past_requests", "kept", "undone")},
        "app_tokens": gathered["app_tokens"],
        "other_tabs": gathered["other_tabs"],
        "references": gathered["references"],
        "apple": [page["topic"] for page in gathered["apple"]],
        "principles": PRINCIPLES,
        "reading": READING_A_PROMPT,
        "avoid": list(AVOID_BY_DEFAULT),
        "model": "",
    }
    if use_model and request:
        try:
            decided = _model_brief(request, _as_text(gathered))
        except Exception as error:  # noqa: BLE001 - a brief without the model is still a brief
            decided = {}
            brief["model_error"] = f"{type(error).__name__}: {error}"[:200]
        if decided:
            avoid = list(decided.get("avoid") or [])
            brief.update({k: v for k, v in decided.items() if k != "avoid"})
            brief["avoid"] = avoid + [item for item in AVOID_BY_DEFAULT if item not in avoid]
    brief["text"] = as_prompt(brief)
    return brief


def as_prompt(brief: Dict[str, Any]) -> str:
    """The brief as text to put in front of whatever writes the actual UI."""
    lines = ["[Design brief — decide for this request, not from habit]"]
    if brief.get("intent"):
        lines.append(f"What it is for: {brief['intent']}")
    if brief.get("audience"):
        lines.append(f"Who uses it: {brief['audience']}")
    if brief.get("mood"):
        lines.append("It should feel: " + ", ".join(str(word) for word in brief["mood"][:6]))
    chosen = brief.get("chosen") or {}
    if chosen:
        lines.append(f"Direction: {chosen.get('name', '')} — {chosen.get('because', '')}")
    tokens = brief.get("tokens") or {}
    if tokens:
        palette = ", ".join(f"{p.get('role')} {p.get('value')}" for p in (tokens.get("palette") or [])[:8]
                            if isinstance(p, dict))
        parts = [f"palette: {palette}" if palette else "", f"type: {tokens.get('type', '')}",
                 f"spacing: {tokens.get('spacing', '')}", f"radius: {tokens.get('radius', '')}",
                 f"motion: {tokens.get('motion', '')}", f"surface: {tokens.get('surface', '')}"]
        lines.append("Tokens — " + "; ".join(part for part in parts if part.strip(": ")))
    if brief.get("layout"):
        lines.append(f"Layout: {brief['layout']}")
    if brief.get("components"):
        lines.append("On screen, in order: " + "; ".join(str(c) for c in brief["components"][:10]))
    states = brief.get("states") or {}
    if states:
        lines.append("States — " + "; ".join(f"{k}: {v}" for k, v in list(states.items())[:5]))
    if brief.get("accessibility"):
        lines.append("Accessibility: " + "; ".join(str(a) for a in brief["accessibility"][:5]))
    if brief.get("assumptions"):
        lines.append("Assumed (say these in the answer): " + "; ".join(str(a) for a in brief["assumptions"][:5]))
    taste_part = brief.get("taste") or {}
    if taste_part.get("undone"):
        lines.append("They undid before: " + "; ".join(taste_part["undone"][:4]))
    lines.append("Avoid: " + "; ".join(str(a) for a in (brief.get("avoid") or [])[:8]))
    if not brief.get("intent"):
        # No model answered: give the writer the method instead of a half brief.
        lines.append("No model was reachable for this brief. Decide it yourself, out loud, in this order: "
                     + " ".join(READING_A_PROMPT[:4]))
    return "\n".join(lines)


def brief_for_prompt(text: str, tab_id: Optional[str] = None, *, use_model: bool = True) -> str:
    """One line for callers that just want the brief as text. Never raises."""
    try:
        return build_brief(text, tab_id=tab_id, research=False, use_model=use_model)["text"]
    except Exception:  # noqa: BLE001 - a design must never fail because of its brief
        return "[Design brief] Decide for this request rather than from habit. " + " ".join(READING_A_PROMPT[:3])


# ---------------------------------------------------------------------------
# In chat
# ---------------------------------------------------------------------------


def tool_design_brief(request: str, tab_id: str = "", research: bool = True) -> str:
    """Nyx asking itself how something should look before it builds it."""
    brief = build_brief(request, tab_id=tab_id or None, research=research)
    extra = []
    if brief.get("directions"):
        extra.append("Other directions considered: " + "; ".join(
            f"{d.get('name')} ({d.get('idea')})" for d in brief["directions"][:3] if isinstance(d, dict)))
    if brief.get("model"):
        extra.append(f"(decided with {brief['model']})")
    return brief["text"] + ("\n" + "\n".join(extra) if extra else "")


def tool_design_decision(summary: str, verdict: str = "applied", kind: str = "ui") -> str:
    """Remember how a design decision went, so the next brief knows this owner's taste."""
    entry = record_decision(kind, summary, verdict=verdict)
    return f"Noted: {entry['summary']} ({entry['verdict']}). Future design briefs will take this into account."


def register_design_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        "design_brief",
        "Before designing or restyling anything on screen (a tab, a page, a panel), decide how it should look for "
        "THIS request: reads the owner's past UI decisions, their other tabs, Apple's guidance and the web, and "
        "returns the direction, tokens, layout and what to avoid. There is no default design to fall back on.",
        [ToolParam("request", "string", "What is being designed, in the owner's words"),
         ToolParam("tab_id", "string", "The tab being redesigned, if it exists already", required=False),
         ToolParam("research", "boolean", "Look for references on the web too (default true)", required=False)],
        tool_design_brief, category="general", label=lambda a: "Deciding how it should look",
    )
    registry.register(
        "design_decision",
        "Record a design decision and how it went: applied, undone, liked or disliked. An undone one is the most "
        "useful thing to remember.",
        [ToolParam("summary", "string", "What was decided, in one line"),
         ToolParam("verdict", "string", "applied | undone | liked | disliked", required=False,
                   enum_values=["applied", "undone", "liked", "disliked"]),
         ToolParam("kind", "string", "What it was about (tab, page, theme…)", required=False)],
        tool_design_decision, category="general", label=lambda a: "Remembering a design decision",
    )
