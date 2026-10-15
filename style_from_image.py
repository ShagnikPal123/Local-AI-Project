"""Style from an image (owner, 2026-10-15: "the user can input an image and the ai sees and tries to rearrange and
rewrite for that").

The Appearance page reads the colours out of the picture itself (fast, offline). This module adds what only a model
that can see can tell: which colour is the page, which the panels, which the accent, how round the corners are, how
dense the layout is and where the navigation sits. The answer is cleaned into a small, safe "look" that the page
previews and the owner keeps or undoes. Nothing here changes files or code; the result is only ever CSS values.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
NAV = {"left", "right", "top", "bottom"}
DENSITY = {"compact", "comfortable", "spacious"}
COLOUR_KEYS = ("background", "sidebar", "panel", "text", "muted", "accent")

PROMPT = (
    "This is a picture of an app or website the user likes. Read its visual style so another app can copy it.\n"
    "Reply with JSON only, no prose:\n"
    '{"background": "#rrggbb", "sidebar": "#rrggbb", "panel": "#rrggbb", "text": "#rrggbb", "muted": "#rrggbb", '
    '"accent": "#rrggbb", "radius": 0-24, "density": "compact|comfortable|spacious", "nav": "left|right|top|bottom", '
    '"dark": true|false, "name": "two or three words naming the look", "notes": "one sentence on the layout"}\n'
    "background is the main page, sidebar the navigation column or bar, panel the cards or boxes, accent the one "
    "colour used for buttons and highlights. radius is the corner rounding of cards in pixels."
)


def _json_from(text: str) -> Dict[str, Any]:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def clean_look(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only values that are safe to put into CSS: six-digit colours, a bounded radius, known words."""
    look: Dict[str, Any] = {}
    for key in COLOUR_KEYS:
        value = str(raw.get(key) or "").strip()
        if HEX.match(value):
            look[key] = value.lower()
    try:
        radius = int(round(float(raw.get("radius"))))
        look["radius"] = max(0, min(24, radius))
    except (TypeError, ValueError):
        pass
    density = str(raw.get("density") or "").lower()
    if density in DENSITY:
        look["density"] = density
    nav = str(raw.get("nav") or "").lower()
    if nav in NAV:
        look["nav"] = nav
    if isinstance(raw.get("dark"), bool):
        look["dark"] = raw["dark"]
    name = re.sub(r"[^\w\s'-]", "", str(raw.get("name") or "")).strip()[:40]
    if name:
        look["name"] = name
    notes = str(raw.get("notes") or "").strip()[:240]
    if notes:
        look["notes"] = notes
    return look


def read_style(image: bytes, mime: str) -> Dict[str, Any]:
    """Ask a model that can see for the image's style. Raises vision.VisionUnavailable when none is set up."""
    import vision

    answer = vision._ask(image, mime or "image/png", PROMPT, role="image_check")
    return clean_look(_json_from(answer))
