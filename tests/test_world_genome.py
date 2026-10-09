"""The genetic code (U40) and the world's two clocks (U38): small, exact, and the same in every world."""

import pytest

from world import clock, genome


def test_a_code_round_trips_and_is_short():
    code = genome.encode(generation=1, role=7, rank=1, part_time=False, model=3, skills=[10, 11, 17])

    assert code == "1072F03:0A0B11"
    assert genome.decode(code) == {"generation": 1, "role": 7, "rank": 1, "part_time": False, "model": 3,
                                   "skills": [10, 11, 17]}
    assert genome.pretty(code) == "G1 · R07 · K2 · F · M03 · S0A.0B.11"


def test_promotion_and_part_time_rewrite_only_their_own_digits():
    code = genome.encode(generation=2, role=4, rank=0, model=9, skills=[1, 2])

    moved = genome.with_employment(code, rank=2, part_time=True)

    parts = genome.decode(moved)
    assert parts["rank"] == 2 and parts["part_time"] is True
    assert (parts["generation"], parts["role"], parts["model"], parts["skills"]) == (2, 4, 9, [1, 2])


def test_skills_come_from_the_role_and_new_words_get_their_own_codes():
    extra = []
    assert genome.skills_for("Finance Analyst", "knowledge") == ["finance", "data", "research"]
    assert genome.skill_code("code", extra) == genome.SKILLS.index("code")
    first = genome.skill_code("astrology", extra)
    assert first == len(genome.SKILLS) and genome.skill_code("astrology", extra) == first
    assert genome.skill_word(first, extra) == "astrology"


@pytest.mark.parametrize("a_title,a_domain,b_title,expected", [
    ("Finance", "knowledge", "Coder", "Finance Coder"),          # the owner's own example
    ("Researcher", "web", "Writer", "Research Writer"),
    ("Data Analyst", "files", "Tester", "Data Tester"),
    ("Reviewer", "code", "Coder", "Review Coder"),   # live run 2026-10-06: it came out as plain "Coder" before
    ("Optimizer", "code", "Writer", "Code Writer"),
    ("Manager", "agents", "Designer", "Management Designer"),
    ("Coder", "code", "Coder", "Coder"),
])
def test_a_child_is_named_from_both_parents(a_title, a_domain, b_title, expected):
    assert genome.child_title(a_title, a_domain, b_title) == expected


def test_a_child_is_the_next_generation_with_both_skill_sets():
    finance = genome.encode(generation=0, role=1, skills=[6, 5])
    coder = genome.encode(generation=2, role=2, skills=[1, 5])

    child = genome.decode(genome.child(finance, coder, role=9, model=4))

    assert child["generation"] == 3 and child["role"] == 9 and child["model"] == 4
    assert sorted(child["skills"]) == [1, 5, 6], "the union, with no skill twice"


@pytest.mark.parametrize("text,seconds", [
    ("work on this for 5 days", 5 * 86400),
    ("3 hours", 3 * 3600),
    ("run it for a week", 7 * 86400),
    ("keep going for two months", 60 * 86400),
    ("until it's done", 0),
    ("until done", 0),
    ("just make a website", None),
    ("overnight please", 10 * 3600),
])
def test_real_time_is_read_from_the_owners_words(text, seconds):
    assert clock.parse_duration(text) == seconds


def test_game_time_runs_by_speed_and_has_its_own_calendar():
    days = clock.advance(0.0, 120, 3.0)
    assert days == 6.0
    assert clock.game_date(days) == (1, 7)
    assert clock.game_date(360.0) == (2, 1)
    assert clock.describe_seconds(5 * 86400 + 3600) == "5 days 1 h"
