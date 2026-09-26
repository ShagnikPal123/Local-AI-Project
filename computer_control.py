"""Computer control with a mouse the user can see (contract §4.2).

Nyx looks at the screen (``screen_view``, ``find_on_screen``), moves and clicks the
real mouse, types, presses shortcuts, scrolls, drags, and manages windows. Every
action:

* glides the real cursor (never teleports) and shows the **AI cursor overlay** —
  a labelled purple arrow with a click ripple (``cursor_overlay.py``);
* publishes ``computer.action`` so the web UI can show it live;
* checks that **the user is still in charge**: slam the real mouse into the
  top-left corner, press Esc three times, or hit Stop, and the sequence aborts —
  further computer actions in that turn are refused.

Windows only; pure ``ctypes`` (SendInput, EnumWindows) + Pillow for screenshots.
Coordinates are physical pixels on the virtual desktop, the same space as the
screenshots — each call runs per-monitor DPI aware for its own thread only.
"""

from __future__ import annotations

import ctypes
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

IS_WINDOWS = os.name == "nt"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

GLIDE_MS = 280
TYPE_DELAY = 0.008
ABORT_REFUSAL_SECONDS = 30.0
WATCH_SECONDS = 60.0


class ComputerAborted(RuntimeError):
    """The user took over (corner / Esc×3 / Stop)."""


class ComputerError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Win32 plumbing
# ---------------------------------------------------------------------------

if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

MOUSE_FLAGS = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}
WHEEL, HWHEEL, KEYUP, UNICODE, EXTENDED = 0x0800, 0x1000, 0x0002, 0x0004, 0x0001

VK: Dict[str, int] = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D, "shift": 0x10, "ctrl": 0x11, "control": 0x11,
    "alt": 0x12, "pause": 0x13, "capslock": 0x14, "esc": 0x1B, "escape": 0x1B, "space": 0x20, "pageup": 0x21,
    "pagedown": 0x22, "end": 0x23, "home": 0x24, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "printscreen": 0x2C, "insert": 0x2D, "delete": 0x2E, "del": 0x2E, "win": 0x5B, "windows": 0x5B, "cmd": 0x5B,
    "meta": 0x5B, "super": 0x5B, "apps": 0x5D, "menu": 0x5D, "numlock": 0x90, "scrolllock": 0x91,
    "volumemute": 0xAD, "volumedown": 0xAE, "volumeup": 0xAF, "playpause": 0xB3,
    **{f"f{i}": 0x6F + i for i in range(1, 25)},
    **{chr(c): c for c in range(0x30, 0x3A)}, **{chr(c).lower(): c for c in range(0x41, 0x5B)},
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF, "`": 0xC0, "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
    "plus": 0xBB, "minus": 0xBD,
}
_EXTENDED_VKS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2C, 0x2D, 0x2E, 0x5B, 0x5D}
_MODIFIERS = {0x10, 0x11, 0x12, 0x5B}


def _send(inputs: List[Any]) -> None:
    """The one place real input is generated. Tests replace this."""
    if not IS_WINDOWS or not inputs:
        return
    array = (INPUT * len(inputs))(*inputs)
    if user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT)) != len(inputs):
        raise ComputerError("Windows refused the input (an elevated app may be in front; Nyx can't control admin windows).")


def _set_cursor(x: int, y: int) -> None:
    """Move the real cursor. Tests replace this."""
    if IS_WINDOWS:
        user32.SetCursorPos(int(x), int(y))


def _get_cursor() -> Tuple[int, int]:
    if not IS_WINDOWS:
        return (0, 0)
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def _key_down(vk: int) -> bool:
    return bool(IS_WINDOWS and user32.GetAsyncKeyState(vk) & 0x8000)


@contextmanager
def _dpi_aware() -> Iterator[None]:
    """Physical pixels for this thread only (so the tray/UI of the engine are untouched)."""
    previous = None
    if IS_WINDOWS:
        try:
            user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
            previous = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            previous = None
    try:
        yield
    finally:
        if previous:
            try:
                user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(previous))
            except Exception:
                pass


_bounds_cache: Dict[str, Any] = {}


def screen_bounds(max_age: float = 3.0) -> Dict[str, Any]:
    """Virtual desktop (all monitors) and each monitor, in physical pixels (cached a few seconds)."""
    if not IS_WINDOWS:
        return {"left": 0, "top": 0, "width": 0, "height": 0, "monitors": []}
    cached = _bounds_cache.get("value")
    if cached and time.monotonic() - _bounds_cache.get("at", 0) < max_age:
        return cached
    value = _read_bounds()
    _bounds_cache.update(value=value, at=time.monotonic())
    return value


