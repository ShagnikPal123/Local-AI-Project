"""Offline tests for the voice engine: voiceprints, voice selection, tools, endpoints."""

import math
from unittest.mock import patch
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

import voice
from connectors import CONNECTOR_REGISTRY
from server import app
from tools import TOOL_REGISTRY

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers: synthesize a WAV sample (no microphone needed)
# ---------------------------------------------------------------------------


def _make_wav(path, frequency=200.0, seconds=2.0, rate=16000, amplitude=0.4):
    """Write a mono 16-bit WAV containing a sine tone."""
    t = np.arange(int(rate * seconds)) / rate
    samples = (amplitude * np.sin(2 * math.pi * frequency * t) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())
    return str(path)


# ---------------------------------------------------------------------------
# Voiceprint extraction (pure DSP, offline)
# ---------------------------------------------------------------------------


def test_extract_voiceprint_on_sine(tmp_path):
    wav = _make_wav(tmp_path / "tone.wav", frequency=200.0)
    vp = voice.extract_voiceprint(wav)
    assert vp is not None
    assert vp["duration"] == pytest.approx(2.0, abs=0.05)
    # The autocorrelation pitch detector should find ~200 Hz.
    assert abs(vp["features"]["f0_mean"] - 200.0) < 10.0
    assert 0.0 < vp["features"]["rms"] < 1.0


def test_extract_voiceprint_different_frequencies_differ(tmp_path):
    low = voice.extract_voiceprint(_make_wav(tmp_path / "low.wav", frequency=120.0))
    high = voice.extract_voiceprint(_make_wav(tmp_path / "high.wav", frequency=300.0))
    assert abs(low["features"]["f0_mean"] - high["features"]["f0_mean"]) > 50.0


def test_extract_voiceprint_invalid_file(tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not a wav file")
    assert voice.extract_voiceprint(str(bad)) is None


def test_feature_vector_normalized_to_unit_range():
    features = {
        "f0_mean": 200.0, "f0_std": 30.0, "centroid_mean": 2000.0, "centroid_std": 500.0,
        "rolloff": 3000.0, "zcr": 0.1, "rms": 0.2, "band_high": 0.4, "band_low": 0.6, "flatness": 0.3,
    }
    vector = voice._feature_vector(features)
    assert len(vector) == len(voice._FEATURE_MAX)
    assert all(0.0 <= value <= 1.0 for value in vector)


def test_cosine_similarity_identical_is_one():
    vector = [0.5, 0.25, 0.75, 0.1, 0.9]
    assert voice._cosine_similarity(vector, vector) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Enroll + verify flow (capture mocked, DSP real)
# ---------------------------------------------------------------------------


def test_enroll_and_verify_flow(tmp_path, monkeypatch):
    wav = _make_wav(tmp_path / "voice.wav", frequency=180.0)
    profile_path = tmp_path / "voice_profile.json"
    monkeypatch.setattr(voice, "VOICE_PROFILE", profile_path)
    monkeypatch.setattr(voice, "capture_sample", lambda duration=3.0, out_path=None: wav)

    enrolled = voice.enroll_voice(label="user")
    assert enrolled["success"] is True
    assert enrolled["enrolled"] is True

    status = voice.voice_status()
    assert status["enrolled"] is True
    assert "user" in status["voiceprints"]

    verified = voice.verify_voice()
    assert verified["success"] is True
    assert verified["match"] is True
    assert verified["best_match"] == "user"
    assert verified["confidence"] > 0.8


def test_verify_without_enrollment(tmp_path, monkeypatch):
    profile_path = tmp_path / "empty_profile.json"
    monkeypatch.setattr(voice, "VOICE_PROFILE", profile_path)
    result = voice.verify_voice()
    assert result["success"] is False
    assert "No voice enrolled" in result["error"]


# ---------------------------------------------------------------------------
# Voice selection & profile persistence
# ---------------------------------------------------------------------------


def test_set_voice_persists_and_matches_partial(tmp_path, monkeypatch):
    profile_path = tmp_path / "voice_profile.json"
    monkeypatch.setattr(voice, "VOICE_PROFILE", profile_path)
    monkeypatch.setattr(
        voice,
        "list_voices",
        lambda: [
            {"name": "Microsoft David Desktop", "culture": "en-US", "gender": "male"},
            {"name": "Microsoft Zira Desktop", "culture": "en-US", "gender": "female"},
        ],
    )
    message = voice.set_voice("zira")
    assert "Zira" in message
    assert voice.get_voice() == "Microsoft Zira Desktop"
    # Persisted across a fresh profile load.
    monkeypatch.undo()
    monkeypatch.setattr(voice, "VOICE_PROFILE", profile_path)
    assert voice._load_profile()["voice"] == "Microsoft Zira Desktop"


def test_set_voice_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "VOICE_PROFILE", tmp_path / "p.json")
    monkeypatch.setattr(voice, "list_voices", lambda: [{"name": "Microsoft David Desktop", "culture": "en-US", "gender": "male"}])
    assert "not found" in voice.set_voice("nope")


# ---------------------------------------------------------------------------
# Connector, tools, server
# ---------------------------------------------------------------------------


def test_voice_connector_registered_and_actions():
    manifest = CONNECTOR_REGISTRY.get("voice").manifest
    assert manifest.name == "voice"
    assert "audio" in manifest.permissions


def test_voice_connector_speak_action():
    with patch("voice.speak", return_value="Speaking with voice: X") as mock_speak:
        result = CONNECTOR_REGISTRY.execute("voice", "speak", text="Hello")
    assert result["success"] is True
    mock_speak.assert_called_once_with("Hello", voice=None)


def test_voice_tools_registered():
    names = {tool.name for tool in TOOL_REGISTRY.list_tools()}
    assert {"speak", "listen", "list_voices", "set_voice", "voice_scan"} <= names


def test_server_voice_status_endpoint():
    with patch("voice.voice_status", return_value={"enrolled": True, "voiceprints": ["user"], "voice": "X", "voices": [], "mic": "Mic"}):
        response = client.get("/api/voice/status")
    assert response.status_code == 200
    assert response.json()["enrolled"] is True


def test_server_voice_speak_endpoint():
    with patch("voice.speak", return_value="Speaking with voice: X") as mock_speak:
        response = client.post("/api/voice/speak", json={"text": "hello there"})
    assert response.status_code == 200
    assert "Speaking" in response.json()["message"]
    mock_speak.assert_called_once_with("hello there", voice=None)


def test_server_voice_scan_enroll_endpoint():
    with patch("voice.enroll_voice", return_value={"success": True, "enrolled": True}) as mock_enroll:
        response = client.post("/api/voice/scan", json={"mode": "enroll", "label": "user"})
    assert response.status_code == 200
    assert response.json()["enrolled"] is True
    mock_enroll.assert_called_once_with(label="user", duration=3.0)


def test_server_voice_listen_endpoint():
    with patch("voice.listen", return_value="what is the weather") as mock_listen:
        response = client.post("/api/voice/listen", json={"timeout": 5})
    assert response.status_code == 200
    assert response.json()["text"] == "what is the weather"
    mock_listen.assert_called_once_with(timeout=5)
