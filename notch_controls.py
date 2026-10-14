"""The notch's controls and home view (owner, Fixer Upper S30, 2026-10-13).

The owner: "add a couple of things that can use system … Sound, settings, technical settings, toggle light and dark
mode for the computer system, and certain apps, opening File Explorer, cmd, setting a certain prompt for cmd like
Claude Code which can be typed before hand … when they hover over the notch they will be able to see the apps. They
can also have a default view so without clicking anything it can show apps or Spotify or song apps playing, weather,
day and calendar … and videos. This can be customizable … a triple click changes the apps shown or the home page or
a H button on top can be used to switch the default. If something is not added … the AI can figure out the link and
build for the user."

Three parts, all data:

* **System controls** — a closed set (``SYSTEM``). The notch can only ask for one of these ids; how each one runs
  is decided here, never by the page.
* **Launchers** — the owner's own buttons: an app, a site, a folder, or a command typed beforehand that opens in a
  new cmd window in a chosen folder (``claude`` in the project folder, say). ``suggest()`` turns a bare name into a
  launcher without a model: an installed app, a known site, a domain, or a web search as the last resort.
* **Home** — which view the notch shows without a click (apps, now playing, weather, calendar, timer, agents), the
  order a triple click walks through, and the small data each view needs.

Its own file (``notch_controls.json``) rather than ``equalize_assistant.json``: the Voice team edits that module's
settings at the same time, and these are only the notch's.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from paths import atomic_replace, data_path

STORE = data_path("notch_controls.json")

#: Every system control the notch can show. id -> (label, icon, what it does). Only these ids ever run.
SYSTEM: Dict[str, tuple] = {
    "settings": ("Settings", "gear", ("open", "ms-settings:")),
    "sound": ("Sound settings", "sound", ("open", "ms-settings:sound")),
    "display": ("Display and brightness", "sun", ("open", "ms-settings:display")),
    "technical": ("Technical settings", "sliders", ("run", ["SystemPropertiesAdvanced.exe"])),
    "theme": ("Light or dark mode", "contrast", ("theme",)),
    "explorer": ("File Explorer", "folder", ("run", ["explorer.exe"])),
    "cmd": ("Command prompt", "terminal", ("console", [])),
    "task_manager": ("Task Manager", "pulse", ("run", ["taskmgr.exe"])),
    "volume_down": ("Volume down", "volume_down", ("volume", "down")),
    "volume_up": ("Volume up", "volume_up", ("volume", "up")),
    "mute": ("Mute", "mute", ("volume", "mute")),
    "play_pause": ("Play or pause", "play", ("media", "play_pause")),
    "next": ("Next track", "next", ("media", "next")),
    "previous": ("Previous track", "previous", ("media", "previous")),
}

#: The views the notch can rest on. "apps" is the controls and launchers row.
VIEWS = ("apps", "now_playing", "weather", "calendar", "timer", "agents")
KINDS = ("app", "site", "folder", "command")
MAX_LAUNCHERS = 12

DEFAULTS: Dict[str, Any] = {
    # The left row of the reference image (p05): settings, sound, display, theme; the right row is the owner's apps.
    "system": ["settings", "technical", "sound", "display", "theme", "explorer", "cmd"],
    "launchers": [],
    "home": {"default": "apps", "views": ["apps", "now_playing", "weather", "calendar"], "city": "",
             "triple_click": True},
    # Where the notch and the hands-off sidebar sit, and whether they are locked there (Fixer Upper S2: "They can be
    # dragged and locked onto a part of the screen"). The notch slides along the top edge (x = offset from centre);
    # the sidebar docks to the left or right edge, or floats where it was dropped.
    "place": {"notch": {"x": 0, "locked": False},
              "sidebar": {"enabled": False, "edge": "right", "x": 0, "y": 96, "locked": False, "collapsed": False}},
}

EDGES = ("left", "right", "free")

_lock = threading.RLock()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def _clean_launcher(raw: Dict[str, Any], index: int = 0) -> Optional[Dict[str, Any]]:
    """One launcher, or None when it cannot work (no name, a site that is not a web address…)."""
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()[:40]
    kind = str(raw.get("kind") or "app").lower()
    if not name or kind not in KINDS:
        return None
    target = str(raw.get("target") or "").strip()[:400]
    if kind == "site" and not re.match(r"^https?://", target, re.I):
        return None
    if kind in ("app", "folder") and not target:
        return None
    command = str(raw.get("command") or "").strip()[:300] if kind == "command" else ""
    if kind == "command" and not command:
        return None
    from equalize_assistant import APP_COLORS, COLORS

    key = name.lower().replace(" ", "")
    return {"id": str(raw.get("id") or uuid.uuid4().hex[:8])[:24], "name": name, "kind": kind, "target": target,
            "command": command, "folder": str(raw.get("folder") or "").strip()[:300] if kind == "command" else "",
            "color": str(raw.get("color") or APP_COLORS.get(key, COLORS[index % len(COLORS)]))[:16]}


def _check(state: Dict[str, Any]) -> Dict[str, Any]:
    state["system"] = [s for s in dict.fromkeys(state.get("system") or []) if s in SYSTEM]
    launchers = []
    for raw in state.get("launchers") or []:
        item = _clean_launcher(raw, len(launchers))
        if item and item["id"] not in {l["id"] for l in launchers}:
            launchers.append(item)
    state["launchers"] = launchers[:MAX_LAUNCHERS]
    home = state["home"]
    home["views"] = [v for v in dict.fromkeys(home.get("views") or []) if v in VIEWS] or ["apps"]
    if home.get("default") not in home["views"]:
        home["default"] = home["views"][0]
    home["city"] = str(home.get("city") or "").strip()[:60]
    home["triple_click"] = bool(home.get("triple_click", True))
    place = state["place"]
    num = lambda v, lo, hi: max(lo, min(hi, int(float(v or 0))))  # noqa: E731
    place["notch"] = {"x": num(place["notch"].get("x"), -4000, 4000), "locked": bool(place["notch"].get("locked"))}
    bar = place["sidebar"]
    place["sidebar"] = {"enabled": bool(bar.get("enabled")), "edge": bar.get("edge") if bar.get("edge") in EDGES else "right",
                        "x": num(bar.get("x"), -8000, 8000), "y": num(bar.get("y"), 0, 4000),
                        "locked": bool(bar.get("locked")), "collapsed": bool(bar.get("collapsed"))}
    return state


def _load() -> Dict[str, Any]:
    state = json.loads(json.dumps(DEFAULTS))
    try:
        saved = json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    for key in ("system", "launchers"):
        if isinstance(saved.get(key), list):
            state[key] = saved[key]
    if isinstance(saved.get("home"), dict):
        state["home"].update({k: v for k, v in saved["home"].items() if k in state["home"]})
    _merge_place(state, saved.get("place"))
    return _check(state)


def _merge_place(state: Dict[str, Any], place: Any) -> None:
    if not isinstance(place, dict):
        return
    for part in ("notch", "sidebar"):
        if isinstance(place.get(part), dict):
            state["place"][part].update({k: v for k, v in place[part].items() if k in state["place"][part]})


def settings() -> Dict[str, Any]:
    with _lock:
        return _load()


def update(changes: Dict[str, Any]) -> Dict[str, Any]:
    """Save what the owner changed (any of system, launchers, home); everything else is kept."""
    with _lock:
        state = _load()
        for key in ("system", "launchers"):
            if isinstance(changes.get(key), list):
                state[key] = changes[key]
        if isinstance(changes.get("home"), dict):
            state["home"].update({k: v for k, v in changes["home"].items() if k in state["home"]})
        _merge_place(state, changes.get("place"))
        state = _check(state)
        STORE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STORE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        atomic_replace(tmp, STORE)
        return state


def place(part: str) -> Dict[str, Any]:
    """Where the notch or the sidebar sits now (read by their windows at start and after a drag)."""
    return settings()["place"][part]


def move(part: str, changes: Dict[str, Any]) -> Dict[str, Any]:
    """A drag ended (or a lock was toggled). A locked window keeps its place: only unlocking moves it again."""
    if part not in ("notch", "sidebar"):
        raise ValueError("Only the notch and the sidebar move.")
    current = place(part)
    if current["locked"] and changes.get("locked") is not False:
        changes = {k: v for k, v in changes.items() if k in ("locked", "enabled", "collapsed")}
    return update({"place": {part: changes}})["place"][part]


def add_launcher(item: Dict[str, Any]) -> Dict[str, Any]:
    state = settings()
    cleaned = _clean_launcher(item, len(state["launchers"]))
    if cleaned is None:
        raise ValueError("A launcher needs a name and a target that can open (a web address for a site).")
    if len(state["launchers"]) >= MAX_LAUNCHERS:
        raise ValueError(f"The notch holds {MAX_LAUNCHERS} launchers; remove one first.")
    return update({"launchers": state["launchers"] + [cleaned]})


def remove_launcher(launcher_id: str) -> Dict[str, Any]:
    state = settings()
    return update({"launchers": [l for l in state["launchers"] if l["id"] != launcher_id]})


def cycle(current: str) -> str:
    """The next view a triple click shows, wrapping round the owner's list."""
    views = settings()["home"]["views"]
    return views[(views.index(current) + 1) % len(views)] if current in views else views[0]


