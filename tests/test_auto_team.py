"""Auto skill / Auto agent (Update 1, U21): "/auto" or "@auto" picks and runs the best team for a job."""

from __future__ import annotations

import types

import auto_team
import commands

ROSTER = [
    {"name": "Manager", "role": "master"},
    {"name": "Coder", "emoji": "C", "role": "worker", "goal": "Ship working code", "expertise": ["python", "debugging", "tests"]},
    {"name": "Web Design", "emoji": "W", "role": "worker", "goal": "Beautiful sites", "expertise": ["landing pages", "layout", "css"]},
    {"name": "Finance", "emoji": "F", "role": "worker", "goal": "Explain money and markets", "expertise": ["stocks", "funds", "budget"]},
]


def _skill(name, description, triggers=(), instructions="do it well"):
    return types.SimpleNamespace(skill_id=f"s-{name.lower()}", name=name, description=description, enabled=True,
                                 triggers=list(triggers), instructions=instructions,
                                 match_score=lambda text, t=list(triggers): sum(1 for x in t if x in text.lower()))


SKILLS = [
    _skill("Debugging", "Reproduce, isolate, and fix a bug rather than guessing", ["bug", "error"], "Reproduce first."),
    _skill("Landing pages", "Design a landing page that converts", ["landing page"], "Hero, proof, one call to action."),
    _skill("Poetry", "Write poems", ["poem"]),
]


def test_both_spellings_call_it_and_lookalikes_do_not():
    assert auto_team.called("/auto build me a site") and auto_team.called("please @auto sort this out")
    assert not auto_team.called("see C:/auto/notes.txt") and not auto_team.called("/automation ideas")
    assert not auto_team.called("email me at bob@auto.com")
    assert auto_team.strip("/auto build me a site") == "build me a site"


def test_it_picks_the_skills_and_agents_that_fit_the_job():
    team = auto_team.assemble("/auto fix the bug in my python script and add tests", roster=ROSTER, skills=SKILLS)
    assert [s["name"] for s in team["skills"]] == ["Debugging"]
    assert team["agents"][0]["name"] == "Coder"
    assert all(a["name"] != "Manager" for a in team["agents"])
    assert not team["create_agent"]

    page = auto_team.assemble("@auto make a landing page with a clean layout for my bakery", roster=ROSTER, skills=SKILLS)
    assert page["agents"][0]["name"] == "Web Design" and page["skills"][0]["name"] == "Landing pages"


def test_when_nobody_fits_it_makes_the_agent_it_needs():
    team = auto_team.assemble("/auto plan a week of vegetarian dinners with a shopping list", roster=ROSTER, skills=SKILLS)
    assert team["agents"] == [] and team["create_agent"] is True
    assert "create_agent" in auto_team.brief(team)
    assert auto_team.assemble("/auto hi", roster=ROSTER, skills=SKILLS)["create_agent"] is False, "no team for a greeting"


def test_the_brief_says_how_to_run_the_team_so_each_request_is_visible():
    team = auto_team.assemble("/auto fix the bug in my python script and add tests", roster=ROSTER, skills=SKILLS)
    text = auto_team.brief(team)
    assert text.startswith(auto_team.PREFIX)
    assert "Reproduce first." in text, "picked skills arrive with their full instructions"
    assert "dispatch_agents" in text and "exactly what each agent was asked" in text
    shown = auto_team.view(team)
    assert "instructions" not in str(shown), "the chat shows names and why, not whole skill texts"
    assert auto_team.status_line(team).startswith("Auto picked skills Debugging")


def test_auto_is_a_command_and_a_skill():
    assert any(c["name"] == "auto" and c["kind"] == "auto" for c in commands.all_commands())
    brief = commands.brief_for("/auto tidy my downloads folder")
    assert brief["found"] == ["auto"] and "[Auto team]" in brief["context"]

    from skills import BUILTIN_SKILLS

    auto = next(s for s in BUILTIN_SKILLS if s["name"] == auto_team.SKILL_NAME)
    assert auto["triggers"] == [], "it runs when called, never because a word happened to match"
