"""Screen Share (Request R10): Nyx looks at your screen and helps, at your pace, with limited control.

The owner's words: "Another tab will be screen share so it views a persons screen and can help them using its cursor
and typing. It works with the user and at its pace. This will mainly us ollama … Don't allow it to have too mc control
and instead just work properly."

What "limited control" means, enforced here and not only in the page:

* Nothing is seen until the owner presses Start Sharing, and then only what they picked: one screen or one window.
  Frames are kept in memory only, never written to disk. Sharing stops by itself after 15 minutes without the page
  asking for a frame, and the page stops it when the owner leaves the tab.
* Nyx never acts on its own. An answer carries at most ONE proposed step; it runs only when the owner presses a button
  for it, it expires after two minutes, and there is no "keep going" mode.
* Pace "Show Me" (the default) is point-only: Nyx moves its own purple cursor to show where and hands over any text or
  keys for the owner to use. The owner's mouse and keyboard are never touched. Pace "Ask First" lets one approved
  step click, type, press keys or scroll.
* Typing is capped at 2,000 characters and refused for anything that looks like a password, card, PIN or code. Keys
  come from a short list (Enter, Tab, arrows, Ctrl+C/V/X/Z/Y/A/S/F …): no Win key, no Alt+F4, no Ctrl+Alt.
  Steps that look irreversible (delete, send, pay, buy, submit …) are marked so the owner looks twice.
* The usual stops still work while a step runs: mouse into the top-left corner, Esc three times, or Stop.
* Local first: the screenshot goes to a vision model in Ollama on this PC. Only when there is none, and only after the
  owner allows it for this session, does it go to the online model assigned to "Finding things on screen".
"""

from __future__ import annotations

import io
import logging
import re
import threading
import time
import uuid
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple

_LOG = logging.getLogger("nyx.screen_share")

IDLE_STOP_SECONDS = 15 * 60
STEP_TTL_SECONDS = 120.0
MAX_TYPE = 2000
MAX_HISTORY = 40
FRAME_WIDTH = 1280
LOOK_WIDTH = 1600
PACES = ("show", "ask")
KINDS = ("point", "click", "double_click", "type", "keys", "scroll")

#: The only key presses Nyx makes for the owner, and only after they press Do It. Anything else they press themselves.
#: Ctrl+Enter is left out on purpose: in mail and chat apps it sends.
ALLOWED_KEYS = frozenset({
    "enter", "shift+enter", "alt+enter", "tab", "shift+tab", "esc", "backspace", "delete", "space",
    "up", "down", "left", "right", "home", "end", "pageup", "pagedown", "f2",
    "ctrl+a", "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z", "ctrl+y", "ctrl+s", "ctrl+f", "ctrl+b", "ctrl+i", "ctrl+u",
    "ctrl+home", "ctrl+end", "ctrl+left", "ctrl+right", "shift+up", "shift+down", "shift+left", "shift+right",
    "shift+home", "shift+end", "ctrl+shift+left", "ctrl+shift+right",
})
_KEY_ALIASES = {"control": "ctrl", "cmd": "ctrl", "command": "ctrl", "return": "enter", "escape": "esc", "del": "delete",
                "pgup": "pageup", "pgdn": "pagedown", "page up": "pageup", "page down": "pagedown", "spacebar": "space",
                "arrowup": "up", "arrowdown": "down", "arrowleft": "left", "arrowright": "right", "up arrow": "up",
                "down arrow": "down", "left arrow": "left", "right arrow": "right", "bksp": "backspace"}

#: A field Nyx will not type into, by what the model called it.
SENSITIVE = re.compile(
    r"(?i)\b(pass(word|code|phrase)?s?|pins?|cvv|cvc|security code|card (number|no)|credit card|debit card|ssn|"
    r"social security|one[- ]time (code|password)|otp|2fa|two[- ]factor|verification code|auth(entication)? code|"
    r"secret|api[ _-]?key|access key|private key|seed phrase|recovery (phrase|code)|token|routing number|"
    r"account number|iban|sort code)\b")
#: Text Nyx will not type, whatever the field: keys and card-like numbers.
SECRET_TEXT = re.compile(r"(?i)\b(sk|pk|rk)[-_][a-z0-9_-]{12,}|\bAKIA[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9]{20,}|"
                         r"\b(?:\d[ -]?){13,19}\b")
#: Words that mean "this may not be undoable": the step still runs if the owner says so, but it is marked.
CAUTION = re.compile(
    r"(?i)\b(delete|remove|erase|discard|send|submit|pay|payment|buy|purchase|order|checkout|transfer|withdraw|"
    r"deposit|trade|sell|confirm|publish|post|uninstall|format|reset|sign out|log ?out|don'?t save|overwrite|"
    r"replace all|empty)\b")

#: Vision models Ollama can run, best first for reading screens. gemma3's 270m/1b sizes cannot see.
LOCAL_VISION = ("qwen2.5vl", "qwen2.5-vl", "qwen3-vl", "qwen3vl", "llama3.2-vision", "llama4", "gemma3",
                "minicpm-v", "mistral-small3.1", "mistral-small3.2", "granite3.2-vision", "llava", "bakllava", "moondream")