def set_default(view: str) -> Dict[str, Any]:
    """The H button: the view on screen becomes the one the notch rests on (added to the list if it was not)."""
    if view not in VIEWS:
        raise ValueError(f"Unknown view: {view}")
    home = settings()["home"]
    views = home["views"] if view in home["views"] else home["views"] + [view]
    return update({"home": {"default": view, "views": views}})


# ---------------------------------------------------------------------------
# "The AI can figure out the link and build for the user"
# ---------------------------------------------------------------------------

def suggest(name: str, apps: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """A launcher for ``name`` without a model: installed app, known site, a domain, else a web search."""
    import ultrafast

    words = re.sub(r"\s+", " ", str(name or "").strip().lower())[:60]
    if not words:
        raise ValueError("Name the app or site.")
    title = str(name).strip()[:40]
    if apps is None:
        try:
            apps = ultrafast.installed_apps()
        except Exception:  # noqa: BLE001 - not on Windows, or the Start Menu could not be read
            apps = {}
    found = ultrafast._match_app(words, apps or {})
    site = ultrafast.SITE_WORDS.get(words, words.replace(" ", ""))
    # An app with exactly this name wins; a known site beats a loose app match ("google" is not Google Chrome).
    if found and (found == words or site not in ultrafast.SITES):
        return {"name": title, "kind": "app", "target": found, "how": "installed app"}
    if site in ultrafast.SITES:
        return {"name": title, "kind": "site", "target": ultrafast.SITES[site], "how": "known site"}
    if re.fullmatch(r"(https?://)?[\w-]+(\.[\w-]+)+(/\S*)?", words):
        return {"name": title, "kind": "site", "target": words if words.startswith("http") else f"https://{words}",
                "how": "web address"}
    from urllib.parse import quote_plus

    return {"name": title, "kind": "site", "target": f"https://www.google.com/search?q={quote_plus(words)}&btnI=1",
            "how": "first web result (check it)"}


# ---------------------------------------------------------------------------
# Running a control or a launcher
# ---------------------------------------------------------------------------

def _start(target: str) -> None:
    os.startfile(target)  # type: ignore[attr-defined]  # noqa: S606 - a closed-set id or the owner's own launcher


def _popen(args: List[str], cwd: Optional[str] = None, console: bool = False) -> None:
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if console else 0
    subprocess.Popen(args, cwd=cwd or None, creationflags=flags)  # noqa: S603 - list form, no shell parsing here


THEME_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def toggle_theme(registry: Any = None, broadcast: Optional[Callable[[], None]] = None) -> str:
    """Flip Windows between light and dark (apps and the taskbar together); returns the new mode."""
    if registry is None:
        import winreg as registry  # type: ignore[no-redef]
    with registry.OpenKey(registry.HKEY_CURRENT_USER, THEME_KEY, 0,
                          registry.KEY_READ | registry.KEY_SET_VALUE) as key:
        try:
            light = int(registry.QueryValueEx(key, "AppsUseLightTheme")[0])
        except OSError:
            light = 1
        new = 0 if light else 1
        for name in ("AppsUseLightTheme", "SystemUsesLightTheme"):
            registry.SetValueEx(key, name, 0, registry.REG_DWORD, new)
    (broadcast or _broadcast_theme)()
    return "light" if new else "dark"


def _broadcast_theme() -> None:
    """Tell open windows the colours changed (what Settings itself sends), so they repaint without a sign-out."""
    try:
        import ctypes

        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "ImmersiveColorSet", 0x0002, 2000,
                                                 ctypes.byref(result))
    except Exception:  # noqa: BLE001
        pass


