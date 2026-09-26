"""Better talking: natural neural voices, and a different voice for each speaker.

The owner asked to "make sure the AI talking is better. Multiple voices." Windows'
SAPI voices (David, Zira) are all this PC had. This adds:

* **Neural voices** — Microsoft's free online voices through ``edge-tts``
  (Ava, Andrew, Sonia, Natasha…, 400+ in every language). Online only.
* **SAPI** — the installed Windows voices, rendered to WAV, as the offline fallback.
* **A voice per role** — Nyx's replies, the narrator, and each default agent
  (Manager, Coder, Educator…) speak in their own voice; the owner or Nyx can
  change any of them.

Speech is synthesized here and *played by the browser*: the ``speak`` tool
publishes ``voice.say`` with a URL to the cached audio. If no window is open to
hear it, it plays through the PC's speakers with the existing ``voice`` module.
Audio is cached by (engine, voice, rate, pitch, text) so repeats are instant.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from paths import data_path

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_MAX_CHARS = 5000
_CACHE_FILES = 300
_CATALOG_TTL = 7 * 24 * 3600

#: Default voice for each role. Chosen from the roster's ``voice_hint``s.
DEFAULT_ROLE_VOICES: Dict[str, str] = {
    "reply": "en-US-AvaMultilingualNeural",
    "narrator": "en-US-AndrewMultilingualNeural",
    "manager": "en-US-BrianMultilingualNeural",
    "coder": "en-US-GuyNeural",
    "web_design": "en-GB-SoniaNeural",
    "app_design": "en-NZ-MollyNeural",
    "finance": "en-US-EricNeural",
    "educator": "en-GB-LibbyNeural",
    "tech": "en-US-ChristopherNeural",
    "hardware": "en-US-RogerNeural",
    "news": "en-US-AriaNeural",
    "researcher": "en-GB-RyanNeural",
    "writer_editor": "en-IE-EmilyNeural",
    "email_comms": "en-US-JennyNeural",
    "computer_operator": "en-US-SteffanNeural",
    "data_analyst": "en-US-EmmaMultilingualNeural",
    "security": "en-GB-ThomasNeural",
    "planner": "en-US-MichelleNeural",
    "creative_games": "en-CA-ClaraNeural",
    "travel": "en-AU-NatashaNeural",
}

#: Shown when the online catalog can't be fetched (offline first run).
_FALLBACK_CATALOG = [
    {"id": voice, "name": re.sub(r"(Multilingual)?Neural$", "", voice.split("-", 2)[2]), "locale": "-".join(voice.split("-")[:2]),
     "gender": "", "engine": "edge"}
    for voice in dict.fromkeys(DEFAULT_ROLE_VOICES.values())
]


class TTSError(RuntimeError):
    pass


_lock = threading.Lock()


def _cache_dir() -> Path:
    path = data_path("tts_cache")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _roles_path() -> Path:
    return data_path("voice_roles.json")


def _catalog_path() -> Path:
    return data_path("edge_voices.json")


def edge_available() -> bool:
    try:
        import edge_tts  # noqa: F401

        return True
    except Exception:
        return False


def sapi_available() -> bool:
    return os.name == "nt"


def engines() -> List[Dict[str, Any]]:
    return [
        {"id": "browser", "available": True, "note": "The browser's own voices; no server needed."},
        {"id": "edge", "available": edge_available(), "note": "Microsoft neural voices (free, needs internet)."},
        {"id": "sapi", "available": sapi_available(), "note": "Voices installed in Windows; works offline."},
    ]


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


def _run_async(coro: Any) -> Any:
    """Run a coroutine from sync code, even if this thread already has a loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    result: Dict[str, Any] = {}

    def worker() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as error:  # noqa: BLE001 - re-raised below
            result["error"] = error

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def neural_voices(locale: str = "", refresh: bool = False) -> List[Dict[str, Any]]:
    """Every edge voice (cached for a week), optionally filtered by locale prefix ("en", "en-GB")."""
    catalog: List[Dict[str, Any]] = []
    path = _catalog_path()
    try:
        if not refresh and path.is_file() and time.time() - path.stat().st_mtime < _CATALOG_TTL:
            catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        catalog = []
    if not catalog and edge_available():
        try:
            import edge_tts

            raw = _run_async(edge_tts.list_voices())
            catalog = [{"id": v["ShortName"], "name": v.get("FriendlyName", v["ShortName"]).replace("Microsoft ", "").split(" Online")[0],
                        "locale": v.get("Locale", ""), "gender": v.get("Gender", ""), "engine": "edge",
                        "styles": (v.get("VoiceTag") or {}).get("VoicePersonalities", [])}
                       for v in raw]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(catalog), encoding="utf-8")
        except Exception:
            catalog = []
    if not catalog:
        catalog = list(_FALLBACK_CATALOG)
    wanted = (locale or "").lower()
    return [v for v in catalog if not wanted or v["locale"].lower().startswith(wanted)]


