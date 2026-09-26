"""Custom backgrounds: your GIF, video or picture — or one Nyx makes — with motion (Request G8).

The owner: "allow to check background for users such as Loki God of time
background with animations done by AI or from a gif."

A background is data (invariant 2): which upload to show, a named motion
preset, and how much to dim it so text stays readable. GIFs and videos move on
their own; a still picture gets a preset —

* ``drift``  — a slow pan and zoom across the picture
* ``breathe`` — a gentle swell of scale and light
* ``parallax`` — follows the pointer a little
* ``embers`` — glowing particles rising over it
* ``time`` — rotating clock rings and ticking marks (made for "god of time")
* ``still`` — no motion

When Nyx makes one it writes a wallpaper prompt, generates the picture with the
image model, and picks the motion that fits the words. Reduced Motion always wins
in the browser.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from paths import atomic_replace, data_path

ANIMATIONS = ("still", "drift", "breathe", "parallax", "embers", "time")
_LOCK = threading.Lock()

_MOTION_WORDS = [
    ("time", r"\b(time|clock|chrono|hourglass|loki|tva|eternity|temporal|timeline)\b"),
    ("embers", r"\b(fire|ember|flame|lava|spark|phoenix|forge|inferno|magic|sorcer)\b"),
    ("parallax", r"\b(space|galaxy|stars?|nebula|city|skyline|mountains?|forest|depth)\b"),
    ("breathe", r"\b(ocean|calm|zen|aurora|glow|soft|dream|mist|fog|underwater)\b"),
]


def _path():
    return data_path("backgrounds.json")


def _read() -> Dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"active": None, "items": []}


def _write(data: Dict[str, Any]) -> None:
    temp = _path().with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    atomic_replace(temp, _path())


def pick_animation(prompt: str) -> str:
    """The motion that fits the words, or a slow drift."""
    for name, pattern in _MOTION_WORDS:
        if re.search(pattern, prompt or "", re.I):
            return name
    return "drift"


def _kind_for(mime: str) -> str:
    mime = (mime or "").lower()
    if mime == "image/gif":
        return "gif"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("image/"):
        return "image"
    raise ValueError("A background must be a picture, a GIF, or an MP4/WebM video.")


def _clean_look(dim: Any = None, blur: Any = None, animation: Any = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if dim is not None:
        out["dim"] = round(min(0.9, max(0.0, float(dim))), 2)
    if blur is not None:
        out["blur"] = int(min(24, max(0, float(blur))))
    if animation is not None:
        if animation not in ANIMATIONS:
            raise ValueError(f"Motion must be one of: {', '.join(ANIMATIONS)}.")
        out["animation"] = animation
    return out


def public(item: Dict[str, Any]) -> Dict[str, Any]:
    return {**item, "url": f"/api/uploads/{item['upload_id']}"}


def state() -> Dict[str, Any]:
    with _LOCK:
        data = _read()
    active = next((i for i in data["items"] if i["id"] == data.get("active")), None)
    return {"active": public(active) if active else None, "items": [public(i) for i in data["items"]],
            "animations": list(ANIMATIONS)}


def add(upload_id: str, name: str = "", animation: str = "", dim: float = 0.55, prompt: str = "",
        activate: bool = True, source: str = "upload") -> Dict[str, Any]:
    import uploads

    record = uploads.get_upload(upload_id)
    if record is None:
        raise ValueError("That upload no longer exists — add the file again.")
    kind = _kind_for(record.get("mime", ""))
    look = _clean_look(dim=dim, blur=0, animation=animation or ("still" if kind in ("gif", "video") else pick_animation(prompt or name)))
    item = {"id": uuid.uuid4().hex[:10], "upload_id": upload_id, "name": (name or record.get("name") or "Background")[:80],
            "kind": kind, "prompt": prompt[:500], "source": source, "created_at": time.time(), **look}
    with _LOCK:
        data = _read()
        data["items"] = [item] + data["items"][:39]
        if activate:
            data["active"] = item["id"]
        _write(data)
    _announce()
    return public(item)


def update(background_id: str, **changes: Any) -> Dict[str, Any]:
    look = _clean_look(changes.get("dim"), changes.get("blur"), changes.get("animation"))
    with _LOCK:
        data = _read()
        item = next((i for i in data["items"] if i["id"] == background_id), None)
        if item is None:
            raise KeyError("No such background.")
        item.update(look)
        if changes.get("name"):
            item["name"] = str(changes["name"])[:80]
        _write(data)
    _announce()
    return public(item)


def activate(background_id: Optional[str]) -> Dict[str, Any]:
    with _LOCK:
        data = _read()
        if background_id and not any(i["id"] == background_id for i in data["items"]):
            raise KeyError("No such background.")
        data["active"] = background_id or None
        _write(data)
    _announce()
    return state()


def remove(background_id: str) -> bool:
    with _LOCK:
        data = _read()
        before = len(data["items"])
        data["items"] = [i for i in data["items"] if i["id"] != background_id]
        if data.get("active") == background_id:
            data["active"] = None
        _write(data)
    _announce()
    return len(data["items"]) < before


def wallpaper_prompt(idea: str) -> str:
    """Turn "Loki god of time" into a prompt that makes a good screen background."""
    return (f"{idea.strip()}. Cinematic desktop wallpaper, wide 16:9 composition, dark and moody with deep blacks, "
            "rich detail, soft volumetric light, the subject off-centre so the middle stays calm for text, no words, no logos.")


def generate(idea: str, animation: str = "", dim: float = 0.55, activate_it: bool = True) -> Dict[str, Any]:
    """Make a background with the image model and use it. Raises ValueError with the model's reason."""
    from image_gen import generate_image

    if not (idea or "").strip():
        raise ValueError("Describe the background you want, e.g. “Loki, god of time, in the TVA”.")
    result = generate_image(wallpaper_prompt(idea), size="1792x1024")
    if not result.ok:
        result = generate_image(wallpaper_prompt(idea), size="1024x1024")
    if not result.ok:
        raise ValueError(f"The image model could not make it: {result.error}")
    item = add(result.image_id, name=idea.strip()[:60], animation=animation or pick_animation(idea), dim=dim,
               prompt=idea, activate=activate_it, source=f"generated · {result.label}")
    item["model"] = result.label
    return item


