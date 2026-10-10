"""Morning Digest: sections that fail on their own, a schedule that fires once a day, and owner-only routes."""

from __future__ import annotations

from datetime import datetime

import pytest

import morning_digest as md


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(md, "data_path", lambda name: tmp_path / name)
    yield


def test_a_source_that_fails_is_named_and_the_rest_still_arrive(monkeypatch):
    def broken(_conf):
        raise md.DigestError("Google Calendar is not connected")

    monkeypatch.setattr(md, "SECTIONS", {"calendar": broken, "weather": lambda c: ["Austin: 24°C now."],
                                         "news": lambda c: []})
    monkeypatch.setattr(md, "_speak_words", lambda facts: "Good morning. " + " ".join(sum(facts.values(), [])))
    digest = md.build()
    assert digest["facts"] == {"weather": ["Austin: 24°C now."]}
    assert "not connected" in digest["skipped"]["calendar"]
    assert "24°C" in digest["text"] and md.settings()["last"]["text"] == digest["text"]


def test_switched_off_sources_are_not_asked(monkeypatch):
    asked = []
    monkeypatch.setattr(md, "SECTIONS", {"news": lambda c: asked.append("news") or ["x"], "email": lambda c: ["y"]})
    monkeypatch.setattr(md, "_speak_words", lambda facts: "ok")
    md.save({"sources": {"news": False}})
    md.build()
    assert asked == []


def test_settings_are_checked():
    saved = md.save({"time": "06:45", "city": "Austin", "topics": ["AI", " ", "F1"], "symbols": ["spy", "qqq$"]})
    assert saved["time"] == "06:45" and saved["topics"] == ["AI", "F1"] and saved["symbols"] == ["SPY", "QQQ"]
    with pytest.raises(md.DigestError):
        md.save({"time": "7am"})


def test_the_schedule_fires_once_a_day_after_its_time():
    conf = {**md.DEFAULTS, "enabled": True, "time": "07:30"}
    assert not md.due(conf, datetime(2026, 10, 10, 7, 0))
    assert md.due(conf, datetime(2026, 10, 10, 7, 31))
    assert not md.due({**conf, "last_day": "2026-10-10"}, datetime(2026, 10, 10, 9, 0))
    assert not md.due({**conf, "enabled": False}, datetime(2026, 10, 10, 9, 0))


def test_digest_routes_are_the_owner_s():
    from fastapi.testclient import TestClient

    import server

    remote = TestClient(server.app, client=("203.0.113.9", 50091))
    assert remote.get("/api/jarvis/digest").status_code in (401, 403)
    assert remote.put("/api/jarvis/digest", json={"city": "x"}).status_code in (401, 403)
    assert remote.post("/api/jarvis/digest/run").status_code in (401, 403)


def test_reading_the_offices_for_the_digest_writes_nothing(tmp_path, monkeypatch):
    from office import engine as office_engine
    from office import library
    from office.state import Output

    library.use_root(tmp_path / "offices")
    try:
        office, _ = library.create_office("Night shift")
        loaded = library.load(office.id)
        loaded.add_output(Output(id="o1", title="Report on prices", text="…"))
        library.save(loaded)
        saves = []
        monkeypatch.setattr(library, "save", lambda *a, **k: saves.append(a))
        office_engine.ENGINE.reset_for_tests()
        lines = md._nyx({})
        assert any("Report on prices" in line for line in lines)
        assert saves == [] and office_engine.ENGINE.opened(office.id) is None
    finally:
        library.use_root(None)