def sapi_voices() -> List[Dict[str, Any]]:
    try:
        import voice

        return [{"id": v["name"], "name": v["name"], "locale": v.get("culture", ""), "gender": v.get("gender", ""), "engine": "sapi"}
                for v in voice.list_voices()]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Role voices
# ---------------------------------------------------------------------------


def role_voices() -> Dict[str, str]:
    try:
        saved = json.loads(_roles_path().read_text(encoding="utf-8"))
        saved = {k: v for k, v in saved.items() if isinstance(v, str) and v}
    except (OSError, ValueError, AttributeError):
        saved = {}
    return {**DEFAULT_ROLE_VOICES, **saved}


def voice_for(role: str = "reply") -> str:
    voices = role_voices()
    key = re.sub(r"[^a-z0-9_]+", "_", (role or "reply").lower()).strip("_")
    return voices.get(key) or voices["reply"]


def set_role_voice(role: str, voice_id: str) -> Dict[str, str]:
    key = re.sub(r"[^a-z0-9_]+", "_", (role or "").lower()).strip("_")
    if not key:
        raise TTSError("Which role? For example reply, narrator, coder, educator.")
    with _lock:
        try:
            saved = json.loads(_roles_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        if voice_id:
            saved[key] = voice_id
        else:
            saved.pop(key, None)
        path = _roles_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(saved, indent=2), encoding="utf-8")
    try:
        from agent_events import publish_ui

        publish_ui("voice.roles.changed", role=key, voice=voice_id or DEFAULT_ROLE_VOICES.get(key, ""))
    except Exception:
        pass
    return role_voices()


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------


_RATE = re.compile(r"^[+-]\d{1,3}%$")
_PITCH = re.compile(r"^[+-]\d{1,3}Hz$")


def _clean_text(text: str) -> str:
    """Speakable text: drop markdown, code blocks, links and image syntax."""
    value = re.sub(r"```.*?```", " (code omitted) ", text or "", flags=re.S)
    value = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"`([^`]*)`", r"\1", value)
    value = re.sub(r"^\s{0,3}#{1,6}\s*", "", value, flags=re.M)
    value = re.sub(r"[*_~>|]+", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:_MAX_CHARS]


def cache_key(engine: str, voice_id: str, rate: str, pitch: str, text: str) -> str:
    return hashlib.sha256(f"{engine}|{voice_id}|{rate}|{pitch}|{text}".encode("utf-8")).hexdigest()[:32]


def cached_audio(key: str) -> Optional[Tuple[Path, str]]:
    if not re.fullmatch(r"[0-9a-f]{32}", key or ""):
        return None
    for ext, mime in (("mp3", "audio/mpeg"), ("wav", "audio/wav")):
        path = _cache_dir() / f"{key}.{ext}"
        if path.is_file():
            return path, mime
    return None


def _trim_cache() -> None:
    try:
        files = sorted(_cache_dir().glob("*.*"), key=lambda p: p.stat().st_mtime)
        for old in files[:-_CACHE_FILES]:
            old.unlink(missing_ok=True)
    except OSError:
        pass


def _edge_bytes(text: str, voice_id: str, rate: str, pitch: str) -> bytes:
    import edge_tts

    async def run() -> bytes:
        chunks = []
        async for chunk in edge_tts.Communicate(text, voice_id, rate=rate, pitch=pitch).stream():
            if chunk.get("type") == "audio":
                chunks.append(chunk["data"])
        return b"".join(chunks)

    try:
        audio = _run_async(run())
    except Exception as error:
        raise TTSError(f"Neural voice {voice_id} failed ({type(error).__name__}: {str(error)[:120]}). "
                       "It needs internet; the Windows voices work offline.") from error
    if not audio:
        raise TTSError(f"Neural voice {voice_id} returned no audio — check the voice name.")
    return audio


