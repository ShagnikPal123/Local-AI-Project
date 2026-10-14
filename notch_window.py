"""The Equalize notch's desktop window — its own process, outside the browser (owner, 2026-10-10/11).

A frameless, transparent, always-on-top WebView2 window (pywebview, already installed — no download) at the top
centre of the main screen, showing ``/notch`` from the engine. Coucou keeps a fixed panel and toggles click-through
at 60 Hz; here the window simply *is* the island: the page reports the island's size (``set_hit``) and the window
grows to it at once and shrinks after the closing animation, so everything outside the island reaches the apps
below. The page also reports the black shapes it draws (``set_shape``) and the window is clipped to exactly those,
so no backing colour can show around the island (the "white box"). It never shows a taskbar button, hides while a full-screen game or video owns the screen, and feeds the
cursor position into the page so Io's eyes follow the pointer anywhere on screen.

Run by notch.py: ``pythonw notch_window.py http://127.0.0.1:8000/notch``. The owner's session arrives in the
``ICHOS_NOTCH_TOKEN`` environment variable and is handed to the page through the bridge, never in the URL.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import time
import urllib.request

TITLE = "Ichos notch"
TOKEN = os.environ.pop("ICHOS_NOTCH_TOKEN", "")
URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/notch"
BASE = URL.rsplit("/notch", 1)[0]

user32 = ctypes.windll.user32 if sys.platform == "win32" else None
if user32 is not None:
    from ctypes import wintypes

    # HWND_TOPMOST is (HWND)-1: without these the -1 goes in as a 32-bit int and SetWindowPos refuses it on 64-bit.
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_uint]
    user32.FindWindowW.restype = wintypes.HWND
GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = -20, 0x80, 0x40000
HWND_TOPMOST = ctypes.c_void_p(-1)
SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x0010, 0x0040

_target = {"w": 240, "h": 6}
_shown = {"w": 240, "h": 6}
#: The black shapes the page draws (island, ears, pills), in CSS pixels. The window is clipped to them.
_shapes: list = []
_lock = threading.Lock()
_window = None
_quit = threading.Event()


LOG = os.path.join(os.environ.get("LOCALAPPDATA", "."), "Ichos", "notch", "notch.log")


def _log(text: str) -> None:
    """A short trail for troubleshooting the window (sizes it was asked for and got)."""
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as handle:
            print(time.strftime("%H:%M:%S"), text, file=handle)
    except OSError:
        pass


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _hwnd() -> int:
    return int(user32.FindWindowW(None, TITLE) or 0) if user32 else 0


def _scale(hwnd: int) -> float:
    try:
        return max(1.0, user32.GetDpiForWindow(hwnd) / 96.0)
    except Exception:  # noqa: BLE001
        return 1.0


def _screen_width() -> int:
    return int(user32.GetSystemMetrics(0)) if user32 else 1920


def _place(width: float, height: float) -> None:
    """Size the window to ``width`` x ``height`` CSS pixels, centred at the top of the main screen."""
    hwnd = _hwnd()
    if not hwnd:
        return
    scale = _scale(hwnd)
    w, h = max(1, int(round(width * scale))), max(1, int(round(height * scale)))
    x = (_screen_width() - w) // 2
    ok = user32.SetWindowPos(hwnd, HWND_TOPMOST, x, 0, w, h, SWP_NOACTIVATE | SWP_SHOWWINDOW)
    _shown.update(w=width, h=height)
    _log(f"place {w}x{h} at {x} ok={ok}")


# ── The white box (owner, Fixer Upper S34: "a white outline around it like a white box of where the UI goes") ──
#
# pywebview's ``transparent=True`` on Windows makes the WebView2 page see-through but skips the form's background
# colour, so wherever the page is transparent (the 14 px beside the island, under its rounded corners, the gap
# between the trio pills) the form's default light grey shows. Instead of trusting the window's transparency, the
# window is clipped to the black shapes the page actually draws: nothing outside them is part of the window at all,
# so nothing can show there and clicks go straight to the apps below.

EAR = 14  # the concave "ears" beside the island (.nx-island::before/::after in notch.css)


def _clean_shape(raw: dict) -> dict:
    """One shape from the page, as plain numbers. Unknown kinds become plain rounded boxes."""
    kind = str(raw.get("kind") or "box")
    num = lambda key: max(0.0, float(raw.get(key) or 0))  # noqa: E731
    return {"kind": kind if kind in ("island", "box") else "box", "x": float(raw.get("x") or 0), "y": float(raw.get("y") or 0),
            "w": num("w"), "h": num("h"), "r": num("r")}


def region_plan(shapes: list, scale: float = 1.0) -> list:
    """The GDI steps that build the window's outline: ``("add", kind, x1, y1, x2, y2, rx, ry)`` adds a shape,
    ``("cut", x1, y1, x2, y2)`` removes an ellipse (the inside of an ear). Device pixels.

    Curved edges sit one pixel inside the page's own anti-aliased edge, so the half-see-through pixels of the curve
    never reach the window's backing colour (that was the faint light rim).
    """
    steps: list = []
    s = max(1.0, float(scale))
    px = lambda v: int(round(v * s))  # noqa: E731
    for shape in shapes:
        x, y, w, h, r = shape["x"], shape["y"], shape["w"], shape["h"], shape["r"]
        if w < 1 or h < 1:
            continue
        if shape["kind"] == "island":
            # The island hangs from the top edge: square top corners (extend the round box above the window),
            # rounded bottom corners, and an ear on each side that curves into the top of the screen.
            d = px(2 * r)
            steps.append(("add", "round", px(x) + 1, px(y) - d, px(x + w) - 1, px(y + h) - 1, d, d))
            if r:
                # Each ear is a square minus a circle centred on its outer bottom corner (one pixel wider).
                e, top, left, right = px(EAR), px(y), px(x), px(x + w)
                steps.append(("add", "rect", left - e, top, left + 1, top + e))
                steps.append(("cut", left - 2 * e - 1, top - 1, left + 1, top + 2 * e + 1))
                steps.append(("add", "rect", right - 1, top, right + e, top + e))
                steps.append(("cut", right - 1, top - 1, right + 2 * e + 1, top + 2 * e + 1))
        else:
            d = px(2 * min(r, w / 2, h / 2))
            steps.append(("add", "round", px(x), px(y), px(x + w), px(y + h), d, d))
    return steps


def _apply_region(hwnd: int, shapes: list, gdi32=None, user=None) -> bool:
    """Clip the window to ``shapes``. No shapes means no clipping (an older page that does not report them)."""
    user = user or user32
    if not hwnd or user is None:
        return False
    if not shapes:
        user.SetWindowRgn(hwnd, None, True)
        return True
    gdi32 = gdi32 or ctypes.windll.gdi32
    RGN_OR, RGN_DIFF = 2, 4
    total = gdi32.CreateRectRgn(0, 0, 0, 0)
    for step in region_plan(shapes, _scale(hwnd)):
        if step[0] == "add":
            _, kind, x1, y1, x2, y2, *radii = step
            part = gdi32.CreateRoundRectRgn(x1, y1, x2, y2, *radii) if kind == "round" else gdi32.CreateRectRgn(x1, y1, x2, y2)
            gdi32.CombineRgn(total, total, part, RGN_OR)
        else:
            _, x1, y1, x2, y2 = step
            part = gdi32.CreateEllipticRgn(x1, y1, x2, y2)
            gdi32.CombineRgn(total, total, part, RGN_DIFF)
        gdi32.DeleteObject(part)
    # The window owns the region from here on (it frees it), so it is not deleted.
    return bool(user.SetWindowRgn(hwnd, total, True))


def _no_frame(hwnd: int) -> None:
    """Windows 11 rounds and outlines every top-level window with a 1 px border; the notch draws its own shape."""
    try:
        dwm = ctypes.windll.dwmapi
        for attribute, value in ((33, 1), (34, 0xFFFFFFFE)):  # corner: do not round · border colour: none
            dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(ctypes.c_uint(value)), 4)
    except Exception:  # noqa: BLE001 - Windows 10 has neither attribute; nothing to remove there
        pass


def _fullscreen_app_running() -> bool:
    """A game, video or presentation owns the screen (SHQueryUserNotificationState: busy / D3D / presentation)."""
    try:
        value = ctypes.c_int(0)
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(value)) != 0:
            return False
        return value.value in (2, 3, 4)
    except Exception:  # noqa: BLE001
        return False


def _post(path: str, body: dict) -> None:
    request = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {})})
    try:
        urllib.request.urlopen(request, timeout=5).read()  # noqa: S310 - our own engine on loopback
    except Exception:  # noqa: BLE001
        pass


class Bridge:
    """What the page can ask of this window (window.pywebview.api.*)."""

    def token(self) -> str:
        return TOKEN

    def set_hit(self, x: float, y: float, w: float, h: float) -> None:  # noqa: ARG002 - x/y: the page centres itself
        with _lock:
            if (_target["w"], _target["h"]) != (float(w), float(h)):
                _log(f"page asks {w}x{h}")
            _target.update(w=max(1.0, float(w)), h=max(1.0, float(h)))

    def set_shape(self, shapes: list) -> None:
        """The black shapes on the page right now (sent while they move, so the outline follows the animation)."""
        try:
            cleaned = [_clean_shape(raw) for raw in list(shapes or [])[:12] if isinstance(raw, dict)]
        except (TypeError, ValueError):
            return
        with _lock:
            _shapes[:] = cleaned

    def open_app(self, tab: str = "chat") -> None:
        threading.Thread(target=_post, args=("/api/notch/open-app", {"tab": str(tab)[:40]}), daemon=True).start()

    def hide(self) -> None:
        _quit.set()
        if _window is not None:
            _window.destroy()


def _watch() -> None:
    """Grow at once, shrink after the closing animation; hide for full-screen apps; feed the cursor to the page."""
    hwnd = 0
    while not hwnd and not _quit.is_set():
        time.sleep(0.1)
        hwnd = _hwnd()
    if not hwnd:
        return
    time.sleep(0.5)  # let pywebview finish styling the window first
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
    _no_frame(hwnd)
    _place(_target["w"], _target["h"])  # also puts it back on top
    clipped_to: list = []
    shrink_at = 0.0
    hidden_for_fullscreen = False
    last_cursor = (-1, -1)
    last_check = 0.0
    while not _quit.is_set():
        now = time.time()
        with _lock:
            want = dict(_target)
            shapes = list(_shapes)
        if shapes != clipped_to:
            _apply_region(hwnd, shapes)
            clipped_to = shapes
        if want["w"] >= _shown["w"] and want["h"] >= _shown["h"]:
            if want != _shown:
                _place(want["w"], want["h"])
            shrink_at = 0.0
        elif not shrink_at:
            # Grow whichever side grew now; shrink the rest once the island has finished closing.
            _place(max(want["w"], _shown["w"]), max(want["h"], _shown["h"]))
            shrink_at = now + 0.42
        elif now >= shrink_at:
            _place(want["w"], want["h"])
            shrink_at = 0.0
        if now - last_check > 1.0:
            last_check = now
            busy = _fullscreen_app_running()
            if busy != hidden_for_fullscreen:
                hidden_for_fullscreen = busy
                user32.ShowWindow(hwnd, 0 if busy else 4)  # SW_HIDE / SW_SHOWNOACTIVATE
        point = POINT()
        if user32.GetCursorPos(ctypes.byref(point)) and (point.x, point.y) != last_cursor and _window is not None:
            last_cursor = (point.x, point.y)
            scale = _scale(hwnd)
            left = (_screen_width() - _shown["w"] * scale) / 2
            x, y = (point.x - left) / scale, point.y / scale
            try:
                _window.run_js(f"window.__notchCursor && window.__notchCursor({x:.0f}, {y:.0f})")
            except Exception:  # noqa: BLE001 - the page is still loading
                pass
        time.sleep(1 / 30)


MODS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}


def parse_hotkey(text: str) -> tuple:
    """'Ctrl+Alt+Space' -> (modifiers, virtual key). Unknown keys fall back to Ctrl+Alt+Space."""
    mods, key = 0, 0
    for part in [p.strip().lower() for p in str(text or "").split("+") if p.strip()]:
        if part in MODS:
            mods |= MODS[part]
        elif part == "space":
            key = 0x20
        elif len(part) == 1 and part.isalnum():
            key = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 12:
            key = 0x6F + int(part[1:])
    return (mods, key) if mods and key else (0x3, 0x20)


def _hotkey_loop(text: str) -> None:
    """Ctrl+Alt+Space (or the owner's own) from any app: bring the notch forward on its chat."""
    from ctypes import wintypes

    mods, key = parse_hotkey(text)
    if not user32.RegisterHotKey(None, 1, mods | 0x4000, key):  # MOD_NOREPEAT
        _log(f"hotkey {text} is taken by another app")
        return
    message = wintypes.MSG()
    while not _quit.is_set() and user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
        if message.message == 0x0312 and _window is not None:  # WM_HOTKEY
            hwnd = _hwnd()
            if hwnd:
                user32.SetForegroundWindow(hwnd)
            try:
                _window.run_js("window.__notchHotkey && window.__notchHotkey()")
            except Exception:  # noqa: BLE001
                pass


def _hotkey_setting() -> str:
    try:
        request = urllib.request.Request(BASE + "/api/equalize/assistant",
                                         headers={"Authorization": f"Bearer {TOKEN}"} if TOKEN else {})
        settings = json.loads(urllib.request.urlopen(request, timeout=5).read())["settings"]  # noqa: S310
        activation = settings.get("activation") or {}
        return activation.get("hotkey", "Ctrl+Alt+Space") if "hotkey" in (activation.get("gestures") or []) else ""
    except Exception:  # noqa: BLE001
        return "Ctrl+Alt+Space"


def main() -> None:
    global _window
    # WebView2 paints white until the page's own transparent background arrives; a transparent default means no white
    # flash or box even before the window clip (set_shape) is in place.
    os.environ.setdefault("WEBVIEW2_DEFAULT_BACKGROUND_COLOR", "00000000")
    import webview

    try:
        if os.path.getsize(LOG) > 200_000:
            os.remove(LOG)
    except OSError:
        pass
    width = _screen_width()
    _window = webview.create_window(TITLE, URL, js_api=Bridge(), width=240, height=6, x=(width - 240) // 2, y=0,
                                    frameless=True, transparent=True, on_top=True, resizable=True, easy_drag=False,
                                    min_size=(1, 1), background_color="#000000", shadow=False)
    threading.Thread(target=_watch, name="notch-watch", daemon=True).start()
    hotkey = _hotkey_setting()
    if hotkey and user32 is not None:
        threading.Thread(target=_hotkey_loop, args=(hotkey,), name="notch-hotkey", daemon=True).start()
    webview.start(private_mode=False, storage_path=os.path.join(os.environ.get("LOCALAPPDATA", "."), "Ichos", "notch"))


if __name__ == "__main__":
    main()
