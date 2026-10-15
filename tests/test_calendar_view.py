"""Week calendar: Orbit rules expand to dated runs, Google is optional, and the look is a checked spec the AI can change."""

from __future__ import annotations

from datetime import date, datetime

import pytest

import calendar_view as cv


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(cv, "_path", lambda: tmp_path / "calendar_look.json")
    yield


def task(**changes):
    base = {"id": "sc-1", "title": "Morning mail", "repeat": "daily", "time": "08:30", "days": [0], "every_minutes": 60,
            "at": 0.0, "avatar": "orbit", "enabled": True}
    return {**base, **changes}


MONDAY = date(2026, 10, 12)


def test_week_starts_on_monday_or_sunday():
    assert cv.week_start(date(2026, 10, 14)) == MONDAY
    assert cv.week_start(date(2026, 10, 14), "sun") == date(2026, 10, 11)
    assert cv.week_start(date(2026, 10, 18), "sun") == date(2026, 10, 18)


def test_daily_weekdays_and_weekly_rules_land_on_the_right_days():
    rows = cv.occurrences([task(), task(id="b", repeat="weekdays", time="09:00"), task(id="c", repeat="weekly", days=[2, 4], time="17:00")], MONDAY)
    assert [r["day"] for r in rows if r["id"] == "sc-1"] == [0, 1, 2, 3, 4, 5, 6]
    assert [r["day"] for r in rows if r["id"] == "b"] == [0, 1, 2, 3, 4]
    assert [r["day"] for r in rows if r["id"] == "c"] == [2, 4]
    assert rows == sorted(rows, key=lambda r: (r["at"], r["title"]))


def test_once_only_shows_inside_the_week():
    inside = datetime(2026, 10, 15, 14, 0).timestamp()
    outside = datetime(2026, 10, 25, 14, 0).timestamp()
    rows = cv.occurrences([task(repeat="once", at=inside), task(id="o", repeat="once", at=outside)], MONDAY)
    assert [(r["id"], r["day"], r["time"]) for r in rows] == [("sc-1", 3, "14:00")]


def test_fast_repeats_do_not_flood_the_week():
    rows = cv.occurrences([task(repeat="every", every_minutes=5)], MONDAY)
    assert len(rows) == 7 and all(r["all_day"] for r in rows)
    hourly = cv.occurrences([task(repeat="every", every_minutes=180)], MONDAY)
    assert len(hourly) == 7 * 8 and not any(r["all_day"] for r in hourly)
    assert len(cv.occurrences([task(repeat="every", every_minutes=60)], MONDAY)) == cv.MAX_PER_TASK


def test_paused_and_unassigned_tasks_are_shown_but_marked():
    rows = cv.occurrences([task(enabled=False), task(id="n", avatar="")], MONDAY, days=1)
    by_id = {r["id"]: r for r in rows}
    assert by_id["sc-1"]["enabled"] is False and by_id["n"]["runs"] is False


def test_the_look_keeps_only_valid_values():
    look = cv.set_look({"view": "agenda", "density": "huge", "start_hour": 30, "end_hour": 1, "accent": "red", "evil": "<script>"})
    assert look["view"] == "agenda" and look["density"] == "comfortable"
    assert look["start_hour"] == 22 and look["end_hour"] == 24
    assert look["accent"] == "" and "evil" not in look
    assert cv.set_look({"accent": "#FF7A2E"})["accent"] == "#ff7a2e"
    assert cv.get_look()["view"] == "agenda"  # saved between calls
    assert cv.reset_look() == cv.DEFAULT_LOOK


def test_the_ai_tool_restyles_and_says_what_changed():
    assert "density compact" in cv.tool_restyle(density="compact", show_weekend=False)
    assert cv.get_look()["show_weekend"] is False
    assert "unchanged" in cv.tool_restyle(density="gigantic")
    assert "default look" in cv.tool_restyle(reset=True)
    assert "Options" in cv.tool_restyle()


def test_google_events_are_folded_in_and_failures_stay_quiet():
    def fake_call(_name, _action, params=None):
        return {"data": {"items": [
            {"id": "e1", "summary": "Dentist", "start": {"dateTime": "2026-10-14T10:00:00"}},
            {"id": "e2", "summary": "Holiday", "start": {"date": "2026-10-16"}},
            {"id": "e3", "summary": "Next month", "start": {"date": "2026-11-20"}}]}}

    ok, events, error = cv.google_events(MONDAY, call=fake_call, connected=lambda: True)
    assert ok and error == "" and [e["title"] for e in events] == ["Dentist", "Holiday"]
    assert events[1]["all_day"] is True and events[1]["day"] == 4

    assert cv.google_events(MONDAY, call=fake_call, connected=lambda: False) == (False, [], "")

    def broken(*_a, **_k):
        raise RuntimeError("quota")

    assert cv.google_events(MONDAY, call=broken, connected=lambda: True) == (False, [], "quota")


def test_week_bundles_days_items_look_and_google_state():
    data = cv.week(date(2026, 10, 14), tasks=[task()], google=lambda start: (True, [{"id": "g", "title": "Call", "at": 1.0, "time": "09:00",
                                                                                   "day": 0, "all_day": False, "source": "google",
                                                                                   "avatar": "", "repeat": "", "enabled": True, "runs": False}], ""))
    assert data["start"] == "2026-10-12" and [d["label"] for d in data["days"]][:2] == ["Mon", "Tue"]
    assert data["google"] == {"connected": True, "error": ""}
    assert {i["source"] for i in data["items"]} == {"orbit", "google"}
    cv.set_look({"show_google": False})
    assert cv.week(date(2026, 10, 14), tasks=[task()])["google"]["connected"] is False


def test_a_repeating_task_has_no_runs_before_the_day_it_was_made():
    made = datetime(2026, 10, 15, 10, 0).timestamp()
    rows = cv.occurrences([task(created=made)], MONDAY)
    assert [r["day"] for r in rows] == [3, 4, 5, 6]
    once = datetime(2026, 10, 13, 9, 0).timestamp()
    assert [r["day"] for r in cv.occurrences([task(id="o", repeat="once", at=once, created=made)], MONDAY)] == [1]
