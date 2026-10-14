"""The hands-off sidebar's desktop window: its own process, like the notch (Fixer Upper S2, reference p38).

A frameless, always-on-top WebView2 window (pywebview) docked to the left or right edge of the main screen, showing
``/sidebar`` from the engine: a menu of the app's tabs, a search box that asks the assistant, and the hands-off
switch. In hands-off mode the AI picks the tab and the sidebar lights it up as it opens.

The owner (S2): "The sidebar and notch can be dragged and locked onto a part of the screen." Pressing the grip at the
top of the page starts a drag: the window follows the mouse until the button is let go, then snaps to the nearest
edge when it is close to one (otherwise it floats where it was dropped) and the spot is saved through
``/api/notch/place/sidebar``. A locked sidebar does not move.

Run by notch.py: ``pythonw sidebar_window.py http://127.0.0.1:8000/sidebar``. The owner's session arrives in the
``ICHOS_SIDEBAR_TOKEN`` environment variable and is handed to the page through the bridge, never in the URL.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import time
import urllib.request

import notch_window as nw

TITLE = "Ichos sidebar"
TOKEN = os.environ.pop("ICHOS_SIDEBAR_TOKEN", "")
URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/sidebar"
BASE = URL.rsplit("/sidebar", 1)[0]

user32 = nw.user32
SNAP = 40  # CSS px: dropped this close to a side, it docks to that side
RADIUS = 18  # the page's own corner radius (.sb-root in sidebar.css)
SIZES = {"open": (264, 600), "collapsed": (64, 600)}

_place = {"edge": "right", "x": 0, "y": 96, "locked": False, "collapsed": False}
_size = {"w": SIZES["open"][0], "h": SIZES["open"][1]}
_drag = {"on": False, "dx": 0, "dy": 0}
_lock = threading.Lock()
_window = None
_quit = threading.Event()


def _screen() -> tuple:
    return (int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))) if user32 else (1920, 1080)


def spot(place: dict, screen_w: int, screen_h: int, w: float, h: float, scale: float) -> tuple:
    """Where the window's top-left corner goes (device px) for a saved ``place`` and a window of ``w`` x ``h`` CSS px.
    Docked windows sit 12 px off their edge; every spot is kept fully on screen."""
    scale = max(1.0, scale)
    dw, dh, gap = int(round(w * scale)), int(round(h * scale)), int(round(12 * scale))
    if place.get("edge") == "left":
        x = gap
    elif place.get("edge") == "free":
        x = int(round(float(place.get("x") or 0) * scale))
    else:
        x = screen_w - dw - gap
    y = int(round(float(place.get("y") or 0) * scale))
    return max(0, min(screen_w - dw, x)), max(0, min(screen_h - dh, y))


def dropped(left: int, top: int, screen_w: int, screen_h: int, w: float, h: float, scale: float) -> dict:
    """The place to save for a window let go with its top-left at ``left``, ``top`` (device px): docked to a side when
    it is within SNAP of it, floating otherwise. Saved in CSS px so it survives a change of display scale."""
    scale = max(1.0, scale)
    dw, dh = w * scale, h * scale
    top = max(0, min(screen_h - dh, top))
    y = round(top / scale)
    if left <= SNAP * scale:
        return {"edge": "left", "y": y}
    if screen_w - (left + dw) <= SNAP * scale:
        return {"edge": "right", "y": y}
    return {"edge": "free", "x": round(max(0, min(screen_w - dw, left)) / scale), "y": y}


def _hwnd() -> int:
    return int(user32.FindWindowW(None, TITLE) or 0) if user32 else 0


def _move(left: int = None, top: int = None) -> None:  # type: ignore[assignment]
    """Put the window at its saved place (or at ``left``, ``top`` while dragging), sized and clipped to the page."""
    hwnd = _hwnd()
    if not hwnd:
        return
    scale = nw._scale(hwnd)
    with _lock:
        w, h, place = _size["w"], _size["h"], dict(_place)
    if left is None or top is None:
        sw, sh = _screen()
        left, top = spot(place, sw, sh, w, h, scale)
    user32.SetWindowPos(hwnd, nw.HWND_TOPMOST, int(left), int(top), int(round(w * scale)), int(round(h * scale)),
                        nw.SWP_NOACTIVATE | nw.SWP_SHOWWINDOW)
    nw._apply_region(hwnd, [{"kind": "box", "x": 0, "y": 0, "w": w, "h": h, "r": RADIUS}])


def _request(path: str, body: dict = None) -> dict:  # type: ignore[assignment]
    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
    data = None
    if body is not None:
        data, headers = json.dumps(body).encode(), {**headers, "Content-Type": "application/json"}
    request = urllib.request.Request(BASE + path, data=data, method="POST" if body is not None else "GET",
                                     headers=headers)
    return json.loads(urllib.request.urlopen(request, timeout=5).read() or b"{}")  # noqa: S310 - our own engine


def _save(changes: dict) -> None:
    try:
        _request("/api/notch/place/sidebar", changes)
    except Exception:  # noqa: BLE001 - the engine is restarting; the next drag saves it
        pass


def _follow_settings() -> None:
    """A side or lock picked in Equalize (Notch controls) applies to the open window without a restart."""
    if _drag["on"]:
        return
    try:
        saved = _request("/api/notch/place/sidebar")
    except Exception:  # noqa: BLE001
        return
    with _lock:
        changed = any(saved.get(k) != _place[k] for k in ("edge", "x", "y", "locked") if k in saved)
        _place.update({k: saved[k] for k in ("edge", "x", "y", "locked") if k in saved})
    if changed:
        _move()


class Bridge:
    """What the page can ask of this window (window.pywebview.api.*)."""

    def token(self) -> str:
        return TOKEN

    def place(self) -> dict:
        with _lock:
            return dict(_place)

    def drag_start(self) -> bool:
        """The grip was pressed: follow the mouse until the button is let go."""
        hwnd = _hwnd()
        if _place["locked"] or not hwnd:
            return False
        point, rect = nw.POINT(), (ctypes.c_long * 4)()
        user32.GetCursorPos(ctypes.byref(point))
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        _drag.update(on=True, dx=point.x - rect[0], dy=point.y - rect[1])
        return True

    def set_lock(self, locked: bool) -> bool:
        with _lock:
            _place["locked"] = bool(locked)
        threading.Thread(target=_save, args=({"locked": bool(locked)},), daemon=True).start()
        return bool(locked)

    def set_collapsed(self, collapsed: bool) -> bool:
        """Fold to a strip of icons, or open to the full menu; the window follows the page's size."""
        with _lock:
            _place["collapsed"] = bool(collapsed)
            _size["w"], _size["h"] = SIZES["collapsed" if collapsed else "open"]
        _move()
        threading.Thread(target=_save, args=({"collapsed": bool(collapsed)},), daemon=True).start()
        return bool(collapsed)

    def hide(self) -> None:
        _quit.set()
        threading.Thread(target=_request, args=("/api/notch/sidebar/stop", {}), daemon=True).start()
        if _window is not None:
            _window.destroy()