def _sapi_bytes(text: str, voice_id: str, rate: str) -> bytes:
    if not sapi_available():
        raise TTSError("Windows voices are only available on Windows.")
    fd, out = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    speed = max(-10, min(10, round(int(rate.rstrip("%")) / 10))) if _RATE.match(rate) else 0
    script = (
        "Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "if ($env:NYX_VOICE) { try { $s.SelectVoice($env:NYX_VOICE) } catch {} }; $s.Rate = [int]$env:NYX_RATE; "
        "$s.SetOutputToWaveFile($env:NYX_OUT); $s.Speak($env:NYX_TEXT); $s.Dispose()"
    )
    env = {**os.environ, "NYX_VOICE": voice_id if not voice_id.endswith("Neural") else "", "NYX_RATE": str(speed),
           "NYX_OUT": out, "NYX_TEXT": text}
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                                text=True, timeout=120, env=env, creationflags=_NO_WINDOW)
        data = Path(out).read_bytes() if Path(out).is_file() else b""
        if result.returncode != 0 or len(data) < 100:
            raise TTSError(f"Windows voice failed: {(result.stderr or '').strip()[:160]}")
        return data
    except subprocess.TimeoutExpired as error:
        raise TTSError("Windows voice timed out.") from error
    finally:
        try:
            os.unlink(out)
        except OSError:
            pass


def synthesize(text: str, voice_id: str = "", rate: str = "+0%", pitch: str = "+0Hz", engine: str = "",
               role: str = "") -> Dict[str, Any]:
    """Audio for ``text``. Returns ``{key, path, mime, engine, voice, cached, chars}``.

    Engine defaults to edge for neural voice ids and SAPI otherwise; a failed
    neural voice falls back to SAPI (and says so in ``fallback``).
    """
    spoken = _clean_text(text)
    if not spoken:
        raise TTSError("Nothing to say.")
    chosen = voice_id or voice_for(role or "reply")
    rate = rate if _RATE.match(rate or "") else "+0%"
    pitch = pitch if _PITCH.match(pitch or "") else "+0Hz"
    engine = engine or ("edge" if chosen.endswith("Neural") and edge_available() else "sapi")
    fallback = ""
    key = cache_key(engine, chosen, rate, pitch, spoken)
    hit = cached_audio(key)
    if hit:
        os.utime(hit[0])
        return {"key": key, "path": str(hit[0]), "mime": hit[1], "engine": engine, "voice": chosen, "cached": True,
                "chars": len(spoken), "fallback": ""}
    if engine == "edge":
        try:
            data, ext, mime = _edge_bytes(spoken, chosen, rate, pitch), "mp3", "audio/mpeg"
        except TTSError as error:
            if not sapi_available():
                raise
            fallback = str(error)
            engine, key = "sapi", cache_key("sapi", chosen, rate, pitch, spoken)
            data, ext, mime = _sapi_bytes(spoken, "", rate), "wav", "audio/wav"
    elif engine == "sapi":
        data, ext, mime = _sapi_bytes(spoken, chosen, rate), "wav", "audio/wav"
    else:
        raise TTSError(f"Unknown voice engine {engine!r}. Use edge or sapi.")
    path = _cache_dir() / f"{key}.{ext}"
    path.write_bytes(data)
    _trim_cache()
    return {"key": key, "path": str(path), "mime": mime, "engine": engine, "voice": chosen, "cached": False,
            "chars": len(spoken), "fallback": fallback}


def say(text: str, role: str = "reply", voice_id: str = "", rate: str = "+0%", pitch: str = "+0Hz") -> Dict[str, Any]:
    """Speak to the user: the open Nyx window plays it; with no window, the PC speakers do."""
    result = synthesize(text, voice_id=voice_id, rate=rate, pitch=pitch, role=role)
    listeners = 0
    try:
        from agent_events import BUS, publish_ui

        listeners = BUS.subscriber_count("ui")
        publish_ui("voice.say", say_id=uuid.uuid4().hex[:12], text=_clean_text(text)[:600], role=role,
                   voice=result["voice"], engine=result["engine"],
                   audio_url=f"/api/voice/audio/{result['key']}", mime=result["mime"])
    except Exception:
        listeners = 0
    result["played_by"] = "browser" if listeners else "speakers"
    if not listeners:
        _play_locally(result["path"])
    return result


