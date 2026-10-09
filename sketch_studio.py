"""The Create tab's drawing studio (UPDATE_IDEAS U2): the owner draws, Nyx draws with them, Nyx "scans" the drawing
to make it better, and a bar says what Nyx should draw.

The owner: *"add create tab for images where the user can draw and the AI helps and can scan to make the image
better with a bar for what the user wants the AI to draw."*

How each part works, and why:

* **Nyx draws** — a model answers with *shapes as data* (lines, curves, rectangles, ellipses, polygons, text, each
  with colour and width) on a fixed 1000 × 700 canvas. ``clean_shapes`` checks every one; the page draws them as
  a layer the owner can keep drawing over or undo. Data, never code (invariant 2) — and it works with any text
  model, including the local one, because no image model is needed for it.
* **Scan** — the drawing goes to the vision role (``image_check``; the local Ollama model when that is the one set)
  which says what it sees, what would make it better, and returns those improvements as shapes too.
* **Make it a picture** — the image role (``image_gen``) paints a finished picture from what the scan saw plus the
  owner's words. That one goes to an online image model, so the page says so before it is used.

Drawings are saved as PNGs in ``sketches/`` (account-scoped, git-ignored).
"""

from __future__ import annotations

import base64
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from paths import data_path

WIDTH, HEIGHT = 1000, 700
MAX_SHAPES = 300
MAX_POINTS = 120
KINDS = ("line", "path", "rect", "ellipse", "polygon", "text")
_COLOUR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_NAMED = {"black": "#111111", "white": "#ffffff", "red": "#e5484d", "orange": "#f76b15", "yellow": "#ffd60a",
          "green": "#30a46c", "blue": "#3e63dd", "purple": "#8e4ec6", "pink": "#e93d82", "brown": "#8d5b3a",
          "grey": "#8b8d98", "gray": "#8b8d98", "sky": "#7ce2fe", "teal": "#12a594", "none": ""}
MAX_SKETCH_BYTES = 6 * 1024 * 1024

FORMAT = f"""Answer with JSON only: {{"say": "one short sentence about what you drew", "shapes": [...]}}.
The canvas is {WIDTH} wide and {HEIGHT} tall; (0,0) is the top-left corner. Each shape is one of:
  {{"kind": "line", "points": [[x,y],[x,y]], "stroke": "#hex", "width": 4}}
  {{"kind": "path", "points": [[x,y], ... up to {MAX_POINTS}], "stroke": "#hex", "width": 3, "fill": "#hex or none", "smooth": true}}
  {{"kind": "rect", "x": 0, "y": 0, "w": 100, "h": 50, "stroke": "#hex", "fill": "#hex or none", "width": 2, "radius": 8}}
  {{"kind": "ellipse", "cx": 500, "cy": 350, "rx": 80, "ry": 60, "stroke": "#hex", "fill": "#hex or none", "width": 2}}
  {{"kind": "polygon", "points": [[x,y],[x,y],[x,y]], "stroke": "#hex", "fill": "#hex or none", "width": 2}}
  {{"kind": "text", "x": 100, "y": 100, "text": "words", "size": 28, "fill": "#hex"}}
Draw back to front (sky and ground first, details last). Use clear colours and enough shapes to be recognisable:
a simple object needs 5-20 shapes, a scene 20-80. At most {MAX_SHAPES} shapes."""


class SketchError(RuntimeError):
    """Something the owner can act on."""


# ---------------------------------------------------------------------------
# Shapes are data: every one is checked
# ---------------------------------------------------------------------------