def _read_bounds() -> Dict[str, Any]:
    with _dpi_aware():
        left, top = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
        width, height = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
        monitors: List[Dict[str, Any]] = []

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        def callback(hmonitor, _hdc, _rect, _data):
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                r = info.rcMonitor
                monitors.append({"x": r.left, "y": r.top, "width": r.right - r.left, "height": r.bottom - r.top,
                                 "primary": bool(info.dwFlags & 1)})
            return True

        proc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(callback)
        user32.EnumDisplayMonitors(None, None, proc, 0)
    return {"left": left, "top": top, "width": width, "height": height, "monitors": monitors}


# ---------------------------------------------------------------------------
# State, safety, announcements
# ---------------------------------------------------------------------------


class _State:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.overlay_enabled = True
        self.aborted_at = 0.0
        self.aborted_turn = ""
        self.abort_reason = ""
        self.last_action: Optional[Dict[str, Any]] = None
        self.actions: List[Dict[str, Any]] = []
        self.last_ai_pos: Optional[Tuple[int, int]] = None
        self.last_active = 0.0
        self.last_turn = ""
        self.ai_escape_until = 0.0
        self.watcher: Optional[threading.Thread] = None
        self.overlay: Optional[subprocess.Popen] = None


STATE = _State()


def _turn_id() -> str:
    try:
        from tool_context import current

        ctx = current()
        return ctx.turn_id if ctx else ""
    except Exception:
        return ""


def abort(reason: str = "Stopped") -> None:
    with STATE.lock:
        STATE.aborted_at = time.monotonic()
        # The watcher thread has no turn of its own: stop the turn that was acting.
        STATE.aborted_turn = _turn_id() or STATE.last_turn
        STATE.abort_reason = reason
    # The web UI's ComputerBanner shows this; no separate toast.
    _publish("computer.state", active=False, overlay=STATE.overlay_enabled, stopped=reason)
    _overlay_send({"op": "hide"})


def _check_abort() -> None:
    with STATE.lock:
        if not STATE.aborted_at:
            return
        recent = time.monotonic() - STATE.aborted_at < ABORT_REFUSAL_SECONDS
        same_turn = bool(STATE.aborted_turn) and STATE.aborted_turn == _turn_id()
        if recent or same_turn:
            raise ComputerAborted(f"{STATE.abort_reason} — the user took over. Do not retry computer actions this turn; "
                                  "tell the user what was done so far.")
        STATE.aborted_at, STATE.aborted_turn, STATE.abort_reason = 0.0, "", ""


def _on_monitor(x: int, y: int, monitors: List[Dict[str, Any]]) -> bool:
    return any(m["x"] <= x < m["x"] + m["width"] and m["y"] <= y < m["y"] + m["height"] for m in monitors)


def failsafe_corners(bounds: Dict[str, Any]) -> List[Tuple[int, int]]:
    """Top-left corners the pointer can actually be slammed into: a monitor's corner with no screen left of or above it.

    With monitors of different sizes the virtual desktop's own corner can be dead
    space the pointer never reaches (on this PC it is (0, -367)).
    """
    monitors = bounds.get("monitors") or []
    if not monitors:
        return [(bounds["left"], bounds["top"])]
    corners = [(m["x"], m["y"]) for m in monitors
               if not _on_monitor(m["x"] - 1, m["y"], monitors) and not _on_monitor(m["x"], m["y"] - 1, monitors)]
    return corners or [(monitors[0]["x"], monitors[0]["y"])]


def _near_corner(x: int, y: int, corners: List[Tuple[int, int]]) -> bool:
    return any(cx <= x <= cx + 1 and cy <= y <= cy + 1 for cx, cy in corners)


def _user_override() -> Optional[str]:
    """Checks the real inputs: cursor slammed into a top-left screen corner (not by Nyx)."""
    bounds = screen_bounds()
    with _dpi_aware():
        x, y = _get_cursor()
    if _near_corner(x, y, failsafe_corners(bounds)) and STATE.last_ai_pos != (x, y):
        return "mouse moved to the top-left corner"
    return None


class EscCounter:
    """Three separate Esc presses within two seconds (ignoring Esc that Nyx itself sent)."""

    def __init__(self) -> None:
        self.presses: List[float] = []
        self.was_down = False

    def feed(self, down: bool, now: float, ignore_until: float = 0.0) -> bool:
        pressed = down and not self.was_down
        self.was_down = down
        if not pressed or now <= ignore_until:
            return False
        self.presses = [t for t in self.presses if now - t < 2.0] + [now]
        if len(self.presses) >= 3:
            self.presses = []
            return True
        return False