def _watch() -> None:
    """Style the window once, then follow the mouse during a drag and hide for full-screen apps."""
    hwnd = 0
    while not hwnd and not _quit.is_set():
        time.sleep(0.1)
        hwnd = _hwnd()
    if not hwnd:
        return
    time.sleep(0.5)  # let pywebview finish styling the window first
    style = user32.GetWindowLongW(hwnd, nw.GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, nw.GWL_EXSTYLE, (style | nw.WS_EX_TOOLWINDOW) & ~nw.WS_EX_APPWINDOW)
    nw._no_frame(hwnd)
    _move()
    hidden_for_fullscreen = False
    last_check = 0.0
    while not _quit.is_set():
        if _drag["on"]:
            point = nw.POINT()
            user32.GetCursorPos(ctypes.byref(point))
            left, top = point.x - _drag["dx"], point.y - _drag["dy"]
            if user32.GetAsyncKeyState(0x01) & 0x8000:
                _move(left, top)
            else:  # let go: dock or float, then remember it
                _drag["on"] = False
                sw, sh = _screen()
                with _lock:
                    changes = dropped(left, top, sw, sh, _size["w"], _size["h"], nw._scale(hwnd))
                    _place.update(changes)
                _move()
                threading.Thread(target=_save, args=(changes,), daemon=True).start()
        now = time.time()
        if now - last_check > 1.0:
            last_check = now
            nw._no_frame(hwnd)  # pywebview turns the backdrop back on after a dark/light switch
            _follow_settings()
            busy = nw._fullscreen_app_running()
            if busy != hidden_for_fullscreen:
                hidden_for_fullscreen = busy
                user32.ShowWindow(hwnd, 0 if busy else 4)  # SW_HIDE / SW_SHOWNOACTIVATE
        time.sleep(1 / 60 if _drag["on"] else 1 / 10)


def main() -> None:
    global _window
    import webview

    try:
        _place.update({k: v for k, v in _request("/api/notch/place/sidebar").items() if k in _place})
    except Exception:  # noqa: BLE001 - the engine is still starting: the right edge is fine
        pass
    _size["w"], _size["h"] = SIZES["collapsed" if _place["collapsed"] else "open"]
    sw, sh = _screen()
    x, y = spot(_place, sw, sh, _size["w"], _size["h"], 1.0)
    _window = webview.create_window(TITLE, URL, js_api=Bridge(), width=_size["w"], height=_size["h"], x=x, y=y,
                                    frameless=True, on_top=True, resizable=False, easy_drag=False,
                                    background_color="#0B0B10", shadow=False)
    threading.Thread(target=_watch, name="sidebar-watch", daemon=True).start()
    webview.start(private_mode=False, storage_path=os.path.join(os.environ.get("LOCALAPPDATA", "."), "Ichos", "sidebar"))


if __name__ == "__main__":
    main()
