"""Morning Digest: one short briefing each day — what's on, what came in, the weather, the news you follow, the
markets, and what Nyx's offices finished overnight. Spoken on the equalize page, and texted to the phone if wanted.

From OpenJarvis (Apache-2.0), which the owner pointed at on 2026-10-09: its ``morning_digest`` agent is "a daily
spoken briefing from email, calendar, health, and news". This is Nyx's own version, built from what Nyx already has:
Google Calendar and Gmail through Connectors, the mail accounts in Keys, Open-Meteo for the weather (no key),
``web_access`` for the news, ``trading.market`` for prices, and the offices' Output boxes.

Every section is optional and fails on its own: a source that is not connected, or does not answer, is left out and
named in ``skipped`` — the digest still arrives. The model only writes the spoken words from the facts gathered; with
no model answering, the facts are read out as they are.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from paths import data_path

log = logging.getLogger("nyx.digest")

SETTINGS_FILE = "digest.json"
SOURCES = ("calendar", "email", "weather", "news", "markets", "nyx")
DEFAULTS: Dict[str, Any] = {
    "enabled": False,               # the daily schedule; "Brief me now" works either way
    "time": "07:30",
    "city": "",
    "topics": ["AI", "technology"],
    "symbols": ["SPY", "QQQ"],
    "sources": {name: True for name in SOURCES},
    "whatsapp": False,              # also text it to the owner's phone (whatsapp_link, opt-in there too)
    "last": {},
    "last_day": "",
}


class DigestError(RuntimeError):
    """Something the owner can act on."""


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def _path():
    return data_path(SETTINGS_FILE)


def settings() -> Dict[str, Any]:
    try:
        saved = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    merged = {**DEFAULTS, **(saved if isinstance(saved, dict) else {})}
    merged["sources"] = {**DEFAULTS["sources"], **(merged.get("sources") or {})}
    return merged


def _write(data: Dict[str, Any]) -> None:
    target = _path()
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, target)


def save(changes: Dict[str, Any]) -> Dict[str, Any]:
    data = settings()
    if "enabled" in changes:
        data["enabled"] = bool(changes["enabled"])
    if "time" in changes:
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(changes["time"] or "")):
            raise DigestError("Give the time as HH:MM, e.g. 07:30.")
        data["time"] = str(changes["time"])
    if "city" in changes:
        data["city"] = str(changes["city"] or "").strip()[:60]
    if "topics" in changes:
        data["topics"] = [str(t).strip()[:40] for t in (changes["topics"] or []) if str(t).strip()][:5]
    if "symbols" in changes:
        data["symbols"] = [re.sub(r"[^A-Z0-9.\-]", "", str(s).upper())[:10] for s in (changes["symbols"] or [])
                           if str(s).strip()][:6]
    if "sources" in changes and isinstance(changes["sources"], dict):
        data["sources"] = {**data["sources"], **{k: bool(v) for k, v in changes["sources"].items() if k in SOURCES}}
    if "whatsapp" in changes:
        data["whatsapp"] = bool(changes["whatsapp"])
    _write(data)
    return data


# ---------------------------------------------------------------------------
# The sections — each returns lines of plain facts, or raises to be skipped
# ---------------------------------------------------------------------------


def _calendar(_conf: Dict[str, Any]) -> List[str]:
    import connector_use

    if not connector_use.is_connected("google_calendar"):
        raise DigestError("Google Calendar is not connected")
    start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    result = connector_use.call("google_calendar", "events", params={
        "calendar_id": "primary", "timeMin": start.isoformat(), "timeMax": (start + timedelta(days=1)).isoformat(),
        "singleEvents": "true", "orderBy": "startTime", "maxResults": "10"})
    events = (result.get("data") or {}).get("items") or []
    lines = []
    for event in events:
        when = (event.get("start") or {}).get("dateTime") or (event.get("start") or {}).get("date") or ""
        clock = when[11:16] if "T" in when else "all day"
        lines.append(f"{clock} {event.get('summary') or 'Untitled'}")
    return lines or ["Nothing on the calendar today."]


def _email(_conf: Dict[str, Any]) -> List[str]:
    import connector_use

    if connector_use.is_connected("gmail"):
        try:
            result = connector_use.call("gmail", "search", params={"q": "is:unread newer_than:1d", "maxResults": "10"})
            data = result.get("data") or {}
            count = int(data.get("resultSizeEstimate") or len(data.get("messages") or []))
            return [f"{count} unread email{'s' if count != 1 else ''} from the last day."]
        except Exception:  # noqa: BLE001 - e.g. Gmail set up with an app password: Nyx's own mail reader instead
            pass
    import email_client

    messages = email_client.list_emails(unread_only=True, limit=8)
    lines = [f"{len(messages)} unread email{'s' if len(messages) != 1 else ''}."]
    lines += [f"From {m.get('from', '')[:40]}: {m.get('subject', '')[:80]}" for m in messages[:4]]
    return lines


def _weather(conf: Dict[str, Any]) -> List[str]:
    import requests

    city = conf.get("city") or ""
    if not city:
        raise DigestError("no city set")
    place = requests.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": city, "count": 1},
                         timeout=10).json().get("results") or []
    if not place:
        raise DigestError(f"could not find {city}")
    p = place[0]
    data = requests.get("https://api.open-meteo.com/v1/forecast", timeout=10, params={
        "latitude": p["latitude"], "longitude": p["longitude"], "current": "temperature_2m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max", "timezone": "auto",
        "forecast_days": 1}).json()
    daily = data.get("daily") or {}
    now = (data.get("current") or {}).get("temperature_2m")
    high = (daily.get("temperature_2m_max") or [None])[0]
    low = (daily.get("temperature_2m_min") or [None])[0]
    rain = (daily.get("precipitation_probability_max") or [None])[0]
    return [f"{p.get('name', city)}: {now}°C now, high {high}°C, low {low}°C, {rain}% chance of rain."]


def _news(conf: Dict[str, Any]) -> List[str]:
    import web_access

    lines = []
    for topic in (conf.get("topics") or [])[:3]:
        results = web_access.search_results(f"{topic} news today", freshness="day")[:2]
        for item in results:
            title = str(item.get("title") or "").strip()
            if title:
                lines.append(f"{topic}: {title[:120]}")
    if not lines:
        raise DigestError("no news came back")
    return lines


def _markets(conf: Dict[str, Any]) -> List[str]:
    from trading import market

    lines = []
    for symbol in conf.get("symbols") or []:
        try:
            q = market.quote(symbol)
            lines.append(f"{symbol} {q['price']:.2f} ({q.get('change_pct', 0):+.2f}%)")
        except Exception:  # noqa: BLE001 - one symbol missing is not the section
            continue
    if not lines:
        raise DigestError("no prices came back")
    return lines


def _nyx(_conf: Dict[str, Any]) -> List[str]:
    from office import engine as office_engine, library

    since = time.time() - 86400
    lines = []
    for item in library.tree().get("offices", [])[:30]:
        # An office already open in the engine is read from memory (it may have news not yet saved); any other is
        # read from its file. Never ENGINE.open: that would keep it in memory and save idle offices back to disk.
        office = office_engine.ENGINE.opened(item["id"])
        if office is None:
            try:
                office = library.load(item["id"])
            except Exception:  # noqa: BLE001
                continue
        for output in office.outputs:
            if output.ts >= since:
                lines.append(f"Office {office.name} delivered: {output.title[:80]} ({output.status})")
    running = office_engine.ENGINE.running_offices()
    if running:
        lines.append(f"{len(running)} office{'s are' if len(running) != 1 else ' is'} still working.")
    return lines or ["Nothing new from the offices overnight."]


SECTIONS: Dict[str, Callable[[Dict[str, Any]], List[str]]] = {
    "calendar": _calendar, "email": _email, "weather": _weather, "news": _news, "markets": _markets, "nyx": _nyx,
}
TITLES = {"calendar": "Today", "email": "Email", "weather": "Weather", "news": "News", "markets": "Markets",
          "nyx": "Nyx overnight"}


# ---------------------------------------------------------------------------
# Building and delivering
# ---------------------------------------------------------------------------


def _speak_words(facts: Dict[str, List[str]]) -> str:
    """The briefing as spoken words: a model writes it from the facts; without one, the facts are read out."""
    plain = " ".join(f"{TITLES[name]}: " + " ".join(lines) for name, lines in facts.items())
    try:
        from model_roles import MODEL_ROLES

        run = MODEL_ROLES.run("fast_chat", (
            "Write a morning briefing to be read aloud, under 140 words, warm and plain, no lists or markdown. Use only "
            "these facts; skip a section with nothing worth saying.\n\n"
            + "\n".join(f"{TITLES[n]}:\n- " + "\n- ".join(lines) for n, lines in facts.items())), max_tokens=400)
        text = re.sub(r"<think>.*?</think>", "", run.text or "", flags=re.S).strip()
        return text or plain
    except Exception:  # noqa: BLE001 - no model: the facts themselves
        return plain


def build(conf: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    conf = conf or settings()
    facts: Dict[str, List[str]] = {}
    skipped: Dict[str, str] = {}
    for name, gather in SECTIONS.items():
        if not conf["sources"].get(name, True):
            continue
        try:
            lines = [line for line in gather(conf) if line]
            if lines:
                facts[name] = lines[:8]
        except Exception as error:  # noqa: BLE001 - a missing source is named, never fatal
            skipped[name] = str(error)[:120] or type(error).__name__
    digest = {"at": time.time(), "facts": facts, "skipped": skipped,
              "text": _speak_words(facts) if facts else "Good morning. Nothing to report yet — connect a calendar or "
                                                         "set a city in the equalize page's Morning Digest."}
    data = settings()
    data["last"] = digest
    _write(data)
    return digest


def deliver(digest: Dict[str, Any]) -> None:
    """Where a finished digest goes besides the equalize page: a toast, and the phone when both switches allow it."""
    try:
        from landscape_tools import tool_ui_notify

        tool_ui_notify("Your morning digest is ready — open Jarvis to hear it.", "info")
    except Exception:  # noqa: BLE001
        pass
    if settings().get("whatsapp"):
        try:
            import whatsapp_link

            link = whatsapp_link._LINK or whatsapp_link.link()
            if link.state.get("status") == "linked" and link.connected:
                link.send("Morning digest\n\n" + digest["text"], origin="digest")
        except Exception:  # noqa: BLE001
            log.info("digest not sent to the phone", exc_info=True)


def due(conf: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """Once a day, at or after the chosen time, only when the schedule is on."""
    now = now or datetime.now()
    if not conf.get("enabled") or conf.get("last_day") == now.strftime("%Y-%m-%d"):
        return False
    hour, minute = (int(x) for x in str(conf.get("time") or "07:30").split(":"))
    return (now.hour, now.minute) >= (hour, minute)


def _loop() -> None:
    while True:
        try:
            conf = settings()
            if due(conf):
                conf["last_day"] = datetime.now().strftime("%Y-%m-%d")
                _write(conf)
                deliver(build(conf))
        except Exception:  # noqa: BLE001 - the schedule keeps going
            log.warning("morning digest failed", exc_info=True)
        time.sleep(60)


_started = threading.Event()


def start_in_background() -> None:
    if _started.is_set():
        return
    _started.set()
    threading.Thread(target=_loop, name="nyx-morning-digest", daemon=True).start()


def tool_digest() -> str:
    digest = build()
    return digest["text"] + (f"\n\n(Not included: {', '.join(digest['skipped'])}.)" if digest["skipped"] else "")


def register_digest_tools(registry: Any) -> None:
    registry.register("morning_digest", "Make the owner's morning digest now: today's calendar, unread email, weather, "
                      "the news they follow, markets and what Nyx's offices finished. Use for 'brief me', 'what's my "
                      "day', 'morning update'.", [], tool_digest, category="general", label="Making your morning digest")