def _watch() -> None:
    escapes = EscCounter()
    while time.monotonic() - STATE.last_active < WATCH_SECONDS:
        try:
            reason = _user_override()
            if escapes.feed(_key_down(0x1B), time.monotonic(), STATE.ai_escape_until):
                reason = "Esc pressed three times"
            if reason and not STATE.aborted_at:
                abort(reason)
        except Exception:
            pass
        time.sleep(0.05)
    with STATE.lock:
        STATE.watcher = None


def _begin(kind: str) -> None:
    _check_abort()
    reason = _user_override()
    if reason:
        abort(reason)
        _check_abort()
    with STATE.lock:
        STATE.last_active = time.monotonic()
        STATE.last_turn = _turn_id() or STATE.last_turn
        if STATE.watcher is None and IS_WINDOWS:
            STATE.watcher = threading.Thread(target=_watch, name="nyx-computer-watch", daemon=True)
            STATE.watcher.start()


def _publish(event_type: str, **payload: Any) -> None:
    try:
        from agent_events import publish_ui

        publish_ui(event_type, **payload)
    except Exception:
        pass


def _record(kind: str, label: str, **fields: Any) -> None:
    action = {"kind": kind, "label": label, "at": time.time(), **{k: v for k, v in fields.items() if v is not None}}
    with STATE.lock:
        STATE.last_action = action
        STATE.actions = (STATE.actions + [action])[-30:]
    _publish("computer.action", **action)
    try:
        from tool_context import progress

        progress(label)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Overlay process
# ---------------------------------------------------------------------------


def _overlay_python() -> str:
    exe = Path(sys.executable)
    windowed = exe.with_name("pythonw.exe")
    return str(windowed if windowed.is_file() else exe)


def _overlay_send(command: Dict[str, Any]) -> None:
    if not IS_WINDOWS:
        return
    with STATE.lock:
        if command.get("op") != "hide" and not STATE.overlay_enabled:
            return
        proc = STATE.overlay
        if proc is None or proc.poll() is not None:
            if command.get("op") in {"hide", "quit"}:
                return
            try:
                proc = subprocess.Popen([_overlay_python(), str(Path(__file__).with_name("cursor_overlay.py"))],
                                        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        text=True, creationflags=_NO_WINDOW)
                STATE.overlay = proc
            except OSError:
                return
        try:
            proc.stdin.write(json.dumps(command) + "\n")  # type: ignore[union-attr]
            proc.stdin.flush()  # type: ignore[union-attr]
        except (OSError, ValueError):
            STATE.overlay = None


def set_overlay(enabled: bool) -> Dict[str, Any]:
    with STATE.lock:
        STATE.overlay_enabled = bool(enabled)
    if not enabled:
        _overlay_send({"op": "hide"})
    _publish("computer.state", active=False, overlay=bool(enabled))
    return state()


def state() -> Dict[str, Any]:
    bounds = screen_bounds()
    with _dpi_aware():
        x, y = _get_cursor()
    with STATE.lock:
        return {
            "active": time.monotonic() - STATE.last_active < 5 if STATE.last_active else False,
            "overlay": STATE.overlay_enabled,
            "cursor": {"x": x, "y": y},
            "screen": {"left": bounds["left"], "top": bounds["top"], "width": bounds["width"], "height": bounds["height"],
                       "monitors": bounds["monitors"]},
            "stopped": STATE.abort_reason or None,
            "last_action": STATE.last_action,
            "actions": list(STATE.actions),
        }


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


def _clamp(x: float, y: float) -> Tuple[int, int]:
    """Onto a real monitor (not the dead space between different-sized screens), never on a failsafe corner."""
    bounds = screen_bounds()
    monitors = bounds.get("monitors") or ([{"x": bounds["left"], "y": bounds["top"], "width": bounds["width"],
                                            "height": bounds["height"]}] if bounds["width"] else [])
    if not monitors:
        return int(x), int(y)
    best: Optional[Tuple[float, int, int]] = None
    for m in monitors:
        cx = int(round(min(max(x, m["x"]), m["x"] + m["width"] - 1)))
        cy = int(round(min(max(y, m["y"]), m["y"] + m["height"] - 1)))
        distance = (cx - x) ** 2 + (cy - y) ** 2
        if best is None or distance < best[0]:
            best = (distance, cx, cy)
    _, cx, cy = best  # type: ignore[misc]
    if _near_corner(cx, cy, failsafe_corners(bounds)):
        cx, cy = cx + 3, cy + 3
    return cx, cy


