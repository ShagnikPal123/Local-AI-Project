"""equalize: the name at most once per session, and sentences out of a streaming answer."""

import equalize_voice


def test_the_name_is_said_once_to_introduce_and_never_again():
    equalize_voice.forget("s1")
    first = equalize_voice.clean("Hello! I'm Ichos. Ichos is here to help, and Nyx Ichos can search too.", "s1")
    assert first.lower().count("ichos") + first.lower().count("nyx") == 1
    assert "I'm Ichos" in first
    second = equalize_voice.clean("Ichos here. I'm Ichos and I found it.", "s1")
    assert "ichos" not in second.lower() and "nyx" not in second.lower()
    assert "I found it" in second


def test_a_name_that_is_not_an_introduction_is_dropped_too():
    equalize_voice.forget("s2")
    out = equalize_voice.clean("Sure thing, Ichos, let me check that.", "s2")
    assert "ichos" not in out.lower() and out.startswith("Sure thing")


def test_text_without_the_name_is_untouched_and_sessions_are_separate():
    equalize_voice.forget("a"); equalize_voice.forget("b")
    assert equalize_voice.clean("It is sunny today.", "a") == "It is sunny today."
    equalize_voice.clean("I'm Ichos.", "a")
    assert "Ichos" in equalize_voice.clean("I'm Ichos, hello.", "b"), "another session still gets its introduction"


def test_sentences_come_out_as_soon_as_they_are_whole():
    stream = equalize_voice.SentenceStream(min_chars=10)
    got = stream.feed("The weather in Austin is")
    assert got == []
    got += stream.feed(" sunny today. It will reach thirty")
    assert got == ["The weather in Austin is sunny today."]
    got = stream.feed(" degrees! Bring water.")
    assert got == ["It will reach thirty degrees!"]
    assert stream.finish() == ["Bring water."]


def test_the_speech_route_applies_the_guard_to_replies_only(monkeypatch):
    from fastapi.testclient import TestClient

    import server
    import tts

    spoken = []
    monkeypatch.setattr(tts, "synthesize", lambda text, **k: spoken.append((text, k.get("role"))) or (_ for _ in ()).throw(tts.TTSError("stop")))
    equalize_voice.forget("voice")
    client = TestClient(server.app, client=("127.0.0.1", 50131))
    client.post("/api/voice/tts", json={"text": "Ichos here. It is sunny.", "role": "reply", "session": "voice"})
    client.post("/api/voice/tts", json={"text": "Ichos here. It is sunny.", "role": "", "session": "voice"})
    assert spoken[0][0] == "here. It is sunny." or "ichos" not in spoken[0][0].lower()
    assert spoken[1][0] == "Ichos here. It is sunny.", "a voice sample is read as written"
