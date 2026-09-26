"""Voices: neural synthesis, per-role voices, caching - no audio plays, no network."""

from __future__ import annotations

import sys
import types

import pytest
from fastapi.testclient import TestClient

import tts
from tools import ToolRegistry


@pytest.fixture()
def voices(tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "_cache_dir", lambda: (tmp_path / "cache").mkdir(exist_ok=True) or tmp_path / "cache")
    monkeypatch.setattr(tts, "_roles_path", lambda: tmp_path / "voice_roles.json")
    monkeypatch.setattr(tts, "_catalog_path", lambda: tmp_path / "edge_voices.json")
    played, calls = [], []
    monkeypatch.setattr(tts, "_play_locally", played.append)

    class Communicate:
        def __init__(self, text, voice, rate="+0%", pitch="+0Hz"):
            calls.append({"text": text, "voice": voice, "rate": rate, "pitch": pitch})
            self.voice = voice

        async def stream(self):
            if self.voice == "xx-BrokenNeural":
                raise ConnectionError("offline")
            yield {"type": "WordBoundary"}
            yield {"type": "audio", "data": b"ID3fake-"}
            yield {"type": "audio", "data": self.voice.encode()}

    async def list_voices():
        return [{"ShortName": "en-US-AvaMultilingualNeural", "FriendlyName": "Microsoft Ava Online (Natural) - English",
                 "Locale": "en-US", "Gender": "Female"},
                {"ShortName": "en-GB-SoniaNeural", "FriendlyName": "Microsoft Sonia Online (Natural) - English",
                 "Locale": "en-GB", "Gender": "Female"},
                {"ShortName": "ja-JP-NanamiNeural", "FriendlyName": "Microsoft Nanami Online", "Locale": "ja-JP",
                 "Gender": "Female"}]

    fake = types.SimpleNamespace(Communicate=Communicate, list_voices=list_voices)
    monkeypatch.setitem(sys.modules, "edge_tts", fake)
    return {"played": played, "calls": calls, "tmp": tmp_path}


def test_markdown_and_code_are_not_read_aloud():
    text = "## Result\nHere is **bold** and [a link](https://x.y).\n```python\nprint(1)\n```\n![pic](/api/uploads/1)"
    assert tts._clean_text(text) == "Result Here is bold and a link. (code omitted)"


def test_neural_voice_synthesis_is_cached(voices):
    first = tts.synthesize("Hello **there**", role="reply")
    assert first["engine"] == "edge" and first["voice"] == "en-US-AvaMultilingualNeural" and first["mime"] == "audio/mpeg"
    assert voices["calls"][0]["text"] == "Hello there"
    again = tts.synthesize("Hello there", role="reply")
    assert again["cached"] and again["key"] == first["key"] and len(voices["calls"]) == 1


def test_every_role_has_its_own_voice_and_can_be_changed(voices):
    assert tts.voice_for("coder") != tts.voice_for("educator") != tts.voice_for("reply")
    assert tts.voice_for("Some Unknown Agent") == tts.voice_for("reply")
    tts.set_role_voice("Coder", "en-GB-SoniaNeural")
    assert tts.voice_for("coder") == "en-GB-SoniaNeural"
    tts.set_role_voice("coder", "")
    assert tts.voice_for("coder") == tts.DEFAULT_ROLE_VOICES["coder"]


def test_rate_and_pitch_are_validated(voices):
    tts.synthesize("Fast", voice_id="en-GB-SoniaNeural", rate="+20%", pitch="-5Hz")
    tts.synthesize("Bad", voice_id="en-GB-SoniaNeural", rate="fast; rm -rf", pitch="loud")
    assert voices["calls"][0]["rate"] == "+20%" and voices["calls"][0]["pitch"] == "-5Hz"
    assert voices["calls"][1]["rate"] == "+0%" and voices["calls"][1]["pitch"] == "+0Hz"


def test_offline_neural_voice_falls_back_to_windows(voices, monkeypatch):
    monkeypatch.setattr(tts, "sapi_available", lambda: True)
    monkeypatch.setattr(tts, "_sapi_bytes", lambda text, voice, rate: b"RIFF" + b"0" * 200)
    result = tts.synthesize("Hi", voice_id="xx-BrokenNeural")
    assert result["engine"] == "sapi" and result["mime"] == "audio/wav" and "needs internet" in result["fallback"]


def test_catalog_filters_by_locale_and_is_cached(voices):
    english = tts.neural_voices("en")
    assert [v["id"] for v in english] == ["en-US-AvaMultilingualNeural", "en-GB-SoniaNeural"]
    assert english[0]["name"] == "Ava"
    assert (voices["tmp"] / "edge_voices.json").is_file()
    assert [v["id"] for v in tts.neural_voices("ja")] == ["ja-JP-NanamiNeural"]


def test_say_goes_to_the_browser_when_a_window_is_open(voices, monkeypatch):
    import agent_events

    published = []
    monkeypatch.setattr(agent_events.BUS, "subscriber_count", lambda channel=None: 1)
    monkeypatch.setattr(agent_events, "publish_ui", lambda type, **p: published.append({"type": type, **p}))
    result = tts.say("Build finished.", role="coder")
    assert result["played_by"] == "browser" and voices["played"] == []
    event = published[0]
    assert event["type"] == "voice.say" and event["voice"] == tts.DEFAULT_ROLE_VOICES["coder"]
    assert event["audio_url"] == f"/api/voice/audio/{result['key']}"


def test_say_uses_the_speakers_when_no_window_is_open(voices, monkeypatch):
    import agent_events

    monkeypatch.setattr(agent_events.BUS, "subscriber_count", lambda channel=None: 0)
    result = tts.say("Anyone there?")
    assert result["played_by"] == "speakers" and voices["played"] == [result["path"]]


def test_tools_register_and_speak_reports_where(voices, monkeypatch):
    import agent_events

    monkeypatch.setattr(agent_events.BUS, "subscriber_count", lambda channel=None: 2)
    registry = ToolRegistry()
    tts.register_voice_tools(registry)
    assert {"speak", "list_voices", "set_voice_for"} <= set(registry.tools)
    assert "in the Nyx window" in tts.tool_speak("Hello", role="news")
    assert tts.tool_set_voice_for("news", "sonia").endswith("en-GB-SoniaNeural.")
    assert tts.tool_set_voice_for("news", "Nobody").startswith("Error")


def test_routes_return_audio_and_roles(voices):
    import server

    client = TestClient(server.app, client=("127.0.0.1", 50031))
    engines = {e["id"]: e for e in client.get("/api/voice/engines").json()["engines"]}
    assert engines["edge"]["available"] and engines["browser"]["available"]
    audio = client.post("/api/voice/tts", json={"text": "Testing", "role": "educator"})
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/mpeg"
    assert audio.headers["x-voice"] == tts.DEFAULT_ROLE_VOICES["educator"]
    assert client.get(f"/api/voice/audio/{audio.headers['x-audio-key']}").content == audio.content
    assert client.get("/api/voice/audio/../../secrets").status_code == 404
    assert client.post("/api/voice/tts", json={"text": "   "}).status_code == 400
    assert client.put("/api/voice/roles/reply", json={"voice": "en-GB-SoniaNeural"}).json()["roles"]["reply"] == "en-GB-SoniaNeural"
    assert client.get("/api/voice/neural-voices?locale=en-GB").json()["count"] == 1
