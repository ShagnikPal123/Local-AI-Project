"""Voice engine for Nyx Ichos: talk back, listen, voice selection, and voice ID.

Capabilities (all local-first, no cloud keys required):
- **Talk back (TTS)**: Windows SAPI voices via PowerShell (Microsoft David/Zira
  by default; any installed Windows voice can be selected or added).
- **Listening (STT)**: offline dictation via the Windows SAPI recognizer.
- **Voice ID / voice scan**: captures a short sample with ffmpeg, computes a
  lightweight spectral voiceprint (pitch, spectral centroid, band energy,
  zero-crossing, rolloff) with numpy/scipy, and compares new samples to the
  enrolled one. This is a soft voiceprint for convenience — it is *not*
  biometric-grade speaker verification.

Everything degrades gracefully: if a component (ffmpeg, SAPI, numpy) is
missing, the affected function returns a clear error instead of crashing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Dict, List, Optional
from paths import data_path

VOICE_PROFILE = data_path("voice_profile.json")
_TMP_DIR = Path("voice_tmp")
_ENGLISH_CULTURE = "en-US"


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _ensure_tmp() -> Path:
    _TMP_DIR.mkdir(parents=True, exist_ok=True)
    return _TMP_DIR


#: Never let a PowerShell helper flash a console window over what the owner is typing.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _powershell(script: str, args: List[str], timeout: float = 60.0) -> subprocess.CompletedProcess:
    script_path = _ensure_tmp() / "voice_script.ps1"
    script_path.write_text(script, encoding="utf-8")
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=_NO_WINDOW,
    )


def _load_profile() -> Dict[str, Any]:
    if not VOICE_PROFILE.exists():
        return {"voice": "", "voiceprints": [], "enrolled": False}
    try:
        data = json.loads(VOICE_PROFILE.read_text(encoding="utf-8"))
        data.setdefault("voice", "")
        data.setdefault("voiceprints", [])
        data.setdefault("enrolled", False)
        return data
    except (json.JSONDecodeError, OSError):
        return {"voice": "", "voiceprints": [], "enrolled": False}


def _save_profile(profile: Dict[str, Any]) -> None:
    VOICE_PROFILE.write_text(json.dumps(profile, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Voice selection (installed Windows voices)
# ---------------------------------------------------------------------------


def list_voices() -> List[Dict[str, str]]:
    """Enumerate installed Windows SAPI voices."""
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.GetInstalledVoices() | ForEach-Object { $v = $_.VoiceInfo; "
        'Write-Output ("{0}|{1}|{2}" -f $v.Name, $v.Culture.Name, $v.Gender) }'
    )
    try:
        result = _powershell(script, [], timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return []
    voices = []
    for line in (result.stdout or "").splitlines():
        parts = line.split("|")
        if len(parts) >= 3:
            voices.append(
                {"name": parts[0], "culture": parts[1], "gender": parts[2].lower()}
            )
    return voices


def set_voice(name: str) -> str:
    """Persist the selected speaking voice."""
    name = (name or "").strip()
    if not name:
        return "Voice name cannot be empty. Use /voice voices to list them."
    installed = {v["name"] for v in list_voices()}
    # Allow partial matches (e.g. "zira" -> "Microsoft Zira Desktop").
    match = next((v for v in installed if v.lower() == name.lower() or name.lower() in v.lower()), None)
    if match is None:
        return f"Voice '{name}' not found. Installed: {', '.join(sorted(installed)) or 'none'}."
    profile = _load_profile()
    profile["voice"] = match
    _save_profile(profile)
    return f"Voice set to: {match}"


def get_voice() -> str:
    """Return the currently selected voice (or the first installed one)."""
    profile = _load_profile()
    if profile.get("voice"):
        return profile["voice"]
    voices = list_voices()
    return voices[0]["name"] if voices else ""


# ---------------------------------------------------------------------------
# Talk back (TTS)
# ---------------------------------------------------------------------------


def speak(text: str, voice: Optional[str] = None, wait: bool = False) -> str:
    """Speak text aloud through the selected SAPI voice (async by default)."""
    text = (text or "").strip()
    if not text:
        return "Nothing to say."
    _ensure_tmp()
    text_file = _TMP_DIR / "speak_text.txt"
    text_file.write_text(text, encoding="utf-8")

    script = (
        "param([string]$TextFile, [string]$VoiceName)\n"
        "Add-Type -AssemblyName System.Speech\n"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
        "if ($VoiceName) { $s.SelectVoice($VoiceName) }\n"
        "$text = Get-Content -Raw -LiteralPath $TextFile\n"
        "$s.Speak($text)\n"
    )
    script_path = _ensure_tmp() / "speak.ps1"
    script_path.write_text(script, encoding="utf-8")
    selected = voice or get_voice()
    args = [str(text_file), selected]
    try:
        if wait:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path), *args],
                capture_output=True,
                text=True,
                timeout=120,
                creationflags=_NO_WINDOW,
            )
            if result.returncode != 0:
                return f"Speech failed: {result.stderr.strip() or 'unknown error'}"
        else:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path), *args],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_NO_WINDOW,
            )
        return f"Speaking with voice: {selected}"
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"Speech failed: {error}"


def stop_speaking() -> str:
    """Stop any in-progress speech (kills powershell speak processes)."""
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process powershell -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match 'speak.ps1' } | Stop-Process -Force"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=_NO_WINDOW,
        )
        return "Stopped speaking."
    except (OSError, subprocess.TimeoutExpired):
        return "Could not stop speech."


# ---------------------------------------------------------------------------
# Listening (STT) — offline Windows dictation
# ---------------------------------------------------------------------------


def listen(timeout: int = 10) -> str:
    """Listen to the microphone and return recognized text (offline dictation)."""
    script = (
        "param([int]$TimeoutSeconds)\n"
        "Add-Type -AssemblyName System.Speech\n"
        "$rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine('en-US')\n"
        "$rec.SetInputToDefaultAudioDevice()\n"
        "$rec.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))\n"
        "try {\n"
        "  $result = $rec.Recognize([TimeSpan]::FromSeconds($TimeoutSeconds))\n"
        "  if ($result) { [Console]::Out.Write($result.Text) }\n"
        "} finally { $rec.Dispose() }\n"
    )
    try:
        result = _powershell(script, [str(int(timeout))], timeout=timeout + 30)
    except (subprocess.TimeoutExpired, OSError) as error:
        return f"[listen error: {error}]"
    text = (result.stdout or "").strip()
    if not text:
        return "[no speech detected]"
    return text


# ---------------------------------------------------------------------------
# Voice capture (ffmpeg dshow)
# ---------------------------------------------------------------------------


def _find_mic() -> Optional[str]:
    """Find the first audio input device name via ffmpeg dshow."""
    override = os.getenv("VOICE_MIC", "").strip()
    if override:
        return override
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=_NO_WINDOW,
        )
        for line in (result.stderr or "").splitlines():
            match = re.search(r'"([^"]+)"\s+\(audio\)', line)
            if match:
                return match.group(1)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def capture_sample(duration: float = 3.0, out_path: Optional[str] = None) -> Optional[str]:
    """Record a short mono 16 kHz WAV sample from the default microphone."""
    mic = _find_mic()
    if not mic:
        return None
    target = out_path or str(_ensure_tmp() / f"sample_{int(time.time())}.wav")
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "dshow", "-i", f"audio={mic}",
                "-ar", "16000", "-ac", "1", "-t", str(duration), "-loglevel", "error", target,
            ],
            capture_output=True,
            timeout=int(duration) + 20,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if os.path.exists(target) and os.path.getsize(target) > 0:
        return target
    return None


# ---------------------------------------------------------------------------
# Voice ID / voice scan (lightweight spectral voiceprint)
# ---------------------------------------------------------------------------

_FEATURE_MAX = {
    "f0_mean": 400.0,
    "f0_std": 120.0,
    "centroid_mean": 4000.0,
    "centroid_std": 1500.0,
    "rolloff": 6000.0,
    "zcr": 0.5,
    "rms": 0.5,
    "band_high": 0.8,
    "band_low": 0.8,
    "flatness": 1.0,
}
_MATCH_THRESHOLD = 0.82


def extract_voiceprint(wav_path: str) -> Optional[Dict[str, Any]]:
    """Compute a spectral voiceprint from a WAV file (numpy/scipy)."""
    try:
        import numpy as np
        import wave
    except ImportError:
        return None

    try:
        with wave.open(wav_path, "rb") as handle:
            if handle.getnchannels() != 1:
                return None
            rate = handle.getframerate()
            frames = handle.readframes(handle.getnframes())
        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float64) / 32768.0
    except (wave.Error, OSError, ValueError):
        return None
    if samples.size < rate // 4:  # need at least ~0.25s
        return None

    rms = float(np.sqrt(np.mean(samples**2)))
    zcr = float(np.mean(np.abs(np.diff(np.sign(samples))) / 2.0))

    # Pitch via autocorrelation over 30ms frames (median F0).
    frame_len = int(rate * 0.03)
    min_lag = max(2, int(rate / 500))  # ~500 Hz upper pitch bound
    max_lag = max(min_lag + 1, int(rate / 60))  # ~60 Hz lower pitch bound
    f0_values = []
    for start in range(0, samples.size - frame_len, frame_len):
        frame = samples[start : start + frame_len]
        frame = frame - frame.mean()
        corr = np.correlate(frame, frame, mode="full")[frame_len - 1 :]
        reference = corr[0]
        corr[:min_lag] = 0
        corr[max_lag:] = 0
        peak = int(np.argmax(corr))
        if peak > 0 and corr[peak] > 0.3 * reference:
            f0_values.append(rate / peak)
    f0_mean = float(np.median(f0_values)) if f0_values else 0.0
    f0_std = float(np.std(f0_values)) if f0_values else 0.0

    # Spectral features from the FFT magnitude spectrum.
    spectrum = np.abs(np.fft.rfft(samples))
    freqs = np.fft.rfftfreq(samples.size, d=1.0 / rate)
    total_energy = float(np.sum(spectrum**2)) or 1.0
    centroid_mean = float(np.sum(freqs * spectrum**2) / total_energy)
    centroid_std = float(np.sqrt(np.sum(((freqs - centroid_mean) ** 2) * (spectrum**2)) / total_energy))
    cumulative = np.cumsum(spectrum**2) / total_energy
    rolloff = float(freqs[np.searchsorted(cumulative, 0.85)]) if cumulative.size else 0.0

    band_high = float(np.sum(spectrum[(freqs >= 1000) & (freqs <= 8000)] ** 2) / total_energy)
    band_low = float(np.sum(spectrum[(freqs >= 0) & (freqs < 1000)] ** 2) / total_energy)
    geometric = float(np.exp(np.mean(np.log(spectrum + 1e-12))))
    flatness = float(geometric / (np.mean(spectrum + 1e-12) + 1e-12))

    features = {
        "f0_mean": f0_mean,
        "f0_std": f0_std,
        "centroid_mean": centroid_mean,
        "centroid_std": centroid_std,
        "rolloff": rolloff,
        "zcr": zcr,
        "rms": rms,
        "band_high": band_high,
        "band_low": band_low,
        "flatness": flatness,
    }
    return {"features": features, "duration": round(samples.size / rate, 2)}


def _feature_vector(features: Dict[str, float]) -> List[float]:
    """Normalize features to [0, 1] using fixed physical bounds."""
    vector = []
    for key, max_value in _FEATURE_MAX.items():
        vector.append(min(1.0, features.get(key, 0.0) / max_value))
    return vector


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    import math

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
    norm_b = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (norm_a * norm_b)


def enroll_voice(label: str = "user", duration: float = 3.0) -> Dict[str, Any]:
    """Capture a voice sample and enroll it as the user's voiceprint."""
    label = (label or "user").strip()
    sample = capture_sample(duration=duration)
    if not sample:
        return {"success": False, "error": "Could not capture audio. Check the microphone."}
    voiceprint = extract_voiceprint(sample)
    if not voiceprint:
        return {"success": False, "error": "Could not analyze the audio sample (too quiet or unsupported)."}

    profile = _load_profile()
    profile["voiceprints"] = [
        vp for vp in profile.get("voiceprints", []) if vp.get("label") != label
    ]
    profile["voiceprints"].append(
        {
            "label": label,
            "features": voiceprint["features"],
            "duration": voiceprint["duration"],
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
    )
    profile["enrolled"] = True
    _save_profile(profile)
    return {
        "success": True,
        "enrolled": True,
        "label": label,
        "message": f"Voice scan complete for '{label}'. Voice enrolled.",
    }


def verify_voice(duration: float = 3.0, threshold: float = _MATCH_THRESHOLD) -> Dict[str, Any]:
    """Capture a new sample and compare it against the enrolled voiceprint."""
    profile = _load_profile()
    enrolled = profile.get("voiceprints", [])
    if not enrolled:
        return {"success": False, "enrolled": False, "error": "No voice enrolled yet. Run a voice scan first."}

    sample = capture_sample(duration=duration)
    if not sample:
        return {"success": False, "error": "Could not capture audio. Check the microphone."}
    voiceprint = extract_voiceprint(sample)
    if not voiceprint:
        return {"success": False, "error": "Could not analyze the audio sample."}

    vector = _feature_vector(voiceprint["features"])
    best = None
    for vp in enrolled:
        score = _cosine_similarity(vector, _feature_vector(vp.get("features", {})))
        if best is None or score > best[1]:
            best = (vp.get("label", "user"), score)

    label, score = best
    match = score >= threshold
    return {
        "success": True,
        "match": match,
        "confidence": round(score, 3),
        "best_match": label,
        "message": (
            f"Voice verified as '{label}' (confidence {score:.2f})."
            if match
            else f"Voice did not match '{label}' (confidence {score:.2f})."
        ),
    }


def voice_status() -> Dict[str, Any]:
    """Return enrollment status, selected voice, and available voices."""
    profile = _load_profile()
    voices = list_voices()
    return {
        "enrolled": profile.get("enrolled", False),
        "voiceprints": [vp.get("label") for vp in profile.get("voiceprints", [])],
        "voice": get_voice(),
        "voices": voices,
        "mic": _find_mic(),
        "capabilities": {
            "tts": bool(voices),
            "stt": True,
            "voice_id": True,
        },
    }