def _announce() -> None:
    try:
        from agent_events import publish_ui

        publish_ui("background.changed", **{"active": state()["active"]})
    except Exception:  # pragma: no cover - the page also re-reads on focus
        pass


def tool_set_background(description: str = "", animation: str = "", dim: float = 0.55, clear: bool = False) -> str:
    """The set_background tool: make and apply a background from words, or clear it."""
    if clear:
        activate(None)
        return "Background cleared — back to plain black."
    try:
        item = generate(description, animation=animation, dim=dim)
    except ValueError as error:
        return f"Error: {error}"
    return (f"Made and applied a background: “{item['name']}” with the {item['animation']} motion "
            f"({item.get('model', 'image model')}). The owner can change the motion or dimming in Settings → Background.")


def register_background_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        "set_background",
        "Make a custom animated background for Nyx from a description (e.g. 'Loki god of time') and apply it, "
        "or clear it. Motion presets: " + ", ".join(ANIMATIONS) + " (picked from the words when not given).",
        [ToolParam("description", "string", "What the background should show", required=False),
         ToolParam("animation", "string", "Motion preset", required=False, enum_values=list(ANIMATIONS)),
         ToolParam("dim", "number", "0–0.9, how much to darken it for readability (default 0.55)", required=False),
         ToolParam("clear", "boolean", "Remove the custom background", required=False)],
        tool_set_background,
        category="general",
        label=lambda a: "Clearing the background" if a.get("clear") else f"Making a background: {str(a.get('description', ''))[:40]}",
    )
