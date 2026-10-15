"""Constellations, Quasars and Orbits: auto-named groups the owner can rename, artifacts that outlive a project, and a
scheduled clock that only runs tasks someone has been assigned to."""

from datetime import datetime

import pytest


@pytest.fixture()
def pr(tmp_path, monkeypatch):
    import projects as module

    monkeypatch.setattr(module, "_path", lambda: tmp_path / "projects.json")
    return module


@pytest.fixture()
def sc(tmp_path, monkeypatch):
    import scheduled as module

    monkeypatch.setattr(module, "_path", lambda: tmp_path / "scheduled.json")
    return module


def test_tabs_are_grouped_and_named_automatically(pr):
    project = pr.create("Moon base", "Plan it", ["code", "research", "learn", "agents", "mystery"])
    names = {g["name"]: g["tabs"] for g in project["groups"]}
    assert names["Lattice"] == ["code"] and names["Spectrum"] == ["research", "learn"]
    assert names["Orbit"] == ["agents"] and names["Nebula"] == ["mystery"]
    assert all(g["auto"] for g in project["groups"])


def test_a_renamed_group_is_never_renamed_back(pr):
    project = pr.create("Moon base", tabs=["code", "research"])
    group = next(g for g in project["groups"] if g["name"] == "Lattice")
    renamed = pr.rename_group(project["id"], group["id"], "Engine room")
    assert any(g["name"] == "Engine room" and not g["auto"] for g in renamed["groups"])
    again = pr.add_tab(project["id"], "learn")           # regrouping must keep the owner's name
    assert any(g["name"] == "Engine room" for g in again["groups"])
    assert not any(g["name"] == "Lattice" for g in again["groups"])


def test_helpers_are_assigned_and_described_for_prompts(pr):
    project = pr.create("Moon base", "Land softly")
    pr.set_member(project["id"], "avatars", "orbit")
    pr.set_member(project["id"], "agents", "Researcher")
    note = pr.project_note(project["id"])
    assert "Moon base" in note and "Land softly" in note and "orbit" in note and "Researcher" in note
    with pytest.raises(pr.ProjectError):
        pr.set_member(project["id"], "robots", "x")


def test_deleting_a_project_keeps_its_artifacts(pr):
    project = pr.create("Moon base")
    artifact = pr.add_artifact("Lander idea", "idea", project_id=project["id"])
    assert pr.get(project["id"])["artifacts"][0]["id"] == artifact["id"]
    assert pr.delete(project["id"]) is True
    assert [a["id"] for a in pr.list_artifacts()] == [artifact["id"]]
    assert pr.list_artifacts()[0]["project_id"] == ""
    with pytest.raises(pr.ProjectError):
        pr.add_artifact("x", project_id="pr-gone")


def test_a_project_needs_a_name(pr):
    with pytest.raises(pr.ProjectError):
        pr.create("   ")


def test_daily_task_is_due_once_per_day(sc):
    task = sc.create({"title": "Mail", "prompt": "Read my mail", "repeat": "daily", "time": "08:00", "avatar": "orbit"})
    raw = sc._load()["tasks"][task["id"]]
    morning = datetime(2026, 10, 12, 8, 0, 30)
    raw["last_run"] = datetime(2026, 10, 11, 8, 0, 5).timestamp()
    assert sc.is_due(raw, morning) is True
    raw["last_run"] = morning.timestamp()
    assert sc.is_due(raw, datetime(2026, 10, 12, 20, 0)) is False
    assert sc.next_run(raw, datetime(2026, 10, 12, 20, 0)).day == 13


def test_a_task_without_an_avatar_never_runs_by_itself(sc):
    task = sc.create({"title": "Mail", "prompt": "Read my mail", "repeat": "every", "every_minutes": 5})
    assert sc.is_due(sc._load()["tasks"][task["id"]]) is False
    with pytest.raises(sc.ScheduleError):
        sc.run_now(task["id"])


def test_weekdays_skip_the_weekend_and_once_runs_once(sc):
    raw = sc.clean({"title": "t", "prompt": "p", "repeat": "weekdays", "time": "09:00", "avatar": "a"})
    saturday = datetime(2026, 10, 10, 10, 0)
    assert sc.next_run(raw, saturday).weekday() == 0
    once = sc.clean({"title": "t", "prompt": "p", "repeat": "once", "at": datetime(2026, 10, 12, 9, 0).timestamp(),
                     "avatar": "a"})
    assert sc.is_due(once, datetime(2026, 10, 12, 9, 1)) is True
    once["last_run"] = 1.0
    assert sc.next_run(once) is None


def test_run_now_records_the_avatars_answer(sc, monkeypatch):
    import avatars

    task = sc.create({"title": "Mail", "prompt": "Read my mail", "repeat": "daily", "avatar": "orbit"})
    monkeypatch.setattr(avatars, "run", lambda aid, text, kind="", wait=0: {"ok": True, "reply": "Read 3 emails"})
    assert sc.run_now(task["id"])["reply"] == "Read 3 emails"
    saved = sc.list_tasks()[0]
    assert saved["last_ok"] is True and saved["last_reply"] == "Read 3 emails" and saved["last_run"] > 0


def test_a_project_keeps_its_folder_like_a_claude_project(pr):
    project = pr.create("Moon base")
    saved = pr.update(project["id"], {"folder": ' "C:\\Users\\me\\Moon base" '})
    assert saved["folder"] == "C:\\Users\\me\\Moon base"
    assert pr.update(project["id"], {"folder": ""})["folder"] == ""