def glide(x: float, y: float, label: str = "", ms: int = GLIDE_MS) -> Tuple[int, int]:
    """Move the real cursor smoothly to (x, y), showing the AI cursor doing it."""
    tx, ty = _clamp(x, y)
    with _dpi_aware():
        sx, sy = _get_cursor()
        _overlay_send({"op": "move", "x": tx, "y": ty, "label": label, "ms": ms})
        steps = max(1, int(ms / 12))
        for i in range(1, steps + 1):
            _check_abort()
            k = 1 - (1 - i / steps) ** 3
            px, py = int(round(sx + (tx - sx) * k)), int(round(sy + (ty - sy) * k))
            _set_cursor(px, py)
            STATE.last_ai_pos = (px, py)
            if i < steps:
                time.sleep(ms / 1000.0 / steps)
    return tx, ty


def point_at(x: float, y: float, label: str = "") -> Tuple[int, int]:
    """Show a place with Nyx's own purple cursor only: the user's mouse and keyboard are not touched (Screen Share)."""
    tx, ty = _clamp(x, y)
    _overlay_send({"op": "move", "x": tx, "y": ty, "label": label or "Here", "ms": 420})
    _record("point", label or "Pointing", x=tx, y=ty)
    return tx, ty


def _mouse(flags: int, data: int = 0) -> Any:
    if not IS_WINDOWS:
        return None
    item = INPUT(type=0)
    item.mi = MOUSEINPUT(0, 0, ctypes.c_ulong(data & 0xFFFFFFFF).value, flags, 0, 0)
    return item


def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> Any:
    if not IS_WINDOWS:
        return None
    item = INPUT(type=1)
    if vk in _EXTENDED_VKS:
        flags |= EXTENDED
    item.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return item


def click(x: float, y: float, button: str = "left", double: bool = False, label: str = "") -> Tuple[int, int]:
    if button not in MOUSE_FLAGS:
        raise ComputerError("button must be left, right or middle.")
    _begin("click")
    label = label or f"{'Double-clicking' if double else 'Right-clicking' if button == 'right' else 'Clicking'}"
    tx, ty = glide(x, y, label)
    _overlay_send({"op": "click", "x": tx, "y": ty, "label": label, "ms": 0, "button": button})
    down, up = MOUSE_FLAGS[button]
    _check_abort()
    for _ in range(2 if double else 1):
        _send([_mouse(down), _mouse(up)])
        time.sleep(0.06)
    _record("click", label, x=tx, y=ty, button=button, double=double or None)
    return tx, ty


def drag(x1: float, y1: float, x2: float, y2: float, label: str = "Dragging") -> None:
    _begin("drag")
    glide(x1, y1, label)
    _check_abort()
    _send([_mouse(MOUSE_FLAGS["left"][0])])
    try:
        time.sleep(0.08)
        glide(x2, y2, label, ms=450)
    finally:
        _send([_mouse(MOUSE_FLAGS["left"][1])])  # never leave the button held down
    _record("drag", label, x=int(x2), y=int(y2), from_x=int(x1), from_y=int(y1))


def scroll(amount: int, x: Optional[float] = None, y: Optional[float] = None, horizontal: bool = False) -> None:
    _begin("scroll")
    label = f"Scrolling {'right' if horizontal and amount > 0 else 'left' if horizontal else 'down' if amount < 0 else 'up'}"
    if x is not None and y is not None:
        glide(x, y, label)
    clicks = max(-50, min(50, int(amount)))
    for _ in range(abs(clicks)):
        _check_abort()
        _send([_mouse(HWHEEL if horizontal else WHEEL, 120 if clicks > 0 else -120)])
        time.sleep(0.03)
    cx, cy = _get_cursor()
    _record("scroll", label, x=cx, y=cy, amount=clicks)


def type_text(text: str, label: str = "") -> int:
    _begin("type")
    cx, cy = _get_cursor()
    shown = label or f"Typing “{text[:24]}{'…' if len(text) > 24 else ''}”"
    _overlay_send({"op": "type", "x": cx, "y": cy, "label": shown, "ms": 0})
    count = 0
    for ch in text:
        _check_abort()
        if ch == "\n":
            _send([_key(0x0D), _key(0x0D, flags=KEYUP)])
        elif ch == "\t":
            _send([_key(0x09), _key(0x09, flags=KEYUP)])
        else:
            units = ch.encode("utf-16-le")
            for i in range(0, len(units), 2):
                code = int.from_bytes(units[i:i + 2], "little")
                _send([_key(0, code, UNICODE), _key(0, code, UNICODE | KEYUP)])
        count += 1
        time.sleep(TYPE_DELAY)
    _record("type", shown, x=cx, y=cy, text=text[:200])
    return count


