"""Ultra Fast — Ichos's own take on Jev (owner, 2026-10-11: "download Jev and add as a model to mine but then copy and
add to ours in a new mode called ultra fast (based on jev) basically everything jev does and has, just ours now").

Jev (TypeSafe's "System One" model, used by kevinbadi/jev-voice, browser-use/jev-ultrafast and jev-chat) never writes
text: code lays out the closed set of things that could happen, one request picks among them, and code does the work.
That is the whole trick, and it is what this module copies:

* **One decision per utterance.** ``plan(text)`` returns a typed action (open an app, open a site, search, type, a
  shortcut, scroll, volume, media, a system action, a multi-step task, or plain chat) with typed arguments.
  With a ``TYPESAFE_API_KEY`` it asks Jev itself in one round trip (~250 ms); without one it runs the same choice
  locally over the same closed sets, in well under a millisecond — no model at all.
* **Select, never generate.** Text to type or search is *picked* from spans cut out of what was said
  (``text_candidates``), so nothing the model writes is ever typed, run or opened.
* **Code owns execution.** ``execute(plan)`` only accepts keys from the closed sets below; the Windows calls are
  plain ``ShellExecute`` / ``SendInput`` with no shell strings built from model output.
* **Judge before replying** (jev-chat): ``judge(conversation)`` reads a message thread for intent, risk and what the
  other person needs, then ranks a few reply drafts. It never sends anything.

Chat: the composer's "Ultra Fast" mode (``chat_modes``) runs ``handle`` first; a desktop command is done and answered
in one line without the big model, anything else falls through to a short, fast answer.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"
#: Below this the plan is not acted on; Ichos says it is not sure instead (jev-voice ACTION_MIN_CONFIDENCE).
MIN_CONFIDENCE = 0.35

ACTIONS: Dict[str, str] = {
    "open_app": "Open or switch to an application installed on this PC",
    "open_site": "Open a website",
    "search": "Search for something on a site or search engine",
    "type_text": "Type text into whatever has focus",
    "shortcut": "Press a keyboard shortcut (copy, paste, close tab, undo, new tab, ...)",
    "scroll": "Scroll the page",
    "volume": "Change the system volume or mute",
    "media": "Play, pause or skip music or video",
    "system": "A system action: screenshot, lock, open a folder, show the desktop, settings",
    "task": "Several steps on screen that need looking at the page (book, fill in, find and pick, reply to...)",
    "chat": "Not a computer command: a question or conversation for the assistant",
}

SITES: Dict[str, str] = {
    "youtube": "https://www.youtube.com", "google": "https://www.google.com", "gmail": "https://mail.google.com",
    "github": "https://github.com", "reddit": "https://www.reddit.com", "x": "https://x.com",
    "amazon": "https://www.amazon.com", "netflix": "https://www.netflix.com", "spotify": "https://open.spotify.com",
    "wikipedia": "https://en.wikipedia.org", "maps": "https://www.google.com/maps",
    "calendar": "https://calendar.google.com", "drive": "https://drive.google.com", "outlook": "https://outlook.live.com",
    "whatsapp": "https://web.whatsapp.com", "linkedin": "https://www.linkedin.com", "twitch": "https://www.twitch.tv",
    "stackoverflow": "https://stackoverflow.com", "chatgpt": "https://chatgpt.com", "claude": "https://claude.ai",
    "vercel": "https://vercel.com/dashboard", "instagram": "https://www.instagram.com", "news": "https://news.google.com",
}
SITE_WORDS = {"twitter": "x", "you tube": "youtube", "mail": "gmail", "google maps": "maps", "stack overflow":
              "stackoverflow", "chat gpt": "chatgpt", "insta": "instagram", "google drive": "drive",
              "google calendar": "calendar", "whats app": "whatsapp"}

SEARCH_ENGINES: Dict[str, str] = {
    "google": "https://www.google.com/search?q={q}", "youtube": "https://www.youtube.com/results?search_query={q}",
    "amazon": "https://www.amazon.com/s?k={q}", "wikipedia": "https://en.wikipedia.org/w/index.php?search={q}",
    "github": "https://github.com/search?q={q}", "reddit": "https://www.reddit.com/search/?q={q}",
    "maps": "https://www.google.com/maps/search/{q}", "spotify": "https://open.spotify.com/search/{q}",
    "images": "https://www.google.com/search?tbm=isch&q={q}", "x": "https://x.com/search?q={q}",
    "news": "https://news.google.com/search?q={q}",
}

# Virtual-key codes (winuser.h). Only these names can ever be pressed.
VK = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "space": 0x20,
      "backspace": 0x08, "delete": 0x2E, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22, "left": 0x25,
      "up": 0x26, "right": 0x27, "down": 0x28, "f4": 0x73, "f5": 0x74, "f11": 0x7A, "printscreen": 0x2C,
      "volume_mute": 0xAD, "volume_down": 0xAE, "volume_up": 0xAF, "media_next": 0xB0, "media_prev": 0xB1,
      "media_stop": 0xB2, "media_play": 0xB3, "plus": 0xBB, "minus": 0xBD, "period": 0xBE,
      **{chr(c): c for c in range(0x41, 0x5B)}, **{str(d): 0x30 + d for d in range(10)}}
VK.update({k.lower(): v for k, v in list(VK.items()) if len(k) == 1})

SHORTCUTS: Dict[str, Tuple[List[str], str]] = {
    "copy": (["ctrl", "c"], "copy"), "paste": (["ctrl", "v"], "paste"), "cut": (["ctrl", "x"], "cut"),
    "undo": (["ctrl", "z"], "undo"), "redo": (["ctrl", "y"], "redo"), "select_all": (["ctrl", "a"], "select all"),
    "save": (["ctrl", "s"], "save"), "find": (["ctrl", "f"], "find"), "print": (["ctrl", "p"], "print"),
    "new_tab": (["ctrl", "t"], "new tab"), "close_tab": (["ctrl", "w"], "close tab"),
    "reopen_tab": (["ctrl", "shift", "t"], "reopen closed tab"), "next_tab": (["ctrl", "tab"], "next tab"),
    "previous_tab": (["ctrl", "shift", "tab"], "previous tab"), "reload": (["f5"], "reload"),
    "back": (["alt", "left"], "go back"), "forward": (["alt", "right"], "go forward"),
    "new_window": (["ctrl", "n"], "new window"), "close_window": (["alt", "f4"], "close window"),
    "address_bar": (["ctrl", "l"], "address bar"), "zoom_in": (["ctrl", "plus"], "zoom in"),
    "zoom_out": (["ctrl", "minus"], "zoom out"), "zoom_reset": (["ctrl", "0"], "reset zoom"),
    "fullscreen": (["f11"], "full screen"), "switch_window": (["alt", "tab"], "switch window"),
    "show_desktop": (["win", "d"], "show desktop"), "minimize": (["win", "down"], "minimize"),
    "maximize": (["win", "up"], "maximize"), "task_view": (["win", "tab"], "task view"),
    "clipboard": (["win", "v"], "clipboard history"), "emoji": (["win", "period"], "emoji panel"),
    "enter": (["enter"], "enter"), "escape": (["esc"], "escape"), "delete": (["delete"], "delete"),
    "task_manager": (["ctrl", "shift", "esc"], "task manager"),
}
SHORTCUT_WORDS = {
    "copy": "copy", "paste": "paste", "cut": "cut", "undo": "undo", "redo": "redo", "select all": "select_all",
    "save": "save", "find": "find", "print": "print", "new tab": "new_tab", "close (?:this |the )?tab": "close_tab",
    "reopen (?:the )?(?:closed )?tab": "reopen_tab", "next tab": "next_tab", "previous tab": "previous_tab",
    "reload|refresh": "reload", "go back": "back", "go forward": "forward", "new window": "new_window",
    "close (?:this |the )?(?:window|app)": "close_window", "address bar": "address_bar", "zoom in": "zoom_in",
    "zoom out": "zoom_out", "reset zoom": "zoom_reset", "full ?screen": "fullscreen", "switch windows?": "switch_window",
    "show (?:the )?desktop": "show_desktop", "minimi[sz]e": "minimize", "maximi[sz]e": "maximize",
    "task view": "task_view", "clipboard": "clipboard", "emoji": "emoji", "press enter|hit enter": "enter",
    "escape": "escape", "task manager": "task_manager",
}
SYSTEM_OPS = {
    "screenshot": "take a screenshot", "lock": "lock the screen", "downloads": "open Downloads",
    "documents": "open Documents", "desktop_folder": "open the Desktop folder", "explorer": "open File Explorer",
    "settings": "open Settings", "bluetooth": "open Bluetooth settings", "wifi": "open Wi-Fi settings",
    "display": "open display settings", "sound_settings": "open sound settings",
}
SYSTEM_WORDS = {"screenshot|screen shot|snip": "screenshot", "lock": "lock", "downloads": "downloads",
                "documents": "documents", "desktop folder": "desktop_folder", "file explorer|explorer|my files":
                "explorer", "bluetooth": "bluetooth", "wi-?fi|wireless": "wifi", "display settings|screen settings":
                "display", "sound settings|audio settings": "sound_settings", "settings": "settings"}
VOLUME_OPS = ("up", "down", "mute", "unmute", "max")
MEDIA_OPS = ("play_pause", "next", "previous", "stop")

#: Apps Windows can always open by name, without a Start Menu shortcut.
BUILTIN_APPS = {"notepad": "notepad.exe", "calculator": "calc.exe", "paint": "mspaint.exe", "command prompt": "cmd.exe",
                "powershell": "powershell.exe", "terminal": "wt.exe", "file explorer": "explorer.exe",
                "task manager": "taskmgr.exe", "settings": "ms-settings:", "microsoft store": "ms-windows-store:",
                "snipping tool": "ms-screenclip:", "camera": "microsoft.windows.camera:", "clock": "ms-clock:",
                "photos": "ms-photos:", "mail": "outlookmail:", "calendar": "outlookcal:"}

_LEAD = re.compile(r"^\s*(?:hey |ok |okay )?(?:ichos|io|alfred|jarvis)[,!.]?\s+", re.I)
_POLITE = re.compile(r"^\s*(?:(?:can|could|would|will) you |please |go ahead and |i want (?:you )?to |i'?d like to )+", re.I)


# ---------------------------------------------------------------------------
# Candidates — the only text that can ever be typed or searched
# ---------------------------------------------------------------------------

def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip(" .,!?:;\"'")


def text_candidates(utterance: str) -> Dict[str, str]:
    """Spans cut from what was said that might be the payload. Jev (or the local chooser) picks one; none is invented."""
    said = _clean(_POLITE.sub("", _LEAD.sub("", utterance or "")))
    found: List[str] = []

    def add(value: str) -> None:
        value = _clean(re.sub(r"\s+(?:and |then )?(?:press|hit) enter$", "", value, flags=re.I))
        if value and value not in found and len(found) < 8:
            found.append(value)

    for quoted in re.findall(r"[\"“']([^\"”']{1,200})[\"”']", utterance or ""):
        add(quoted)
    for pattern in (r"\btype (?:in |out )?(.+)", r"\bwrite (.+)", r"\bsearch (?:for )?(.+?)(?: on (?:\w+(?: \w+)?))?$",
                    r"\b(?:look up|google|find) (.+?)(?: on (?:\w+(?: \w+)?))?$", r"\bplay (.+?)(?: on (?:\w+))?$"):
        match = re.search(pattern, said, re.I)
        if match:
            add(match.group(1))
    add(said)
    return {f"c{i + 1}": value for i, value in enumerate(found)}


# ---------------------------------------------------------------------------
# Installed apps (Start Menu shortcuts), read once
# ---------------------------------------------------------------------------

_apps_cache: Dict[str, Any] = {"at": 0.0, "apps": {}}


def installed_apps() -> Dict[str, str]:
    """name -> launch target. Start Menu shortcuts plus the apps Windows can always open."""
    if time.time() - _apps_cache["at"] < 600 and _apps_cache["apps"]:
        return dict(_apps_cache["apps"])
    apps: Dict[str, str] = dict(BUILTIN_APPS)
    if sys.platform == "win32":
        roots = [Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
                 Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs"]
        for root in roots:
            if not root.is_dir():
                continue
            for link in root.rglob("*.lnk"):
                name = link.stem.lower()
                if any(word in name for word in ("uninstall", "readme", "help", "documentation", "release notes")):
                    continue
                apps.setdefault(name, str(link))
    _apps_cache.update(at=time.time(), apps=apps)
    return dict(apps)


def _match_app(words: str, apps: Dict[str, str]) -> str:
    """The installed app the words mean, by meaning-ish match (exact, then contained, then first word)."""
    words = _clean(words).lower()
    words = re.sub(r"^(?:the |my )", "", words)
    words = re.sub(r"\s+(?:app|application|program)$", "", words)
    if not words:
        return ""
    aliases = {"chrome": "google chrome", "edge": "microsoft edge", "word": "word", "excel": "excel",
               "vs code": "visual studio code", "vscode": "visual studio code", "code": "visual studio code",
               "browser": "google chrome", "calc": "calculator", "files": "file explorer", "cmd": "command prompt"}
    words = aliases.get(words, words)
    if words in apps:
        return words
    contained = sorted((name for name in apps if words in name), key=len)
    if contained:
        return contained[0]
    first = words.split()[0]
    starts = sorted((name for name in apps if name.split()[0] == first), key=len)
    return starts[0] if starts else ""


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

def _plan(action: str, confidence: float, via: str, **args: Any) -> Dict[str, Any]:
    return {"action": action, "args": args, "confidence": round(float(confidence), 3), "via": via}


def split_compound(utterance: str) -> List[str]:
    """'open notepad and type hello' -> two steps. Only splits where both sides start like a command."""
    verbs = r"(?:open|launch|start|go to|search|type|write|press|hit|scroll|close|switch|play|pause|mute|take|lock|copy|paste|select|zoom|volume|turn)"
    parts = re.split(rf"\s*(?:,\s*)?(?:\band then\b|\bthen\b|\band\b)\s+(?={verbs}\b)(?!(?:press|hit) enter\s*$)",
                     utterance or "", flags=re.I)
    return [p for p in (_clean(p) for p in parts) if p]


def plan_local(utterance: str) -> Dict[str, Any]:
    """The same choice Jev makes, over the same closed sets, from the words alone. No model, no network."""
    started = time.perf_counter()
    said = _clean(_POLITE.sub("", _LEAD.sub("", utterance or "")))
    low = said.lower()
    cands = text_candidates(utterance)

    def done(plan: Dict[str, Any]) -> Dict[str, Any]:
        plan["ms"] = round((time.perf_counter() - started) * 1000, 2)
        return plan

    if not low:
        return done(_plan("chat", 0.0, "local"))
    if len(split_compound(said)) > 1:
        return done(_plan("task", 0.6, "local", steps=split_compound(said), compound=True))
    if low.endswith("?") or re.match(r"^(what|why|who|when|how|is|are|do|does|tell me|explain)\b", low):
        return done(_plan("chat", 0.8, "local"))
    match = re.match(r"^(?:turn (?:the )?)?volume (up|down)|^(mute|unmute)\b|^(?:turn|crank) (?:it|the volume) (up|down)", low)
    if match or re.search(r"\b(louder|quieter|max volume)\b", low):
        op = next((g for g in (match.groups() if match else ()) if g), "")
        op = op or ("up" if "louder" in low else "down" if "quieter" in low else "max")
        return done(_plan("volume", 0.9, "local", op=op))
    if re.match(r"^(pause|resume|play)$|^(?:pause|resume) (?:the )?(?:music|song|video)|^(next|skip|previous) (?:song|track)", low):
        op = "next" if re.search(r"next|skip", low) else "previous" if "previous" in low else "play_pause"
        return done(_plan("media", 0.9, "local", op=op))
    match = re.match(r"^scroll (up|down|to the top|to the bottom)(?: (a lot|a little|a bit))?", low)
    if match or low in ("go to the top", "go to the bottom"):
        where = match.group(1) if match else low.split()[-1]
        amount = {"a lot": 15, "a little": 3, "a bit": 3}.get((match.group(2) if match else "") or "", 6)
        return done(_plan("scroll", 0.9, "local", direction="up" if ("up" in where or "top" in where) else "down",
                          amount=50 if ("top" in where or "bottom" in where) else amount))
    for pattern, op in SYSTEM_WORDS.items():
        if re.search(rf"\b(?:take|grab|open|show|lock)\b.*\b(?:{pattern})\b|^(?:{pattern})$", low):
            return done(_plan("system", 0.85, "local", op=op))
    match = re.match(r"^(?:type|write)\b", low)
    if match:
        text_key = next((k for k, v in cands.items() if v.lower() != low), "c1")
        return done(_plan("type_text", 0.85, "local", text=cands.get(text_key, ""), text_key=text_key,
                          submit=bool(re.search(r"(?:press|hit) enter$", low))))
    match = re.match(r"^search (\w+(?: \w+)?) for (.+)$", low)
    if match and SITE_WORDS.get(match.group(1), match.group(1)) in SEARCH_ENGINES:
        engine = SITE_WORDS.get(match.group(1), match.group(1))
        return done(_plan("search", 0.9, "local", engine=engine, text=_clean(match.group(2))))
    if re.search(r"\b(book|fill (?:in|out)|sign up|reply to|order|buy|find (?:me )?(?:the )?(?:cheapest|best)|compare)\b", low):
        return done(_plan("task", 0.55, "local", goal=said))
    match = re.match(r"^(?:search|look up|google|find)\b(?: for)? (.+?)(?: on (\w+(?: \w+)?))?$", low)
    if match:
        engine = SITE_WORDS.get(match.group(2) or "", match.group(2) or "")
        engine = engine if engine in SEARCH_ENGINES else ("google" if low.startswith(("google", "search", "look", "find")) else "google")
        text_key = next((k for k, v in cands.items() if v.lower() == _clean(match.group(1)).lower()), "c1")
        return done(_plan("search", 0.85, "local", engine=engine, text=cands.get(text_key, match.group(1)), text_key=text_key))
    match = re.match(r"^play (.+?)(?: on (youtube|spotify))?$", low)
    if match:
        engine = match.group(2) or "youtube"
        return done(_plan("search", 0.75, "local", engine=engine, text=_clean(match.group(1))))
    for pattern, key in SHORTCUT_WORDS.items():
        if re.fullmatch(rf"(?:press |hit |do (?:a )?)?(?:{pattern})(?: (?:it|this|that|the page))?", low):
            return done(_plan("shortcut", 0.9, "local", key=key))
    match = re.match(r"^(?:go to|open|visit|navigate to|pull up|bring up|show me|launch|start|switch to)\s+(.+)$", low)
    if match:
        target = _clean(match.group(1))
        site = SITE_WORDS.get(target, target.replace(" dot com", "").replace(".com", "").replace(" ", ""))
        url_like = re.search(r"\b([\w-]+(?:\.[\w-]+)+)\b|\b([\w-]+) dot (com|org|net|io|ai|dev|app)\b", target)
        if site in SITES and not low.startswith(("launch", "start", "switch")):
            return done(_plan("open_site", 0.9, "local", site=site, url=SITES[site]))
        app = _match_app(target, installed_apps())
        if app:
            return done(_plan("open_app", 0.9, "local", app=app))
        if site in SITES:
            return done(_plan("open_site", 0.85, "local", site=site, url=SITES[site]))
        if url_like:
            domain = url_like.group(1) or f"{url_like.group(2)}.{url_like.group(3)}"
            return done(_plan("open_site", 0.8, "local", site="other", url=f"https://{domain}"))
        return done(_plan("open_app", 0.3, "local", app="", asked=target))
    return done(_plan("chat", 0.6, "local"))


def jev_key() -> str:
    key = os.getenv("TYPESAFE_API_KEY", "").strip()
    if key:
        return key
    try:
        from secret_store import get_keys

        return (get_keys("TYPESAFE_API_KEY") or [""])[0]
    except Exception:  # noqa: BLE001
        return ""


def jev_questions(cands: Dict[str, str], apps: List[str]) -> Dict[str, Any]:
    """The request jev-voice sends, for Windows: one choice per closed set, answered together in one round trip."""
    yes_no = {"true": "Yes", "false": "No"}
    return {
        "action": {"type": "choice", "criteria": ACTIONS,
                   "instructions": "The user is speaking or typing a command to their Windows PC. `utterance` is what they said. "
                                   "Which single kind of action do they want done right now?"},
        "app": {"type": "choice", "criteria": {**{a: None for a in apps}, "none": "No listed application matches"},
                "instructions": "Assume they want to open or switch to an application. Which app in `apps` do they mean?"},
        "site": {"type": "choice", "criteria": {**{s: None for s in SITES}, "other": "A site not in this list"},
                 "instructions": "Assume they want a website. Which site do they mean?"},
        "engine": {"type": "choice", "criteria": {e: None for e in SEARCH_ENGINES},
                   "instructions": "Assume they want to search. On which site? If none is named, choose google."},
        "text": {"type": "choice", "criteria": dict(cands),
                 "instructions": "Which candidate is exactly the text they want typed or searched, with no command words?"},
        "shortcut": {"type": "choice", "criteria": {k: v[1] for k, v in SHORTCUTS.items()},
                     "instructions": "Assume they want a keyboard shortcut. Which one?"},
        "system_op": {"type": "choice", "criteria": SYSTEM_OPS, "instructions": "Assume a system action. Which one?"},
        "volume_op": {"type": "choice", "criteria": {v: None for v in VOLUME_OPS}, "instructions": "Which volume change?"},
        "media_op": {"type": "choice", "criteria": {m: None for m in MEDIA_OPS}, "instructions": "Which media control?"},
        "scroll_dir": {"type": "choice", "criteria": {"up": None, "down": None, "top": None, "bottom": None},
                       "instructions": "Which way should the page scroll?"},
        "submit": {"type": "noul", "criteria": yes_no, "instructions": "Should Enter be pressed after typing?"},
        "compound": {"type": "noul", "criteria": yes_no,
                     "instructions": "Does the utterance ask for two or more separate actions one after another?"},
    }


def plan_jev(utterance: str, key: str = "", timeout: float = 4.0) -> Dict[str, Any]:
    """Ask Jev itself (TypeSafe) — one HTTPS request with every question in it. Raises on any failure."""
    key = key or jev_key()
    if not key:
        raise RuntimeError("No TYPESAFE_API_KEY")
    apps = sorted(installed_apps())[:400]
    cands = text_candidates(utterance) or {"c1": _clean(utterance)}
    body = {"model": os.getenv("TYPESAFE_MODEL", JEV_MODEL),
            "state": {"utterance": utterance, "platform": "windows", "apps": apps, "candidates": cands},
            "questions": jev_questions(cands, apps)}
    started = time.perf_counter()
    request = urllib.request.Request(JEV_URL, data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https endpoint
        answers = json.loads(response.read().decode("utf-8")).get("answers") or {}
    ms = round((time.perf_counter() - started) * 1000, 1)

    def pick(name: str, allowed: Any) -> Tuple[str, float]:
        answer = answers.get(name) or {}
        choice = str(answer.get("choice", ""))
        if choice not in allowed:
            return "", 0.0
        return choice, float(answer.get("confidence", (answer.get("probabilities") or {}).get(choice, 0)) or 0)

    action, confidence = pick("action", ACTIONS)
    if not action:
        raise RuntimeError("Jev gave no usable action")
    args: Dict[str, Any] = {}
    used = [confidence]

    def take(name: str, allowed: Any) -> str:
        choice, conf = pick(name, allowed)
        used.append(conf)
        return choice

    if action == "open_app":
        app = take("app", apps + ["none"])
        args = {"app": "" if app == "none" else app}
    elif action == "open_site":
        site = take("site", list(SITES) + ["other"])
        args = {"site": site, "url": SITES.get(site, "")}
    elif action == "search":
        key_ = take("text", cands)
        args = {"engine": take("engine", SEARCH_ENGINES) or "google", "text": cands.get(key_, ""), "text_key": key_}
    elif action == "type_text":
        key_ = take("text", cands)
        args = {"text": cands.get(key_, ""), "text_key": key_, "submit": take("submit", ("true", "false")) == "true"}
    elif action == "shortcut":
        args = {"key": take("shortcut", SHORTCUTS)}
    elif action == "system":
        args = {"op": take("system_op", SYSTEM_OPS)}
    elif action == "volume":
        args = {"op": take("volume_op", VOLUME_OPS)}
    elif action == "media":
        args = {"op": take("media_op", MEDIA_OPS)}
    elif action == "scroll":
        way = take("scroll_dir", ("up", "down", "top", "bottom"))
        args = {"direction": "up" if way in ("up", "top") else "down", "amount": 50 if way in ("top", "bottom") else 6}
    elif action == "task":
        args = {"goal": _clean(utterance), "steps": split_compound(utterance)}
    plan = _plan(action, min(used), "jev", **args)
    plan["ms"] = ms
    return plan


def plan(utterance: str) -> Dict[str, Any]:
    """Jev when a key is set and it answers; the local chooser otherwise (and always within a few ms)."""
    if jev_key():
        try:
            return plan_jev(utterance)
        except Exception as error:  # noqa: BLE001 - Jev down or key wrong: never block the command
            local = plan_local(utterance)
            local["jev_error"] = str(error)[:160]
            return local
    return plan_local(utterance)


# ---------------------------------------------------------------------------
# Execution — Windows only, closed sets only
# ---------------------------------------------------------------------------

def _press(keys: List[str]) -> None:
    import ctypes

    codes = [VK[k] for k in keys if k in VK]
    user32 = ctypes.windll.user32
    for code in codes:
        user32.keybd_event(code, 0, 0, 0)
    for code in reversed(codes):
        user32.keybd_event(code, 0, 2, 0)


def _type_unicode(text: str) -> None:
    """SendInput with KEYEVENTF_UNICODE — types any character into the focused window."""
    import ctypes
    from ctypes import wintypes

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    events = []
    for char in text:
        for flags in (0x0004, 0x0004 | 0x0002):
            item = INPUT(type=1)
            item.ki = KEYBDINPUT(0, ord(char) if ord(char) < 0x10000 else 0x3F, flags, 0, 0)
            events.append(item)
    if events:
        array = (INPUT * len(events))(*events)
        ctypes.windll.user32.SendInput(len(events), array, ctypes.sizeof(INPUT))


def _scroll(direction: str, amount: int) -> None:
    import ctypes

    clicks = max(1, min(60, int(amount)))
    ctypes.windll.user32.mouse_event(0x0800, 0, 0, (120 if direction == "up" else -120) * clicks, 0)


def _open(target: str) -> None:
    os.startfile(target)  # type: ignore[attr-defined]  # noqa: S606 - target comes from a closed set or a URL we built


def execute(plan_: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
    """Do what the plan says. Only keys from the closed sets are accepted; returns {ok, said}."""
    action, args = plan_.get("action"), dict(plan_.get("args") or {})
    if plan_.get("confidence", 0) < MIN_CONFIDENCE and action not in ("chat", "task"):
        return {"ok": False, "said": "I'm not sure what you meant — say it another way?"}
    if sys.platform != "win32" and not dry_run:
        return {"ok": False, "said": "Desktop actions only run on Windows."}
    try:
        if action == "open_app":
            apps = installed_apps()
            name = args.get("app") or ""
            if name not in apps:
                return {"ok": False, "said": f"I couldn't find an app called {args.get('asked') or name or 'that'}."}
            if not dry_run:
                _open(apps[name])
            return {"ok": True, "said": f"Opening {name.title()}."}
        if action == "open_site":
            url = args.get("url") or ""
            if not url.startswith("https://"):
                return {"ok": False, "said": "I don't know that site."}
            if not dry_run:
                _open(url)
            return {"ok": True, "said": f"Opening {urllib.parse.urlparse(url).netloc}."}
        if action == "search":
            template = SEARCH_ENGINES.get(args.get("engine") or "google", SEARCH_ENGINES["google"])
            text = _clean(args.get("text") or "")
            if not text:
                return {"ok": False, "said": "Search for what?"}
            if not dry_run:
                _open(template.format(q=urllib.parse.quote_plus(text)))
            return {"ok": True, "said": f"Searching {args.get('engine') or 'google'} for {text}."}
        if action == "type_text":
            text = str(args.get("text") or "")
            if not text:
                return {"ok": False, "said": "Type what?"}
            if not dry_run:
                _type_unicode(text)
                if args.get("submit"):
                    _press(["enter"])
            return {"ok": True, "said": "Typed it."}
        if action == "shortcut":
            key = args.get("key") or ""
            if key not in SHORTCUTS:
                return {"ok": False, "said": "I don't know that shortcut."}
            if not dry_run:
                _press(SHORTCUTS[key][0])
            return {"ok": True, "said": SHORTCUTS[key][1].capitalize() + "."}
        if action == "scroll":
            if not dry_run:
                _scroll(args.get("direction") or "down", int(args.get("amount") or 6))
            return {"ok": True, "said": "Scrolled."}
        if action == "volume":
            op = args.get("op") or "up"
            if not dry_run:
                if op == "max":
                    for _ in range(25):
                        _press(["volume_up"])
                elif op in ("mute", "unmute"):
                    _press(["volume_mute"])
                else:
                    for _ in range(5):
                        _press(["volume_up" if op == "up" else "volume_down"])
            return {"ok": True, "said": {"up": "Louder.", "down": "Quieter.", "max": "Volume all the way up."}.get(op, "Mute toggled.")}
        if action == "media":
            op = args.get("op") or "play_pause"
            if not dry_run:
                _press([{"play_pause": "media_play", "next": "media_next", "previous": "media_prev", "stop": "media_stop"}[op]])
            return {"ok": True, "said": {"next": "Next.", "previous": "Back one.", "stop": "Stopped."}.get(op, "Play / pause.")}
        if action == "system":
            op = args.get("op") or ""
            if op not in SYSTEM_OPS:
                return {"ok": False, "said": "I don't know that one."}
            if not dry_run:
                home = Path.home()
                targets = {"downloads": home / "Downloads", "documents": home / "Documents",
                           "desktop_folder": home / "Desktop", "explorer": "explorer.exe", "settings": "ms-settings:",
                           "bluetooth": "ms-settings:bluetooth", "wifi": "ms-settings:network-wifi",
                           "display": "ms-settings:display", "sound_settings": "ms-settings:sound"}
                if op == "screenshot":
                    _press(["win", "shift", "S"])
                elif op == "lock":
                    import ctypes

                    ctypes.windll.user32.LockWorkStation()
                else:
                    _open(str(targets[op]))
            return {"ok": True, "said": SYSTEM_OPS[op].capitalize() + "."}
    except Exception as error:  # noqa: BLE001 - say what failed instead of crashing the turn
        return {"ok": False, "said": f"That didn't work: {error}"}
    return {"ok": False, "said": ""}


# ---------------------------------------------------------------------------
# The mode
# ---------------------------------------------------------------------------

_history: List[Dict[str, Any]] = []
_history_lock = threading.Lock()


def recent(limit: int = 20) -> List[Dict[str, Any]]:
    with _history_lock:
        return list(_history[-limit:])


def handle(text: str, dry_run: bool = False) -> Dict[str, Any]:
    """Plan and do a command. ``handled`` is False when it is conversation or a multi-step task for the chat."""
    started = time.perf_counter()
    first = plan(text)
    steps = [first]
    if first["action"] == "task" and first["args"].get("compound"):
        steps = [plan(part) for part in first["args"].get("steps") or []]
        if any(step["action"] in ("chat", "task") for step in steps):
            steps = [first]
    if len(steps) == 1 and steps[0]["action"] in ("chat", "task"):
        result = {"handled": False, "plan": first, "reply": "",
                  "ms": round((time.perf_counter() - started) * 1000, 1)}
    else:
        said, ok = [], True
        for index, step in enumerate(steps):
            if index:
                time.sleep(0.6)  # let an app or page open before the next keystrokes land
            done = execute(step, dry_run=dry_run)
            ok = ok and done["ok"]
            if done["said"]:
                said.append(done["said"])
        result = {"handled": True, "ok": ok, "plan": first if len(steps) == 1 else {"action": "compound", "steps": steps},
                  "reply": " ".join(said) or "Done.", "ms": round((time.perf_counter() - started) * 1000, 1)}
    with _history_lock:
        _history.append({"at": time.time(), "text": str(text)[:200], **{k: result[k] for k in ("handled", "reply", "ms")},
                         "action": result["plan"].get("action"), "via": result["plan"].get("via", "local")})
        del _history[:-50]
    return result


def status() -> Dict[str, Any]:
    return {"jev": bool(jev_key()), "model": os.getenv("TYPESAFE_MODEL", JEV_MODEL), "url": JEV_URL,
            "actions": ACTIONS, "recent": recent(10)}


# ---------------------------------------------------------------------------
# Judge before replying (jev-chat)
# ---------------------------------------------------------------------------

JUDGE_PROMPT = (
    "You read a message thread before anyone replies. Work out, in this order: what the other person really means "
    "(intent), how risky this moment is (low / medium / high and why), what they need, and the best action. Only "
    "then write three short reply drafts that fit that judgment, best first, each with a score 0-100 for how well it "
    "fits. Reply with JSON only: {\"intent\": str, \"risk\": \"low|medium|high\", \"risk_why\": str, \"needs\": str, "
    "\"best_action\": str, \"replies\": [{\"text\": str, \"score\": int, \"why\": str}]}. Never claim anything was sent."
)


def judge(conversation: str, me: str = "me", ask: Any = None) -> Dict[str, Any]:
    """Intent, risk and ranked reply drafts for a pasted conversation. Drafts only — nothing is sent."""
    conversation = str(conversation or "").strip()[:6000]
    if not conversation:
        return {"error": "Paste the conversation first."}
    prompt = f"{JUDGE_PROMPT}\n\nI am {me}. The thread:\n{conversation}"
    if ask is None:
        from router import ModelRouter

        def ask(text: str) -> str:
            return str(ModelRouter().chat([{"role": "user", "content": text}])[0] or "")
    raw = ask(prompt)
    match = re.search(r"\{.*\}", raw or "", re.S)
    try:
        data = json.loads(match.group(0)) if match else {}
    except ValueError:
        data = {}
    replies = sorted((r for r in data.get("replies") or [] if isinstance(r, dict) and r.get("text")),
                     key=lambda r: -int(r.get("score") or 0))[:3]
    return {"intent": str(data.get("intent") or ""), "risk": str(data.get("risk") or "low"),
            "risk_why": str(data.get("risk_why") or ""), "needs": str(data.get("needs") or ""),
            "best_action": str(data.get("best_action") or ""), "replies": replies}


def tool_ultrafast(command: str) -> str:
    result = handle(command)
    if not result["handled"]:
        return "Not a desktop command — answer it normally."
    return f"{result['reply']} ({result['ms']} ms, {result['plan'].get('via', 'local')})"


def tool_judge_reply(conversation: str, me: str = "me") -> str:
    return json.dumps(judge(conversation, me), ensure_ascii=False)


def register_ultrafast_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        name="ultrafast_command",
        description="Do a quick desktop command at once (open an app or site, search, type, a shortcut, scroll, "
                    "volume, media, screenshot, lock). Code picks from fixed lists and does it in milliseconds.",
        parameters=[ToolParam("command", "string", "What to do, in plain words")],
        handler=tool_ultrafast, category="machine", label=lambda a: "Ultra Fast",
    )
    registry.register(
        name="judge_reply",
        description="Read a message thread before replying: intent, risk, what they need, the best action, and "
                    "three ranked reply drafts. Never sends anything.",
        parameters=[ToolParam("conversation", "string", "The thread, oldest first"),
                    ToolParam("me", "string", "Which speaker is the owner", required=False)],
        handler=tool_judge_reply, category="general", label=lambda a: "Reading the thread",
    )