def _num(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return round(max(low, min(high, number)), 1)


def _colour(value: Any, default: str = "") -> str:
    text = str(value or "").strip().lower()
    if text in _NAMED:
        return _NAMED[text]
    return text if _COLOUR.match(text) else default


def _points(value: Any) -> List[List[float]]:
    out: List[List[float]] = []
    for pair in (value or [])[:MAX_POINTS] if isinstance(value, list) else []:
        if isinstance(pair, (list, tuple)) and len(pair) >= 2:
            out.append([_num(pair[0], -50, WIDTH + 50, 0), _num(pair[1], -50, HEIGHT + 50, 0)])
        elif isinstance(pair, dict):
            out.append([_num(pair.get("x"), -50, WIDTH + 50, 0), _num(pair.get("y"), -50, HEIGHT + 50, 0)])
    return out


def clean_shapes(raw: Any) -> List[Dict[str, Any]]:
    """Keep only shapes the page knows how to draw, with every number and colour in range. Never raises."""
    shapes: List[Dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or len(shapes) >= MAX_SHAPES:
            continue
        kind = str(item.get("kind") or item.get("type") or "").lower()
        stroke = _colour(item.get("stroke") or item.get("color"), "#111111")
        fill = _colour(item.get("fill"), "")
        width = _num(item.get("width") or item.get("stroke_width"), 0.5, 40, 3)
        if kind in ("line", "path", "polygon"):
            points = _points(item.get("points"))
            if len(points) < 2 or (kind == "polygon" and len(points) < 3):
                continue
            shape: Dict[str, Any] = {"kind": kind, "points": points, "stroke": stroke, "width": width}
            if kind != "line":
                shape["fill"] = fill
            if kind == "path":
                shape["smooth"] = bool(item.get("smooth", True))
        elif kind == "rect":
            shape = {"kind": "rect", "x": _num(item.get("x"), -50, WIDTH, 0), "y": _num(item.get("y"), -50, HEIGHT, 0),
                     "w": _num(item.get("w") or item.get("width_px"), 1, WIDTH + 100, 50),
                     "h": _num(item.get("h") or item.get("height"), 1, HEIGHT + 100, 50),
                     "stroke": stroke, "fill": fill, "width": width, "radius": _num(item.get("radius"), 0, 200, 0)}
        elif kind in ("ellipse", "circle"):
            r = item.get("r")
            shape = {"kind": "ellipse", "cx": _num(item.get("cx"), -50, WIDTH + 50, WIDTH / 2),
                     "cy": _num(item.get("cy"), -50, HEIGHT + 50, HEIGHT / 2),
                     "rx": _num(item.get("rx", r), 1, WIDTH, 40), "ry": _num(item.get("ry", r), 1, HEIGHT, 40),
                     "stroke": stroke, "fill": fill, "width": width}
        elif kind == "text":
            words = str(item.get("text") or "").strip()[:80]
            if not words:
                continue
            shape = {"kind": "text", "x": _num(item.get("x"), 0, WIDTH, 20), "y": _num(item.get("y"), 0, HEIGHT, 40),
                     "text": words, "size": _num(item.get("size"), 8, 160, 28),
                     "fill": _colour(item.get("fill") or item.get("color"), "#111111")}
        else:
            continue
        shapes.append(shape)
    return shapes


def _json_from(text: str) -> Optional[Dict[str, Any]]:
    """The first JSON object in a model's answer, fenced or not."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = [fenced.group(1)] if fenced else []
    start = text.find("{")
    if start >= 0:
        candidates.append(text[start:text.rfind("}") + 1])
    for chunk in candidates:
        try:
            data = json.loads(chunk)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return None


# ---------------------------------------------------------------------------
# The three helpers
# ---------------------------------------------------------------------------


def _roles() -> Any:
    from model_roles import MODEL_ROLES

    return MODEL_ROLES


def draw(request: str, *, existing: str = "") -> Dict[str, Any]:
    """Nyx draws what the bar asks for, as shapes the page adds as a new layer."""
    ask = (request or "").strip()
    if not ask:
        raise SketchError("Say what Nyx should draw.")
    context = f"\nWhat is on the canvas already: {existing[:600]}\nDraw so it fits with that." if existing else ""
    run = _roles().run("code_generation", f"Draw this: {ask[:600]}{context}\n\n{FORMAT}",
                       system="You are a careful illustrator who draws with simple vector shapes. JSON only.",
                       max_tokens=3500)
    data = _json_from(run.text) or {}
    shapes = clean_shapes(data.get("shapes"))
    if not shapes:
        raise SketchError(f"{run.label or 'The model'} did not send back anything drawable. Try again or say it "
                          "more simply.")
    return {"shapes": shapes, "say": str(data.get("say") or "")[:240], "model": run.label}


def _decode(data_url: str) -> Tuple[bytes, str]:
    match = re.match(r"^data:(image/(?:png|jpeg|webp));base64,(.+)$", (data_url or "").strip(), re.S)
    if not match:
        raise SketchError("The drawing did not arrive as a picture.")
    raw = base64.b64decode(match.group(2), validate=False)
    if len(raw) > MAX_SKETCH_BYTES:
        raise SketchError("The drawing is too large to send.")
    return raw, match.group(1)


def scan(image: str, request: str = "") -> Dict[str, Any]:
    """Look at the drawing: what it is, what would make it better, and those improvements as shapes."""
    picture, mime = _decode(image)
    goal = f"The owner wants: {request.strip()[:400]}\n" if (request or "").strip() else ""
    prompt = (f"{goal}This is a drawing on a {WIDTH}x{HEIGHT} canvas. Say in one sentence what it shows, give up "
              "to three short suggestions that would make it better, then add those improvements as new shapes "
              "drawn on top (outlines, shading, missing parts, a background) — never redraw what is there. "
              'JSON only: {"sees": "...", "suggestions": ["..."], "shapes": [...]}. Shape format:\n' + FORMAT)
    run = _roles().run("image_check", prompt, images=[(picture, mime)], max_tokens=3000)
    data = _json_from(run.text) or {}
    sees = str(data.get("sees") or "").strip()[:300] or run.text.strip()[:300]
    suggestions = [str(s)[:200] for s in (data.get("suggestions") or []) if str(s).strip()][:3]
    return {"sees": sees, "suggestions": suggestions, "shapes": clean_shapes(data.get("shapes")), "model": run.label}


def render(request: str, sees: str = "") -> Dict[str, Any]:
    """A finished picture from the sketch's description and the owner's words (an online image model)."""
    import image_gen

    words = ", ".join(part for part in ((request or "").strip(), (sees or "").strip()) if part)
    if not words:
        raise SketchError("Scan the drawing or say what the picture should be first.")
    result = image_gen.generate_image(f"A finished illustration of: {words[:900]}")
    if not result.ok:
        raise SketchError(result.error or "No picture came back.")
    try:
        raw = Path(result.file_path).read_bytes()
    except OSError as error:
        raise SketchError(f"The picture was made but could not be read back: {error}") from error
    mime = "image/jpeg" if raw[:3] == bytes((0xFF, 0xD8, 0xFF)) else "image/png"
    return {"image": f"data:{mime};base64," + base64.b64encode(raw).decode("ascii"),
            "model": result.label or result.provider}


# ---------------------------------------------------------------------------
# Saved drawings
# ---------------------------------------------------------------------------


def _folder():
    folder = data_path("sketches")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def save(image: str, name: str = "") -> Dict[str, Any]:
    picture, mime = _decode(image)
    if mime != "image/png":
        raise SketchError("Drawings are saved as PNG.")
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "drawing").lower()).strip("-")[:40] or "drawing"
    sketch_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{slug}-{uuid.uuid4().hex[:4]}"
    (_folder() / f"{sketch_id}.png").write_bytes(picture)
    return {"id": sketch_id, "name": name or "Drawing"}


def sketches(limit: int = 60) -> List[Dict[str, Any]]:
    files = sorted(_folder().glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    return [{"id": p.stem, "name": p.stem.split("-", 2)[-1].rsplit("-", 1)[0].replace("-", " ") or "Drawing",
             "saved": p.stat().st_mtime, "bytes": p.stat().st_size} for p in files]


def load(sketch_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", sketch_id or ""):
        raise SketchError("No such drawing.")
    target = _folder() / f"{sketch_id}.png"
    if not target.is_file():
        raise SketchError("No such drawing.")
    return "data:image/png;base64," + base64.b64encode(target.read_bytes()).decode("ascii")
