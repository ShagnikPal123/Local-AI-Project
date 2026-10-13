"""The Equalize notch's desktop window — its own process, outside the browser (owner, 2026-10-10/11).

A frameless, transparent, always-on-top WebView2 window (pywebview, already installed — no download) at the top
centre of the main screen, showing ``/notch`` from the engine. Coucou keeps a fixed panel and toggles click-through
at 60 Hz; here the window simply *is* the island: the page reports the island's size (``set_hit``) and the window
grows to it at once and shrinks after the closing animation, so everything outside the island reaches the apps
below. It never shows a taskbar button, hides while a full-screen game or video owns the screen, and feeds the
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
    _place(_target["w"], _target["h"])  # also puts it back on top
    shrink_at = 0.0
    hidden_for_fullscreen = False
    last_cursor = (-1, -1)
    last_check = 0.0
    while not _quit.is_set():
        now = time.time()
        with _lock:
            want = dict(_target)
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


def main() -> None:
    global _window
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
    webview.start(private_mode=False, storage_path=os.path.join(os.environ.get("LOCALAPPDATA", "."), "Ichos", "notch"))


if __name__ == "__main__":
    main()
