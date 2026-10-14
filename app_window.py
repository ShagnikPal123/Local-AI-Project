"""Nyx as a real desktop app: its own window, taskbar button and icon, with no browser around it (owner, 2026-10-13:
"make both AI an actual app ... perhaps app by default, browser if wanted"; "use Electron js or a similar app").

Why not Electron
----------------
An Electron app is a new .exe of our own, and Windows Smart App Control blocks unsigned executables on the owner's PC.
That is the same wall the PyInstaller ``Nyx.exe`` hit (AGENTS.md §3), and Electron would add ~150 MB on top. This
window is the same idea built only from parts Windows already trusts: WebView2 (the Edge engine that ships with Windows
11, which plays the part Chromium plays inside Electron) driven by pywebview on Python's signed ``pythonw.exe``. The
desktop notch (``notch_window.py``) already runs this way on his PC.

How it fits
-----------
The engine keeps running inside the launcher, behind the tray icon. This file is a separate process because pywebview
needs its process's main thread, and the launcher's main thread belongs to the tray. Closing the window leaves the
engine running, like Discord or Claude's desktop app: the tray's "Open Nyx" or the desktop shortcut brings it back.
Opening it a second time brings the existing window forward instead of starting a second copy.

More than one app
-----------------
``APPS`` lists the apps this window can host. The full app is ``nyx``. The lightweight Ichos app (Fixer Upper WS3)
adds its own entry (title, first page, icon, taskbar id) and gets the same window, taskbar button, remembered size and
single-window behaviour with no other change.

Run by ``launcher.open_app``: ``pythonw app_window.py --app nyx --url http://localhost:8000/``. When the engine starts
the window itself it puts the owner's session in ``NYX_APP_TOKEN``; the page collects it through the bridge, so the
token never appears in a URL, a log, or the command line.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_DIR = Path(__file__).resolve().parent

#: Every app this window can host. ``path`` is the first page, ``app_id`` the Windows taskbar identity: windows that
#: share it stack under one taskbar button with this app's icon instead of under Python's.
APPS: Dict[str, Dict[str, str]] = {
    "nyx": {"title": "Nyx Ichos", "path": "/", "icon": "assets/brand/nyx.ico", "app_id": "NyxIchos.App"},
}
DEFAULT_APP = "nyx"

#: First-run size, and the smallest the window may be dragged to before the layout stops making sense.
DEFAULT_SIZE = (1280, 820)
MIN_SIZE = (720, 480)

#: Marks the page as running inside this window, so it waits for the bridge's session instead of a login screen.
SHELL_PARAM = ("shell", "app")


def app_spec(name: str) -> Dict[str, str]:
    """The app called ``name``, or the full app when the name is unknown (a stale shortcut must still open something)."""
    return dict(APPS.get(str(name or "").strip().lower(), APPS[DEFAULT_APP]))


def app_name(name: str) -> str:
    key = str(name or "").strip().lower()
    return key if key in APPS else DEFAULT_APP


def available() -> bool:
    """Whether this PC can show the native window: Windows with pywebview installed (WebView2 ships with Windows 11).

    Anything else falls back to an Edge/Chrome app window, then to a normal browser tab, in ``launcher.open_app``.
    """
    return sys.platform == "win32" and importlib.util.find_spec("webview") is not None


def window_url(url: str) -> str:
    """``url`` with the marker that tells the page it is inside the app window (kept beside any query it had)."""
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    if SHELL_PARAM not in query:
        query.append(SHELL_PARAM)
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def _windowless_python() -> str:
    """pythonw beside the running interpreter: no console window, and signed, so Smart App Control allows it."""
    exe = Path(sys.executable)
    windowless = exe.with_name("pythonw.exe")
    return str(windowless if windowless.is_file() else exe)


def command(app: str, url: str) -> List[str]:
    """The argv that opens ``app`` at ``url`` in its own window."""
    return [_windowless_python(), str(PROJECT_DIR / "app_window.py"), "--app", app_name(app), "--url", url]


def owner_session() -> str:
    """A session for the window, issued by the engine this process is running.

    Only meaningful inside the engine's own process: sessions live in the engine's memory, so a token minted by any
    other process would be refused. An unclaimed install needs no session at all, hence the empty string.
    """
    try:
        from server_auth import AUTH_STORE, is_claimed

        if not is_claimed():
            return ""
        owner = next((u for u in AUTH_STORE.users.values() if getattr(u.role, "value", u.role) == "owner"), None)
        return AUTH_STORE._issue_session(owner.email) if owner is not None else ""
    except Exception:  # noqa: BLE001 - no session just means the page shows its own sign-in
        return ""


# ---------------------------------------------------------------------------
# Remembering where the window was
# ---------------------------------------------------------------------------


def _geometry_file() -> Path:
    import paths

    return paths.data_path("app_window.json")


def load_geometry(app: str) -> Dict[str, Any]:
    """Last size and place of ``app``'s window, cleaned up so a bad file can never open an unusable window."""
    try:
        saved = json.loads(_geometry_file().read_text(encoding="utf-8")).get(app_name(app)) or {}
    except (OSError, ValueError, AttributeError):
        saved = {}
    width = _clamp(saved.get("width"), MIN_SIZE[0], 10_000, DEFAULT_SIZE[0])
    height = _clamp(saved.get("height"), MIN_SIZE[1], 10_000, DEFAULT_SIZE[1])
    geometry: Dict[str, Any] = {"width": width, "height": height, "maximized": bool(saved.get("maximized"))}
    # A position from a monitor that has since been unplugged would put the window off screen; -2000 is generous
    # enough for a second screen on the left, and None lets Windows centre it.
    x, y = saved.get("x"), saved.get("y")
    if isinstance(x, int) and isinstance(y, int) and -2000 < x < 10_000 and -200 < y < 10_000:
        geometry.update(x=x, y=y)
    return geometry


