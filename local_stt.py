"""Listening on this PC: speech to words without the browser's speech service.

Why this exists
---------------
Voice listened through the browser's recognizer (Chrome/Edge ``SpeechRecognition``). That recognizer is an online
service: it stops when the internet does, and Nyx's own app window (WebView2, ``app_window.py``) has no speech
service at all, so in the app window voice heard nothing (Fixer Upper S33, "it doesn't listen"). Here the page only
records — the microphone works in every window — and this module turns each spoken sentence into words on the PC.

Engines, best first
-------------------
* ``whisper`` — faster-whisper (MIT), a Whisper model on the GPU or CPU. Accurate and fast on the owner's RTX card;
  needs ``pip install faster-whisper`` once, and the model downloads on first use (then works offline).
* ``sapi`` — Windows' own dictation (System.Speech), already on every Windows PC, offline, no install. Less accurate.

The page sends one WAV per sentence (16 kHz, mono, 16-bit), cut at the pause the microphone meter heard, so the
answer path is the same as with the browser recognizer: words in, the chat answers. Nothing is kept: the audio is
transcribed from memory (Whisper) or a temp file that is deleted at once (SAPI).
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import threading
import time
import wave
from typing import Any, Dict, List, Optional

#: The largest sentence accepted: 30 s of 16 kHz 16-bit mono is ~960 KB.
MAX_BYTES = 1_200_000
#: Whisper model when none is set: small.en is accurate for English and quick on a GPU.
DEFAULT_MODEL = os.getenv("NYX_WHISPER_MODEL", "small.en")

_lock = threading.Lock()
_whisper: Any = None
_whisper_name = ""


class STTError(RuntimeError):
    """Listening on the PC could not turn this audio into words; the message says why, for the owner."""


def whisper_available() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("faster_whisper") is not None
    except Exception:  # noqa: BLE001
        return False


def sapi_available() -> bool:
    return sys.platform == "win32"


def engines() -> List[Dict[str, Any]]:
    return [
        {"id": "whisper", "available": whisper_available(),
         "note": "Whisper on this PC (faster-whisper). Accurate, offline after the first download."},
        {"id": "sapi", "available": sapi_available(), "note": "Windows dictation. Offline, nothing to install."},
    ]


def best_engine() -> str:
    for engine in engines():
        if engine["available"]:
            return engine["id"]
    return ""


def read_wav(data: bytes) -> Dict[str, Any]:
    """Check the audio is the WAV the page sends and say how long it is."""
    if not data:
        raise STTError("No audio came through.")
    if len(data) > MAX_BYTES:
        raise STTError("That was too long for one sentence — pause a little sooner.")
    try:
        with wave.open(io.BytesIO(data)) as clip:
            rate, channels, width, frames = clip.getframerate(), clip.getnchannels(), clip.getsampwidth(), clip.getnframes()
    except (wave.Error, EOFError) as error:
        raise STTError("The audio was not a WAV recording.") from error
    if channels != 1 or width != 2:
        raise STTError("The audio must be mono 16-bit.")
    return {"rate": rate, "seconds": frames / float(rate or 1)}


def _whisper_model(name: str) -> Any:
    global _whisper, _whisper_name
    with _lock:
        if _whisper is None or _whisper_name != name:
            from faster_whisper import WhisperModel

            # "auto" picks the GPU when CUDA is there and int8 on the CPU otherwise.
            _whisper = WhisperModel(name, device="auto", compute_type="default")
            _whisper_name = name
        return _whisper


def _whisper_text(data: bytes, model: str) -> str:
    import numpy as np

    with wave.open(io.BytesIO(data)) as clip:
        rate = clip.getframerate()
        samples = np.frombuffer(clip.readframes(clip.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    if rate != 16000:
        # Whisper wants 16 kHz; a plain resample is enough for speech.
        target = int(len(samples) * 16000 / rate)
        samples = np.interp(np.linspace(0, len(samples), target, endpoint=False), np.arange(len(samples)), samples)
    segments, _info = _whisper_model(model).transcribe(samples.astype(np.float32), language="en", beam_size=1,
                                                       vad_filter=False, condition_on_previous_text=False)
    return " ".join(segment.text.strip() for segment in segments).strip()


_SAPI_SCRIPT = (
    "param([string]$Path)\n"
    "Add-Type -AssemblyName System.Speech\n"
    "$rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine('en-US')\n"
    "$rec.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))\n"
    "$rec.SetInputToWaveFile($Path)\n"
    "$words = @()\n"
    "try { while ($true) { $r = $rec.Recognize(); if (-not $r) { break }; $words += $r.Text } }\n"
    "finally { $rec.Dispose() }\n"
    "[Console]::Out.Write(($words -join ' '))\n"
)


def _sapi_text(data: bytes) -> str:
    handle, path = tempfile.mkstemp(suffix=".wav", prefix="nyx-ear-")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
             f"& {{ {_SAPI_SCRIPT} }} -Path '{path}'"],
            capture_output=True, text=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (result.stdout or "").strip()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def transcribe(data: bytes, engine: str = "", model: str = "") -> Dict[str, Any]:
    """Words for one spoken sentence. Returns ``{text, engine, ms, seconds}``."""
    info = read_wav(data)
    engine = engine or best_engine()
    if not engine:
        raise STTError("Nothing on this PC can listen yet. Install faster-whisper, or use Windows for its dictation.")
    started = time.perf_counter()
    try:
        if engine == "whisper":
            if not whisper_available():
                raise STTError("Whisper isn't installed on this PC (pip install faster-whisper).")
            text = _whisper_text(data, model or DEFAULT_MODEL)
        elif engine == "sapi":
            if not sapi_available():
                raise STTError("Windows dictation only works on Windows.")
            text = _sapi_text(data)
        else:
            raise STTError(f"Unknown listening engine {engine!r}. Use whisper or sapi.")
    except STTError:
        raise
    except Exception as error:  # noqa: BLE001 - the owner gets a reason, not a stack trace
        raise STTError(f"Listening on this PC failed ({type(error).__name__}: {str(error)[:120]}).") from error
    return {"text": text, "engine": engine, "ms": round((time.perf_counter() - started) * 1000, 1),
            "seconds": round(info["seconds"], 2)}