def run_system(control_id: str, dry_run: bool = False) -> Dict[str, Any]:
    """Run one of ``SYSTEM``. Returns {ok, said}."""
    if control_id not in SYSTEM:
        return {"ok": False, "said": "That control isn't one the notch knows."}
    label, _icon, how = SYSTEM[control_id]
    if sys.platform != "win32" and not dry_run:
        return {"ok": False, "said": "System controls only run on Windows."}
    try:
        if how[0] in ("volume", "media"):
            import ultrafast

            return ultrafast.execute({"action": how[0], "confidence": 1.0, "args": {"op": how[1]}}, dry_run=dry_run)
        if dry_run:
            return {"ok": True, "said": f"{label}."}
        if how[0] == "open":
            _start(how[1])
        elif how[0] == "run":
            _popen(list(how[1]))
        elif how[0] == "console":
            _popen(["cmd.exe"], cwd=str(Path.home()), console=True)
        elif how[0] == "theme":
            return {"ok": True, "said": f"Switched to {toggle_theme()} mode."}
        return {"ok": True, "said": f"{label}."}
    except Exception as error:  # noqa: BLE001 - say what failed instead of breaking the notch
        return {"ok": False, "said": f"{label} didn't open: {error}"}


def run_launcher(launcher_id: str, dry_run: bool = False) -> Dict[str, Any]:
    """Open one of the owner's launchers. A command opens a new cmd window that runs it and stays open."""
    item = next((l for l in settings()["launchers"] if l["id"] == launcher_id), None)
    if item is None:
        return {"ok": False, "said": "That launcher is gone."}
    if sys.platform != "win32" and not dry_run:
        return {"ok": False, "said": "Launchers only run on Windows."}
    try:
        if item["kind"] == "command":
            folder = item["folder"] or str(Path.home())
            if not Path(folder).is_dir():
                return {"ok": False, "said": f"The folder for {item['name']} isn't there any more."}
            if not dry_run:
                # /k keeps the window open after the command, the way the owner would have typed it.
                _popen(["cmd.exe", "/k", item["command"]], cwd=folder, console=True)
            return {"ok": True, "said": f"{item['name']} — running {item['command']}."}
        if item["kind"] == "app":
            import ultrafast

            apps = {} if dry_run else ultrafast.installed_apps()
            target = apps.get(item["target"].lower(), item["target"])
        else:
            target = item["target"]
        if item["kind"] == "folder" and not Path(target).is_dir() and not dry_run:
            return {"ok": False, "said": f"{target} isn't a folder on this PC."}
        if not dry_run:
            _start(target)
        return {"ok": True, "said": f"Opening {item['name']}."}
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "said": f"{item['name']} didn't open: {error}"}


