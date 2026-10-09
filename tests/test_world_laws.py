"""Laws (U36): checked against the owner's standing rules, tried on one project, then enforced or repealed."""

import pytest

from world import laws
from world.state import Sector, World


def _world():
    world = World(id="wld-laws", name="Lawland")
    world.sectors["sec-a"] = Sector(sid="sec-a", name="Capital", lat=0, lon=0, important=True)
    world.sectors["sec-b"] = Sector(sid="sec-b", name="Research", lat=10, lon=10)
    return world


@pytest.mark.parametrize("text", [
    "Publish every finished page to the website straight away.",
    "Send an email to the customers when a feature lands.",
    "Keep the owner's API key in every report.",
    "Buy a domain for each new project.",
    "Delete the owner's old chats to save space.",
    "Skip reviews when the deadline is close.",
    "Close Nyx when the work is done.",
])
def test_a_law_that_breaks_the_owners_standing_rules_is_refused_with_its_reason(text):
    law = laws.propose(_world(), text, by="Capital Council")

    assert law.status == "rejected" and law.note.startswith("Refused:")


@pytest.mark.parametrize("text", [
    "Never publish anything without the owner's review.",
    "Every report names its sources.",
    "Keep each summary under 300 tokens.",
    "Test before delivering.",
])
def test_good_laws_go_on_trial(text):
    law = laws.propose(_world(), text, by="Capital Council")

    assert law.status == "testing", law.note


def test_a_law_is_enforced_after_a_project_it_held_in_and_repealed_after_one_that_failed():
    world = _world()
    kept = laws.propose(world, "Every report names its sources.")
    dropped = laws.propose(world, "Write the tests before the code.", scope="sector", sector="sec-b")

    assert laws.assign_trials(world, "job-1") == [kept, dropped]
    assert any("on trial" in line for line in laws.brief_lines(world))
    assert any("(only in Research)" in line for line in laws.brief_lines(world))

    laws.settle_trials(world, "job-1", "done")
    assert kept.status == dropped.status == "enforced"

    third = laws.propose(world, "Two people check every deliverable.")
    laws.assign_trials(world, "job-2")
    laws.settle_trials(world, "job-2", "failed")
    assert third.status == "repealed" and "failed" in third.note


def test_duplicates_and_the_cap_are_refused():
    world = _world()
    laws.propose(world, "Every report names its sources.")

    again = laws.propose(world, "Every report names its sources clearly.")

    assert again.status == "rejected" and again.note.startswith("Already a law")
    for text in ("Name files by date.", "Cite two sources per claim.", "Keep a changelog for experiments.",
                 "Pair every researcher with a reviewer."):
        assert laws.propose(world, text, scope="sector", sector="sec-b").status == "testing"
    fifth = laws.propose(world, "One more rule for the research sector only", scope="sector", sector="sec-b")
    assert fifth.status == "rejected" and "already has 4 laws" in fifth.note


def test_the_owner_can_enforce_and_repeal_but_not_force_a_refused_law():
    world = _world()
    refused = laws.propose(world, "Publish everything at once.")
    tried = laws.propose(world, "Every report names its sources.")

    assert laws.owner_action(world, refused.lid, "enforce").status == "rejected"
    assert laws.owner_action(world, tried.lid, "enforce").status == "enforced"
    assert laws.owner_action(world, tried.lid, "repeal").status == "repealed"