SUGGESTED_LOCAL = {"name": "qwen2.5vl:7b", "gb": 6.0}
_OVERLAY_PROCESSES = frozenset({"nvidia overlay.exe", "nvidia share.exe", "textinputhost.exe", "gamebar.exe",
                                "gamebarftserver.exe", "shellexperiencehost.exe", "searchhost.exe",
                                "startmenuexperiencehost.exe", "lockapp.exe", "applicationframehost.exe"})

SYSTEM = ("You are Nyx, sitting beside the owner and looking at their screen with them. You help with whatever is on it "
          "(code, spreadsheets, finance, forms, documents) one small step at a time, at their pace. You never take "
          "over: you suggest, they decide. Reply with JSON only.")

PACE_RULES = {
    "show": ("The owner wants to do it with their own hands: Nyx only shows where. Still describe the next step "
             "exactly (kind, target, point, and any text or keys) so they can do it themselves."),
    "ask": "Nyx may do the next step for them after they press Do It, so make it exact.",
}

REPLY_FORMAT = """Reply with one JSON object and nothing else:
{"answer": "what matters on the screen and what to do, at most four short sentences",
 "step": {"kind": "click", "target": "the exact button, cell or field, in words", "point": {"x": 500, "y": 500},
          "text": "", "keys": "", "amount": 0, "why": "one short sentence"},
 "done": false}
- "point" is the centre of the target: "x" from 0 (left edge) to 1000 (right edge), "y" from 0 (top edge) to
  1000 (bottom edge) of this picture.
- "kind" is one of: point, click, double_click, type, keys, scroll. For type, put the exact text in "text" (it goes
  where the step points, or where the cursor already is). For keys use names like enter, tab, ctrl+s. For scroll,
  "amount" is negative to go down.
- Only one step: the very next one. Use null for "step" when nothing needs doing or you cannot see where it is.
- Never type passwords, card numbers, PINs or codes: say the owner should type those.
- "done" is true when what they wanted already looks finished."""


class ScreenShareError(RuntimeError):
    """Something the owner should read, as it is."""


class NeedsCloud(ScreenShareError):
    """No local vision model, and the owner has not allowed an online one for this session."""