# ---------------------------------------------------------------------------
# What the home views show
# ---------------------------------------------------------------------------

_cache: Dict[str, Any] = {}
WEATHER_TTL = 15 * 60


def weather(city: str = "", fetch: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
            now: Optional[float] = None) -> Dict[str, Any]:
    """Open-Meteo (no key), at most every 15 minutes; offline, the last reading is kept and marked old."""
    now = time.time() if now is None else now
    city = (city or settings()["home"]["city"]).strip()
    if not city:
        try:  # the Morning Digest's city, so it is set once for both
            import morning_digest

            city = str(morning_digest.settings().get("city") or "").strip()
        except Exception:  # noqa: BLE001
            city = ""
    if not city:
        return {"ok": False, "why": "Set a city in Equalize › Notch controls."}
    cached = _cache.get(("weather", city.lower()))
    if cached and now - cached["at"] < WEATHER_TTL:
        return cached["data"]
    if fetch is None:
        import requests

        fetch = lambda url, params: requests.get(url, params=params, timeout=8).json()  # noqa: E731
    try:
        places = fetch("https://geocoding-api.open-meteo.com/v1/search", {"name": city, "count": 1}).get("results") or []
        if not places:
            return {"ok": False, "why": f"Couldn't find {city}."}
        place = places[0]
        data = fetch("https://api.open-meteo.com/v1/forecast", {
            "latitude": place["latitude"], "longitude": place["longitude"], "current": "temperature_2m,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min", "timezone": "auto", "forecast_days": 1})
    except Exception:  # noqa: BLE001 - offline: the last reading, marked as old
        if cached:
            return {**cached["data"], "stale": True}
        return {"ok": False, "why": "No weather while offline."}
    current, daily = data.get("current") or {}, data.get("daily") or {}
    result = {"ok": True, "city": place.get("name", city), "now": current.get("temperature_2m"),
              "code": current.get("weather_code"), "high": (daily.get("temperature_2m_max") or [None])[0],
              "low": (daily.get("temperature_2m_min") or [None])[0], "sky": sky(current.get("weather_code"))}
    _cache[("weather", city.lower())] = {"at": now, "data": result}
    return result