def parse_keys(combo: str) -> List[int]:
    """'ctrl+shift+s' → [VK_CONTROL, VK_SHIFT, 'S']. Raises on unknown names."""
    parts = [p.strip().lower() for p in re.split(r"\s*\+\s*", (combo or "").strip()) if p.strip()]
    if not parts:
        raise ComputerError("Which keys? For example ctrl+s, alt+tab, enter, win+d.")
    codes = []
    for part in parts:
        if part not in VK:
            raise ComputerError(f"Unknown key {part!r}. Use names like ctrl, alt, shift, win, enter, esc, tab, f5, a-z, 0-9.")
        codes.append(VK[part])
    return codes


def _foreground_window() -> Optional[Dict[str, Any]]:
    if not IS_WINDOWS:
        return None
    return next((w for w in list_windows() if w["focused"]), None)


def press_keys(combo: str, repeat: int = 1) -> str:
    codes = parse_keys(combo)
    import self_guard

    refusal = self_guard.check_keys(combo, _foreground_window())
    if refusal:
        raise ComputerError(refusal)
    _begin("keys")
    if 0x1B in codes:
        STATE.ai_escape_until = time.monotonic() + 0.4 * max(1, repeat) + 0.3
    cx, cy = _get_cursor()
    label = f"Pressing {combo}"
    _overlay_send({"op": "type", "x": cx, "y": cy, "label": label, "ms": 0})
    for _ in range(max(1, min(50, int(repeat)))):
        _check_abort()
        modifiers = [c for c in codes[:-1] if c in _MODIFIERS] if len(codes) > 1 else []
        keys = [c for c in codes if c not in modifiers]
        sequence = [_key(m) for m in modifiers]
        for k in keys:
            sequence += [_key(k), _key(k, flags=KEYUP)]
        sequence += [_key(m, flags=KEYUP) for m in reversed(modifiers)]
        _send(sequence)
        time.sleep(0.05)
    _record("keys", label, x=cx, y=cy, text=combo)
    return label


# ---------------------------------------------------------------------------
# Screen
# ---------------------------------------------------------------------------


def grab_screen(region: Optional[Tuple[int, int, int, int]] = None) -> Tuple[Any, Tuple[int, int]]:
    """(PIL image, origin) of the whole virtual desktop or a region, in physical pixels."""
    from PIL import ImageGrab

    bounds = screen_bounds()
    with _dpi_aware():
        image = ImageGrab.grab(all_screens=True)
    origin = (bounds["left"], bounds["top"])
    if region:
        x, y, w, h = region
        box = (max(0, x - origin[0]), max(0, y - origin[1]), min(image.width, x - origin[0] + w), min(image.height, y - origin[1] + h))
        if box[2] <= box[0] or box[3] <= box[1]:
            raise ComputerError("That region is off the screen.")
        image = image.crop(box)
        origin = (origin[0] + box[0], origin[1] + box[1])
    return image, origin