def _clean(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def normalize_keys(combo: Any) -> str:
    """'Control + S' → 'ctrl+s'; modifiers first, in one order, so the allowed list can be matched exactly."""
    parts = [_KEY_ALIASES.get(p, p) for p in (s.strip().lower() for s in str(combo or "").split("+")) if p]
    modifiers = [m for m in ("ctrl", "alt", "shift") if m in parts]
    keys = [p for p in parts if p not in ("ctrl", "alt", "shift")]
    return "+".join(modifiers + keys)


def norm_point(value: Any, width: int = 0, height: int = 0, order: str = "yx") -> Optional[Tuple[float, float]]:
    """A model's point → (x, y) in 0–1. Asked for as {"x", "y"} 0–1000, which no model misreads. A bare pair is read in
    ``order``: Gemini writes [y, x], Qwen writes [x, y]. Pixel answers are mapped by the picture's own size; a box
    gives its centre."""
    if isinstance(value, dict):
        value = [value.get("y"), value.get("x")]
        order = "yx"
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            value = [(float(value[0]) + float(value[2])) / 2, (float(value[1]) + float(value[3])) / 2]
        except (TypeError, ValueError):
            return None
    if not (isinstance(value, (list, tuple)) and len(value) == 2):
        return None
    try:
        first, second = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    y, x = (first, second) if order == "yx" else (second, first)
    if x < 0 or y < 0:
        return None
    if max(x, y) > 1000:
        if width and height and x <= width and y <= height:
            return x / width, y / height
        return None
    return x / 1000.0, y / 1000.0


def parse_reply(reply: str) -> Dict[str, Any]:
    """The answer, the proposed step and whether it looks done. A reply that is not JSON is kept as the answer."""
    data: Any = None
    try:
        from absorb_engine import json_from

        data = json_from(reply)
    except Exception:  # noqa: BLE001 - a reply we cannot parse is still an answer
        data = None
    if not isinstance(data, dict) or not any(k in data for k in ("answer", "step", "reply", "done")):
        text = re.sub(r"```.*?```", "", str(reply or ""), flags=re.S)
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
        return {"answer": _clean(text, 1200) or "Nyx could not make out the screen this time.", "step": None, "done": False}
    step = data.get("step") if isinstance(data.get("step"), dict) else None
    return {"answer": _clean(data.get("answer") or data.get("reply") or data.get("text"), 1200), "step": step,
            "done": bool(data.get("done"))}


def vet_step(raw: Any, *, pace: str, geometry: Dict[str, int], order: str = "yx") -> Optional[Dict[str, Any]]:
    """Turn what the model proposed into a step Nyx is allowed to show or do, or None when there is nothing usable.

    ``geometry`` is where the picture sits on the real screen: x, y, w, h in physical pixels, and iw, ih the size of
    the picture the model saw. ``order`` is how that model writes a bare [a, b] point (see ``norm_point``)."""
    if not isinstance(raw, dict):
        return None
    kind = re.sub(r"[\s-]+", "_", str(raw.get("kind") or raw.get("action") or "point").strip().lower())
    kind = {"doubleclick": "double_click", "press": "keys", "key": "keys", "hotkey": "keys", "shortcut": "keys",
            "write": "type", "enter_text": "type", "move": "point", "show": "point", "highlight": "point"}.get(kind, kind)
    if kind not in KINDS:
        kind = "point"
    target = _clean(raw.get("target") or raw.get("label"), 140)
    why = _clean(raw.get("why") or raw.get("reason"), 240)
    if raw.get("point_2d") is not None and raw.get("point") is None:
        point = norm_point(raw["point_2d"], geometry.get("iw", 0), geometry.get("ih", 0), order="xy")  # Qwen's own key
    else:
        point = norm_point(raw.get("point") or raw.get("box_2d") or raw.get("box"), geometry.get("iw", 0),
                           geometry.get("ih", 0), order=order)
    text = str(raw.get("text") or "")
    keys = normalize_keys(raw.get("keys") or "")
    try:
        amount = int(float(raw.get("amount") or 0))
    except (TypeError, ValueError):
        amount = 0

    blocked = ""
    if kind in ("point", "click", "double_click") and point is None:
        return None
    if kind == "type":
        if not text.strip():
            return None
        text = text[:MAX_TYPE]
        if raw.get("sensitive") or SENSITIVE.search(f"{target} {why}") or SECRET_TEXT.search(text):
            blocked = "This looks like a password, code or card detail. Type it yourself: Nyx never types those."
    if kind == "keys":
        if not keys:
            return None
        if keys not in ALLOWED_KEYS:
            blocked = (f"Nyx only presses simple keys for you (Enter, Tab, arrows, Ctrl+C/V/Z/S …). "
                       f"Press {keys} yourself if you want it.")
    if kind == "scroll":
        amount = max(-15, min(15, amount or -5))
    screen = None
    if point is not None:
        screen = [int(round(geometry["x"] + point[0] * geometry["w"])), int(round(geometry["y"] + point[1] * geometry["h"]))]
    return {
        "id": uuid.uuid4().hex[:10], "kind": kind, "target": target, "why": why,
        "point": [round(point[0], 4), round(point[1], 4)] if point is not None else None, "screen": screen,
        "text": text if kind == "type" else "", "keys": keys if kind == "keys" else "",
        "amount": amount if kind == "scroll" else 0,
        "caution": bool(CAUTION.search(f"{target} {why}")) or keys == "delete",
        "blocked": blocked, "hands_on": pace == "show" and kind != "point",
        "created": time.time(), "status": "pending", "geometry": dict(geometry),
    }


def build_prompt(question: str, goal: str, history: List[str], source_label: str, pace: str,
                 geometry: Dict[str, int]) -> str:
    lines = [f'The owner asks: "{question}"']
    if goal and goal != question:
        lines.append(f'What they are working on: "{goal}"')
    if history:
        lines.append("Earlier in this session:\n" + "\n".join(history))
    lines.append(f"The picture is {source_label}, {geometry.get('iw', 0)}x{geometry.get('ih', 0)} pixels.")
    lines.append(PACE_RULES.get(pace, PACE_RULES["show"]))
    lines.append(REPLY_FORMAT)
    return "\n\n".join(lines)


_CAPS: Dict[str, Tuple[float, Optional[List[str]]]] = {}


def ollama_capabilities(name: str) -> Optional[List[str]]:
    """What Ollama says a model can do (``/api/show`` → "completion", "vision", "tools", "thinking"…), or None when it
    does not say (an older Ollama). Cached for ten minutes: the Screen Share page asks often."""
    at, caps = _CAPS.get(name, (0.0, None))
    if at and time.monotonic() - at < 600:
        return caps
    caps = None
    try:
        import local_models
        import requests

        response = requests.post(local_models.host() + "/api/show", json={"model": name}, timeout=3)
        if response.ok and isinstance(response.json().get("capabilities"), list):
            caps = [str(c) for c in response.json()["capabilities"]]
    except Exception:  # noqa: BLE001 - no answer means "ask the name instead"
        caps = None
    _CAPS[name] = (time.monotonic(), caps)
    return caps


def local_vision_model(installed: Optional[List[str]] = None,
                       caps: Optional[Callable[[str], Optional[List[str]]]] = None) -> str:
    """The best vision model already in Ollama, or '' when there is none (or Ollama is not running).

    Ollama's own capability list decides (qwen3.5 sees, though its name does not say so); the name only decides for an
    Ollama too old to report capabilities. Known good screen readers come first."""
    if installed is None:
        try:
            import local_models

            installed = [m["name"] for m in local_models.installed_models()] if local_models.running() else []
        except Exception:  # noqa: BLE001
            installed = []
    ask = caps or ollama_capabilities

    def preference(name: str) -> int:
        low = name.lower()
        return next((i for i, hint in enumerate(LOCAL_VISION) if hint in low), len(LOCAL_VISION))

    seeing, unknown = [], []
    for name in installed:
        reported = ask(name)
        if reported is None:
            unknown.append(name)
        elif "vision" in reported:
            seeing.append(name)
    if seeing:
        return sorted(seeing, key=preference)[0]
    for hint in LOCAL_VISION:
        for name in unknown:
            low = name.lower()
            if hint in low and not (hint == "gemma3" and re.search(r":(270m|1b)\b", low)):
                return name
    return ""


GRID_NOTE = ("The picture has a faint numbered grid to help you point: the numbers along the top are x, the numbers down "
             "the left side are y, in the same 0-1000 units as \"point\".")


def grid_overlay(image: bytes) -> bytes:
    """The model's copy of the picture with a faint 0–1000 grid (the owner's view has none).

    Measured 2026-09-18 with qwen3.5:9b on a synthetic spreadsheet: without it the point was off by 132–196 px
    vertically; with it, two of three points landed inside the right row. Anything that goes wrong returns the
    picture unchanged."""
    try:
        from PIL import Image, ImageDraw, ImageFont

        base = Image.open(io.BytesIO(image)).convert("RGBA")
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        try:
            font = ImageFont.truetype("arialbd.ttf", 13)
        except OSError:
            font = ImageFont.load_default()
        width, height = base.size
        for step in range(100, 1000, 100):
            x, y = round(width * step / 1000), round(height * step / 1000)
            draw.line([(x, 0), (x, height)], fill=(255, 0, 170, 90), width=1)
            draw.line([(0, y), (width, y)], fill=(255, 0, 170, 90), width=1)
            for at in ((x + 3, 2), (3, y + 2)):
                box = draw.textbbox(at, str(step), font=font)
                draw.rectangle([box[0] - 2, box[1] - 1, box[2] + 2, box[3] + 1], fill=(255, 255, 255, 200))
                draw.text(at, str(step), fill=(200, 0, 130, 255), font=font)
        out = io.BytesIO()
        Image.alpha_composite(base, layer).convert("RGB").save(out, "JPEG", quality=85)
        return out.getvalue()
    except Exception:  # noqa: BLE001 - a picture without a grid still works
        return image


def ollama_look(model: str, prompt: str, image: bytes, *, timeout: float = 180) -> str:
    """One look through a local model. Called directly rather than through model_hub so thinking can be switched off
    and the reply capped: a thinking model would otherwise spend a minute reasoning before it points at a cell."""
    import base64

    import local_models
    import requests

    body = {"model": model, "stream": False, "think": False, "options": {"num_predict": 700, "temperature": 0.2},
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": prompt, "images": [base64.b64encode(image).decode("ascii")]}]}
    try:
        response = requests.post(local_models.host() + "/api/chat", json=body, timeout=timeout)
        if response.status_code == 400 and "think" in response.text.lower():
            body.pop("think")  # a model that cannot think refuses the switch
            response = requests.post(local_models.host() + "/api/chat", json=body, timeout=timeout)
    except requests.RequestException as error:
        raise ScreenShareError(f"Ollama did not answer ({error.__class__.__name__}). Is it running?") from error
    if response.status_code != 200:
        raise ScreenShareError(f"{model} answered {response.status_code}: {response.text[:200]}")
    return str((response.json().get("message") or {}).get("content") or "")


# ---------------------------------------------------------------------------
# Seeing one window, even behind others
# ---------------------------------------------------------------------------

_API: Dict[str, Any] = {}


def _win32() -> Any:
    """user32/gdi32 with pointer-sized handles declared (the defaults would cut 64-bit handles in half)."""
    if "api" in _API:
        return _API["api"]
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    vp = ctypes.c_void_p
    for name, args, result in (("IsWindow", [vp], wintypes.BOOL), ("IsIconic", [vp], wintypes.BOOL),
                               ("GetWindowRect", [vp, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
                               ("GetWindowDC", [vp], vp), ("ReleaseDC", [vp, vp], ctypes.c_int),
                               ("PrintWindow", [vp, vp, wintypes.UINT], wintypes.BOOL)):
        function = getattr(user32, name)
        function.argtypes, function.restype = args, result
    for name, args, result in (("CreateCompatibleDC", [vp], vp),
                               ("CreateCompatibleBitmap", [vp, ctypes.c_int, ctypes.c_int], vp),
                               ("SelectObject", [vp, vp], vp),
                               ("GetDIBits", [vp, vp, wintypes.UINT, wintypes.UINT, vp, vp, wintypes.UINT], ctypes.c_int),
                               ("DeleteObject", [vp], wintypes.BOOL), ("DeleteDC", [vp], wintypes.BOOL)):
        function = getattr(gdi32, name)
        function.argtypes, function.restype = args, result

    class BitmapInfoHeader(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    api = SimpleNamespace(ctypes=ctypes, wintypes=wintypes, user32=user32, gdi32=gdi32, header=BitmapInfoHeader)
    _API["api"] = api
    return api


def window_rect(hwnd: int, control: Any) -> Dict[str, int]:
    """Where a shared window is now, in physical pixels; raises when it closed or was minimised."""
    api = _win32()
    with control._dpi_aware():
        if not api.user32.IsWindow(hwnd):
            raise ScreenShareError("That window has closed. Pick another one to share.")
        if api.user32.IsIconic(hwnd):
            raise ScreenShareError("That window is minimised. Restore it, then ask again.")
        rect = api.wintypes.RECT()
        api.user32.GetWindowRect(hwnd, api.ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width < 2 or height < 2:
        raise ScreenShareError("That window has no size to see.")
    return {"x": rect.left, "y": rect.top, "w": width, "h": height}


def capture_window(hwnd: int, control: Any) -> Tuple[Any, Dict[str, int]]:
    """A picture of one window even when others cover it (PrintWindow), else what is on screen where it is."""
    from PIL import Image

    api = _win32()
    rect = window_rect(hwnd, control)
    width, height = rect["w"], rect["h"]
    image = None
    with control._dpi_aware():
        window_dc = api.user32.GetWindowDC(hwnd)
        memory_dc = api.gdi32.CreateCompatibleDC(window_dc)
        bitmap = api.gdi32.CreateCompatibleBitmap(window_dc, width, height)
        old = api.gdi32.SelectObject(memory_dc, bitmap)
        try:
            printed = api.user32.PrintWindow(hwnd, memory_dc, 2)  # PW_RENDERFULLCONTENT: GPU-drawn apps too
            api.gdi32.SelectObject(memory_dc, old)                # GetDIBits wants the bitmap out of the DC
            if printed:
                header = api.header(biSize=api.ctypes.sizeof(api.header), biWidth=width, biHeight=-height, biPlanes=1,
                                    biBitCount=32, biCompression=0)
                buffer = api.ctypes.create_string_buffer(width * height * 4)
                if api.gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer, api.ctypes.byref(header), 0) == height:
                    image = Image.frombuffer("RGB", (width, height), buffer.raw, "raw", "BGRX", 0, 1)
        finally:
            api.gdi32.DeleteObject(bitmap)
            api.gdi32.DeleteDC(memory_dc)
            api.user32.ReleaseDC(hwnd, window_dc)
    if image is None or image.getbbox() is None:
        # Some apps draw nothing into PrintWindow: fall back to what is visible there.
        image, _origin = control.grab_screen((rect["x"], rect["y"], width, height))
    return image, rect


# ---------------------------------------------------------------------------
# The session
# ---------------------------------------------------------------------------


class ScreenShare:
    """One sharing session at a time (there is one screen and one owner). Everything is in memory."""

    def __init__(self, control: Any = None, looker: Optional[Callable[[bytes, str, bool], Tuple[str, str, bool]]] = None,
                 capture: Optional[Callable[..., Tuple[bytes, Dict[str, int]]]] = None,
                 local_model: Optional[Callable[[], str]] = None) -> None:
        self._lock = threading.RLock()
        self._session: Optional[Dict[str, Any]] = None
        self._ended = ""
        self._control = control
        self._looker = looker
        self._capture = capture
        self._local_model = local_model
        self._model_cache: Tuple[float, Dict[str, Any]] = (0.0, {})

    @property
    def control(self) -> Any:
        if self._control is None:
            import computer_control

            self._control = computer_control
        return self._control

    # --- what the page reads -------------------------------------------------------------------------------

    def model_info(self) -> Dict[str, Any]:
        """Who would look: the local model if there is one, and the online fallback the owner may allow."""
        at, cached = self._model_cache
        if cached and time.monotonic() - at < 10:
            return dict(cached)
        info: Dict[str, Any] = {"local": self._find_local(), "suggested": SUGGESTED_LOCAL["name"],
                                "suggested_gb": SUGGESTED_LOCAL["gb"], "ollama_installed": False, "ollama_running": False,
                                "cloud": ""}
        try:
            import local_models

            info["ollama_installed"] = bool(local_models.ollama_exe())
            info["ollama_running"] = local_models.running()
        except Exception:  # noqa: BLE001
            pass
        try:
            from model_roles import MODEL_ROLES

            role = MODEL_ROLES.get_role("ui_pointing") or {}
            info["cloud"] = str(role.get("label") or role.get("model") or "")
        except Exception:  # noqa: BLE001
            pass
        self._model_cache = (time.monotonic(), info)
        return dict(info)

    def _find_local(self) -> str:
        return self._local_model() if self._local_model is not None else local_vision_model()

    def state(self) -> Dict[str, Any]:
        model = self.model_info()  # may ask Ollama: outside the lock
        with self._lock:
            self._expire()
            session = self._session
            base = {"paces": list(PACES), "model": model, "limits": {
                "step_seconds": int(STEP_TTL_SECONDS), "idle_minutes": IDLE_STOP_SECONDS // 60, "max_type": MAX_TYPE,
                "keys": sorted(ALLOWED_KEYS)}}
            if not session:
                return {**base, "sharing": False, "ended": self._ended}
            return {**base, "sharing": True, "id": session["id"], "source": self._public_source(session["source"]),
                    "pace": session["pace"], "allow_cloud": session["allow_cloud"], "goal": session["goal"],
                    "messages": list(session["messages"]), "step": self._public_step(session.get("step")),
                    "busy": session["busy"], "frames": session["frames"],
                    "idle_stop_in": int(max(0, IDLE_STOP_SECONDS - (time.monotonic() - session["seen"])))}

    def sources(self) -> Dict[str, Any]:
        """The screens and windows that can be shared."""
        control = self.control
        bounds = control.screen_bounds(max_age=0)
        screens = [{"kind": "screen", "index": index, "label": f"Screen {index + 1}{' (main)' if m.get('primary') else ''}",
                    "width": m["width"], "height": m["height"]} for index, m in enumerate(bounds.get("monitors") or [])]
        windows = []
        for window in control.list_windows():
            if window["width"] < 200 or window["height"] < 120:
                continue
            if window["title"].strip().lower() == "tk" and window["process"].lower().startswith("python"):
                continue  # Nyx's own purple cursor
            if window["process"].lower() in _OVERLAY_PROCESSES:
                continue  # see-through overlays that cover the screen but show nothing of their own
            windows.append({"kind": "window", "hwnd": window["hwnd"], "title": window["title"][:120],
                            "process": window["process"], "minimized": window["minimized"], "focused": window["focused"]})
        return {"screens": screens, "windows": windows[:40]}

    # --- starting and stopping -----------------------------------------------------------------------------

    def start(self, source: Dict[str, Any], pace: str = "show") -> Dict[str, Any]:
        if not getattr(self.control, "IS_WINDOWS", False) and self._capture is None:
            raise ScreenShareError("Screen Share works on Windows only.")
        chosen = self._resolve(source)
        with self._lock:
            self._session = {"id": uuid.uuid4().hex[:10], "source": chosen, "pace": pace if pace in PACES else "show",
                             "allow_cloud": False, "goal": "", "messages": [], "step": None, "busy": False,
                             "started": time.time(), "seen": time.monotonic(), "frames": 0}
            self._ended = ""
            self._note("note", f"Sharing {chosen['label']}. Nyx looks only when you ask, and acts only when you press "
                               "a button.")
        return self.state()

    def stop(self, reason: str = "You stopped sharing.") -> Dict[str, Any]:
        with self._lock:
            session = self._session
            self._session = None
            if session:
                self._ended = reason
        if session and session.get("busy"):
            try:
                self.control.abort("Screen Share stopped")
            except Exception:  # noqa: BLE001
                pass
        return self.state()

    def set_pace(self, pace: str) -> Dict[str, Any]:
        if pace not in PACES:
            raise ScreenShareError("Pace is show or ask.")
        with self._lock:
            session = self._require()
            session["pace"] = pace
            session["seen"] = time.monotonic()
            step = session.get("step")
            if step:
                step["hands_on"] = pace == "show" and step["kind"] != "point"
            self._note("note", "Show Me: Nyx points, you do." if pace == "show" else
                       "Ask First: Nyx can do one step at a time, each only after you press Do It.")
        return self.state()

    def set_cloud(self, allow: bool) -> Dict[str, Any]:
        label = self.model_info().get("cloud") or "the online model"
        with self._lock:
            session = self._require()
            session["allow_cloud"] = bool(allow)
            self._note("note", f"Allowed {label} to see what you share, for this session only." if allow else
                       "Online model turned off: only a model on this PC may look.")
        return self.state()

    # --- seeing --------------------------------------------------------------------------------------------

    def frame(self, max_width: int = FRAME_WIDTH) -> bytes:
        """The live view for the page. Only while sharing; never stored."""
        with self._lock:
            self._expire()
            session = self._require()
            session["seen"] = time.monotonic()
            session["frames"] += 1
            source = dict(session["source"])
        data, _geometry = self._grab(source, max_width=max(320, min(1920, int(max_width or FRAME_WIDTH))), quality=70,
                                     cursor=True)
        return data

    def ask(self, question: str, next_step: bool = False) -> Dict[str, Any]:
        """Look at the shared screen once and answer, with at most one proposed step."""
        question = _clean(question, 800) or ("What is the next step?" if next_step else "")
        if not question:
            raise ScreenShareError("Ask Nyx something about what you are sharing.")
        local = self._find_local()  # may ask Ollama: outside the lock
        with self._lock:
            self._expire()
            session = self._require()
            if session["busy"]:
                raise ScreenShareError("Nyx is still busy with the last one. One moment.")
            if not local and not session["allow_cloud"]:
                raise NeedsCloud("There is no vision model on this PC yet. Allow the online model for this session, "
                                 "or get a local one in Keys → Local models.")
            session["busy"] = True
            session["seen"] = time.monotonic()
            if not next_step or not session["goal"]:
                session["goal"] = question
            session["step"] = None
            self._note("you", question)
            session_id = session["id"]
            source, pace, allow_cloud, goal = dict(session["source"]), session["pace"], session["allow_cloud"], session["goal"]
            history = self._history(session)
        answer, model_label, on_pc, step, done, failure = "", "", False, None, False, ""
        try:
            image, geometry = self._grab(source, max_width=LOOK_WIDTH, quality=82, cursor=False)
            prompt = build_prompt(question, goal, history, self._describe(source), pace, geometry)
            if local:
                # A small local model points far better with a grid to read off; the owner's view stays clean.
                image, prompt = grid_overlay(image), prompt + "\n\n" + GRID_NOTE
            reply, model_label, on_pc = self._look(image, prompt, allow_cloud, local)
            parsed = parse_reply(reply)
            # A bare [a, b] point: Qwen models write [x, y], Gemini [y, x]. The prompt asks for {"x", "y"} anyway.
            order = "xy" if on_pc and "qwen" in (local or "").lower() else "yx"
            step = vet_step(parsed.get("step"), pace=pace, geometry=geometry, order=order)
            answer, done = parsed["answer"], parsed["done"]
        except ScreenShareError as error:
            failure = str(error)
        except Exception as error:  # noqa: BLE001 - a model or capture failure is told, not thrown at the page
            _LOG.warning("screen share look failed: %s", error)
            failure = f"Nyx could not look this time: {str(error)[:200]}"
        with self._lock:
            session = self._session
            if not session or session["id"] != session_id:
                return self.state()  # sharing stopped while it looked: nothing is kept
            session["busy"] = False
            if failure:
                self._note("error", failure)
                return self.state()
            session["step"] = step
            text = answer or ("That looks done." if done else "Here is the next step." if step else "Nothing to do here.")
            self._note("nyx", text, model=model_label, local=on_pc, step_id=step["id"] if step else None, done=done or None)
        return self.state()

    # --- acting ----------------------------------------------------------------------------------------------

    def act(self, step_id: str, action: str) -> Dict[str, Any]:
        """show: point with Nyx's cursor. do: run the step (Ask First only). mine: the owner did it. skip: drop it."""
        if action not in ("show", "do", "mine", "skip"):
            raise ScreenShareError("Unknown action.")
        with self._lock:
            session = self._require()
            session["seen"] = time.monotonic()
            step = session.get("step")
            if not step or step["id"] != step_id or step["status"] != "pending":
                raise ScreenShareError("That step is no longer waiting. Ask again.")
            if action in ("skip", "mine"):
                step["status"] = "skipped" if action == "skip" else "done"
                session["step"] = None
                self._note("action", "Skipped that step." if action == "skip" else "You did that step.", ok=action == "mine")
                return self.state()
            if time.time() - step["created"] > STEP_TTL_SECONDS:
                step["status"] = "expired"
                session["step"] = None
                raise ScreenShareError("That step is more than two minutes old. Ask again so Nyx looks at the screen "
                                       "as it is now.")
            if action == "do":
                if session["pace"] != "ask":
                    raise ScreenShareError("Nyx is on Show Me: it points, you do. Switch to Ask First to let it do "
                                           "one approved step.")
                if step["blocked"]:
                    raise ScreenShareError(step["blocked"])
            if session["busy"]:
                raise ScreenShareError("Nyx is busy. One moment.")
            session["busy"] = True
            session_id = session["id"]
            source = dict(session["source"])
        control = self.control
        status, message = "done", ""
        try:
            message = self._run(step, source, do=action == "do")
        except getattr(control, "ComputerAborted", ()) as error:  # type: ignore[misc]
            status, message = "stopped", f"Stopped: {error}"
        except (ScreenShareError, getattr(control, "ComputerError", ScreenShareError)) as error:  # type: ignore[misc]
            status, message = "failed", str(error)
        except Exception as error:  # noqa: BLE001
            status, message = "failed", f"That step did not work: {str(error)[:200]}"
        with self._lock:
            session = self._session
            if not session or session["id"] != session_id:
                return self.state()
            session["busy"] = False
            if session.get("step") is step:
                if action == "show":
                    step["shown"] = status == "done"  # still waiting either way: showing where is not doing it
                else:
                    step["status"] = status
                    session["step"] = None
            self._note("action" if status == "done" else "error", message, ok=status == "done")
        return self.state()

    def _run(self, step: Dict[str, Any], source: Dict[str, Any], *, do: bool) -> str:
        control = self.control
        where = step.get("screen")
        if source["kind"] == "window":
            now = window_rect(source["hwnd"], control)
            then = step.get("geometry") or {}
            if any(abs(now[k] - then.get(k, now[k])) > 4 for k in ("x", "y", "w", "h")):
                raise ScreenShareError("The window moved since Nyx looked. Ask again.")
        target = step["target"] or "there"
        if not do or step["kind"] == "point":
            if not where:
                raise ScreenShareError("There is no place to point at in this step.")
            control.point_at(where[0], where[1], step["target"] or "Here")
            return f"Pointed at {target}."
        if source["kind"] == "window":
            control.focus_window(str(source["hwnd"]))
            time.sleep(0.15)
        kind = step["kind"]
        if kind in ("click", "double_click"):
            control.click(where[0], where[1], double=kind == "double_click", label=f"Clicking {target}"[:60])
            return f"{'Double-clicked' if kind == 'double_click' else 'Clicked'} {target}."
        if kind == "type":
            if where:
                control.click(where[0], where[1], label=f"Clicking {target}"[:60])
            count = control.type_text(step["text"])
            return f"Typed {count} characters{' into ' + step['target'] if step['target'] else ''}."
        if kind == "keys":
            control.press_keys(step["keys"])
            return f"Pressed {step['keys']}."
        if kind == "scroll":
            if where:
                control.scroll(step["amount"], where[0], where[1])
            else:
                control.scroll(step["amount"])
            return f"Scrolled {'down' if step['amount'] < 0 else 'up'}."
        raise ScreenShareError("Nyx does not know how to do that step.")

    # --- inside ----------------------------------------------------------------------------------------------

    def _require(self) -> Dict[str, Any]:
        if not self._session:
            raise ScreenShareError("You are not sharing anything. Press Start Sharing first.")
        return self._session

    def _expire(self) -> None:
        session = self._session
        if session and time.monotonic() - session["seen"] > IDLE_STOP_SECONDS and not session["busy"]:
            self._session = None
            self._ended = "Sharing stopped by itself after 15 quiet minutes."

    def _note(self, role: str, text: str, **extra: Any) -> None:
        session = self._session
        if session is None:
            return
        entry = {"role": role, "text": _clean(text, 1400), "at": time.time(),
                 **{k: v for k, v in extra.items() if v is not None}}
        session["messages"] = (session["messages"] + [entry])[-MAX_HISTORY:]

    @staticmethod
    def _history(session: Dict[str, Any]) -> List[str]:
        names = {"you": "Owner", "nyx": "Nyx", "action": "Done"}
        return [f"{names[m['role']]}: {m['text'][:200]}" for m in session["messages"][:-1][-6:] if m["role"] in names]

    def _resolve(self, source: Any) -> Dict[str, Any]:
        if not isinstance(source, dict):
            raise ScreenShareError("Pick a screen or a window to share.")
        if source.get("kind") == "window":
            try:
                hwnd = int(source.get("hwnd"))
            except (TypeError, ValueError):
                raise ScreenShareError("Pick a window to share.") from None
            title = _clean(source.get("title"), 120)
            if self._capture is None:
                window_rect(hwnd, self.control)  # still there, not minimised
                match = next((w for w in self.control.list_windows() if w["hwnd"] == hwnd), None)
                if match is None:
                    raise ScreenShareError("That window has closed. Pick another one to share.")
                title = match["title"][:120]
            return {"kind": "window", "hwnd": hwnd, "title": title, "label": f"the window “{title[:60]}”"}
        try:
            index = int(source.get("index") or 0)
        except (TypeError, ValueError):
            index = 0
        if self._capture is None:
            monitors = self.control.screen_bounds(max_age=0).get("monitors") or []
            if not 0 <= index < len(monitors):
                raise ScreenShareError("That screen is not connected.")
        return {"kind": "screen", "index": index, "label": f"screen {index + 1}"}

    @staticmethod
    def _describe(source: Dict[str, Any]) -> str:
        return (f"a screenshot of the window “{source.get('title', '')[:80]}”" if source["kind"] == "window"
                else f"a screenshot of the whole of screen {source['index'] + 1}")

    @staticmethod
    def _public_source(source: Dict[str, Any]) -> Dict[str, Any]:
        return {k: source[k] for k in ("kind", "label", "title", "index", "hwnd") if k in source}

    @staticmethod
    def _public_step(step: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not step:
            return None
        public = {k: step[k] for k in ("id", "kind", "target", "why", "point", "text", "keys", "amount", "caution",
                                       "blocked", "hands_on", "created", "status")}
        public["shown"] = bool(step.get("shown"))
        public["expires_in"] = int(max(0, STEP_TTL_SECONDS - (time.time() - step["created"])))
        return public

    def _grab(self, source: Dict[str, Any], *, max_width: int, quality: int, cursor: bool) -> Tuple[bytes, Dict[str, int]]:
        """JPEG bytes and where that picture sits on the real screen (x, y, w, h) plus its own size (iw, ih)."""
        if self._capture is not None:
            return self._capture(source, max_width)
        from PIL import Image

        control = self.control
        if source["kind"] == "screen":
            monitors = control.screen_bounds().get("monitors") or []
            if not 0 <= source["index"] < len(monitors):
                raise ScreenShareError("That screen is no longer connected. Stop and share again.")
            m = monitors[source["index"]]
            data, _scale, _origin = control.screenshot_jpeg(max_width=max_width, cursor=cursor, quality=quality,
                                                            region=(m["x"], m["y"], m["width"], m["height"]))
            width, height = Image.open(io.BytesIO(data)).size
            return data, {"x": m["x"], "y": m["y"], "w": m["width"], "h": m["height"], "iw": width, "ih": height}
        image, rect = capture_window(source["hwnd"], control)
        position = None
        if cursor:
            with control._dpi_aware():
                position = control._get_cursor()
        image = control.annotate(image, (rect["x"], rect["y"]), position)
        if max_width and image.width > max_width:
            image = image.resize((max_width, max(1, int(image.height * max_width / image.width))))
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=quality)
        return buffer.getvalue(), {**rect, "iw": image.width, "ih": image.height}

    def _look(self, image: bytes, prompt: str, allow_cloud: bool, local: str) -> Tuple[str, str, bool]:
        """(reply, which model, whether it ran on this PC). Local first; online only when allowed."""
        if self._looker is not None:
            return self._looker(image, prompt, allow_cloud)
        if local:
            try:
                return ollama_look(local, prompt, image), f"{local} on this PC", True
            except ScreenShareError as error:
                if not allow_cloud:
                    raise ScreenShareError(f"The model on this PC could not look: {error}") from error
        if not allow_cloud:
            raise NeedsCloud("There is no vision model on this PC yet. Allow the online model for this session, or get "
                             "a local one in Keys → Local models.")
        from model_roles import MODEL_ROLES

        run = MODEL_ROLES.run("ui_pointing", prompt, images=[(image, "image/jpeg")], system=SYSTEM, max_tokens=700)
        return run.text, run.label, False


SHARE = ScreenShare()