def sky(code: Any) -> str:
    """WMO weather code -> one word the notch can turn into an icon."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return "cloud"
    if code == 0:
        return "sun"
    if code in (1, 2):
        return "partly"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if code >= 95:
        return "storm"
    return "cloud"


def calendar(call: Optional[Callable[..., Dict[str, Any]]] = None, today: Any = None) -> Dict[str, Any]:
    """Today's next events from Google Calendar (the Connectors one), or why there are none."""
    from datetime import datetime, timedelta

    import connector_use

    if call is None:
        if not connector_use.is_connected("google_calendar"):
            return {"ok": False, "why": "Connect Google Calendar in Connectors.", "events": []}
        call = connector_use.call
    start = (today or datetime.now().astimezone()).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        result = call("google_calendar", "events", params={
            "calendar_id": "primary", "timeMin": start.isoformat(), "timeMax": (start + timedelta(days=1)).isoformat(),
            "singleEvents": "true", "orderBy": "startTime", "maxResults": "6"})
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "why": f"Calendar didn't answer: {error}", "events": []}
    events = []
    for event in (result.get("data") or {}).get("items") or []:
        begins = (event.get("start") or {}).get("dateTime") or (event.get("start") or {}).get("date") or ""
        ends = (event.get("end") or {}).get("dateTime") or ""
        events.append({"title": str(event.get("summary") or "Untitled")[:80],
                       "start": begins[11:16] if "T" in begins else "", "end": ends[11:16] if "T" in ends else "",
                       "all_day": "T" not in begins})
    return {"ok": True, "day": start.strftime("%a"), "date": start.day, "events": events}


def now_playing(manager: Any = None) -> Dict[str, Any]:
    """What Windows says is playing (Spotify, a YouTube tab, any app with media controls) — title, artist, app.

    Read through Windows' own media controls (the same ones the volume flyout shows), so no app needs its own
    connector. Needs the small ``winrt-Windows.Media.Control`` package; without it the view says so.
    """
    if manager is None:
        try:
            from winrt.windows.media.control import (  # type: ignore[import-not-found]
                GlobalSystemMediaTransportControlsSessionManager as manager,
            )
        except Exception:  # noqa: BLE001
            return {"ok": False, "why": "Player info needs one package (winrt-Windows.Media.Control)."}
    try:
        import asyncio

        async def read() -> Dict[str, Any]:
            sessions = await manager.request_async()
            session = sessions.get_current_session()
            if session is None:
                return {"ok": True, "playing": False, "title": "", "artist": "", "app": ""}
            props = await session.try_get_media_properties_async()
            status = session.get_playback_info().playback_status
            return {"ok": True, "playing": int(status) == 4, "title": str(props.title or "")[:80],
                    "artist": str(props.artist or "")[:80], "app": str(session.source_app_user_model_id or "")[:80]}

        return asyncio.run(read())
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "why": f"Couldn't read what's playing: {error}"}


def home_data(view: str) -> Dict[str, Any]:
    """The data one home view needs (apps, timer and agents come from the notch's other calls)."""
    if view == "weather":
        return weather()
    if view == "calendar":
        return calendar()
    if view == "now_playing":
        return now_playing()
    return {"ok": True}