def annotate(image: Any, origin: Tuple[int, int], cursor: Optional[Tuple[int, int]] = None, grid: bool = False) -> Any:
    """Draw the AI cursor and (for the model) a coordinate grid in real screen pixels."""
    from PIL import ImageDraw

    image = image.convert("RGB")
    draw = ImageDraw.Draw(image)
    if grid:
        step = 200 if max(image.width, image.height) > 1400 else 100
        start_x = ((origin[0] // step) + 1) * step
        for gx in range(start_x, origin[0] + image.width, step):
            px = gx - origin[0]
            draw.line([(px, 0), (px, image.height)], fill=(255, 0, 170), width=1)
            draw.text((px + 3, 3), str(gx), fill=(255, 0, 170))
        start_y = ((origin[1] // step) + 1) * step
        for gy in range(start_y, origin[1] + image.height, step):
            py = gy - origin[1]
            draw.line([(0, py), (image.width, py)], fill=(255, 0, 170), width=1)
            draw.text((3, py + 3), str(gy), fill=(255, 0, 170))
    if cursor:
        cx, cy = cursor[0] - origin[0], cursor[1] - origin[1]
        if 0 <= cx < image.width and 0 <= cy < image.height:
            arrow = [(cx, cy), (cx, cy + 26), (cx + 7, cy + 20), (cx + 12, cy + 31), (cx + 17, cy + 29), (cx + 12, cy + 18), (cx + 21, cy + 18)]
            draw.polygon(arrow, fill=(139, 92, 246), outline=(11, 11, 18))
    return image


def screenshot_jpeg(max_width: int = 1280, cursor: bool = True, grid: bool = False,
                    region: Optional[Tuple[int, int, int, int]] = None, quality: int = 80) -> Tuple[bytes, float, Tuple[int, int]]:
    """JPEG bytes, the scale applied, and the screen origin of pixel (0, 0)."""
    image, origin = grab_screen(region)
    with _dpi_aware():
        position = _get_cursor() if cursor else None
    image = annotate(image, origin, position, grid=grid)
    scale = 1.0
    if max_width and image.width > max_width:
        scale = max_width / image.width
        image = image.resize((max_width, max(1, int(image.height * scale))))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=quality)
    return buffer.getvalue(), scale, origin


def find_on_screen(description: str) -> Optional[Tuple[int, int]]:
    """Screen coordinates of a described control, via the ``ui_pointing`` model."""
    import vision

    data, scale, origin = screenshot_jpeg(max_width=1600, cursor=False)
    from PIL import Image

    width, height = Image.open(io.BytesIO(data)).size
    point = vision.locate_point(data, "image/jpeg", description)
    if point is None:
        return None
    return int(origin[0] + point[0] * width / scale), int(origin[1] + point[1] * height / scale)


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------


def list_windows() -> List[Dict[str, Any]]:
    if not IS_WINDOWS:
        return []
    import psutil

    found: List[Dict[str, Any]] = []
    foreground = user32.GetForegroundWindow()
    try:
        dwm = ctypes.WinDLL("dwmapi")
    except OSError:
        dwm = None

    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        if dwm is not None:
            cloaked = ctypes.c_int(0)
            dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
            if cloaked.value:
                return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            process = psutil.Process(pid.value).name()
        except Exception:
            process = ""
        found.append({"hwnd": int(hwnd), "title": buffer.value, "process": process, "pid": int(pid.value),
                      "x": rect.left, "y": rect.top, "width": rect.right - rect.left, "height": rect.bottom - rect.top,
                      "minimized": bool(user32.IsIconic(hwnd)), "focused": hwnd == foreground})
        return True

    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(callback)
    with _dpi_aware():
        user32.EnumWindows(proc, 0)
    return [w for w in found if w["title"] not in ("Program Manager",) and w["width"] > 1]


def _match_window(name: str) -> Dict[str, Any]:
    wanted = (name or "").strip().lower()
    if not wanted:
        raise ComputerError("Which window? Give part of its title or app name.")
    windows = list_windows()
    if wanted.isdigit():
        for window in windows:
            if window["hwnd"] == int(wanted):
                return window
    exact = [w for w in windows if w["title"].lower() == wanted or w["process"].lower() in (wanted, wanted + ".exe")]
    partial = [w for w in windows if wanted in w["title"].lower() or wanted in w["process"].lower()]
    matches = exact or partial
    # "chrome" matched by program name must not land on the tab Nyx itself lives in.
    import self_guard

    others = [w for w in matches if not self_guard.is_nyx_window(w)]
    if others and not any(mark in wanted for mark in self_guard.TITLE_MARKS):
        matches = others
    if not matches:
        raise ComputerError(f"No open window matches {name!r}. Open windows: "
                            + "; ".join(w["title"][:40] for w in windows[:12]))
    return matches[0]


def focus_window(name: str) -> Dict[str, Any]:
    window = _match_window(name)
    _begin("focus")
    hwnd = window["hwnd"]
    if IS_WINDOWS:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)
        # Windows only lets the foreground app hand over focus; a synthetic Alt tap satisfies that rule.
        _send([_key(0x12), _key(0x12, flags=KEYUP)])
        user32.SetForegroundWindow(hwnd)
    _record("focus", f"Switching to {window['title'][:40]}", x=window["x"] + window["width"] // 2, y=window["y"] + 20)
    return window


def window_action(name: str, action: str, x: Optional[int] = None, y: Optional[int] = None,
                  width: Optional[int] = None, height: Optional[int] = None) -> str:
    window = _match_window(name)
    act = (action or "").lower()
    import self_guard

    refusal = self_guard.check_window_action(window, act)
    if refusal:
        raise ComputerError(refusal)
    commands = {"minimize": 6, "maximize": 3, "restore": 9}
    _begin("window")
    hwnd = window["hwnd"]
    if act in commands:
        if IS_WINDOWS:
            user32.ShowWindow(hwnd, commands[act])
    elif act == "close":
        if IS_WINDOWS:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)
    elif act in ("move", "resize"):
        nx = window["x"] if x is None else int(x)
        ny = window["y"] if y is None else int(y)
        nw = window["width"] if width is None else int(width)
        nh = window["height"] if height is None else int(height)
        if IS_WINDOWS:
            with _dpi_aware():
                user32.ShowWindow(hwnd, 9)
                user32.MoveWindow(hwnd, nx, ny, nw, nh, True)
    else:
        raise ComputerError("action must be minimize, maximize, restore, close, move or resize.")
    label = f"{act.capitalize()} {window['title'][:40]}"
    _record("window", label, x=window["x"] + window["width"] // 2, y=window["y"] + 20)
    return label


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def _tool(fn: Any) -> str:
    if not IS_WINDOWS:
        return "Error: computer control works on Windows only."
    try:
        return fn()
    except ComputerAborted as error:
        return f"Stopped: {error}"
    except ComputerError as error:
        return f"Error: {error}"


def _region(value: Any) -> Optional[Tuple[int, int, int, int]]:
    if not value:
        return None
    numbers = [int(float(n)) for n in re.findall(r"-?\d+(?:\.\d+)?", str(value))]
    if len(numbers) != 4 or numbers[2] <= 0 or numbers[3] <= 0:
        raise ComputerError("region must be x,y,width,height in screen pixels.")
    return numbers[0], numbers[1], numbers[2], numbers[3]


def tool_screen_view(region: str = "", grid: bool = True) -> str:
    def run() -> str:
        from tool_context import attach_image

        _check_abort()
        box = _region(region)
        data, scale, origin = screenshot_jpeg(max_width=1600 if box else 1280, cursor=True, grid=grid, region=box)
        bounds = screen_bounds()
        # attach_image also shows the picture in the chat timeline (tool.image).
        shown = attach_image(data, "image/jpeg", name="screen.jpg",
                             note=f"Screen {bounds['width']}×{bounds['height']} px. Grid labels are real screen coordinates; "
                                  f"use them directly for mouse_click x/y.")
        _record("screenshot", "Looking at the screen" if not box else "Zooming in", x=origin[0], y=origin[1])
        cx, cy = _get_cursor()
        focus = next((w for w in list_windows() if w["focused"]), None)
        where = f" Focused window: {focus['title']} ({focus['process']})." if focus else ""
        if not shown:
            return ("Captured the screen but could not attach it in this context; use find_on_screen to locate things."
                    + where)
        return (f"Showing the screen{' region ' + region if box else ''} now (desktop {bounds['width']}×{bounds['height']}, "
                f"mouse at {cx},{cy}).{where} Coordinates on the grid are screen pixels.")
    return _tool(run)


def tool_find_on_screen(description: str) -> str:
    def run() -> str:
        _check_abort()
        try:
            point = find_on_screen(description)
        except Exception as error:  # noqa: BLE001 - vision model unavailable
            return f"Error: could not look for it ({error}). Try screen_view and read the grid coordinates."
        _record("find", f"Looking for {description[:40]}")
        if point is None:
            return f"Not visible on screen: {description}."
        return f"Found {description} at x={point[0]}, y={point[1]}."
    return _tool(run)


def tool_mouse_move(x: float, y: float) -> str:
    def run() -> str:
        _begin("move")
        tx, ty = glide(float(x), float(y), "Moving")
        _record("move", "Moving", x=tx, y=ty)
        return f"Mouse at {tx},{ty}."
    return _tool(run)


def tool_mouse_click(x: Any = None, y: Any = None, target: str = "", button: str = "left", double: bool = False) -> str:
    def run() -> str:
        if target and (x is None or y is None):
            point = find_on_screen(target)
            if point is None:
                return f"Not clicked: {target!r} is not visible. Look with screen_view first."
            px, py, label = point[0], point[1], f"Clicking {target[:32]}"
        elif x is not None and y is not None:
            px, py, label = float(x), float(y), ""
        else:
            return "Error: give x and y, or a target description."
        tx, ty = click(px, py, button=button or "left", double=bool(double), label=label)
        return f"{'Double-clicked' if double else 'Clicked'} {button or 'left'} at {tx},{ty}" + (f" ({target})" if target else "") + \
            ". Check the result with screen_view before the next step."
    return _tool(run)


def tool_mouse_drag(from_x: float, from_y: float, to_x: float, to_y: float) -> str:
    def run() -> str:
        drag(float(from_x), float(from_y), float(to_x), float(to_y))
        return f"Dragged from {int(from_x)},{int(from_y)} to {int(to_x)},{int(to_y)}."
    return _tool(run)


def tool_mouse_scroll(amount: int = -5, x: Any = None, y: Any = None, horizontal: bool = False) -> str:
    def run() -> str:
        scroll(int(amount), None if x is None else float(x), None if y is None else float(y), bool(horizontal))
        return f"Scrolled {abs(int(amount))} notches {'horizontally' if horizontal else 'down' if int(amount) < 0 else 'up'}."
    return _tool(run)


def tool_keyboard_type(text: str) -> str:
    def run() -> str:
        count = type_text(str(text))
        return f"Typed {count} characters into the focused window."
    return _tool(run)


def tool_keyboard_keys(keys: str, repeat: int = 1) -> str:
    def run() -> str:
        press_keys(keys, int(repeat or 1))
        return f"Pressed {keys}" + (f" ×{repeat}" if int(repeat or 1) > 1 else "") + "."
    return _tool(run)


def tool_list_windows() -> str:
    def run() -> str:
        windows = list_windows()
        if not windows:
            return "No windows are open."
        return "\n".join(f"- {'▶ ' if w['focused'] else ''}{w['title'][:70]} [{w['process']}] "
                         f"at {w['x']},{w['y']} {w['width']}×{w['height']}{' (minimized)' if w['minimized'] else ''}"
                         for w in windows[:40])
    return _tool(run)


def tool_focus_window(name: str) -> str:
    return _tool(lambda: f"Focused {focus_window(name)['title']}.")


def tool_window_action(name: str, action: str, x: Any = None, y: Any = None, width: Any = None, height: Any = None) -> str:
    return _tool(lambda: window_action(name, action, x, y, width, height) + ".")


def register_computer_tools(registry: Any) -> None:
    from tools import ToolParam as P

    def reg(name, description, params, handler, category, label):
        registry.register(name, description, params, handler, category=category, label=label)

    reg("screen_view", "Look at the screen (all monitors) with a coordinate grid in real screen pixels, the AI cursor "
        "and the focused window. Use before and after clicking. region=x,y,width,height zooms in to read small text.",
        [P("region", "string", "Optional x,y,width,height to zoom into", required=False),
         P("grid", "boolean", "Draw the coordinate grid (default true)", required=False)],
        tool_screen_view, "computer", lambda a: "Zooming in on the screen" if a.get("region") else "Looking at the screen")
    reg("find_on_screen", "Find a button, field, icon or text on screen by description; returns its x,y.",
        [P("description", "string", "What to find, e.g. 'the blue Send button'")],
        tool_find_on_screen, "computer", lambda a: f"Finding {str(a.get('description', ''))[:40]}")
    reg("mouse_move", "Glide the mouse to x,y (screen pixels).",
        [P("x", "number", "Screen x"), P("y", "number", "Screen y")], tool_mouse_move, "computer", "Moving the mouse")
    reg("mouse_click", "Click at x,y — or at a described target (found on screen). The user sees the AI cursor do it.",
        [P("x", "number", "Screen x", required=False), P("y", "number", "Screen y", required=False),
         P("target", "string", "Or describe what to click", required=False),
         P("button", "string", "left, right or middle", required=False, enum_values=["left", "right", "middle"]),
         P("double", "boolean", "Double-click", required=False)],
        tool_mouse_click, "computer",
        lambda a: f"Clicking {a['target'][:40]}" if a.get("target") else f"Clicking at {a.get('x')},{a.get('y')}")
    reg("mouse_drag", "Press, drag and release the left button from one point to another.",
        [P("from_x", "number", "Start x"), P("from_y", "number", "Start y"), P("to_x", "number", "End x"), P("to_y", "number", "End y")],
        tool_mouse_drag, "computer", "Dragging")
    reg("mouse_scroll", "Scroll the wheel (negative = down/left), optionally over x,y first.",
        [P("amount", "number", "Notches; -5 scrolls down five"), P("x", "number", "Over x", required=False),
         P("y", "number", "Over y", required=False), P("horizontal", "boolean", "Scroll sideways", required=False)],
        tool_mouse_scroll, "computer", "Scrolling")
    reg("keyboard_type", "Type text into the focused window (any language, emoji; \\n presses Enter).",
        [P("text", "string", "Text to type")], tool_keyboard_type, "computer",
        lambda a: f"Typing “{str(a.get('text', ''))[:30]}”")
    reg("keyboard_keys", "Press a key or shortcut: enter, esc, tab, ctrl+s, alt+tab, win+d, ctrl+shift+esc, f5…",
        [P("keys", "string", "Key combo joined with +"), P("repeat", "number", "Times to press (default 1)", required=False)],
        tool_keyboard_keys, "computer", lambda a: f"Pressing {a.get('keys', '')}")
    reg("list_windows", "List open windows with titles, apps, positions and which one has focus.", [],
        tool_list_windows, "windows", "Listing windows")
    reg("focus_window", "Bring a window to the front by part of its title or app name.",
        [P("name", "string", "Title or app, e.g. 'Chrome' or 'Untitled - Notepad'")],
        tool_focus_window, "windows", lambda a: f"Switching to {a.get('name', '')}")
    reg("window_action", "Minimize, maximize, restore, close, move or resize a window.",
        [P("name", "string", "Title or app"),
         P("action", "string", "What to do", enum_values=["minimize", "maximize", "restore", "close", "move", "resize"]),
         P("x", "number", "New x (move)", required=False), P("y", "number", "New y (move)", required=False),
         P("width", "number", "New width (resize)", required=False), P("height", "number", "New height (resize)", required=False)],
        tool_window_action, "windows", lambda a: f"{str(a.get('action', '')).capitalize()} {a.get('name', '')}")
