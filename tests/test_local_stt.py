"""Listening on the PC (Fixer Upper S33: "it doesn't listen" — the app window has no browser speech service)."""

from __future__ import annotations

import io
import wave

import pytest
from fastapi.testclient import TestClient

import local_stt


def _wav(seconds: float = 0.5, rate: int = 16000, channels: int = 1, width: int = 2) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as clip:
        clip.setnchannels(channels)
        clip.setsampwidth(width)
        clip.setframerate(rate)
        clip.writeframes(b"\x00" * int(seconds * rate) * channels * width)
    return out.getvalue()


def test_a_page_recording_is_accepted_and_timed():
    assert local_stt.read_wav(_wav(1.5))["seconds"] == pytest.approx(1.5)


@pytest.mark.parametrize("data,why", [
    (b"", "No audio"),
    (b"not a wav at all", "not a WAV"),
    (_wav(channels=2), "mono"),
    (b"RIFF" + b"\x00" * (local_stt.MAX_BYTES + 1), "too long"),
])
def test_bad_audio_gets_a_plain_reason(data, why):
    with pytest.raises(local_stt.STTError, match=why):
        local_stt.read_wav(data)


def test_whisper_is_preferred_and_windows_dictation_is_the_fallback(monkeypatch):
    monkeypatch.setattr(local_stt, "whisper_available", lambda: True)
    monkeypatch.setattr(local_stt, "sapi_available", lambda: True)
    assert local_stt.best_engine() == "whisper"
    monkeypatch.setattr(local_stt, "whisper_available", lambda: False)
    assert local_stt.best_engine() == "sapi"
    monkeypatch.setattr(local_stt, "sapi_available", lambda: False)
    assert local_stt.best_engine() == ""
    with pytest.raises(local_stt.STTError, match="Nothing on this PC can listen"):
        local_stt.transcribe(_wav())


def test_transcribe_uses_the_chosen_engine_and_reports_its_time(monkeypatch):
    monkeypatch.setattr(local_stt, "whisper_available", lambda: True)
    monkeypatch.setattr(local_stt, "sapi_available", lambda: True)
    monkeypatch.setattr(local_stt, "_whisper_text", lambda data, model: "open chrome")
    monkeypatch.setattr(local_stt, "_sapi_text", lambda data: "open notepad")
    heard = local_stt.transcribe(_wav())
    assert heard["text"] == "open chrome" and heard["engine"] == "whisper" and heard["ms"] >= 0
    assert local_stt.transcribe(_wav(), engine="sapi")["text"] == "open notepad"


def test_an_engine_crash_becomes_a_reason_not_a_stack_trace(monkeypatch):
    monkeypatch.setattr(local_stt, "whisper_available", lambda: True)

    def broken(data, model):
        raise OSError("CUDA driver missing")

    monkeypatch.setattr(local_stt, "_whisper_text", broken)
    with pytest.raises(local_stt.STTError, match="CUDA driver missing"):
        local_stt.transcribe(_wav(), engine="whisper")


def test_windows_dictation_deletes_its_temp_file(monkeypatch, tmp_path):
    import subprocess
    import tempfile

    seen = {}
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    def fake_run(args, **kwargs):
        seen["args"] = args
        return subprocess.CompletedProcess(args, 0, stdout=" hello there \n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert local_stt._sapi_text(_wav()) == "hello there"
    assert "SetInputToWaveFile" in seen["args"][-1]
    assert not list(tmp_path.glob("nyx-ear-*")), "the recording is not kept"


def test_the_transcribe_route_returns_words(monkeypatch):
    import server
    from server_auth import require_session

    monkeypatch.setattr(local_stt, "transcribe", lambda data, engine="": {"text": "hi", "engine": "sapi", "ms": 1.0,
                                                                          "seconds": 0.5})
    server.app.dependency_overrides[require_session] = lambda: {"email": "owner@example.com", "role": "owner"}
    try:
        client = TestClient(server.app, client=("127.0.0.1", 50031))
        assert client.post("/api/voice/transcribe", content=_wav(),
                           headers={"Content-Type": "audio/wav"}).json()["text"] == "hi"
        assert "best" in client.get("/api/voice/ears").json()
        monkeypatch.setattr(local_stt, "transcribe", lambda data, engine="": (_ for _ in ()).throw(
            local_stt.STTError("No audio came through.")))
        bad = client.post("/api/voice/transcribe", content=b"")
        assert bad.status_code == 400 and bad.json()["detail"] == "No audio came through."
    finally:
        server.app.dependency_overrides.pop(require_session, None)