def _play_locally(path: str) -> None:
    """Play a cached file on this PC without opening a window (WAV via SoundPlayer, MP3 via MediaPlayer)."""
    if os.name != "nt":
        return
    script = (
        "if ($env:NYX_AUDIO.EndsWith('.wav')) { (New-Object Media.SoundPlayer $env:NYX_AUDIO).PlaySync() } else { "
        "Add-Type -AssemblyName PresentationCore; $p = New-Object System.Windows.Media.MediaPlayer; "
        "$p.Open([uri]$env:NYX_AUDIO); $p.Play(); Start-Sleep -Milliseconds 400; "
        "while (-not $p.NaturalDuration.HasTimeSpan) { Start-Sleep -Milliseconds 100 }; "
        "Start-Sleep -Milliseconds ([int]$p.NaturalDuration.TimeSpan.TotalMilliseconds); $p.Close() }"
    )
    subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                     env={**os.environ, "NYX_AUDIO": path}, creationflags=_NO_WINDOW,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def tool_speak(text: str, role: str = "reply", voice: str = "", rate: str = "+0%") -> str:
    try:
        result = say(text, role=role or "reply", voice_id=voice, rate=rate)
    except TTSError as error:
        return f"Error: {error}"
    where = "in the Nyx window" if result["played_by"] == "browser" else "through the PC speakers"
    note = f" (neural voice unavailable, used a Windows voice: {result['fallback']})" if result["fallback"] else ""
    return f"Spoke {result['chars']} characters as {result['voice']} {where}.{note}"


def tool_list_voices(locale: str = "en", gender: str = "") -> str:
    voices = neural_voices(locale)
    if gender:
        voices = [v for v in voices if v["gender"].lower() == gender.lower()]
    lines = [f"{len(voices)} neural voices for {locale or 'all locales'}:"]
    lines += [f"- {v['id']} ({v['gender']}, {v['locale']})" for v in voices[:60]]
    if sapi_available():
        lines.append("Windows voices (offline): " + (", ".join(v["id"] for v in sapi_voices()) or "none"))
    roles = role_voices()
    lines.append("Current voices by role: " + ", ".join(f"{k}={v}" for k, v in roles.items()))
    return "\n".join(lines)


def tool_set_voice_for(role: str, voice: str) -> str:
    try:
        known = {v["id"] for v in neural_voices()} | {v["id"] for v in sapi_voices()}
        if voice and known and voice not in known:
            close = [v for v in known if voice.lower() in v.lower()]
            if len(close) == 1:
                voice = close[0]
            else:
                return f"Error: no voice {voice!r}. Similar: {', '.join(sorted(close)[:8]) or 'none — use list_voices'}."
        roles = set_role_voice(role, voice)
    except TTSError as error:
        return f"Error: {error}"
    key = re.sub(r"[^a-z0-9_]+", "_", role.lower()).strip("_")
    return f"{key} now speaks as {roles.get(key)}."


def register_voice_tools(registry: Any) -> None:
    from tools import ToolParam as P

    registry.register("speak", "Say something out loud to the user in a natural neural voice. role picks the speaker's "
                      "voice (reply = Nyx, narrator, or an agent id like coder/educator/news).",
                      [P("text", "string", "What to say"),
                       P("role", "string", "reply, narrator, or an agent id", required=False),
                       P("voice", "string", "Exact voice id to use instead, e.g. en-GB-SoniaNeural", required=False),
                       P("rate", "string", "Speed like +10% or -15%", required=False)],
                      tool_speak, category="general", label=lambda a: f"Speaking: {str(a.get('text', ''))[:40]}")
    registry.register("list_voices", "List the neural voices (by locale/gender) and which voice each role uses.",
                      [P("locale", "string", "Locale prefix like en, en-GB, es, ja", required=False),
                       P("gender", "string", "Female or Male", required=False)],
                      tool_list_voices, category="general", label="Looking through voices")
    registry.register("set_voice_for", "Change the voice for a role (reply, narrator, or an agent id). Empty voice resets it.",
                      [P("role", "string", "reply, narrator, or an agent id"), P("voice", "string", "Voice id, e.g. en-US-AndrewMultilingualNeural")],
                      tool_set_voice_for, category="ui", label=lambda a: f"Giving {a.get('role', '')} a new voice")