def save_geometry(app: str, geometry: Dict[str, Any]) -> None:
    path = _geometry_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data[app_name(app)] = {k: geometry[k] for k in ("width", "height", "x", "y", "maximized") if k in geometry}
    try:
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def _clamp(value: Any, low: int, high: int, default: int) -> int:
    return min(high, max(low, value)) if isinstance(value, int) else default


# ---------------------------------------------------------------------------
# Windows details: one window per app, its icon, its taskbar button
# ---------------------------------------------------------------------------


def _user32():
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = wintypes.HWND
    user32.LoadImageW.restype = wintypes.HANDLE
    return user32


def find_window(title: str) -> int:
    user32 = _user32()
    return int(user32.FindWindowW(None, title) or 0) if user32 else 0


def bring_forward(hwnd: int) -> None:
    """Restore a minimised window and put it in front: what a second click on the shortcut should do."""
    user32 = _user32()
    if not user32 or not hwnd:
        return
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)


def set_taskbar_identity(app_id: str) -> None:
    """Give this process its own taskbar group, so the button shows Nyx's icon rather than Python's."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:  # noqa: BLE001 - the window still works, it just groups under Python
        pass


def set_window_icon(hwnd: int, icon_path: Path) -> None:
    """Title-bar and taskbar icon from the brand .ico (pywebview on Windows has no icon option of its own)."""
    user32 = _user32()
    if not user32 or not hwnd or not icon_path.is_file():
        return
    image_icon, load_from_file, wm_seticon = 1, 0x10, 0x80
    for kind, size in ((0, 16), (1, 32)):  # ICON_SMALL, ICON_BIG
        handle = user32.LoadImageW(None, str(icon_path), image_icon, size, size, load_from_file)
        if handle:
            user32.SendMessageW(hwnd, wm_seticon, kind, handle)


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------


class Bridge:
    """What the page may ask of its window (``window.pywebview.api.*``)."""

    def __init__(self, token: str, url: str) -> None:
        self._token = token
        self._url = url

    def token(self) -> str:
        """The owner's session, handed over once; later calls get nothing, so a page that navigates away cannot."""
        token, self._token = self._token, ""
        return token

    def open_in_browser(self, path: str = "") -> None:
        """'Open in browser' for anyone who wants a tab after all (the browser stays optional, not gone)."""
        base = urllib.parse.urlsplit(self._url)
        clean = "/" + str(path or "").lstrip("/")
        webbrowser.open(urllib.parse.urlunsplit((base.scheme, base.netloc, clean, "", "")))


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="app_window", description="Open Nyx in its own desktop window.")
    parser.add_argument("--app", default=DEFAULT_APP, help=f"Which app ({', '.join(APPS)}).")
    parser.add_argument("--url", default="", help="The page to open; defaults to the app's first page on port 8000.")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    name = app_name(args.app)
    spec = app_spec(name)
    url = window_url(args.url or f"http://localhost:8000{spec['path']}")
    token = os.environ.pop("NYX_APP_TOKEN", "")

    set_taskbar_identity(spec["app_id"])
    existing = find_window(spec["title"])
    if existing:
        bring_forward(existing)
        return 0

    import webview

    geometry = load_geometry(name)
    window = webview.create_window(
        spec["title"], url, js_api=Bridge(token, url), width=geometry["width"], height=geometry["height"],
        x=geometry.get("x"), y=geometry.get("y"), min_size=MIN_SIZE, maximized=geometry["maximized"],
        background_color="#0b0b12", text_select=True)
    _track_geometry(window, name, geometry)

    def shown() -> None:
        set_window_icon(find_window(spec["title"]), PROJECT_DIR / spec["icon"])

    window.events.shown += shown
    storage = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "NyxIchos" / "webview" / name
    webview.start(private_mode=False, storage_path=str(storage))
    return 0


def _track_geometry(window: Any, name: str, geometry: Dict[str, Any]) -> None:
    """Follow moves, resizes and maximise, and write them down when the window closes."""
    lock = threading.Lock()

    def resized(width: int, height: int) -> None:
        with lock:
            if not geometry.get("maximized"):
                geometry.update(width=int(width), height=int(height))

    def moved(x: int, y: int) -> None:
        with lock:
            if not geometry.get("maximized"):
                geometry.update(x=int(x), y=int(y))

    def maximized() -> None:
        geometry["maximized"] = True

    def restored() -> None:
        geometry["maximized"] = False

    def closing() -> None:
        save_geometry(name, geometry)

    events = window.events
    for event_name, handler in (("resized", resized), ("moved", moved), ("maximized", maximized),
                                ("restored", restored), ("closing", closing)):
        event = getattr(events, event_name, None)
        if event is not None:  # older pywebview versions lack some of these; the window still works
            event += handler


if __name__ == "__main__":
    raise SystemExit(main())
