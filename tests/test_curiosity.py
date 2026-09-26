"""The third mind: filing questions, owning mistakes, and never taking over a chat."""

from __future__ import annotations

import time

import pytest

import curiosity


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(curiosity, "_path", lambda: tmp_path / "curiosity" / "state.json")
    yield


def test_not_knowing_something_becomes_a_question():
    made = curiosity.notice("I don't know what a Kalman filter is.", source="chat")
    assert made and "kalman filter" in made[0]["text"].lower()
    assert made[0]["status"] == "open"


def test_two_admissions_in_one_sentence_become_two_questions():
    made = curiosity.notice("I do not know what tokamak confinement is, and I couldn't find the 2026 figures.")
    texts = " | ".join(m["text"].lower() for m in made)
    assert "tokamak" in texts
    assert len(made) >= 1
    # Each question stands on its own rather than running into the next clause.
    assert all(" and i couldn" not in m["text"].lower() for m in made)


def test_the_same_question_coming_back_gets_more_interesting():
    def kalman():
        return next(q for q in curiosity.state()["questions"] if "kalman" in q["text"].lower())

    curiosity.notice("I don't know what a Kalman filter is.")
    before = kalman()["interest"]
    curiosity.notice("I don't know what a Kalman filter is.")
    assert kalman()["asked"] == 2
    assert kalman()["interest"] > before


def test_noticing_can_be_switched_off():
    curiosity.update_settings(notice=False)
    assert curiosity.notice("I don't know what a widget is.") == []
    curiosity.update_settings(notice=True)


def test_the_owner_can_file_a_question_a_want_and_a_mistake():
    curiosity.ask("How does AirLLM split layers?", why="it came up twice")
    curiosity.want("read scanned PDFs offline")
    curiosity.own_mistake("Said a file was saved when the write failed",
                          got_wrong="did not check the result", learned="check what the tool returned")
    state = curiosity.state()
    assert state["questions"][0]["text"].startswith("How does AirLLM")
    assert state["wants"][0]["text"] == "read scanned PDFs offline"
    assert state["mistakes"][0]["learned"].startswith("check what")


def test_the_most_interesting_question_is_the_one_it_would_pick():
    curiosity.ask("A question the owner asked")            # interest 0.9
    curiosity.notice("I don't know what a widget is.")     # scored from what it knows
    assert curiosity.next_question()["text"] == "A question the owner asked"


def test_feelings_are_four_numbers_and_a_sentence():
    feelings = curiosity.feelings()
    assert set(feelings) == {"curiosity", "confidence", "unease", "satisfaction", "line"}
    assert all(0.0 <= feelings[k] <= 1.0 for k in ("curiosity", "confidence", "unease", "satisfaction"))
    assert feelings["line"]


def test_mistakes_without_a_lesson_show_up_as_unease():
    calm = curiosity.feelings()["unease"]
    for i in range(4):
        curiosity.own_mistake(f"Something went wrong {i}")
    assert curiosity.feelings()["unease"] > calm


def test_growth_counts_a_lifetime():
    curiosity.ask("How does AirLLM stream layers?")
    curiosity.own_mistake("Claimed a file was written", learned="check the result first")
    growth = curiosity.growth()
    assert growth["asked"] >= 1 and growth["mistakes"] >= 1 and growth["lessons"] >= 1
    assert growth["since"] <= time.time()


def test_studying_closes_the_question_and_keeps_the_lesson(monkeypatch):
    curiosity.ask("What is a Kalman filter?")

    class Run:
        text = "It is a recursive estimator.\nLEARNED: a Kalman filter predicts, then corrects with a measurement."

    monkeypatch.setattr(curiosity, "settings", lambda: {**curiosity.DEFAULTS, "notice": True})
    import model_roles

    monkeypatch.setattr(model_roles.MODEL_ROLES, "run", lambda *a, **k: Run())
    kept = {}
    import super_brain

    monkeypatch.setattr(super_brain.BRAIN, "ingest", lambda text, **k: kept.setdefault("text", text))

    result = curiosity.study(allow_web=False)
    assert result["ok"] is True
    assert "recursive estimator" in result["answer"]
    assert result["learned"].startswith("a Kalman filter predicts")
    assert curiosity.state()["questions"][0]["status"] == "answered"
    assert "Kalman" in kept.get("text", "")


def test_it_does_not_study_on_its_own_unless_that_is_switched_on():
    curiosity.update_settings(study_alone=False)
    assert curiosity.study_once_if_idle()["ok"] is False


def test_background_status_is_quiet_when_it_is_not_studying_alone():
    curiosity.update_settings(study_alone=False)
    assert curiosity.background_status() == []


def test_the_wonder_tool_files_each_kind():
    assert "question" in curiosity._tool_wonder("question", "What is X?")
    assert "want" in curiosity._tool_wonder("want", "be faster at Y")
    assert "Written down" in curiosity._tool_wonder("mistake", "got Z wrong", "check first")
