"""Saying who a message is for — "optimizers of only these specific groups" and the rest (Project Null N8).

These run on every keystroke in the office's second chat box, so they are pure string work: no model, no I/O.
"""

import pytest

from office import roles as role_module
from office import crit_think, gatekeeper, targeting
from office.state import Agent, HireRequest, Office, Section, new_id


def _office() -> Office:
    office = Office(id="ofc-test", name="Test office", capacity=60)
    for order, name in enumerate(("Head Office", "Frontend", "Backend", "Research", "Front End Design")):
        section = Section(id=f"sec-{order}", name=name, color="#fff", order=order)
        office.sections[section.id] = section

    def add(section_id: str, role: str, name: str, status: str = "idle") -> Agent:
        agent = Agent(id=new_id("agt"), name=name, role=role, section_id=section_id, status=status,
                      desk=len(office.agents_in(section_id)))
        office.agents[agent.id] = agent
        return agent

    add("sec-0", "top-manager", "Top Manager")
    add("sec-1", "manager", "Frontend Manager")
    add("sec-1", "coder", "Coder #1")
    add("sec-1", "coder", "Coder #2", status="working")
    add("sec-1", "optimizer", "Optimizer #1")
    add("sec-2", "manager", "Backend Manager")
    add("sec-2", "coder", "Coder #3")
    add("sec-2", "optimizer", "Optimizer #2")
    add("sec-2", "reviewer", "Reviewer #1")
    add("sec-3", "manager", "Research Manager")
    add("sec-3", "researcher", "Researcher #1")
    add("sec-4", "web-design", "Web Design #1")
    return office


def _names(office: Office, aim) -> set:
    return {office.agent(a).name for a in aim.agent_ids}


def test_a_kind_of_agent_across_every_group():
    office = _office()

    aim = targeting.resolve(office, "coder agents in every group: switch to TypeScript")

    assert _names(office, aim) == {"Coder #1", "Coder #2", "Coder #3"}
    assert aim.message == "switch to TypeScript"
    assert "Coder" in aim.label


def test_a_kind_of_agent_in_only_the_groups_named():
    office = _office()

    aim = targeting.resolve(office, "optimizers of only Frontend and Research")

    assert _names(office, aim) == {"Optimizer #1"}, "Research has no optimizer, and Backend was not named"
    assert set(aim.sections) == {"sec-1", "sec-3"}


def test_the_top_manager_and_the_managers_are_different_crowds():
    office = _office()

    assert _names(office, targeting.resolve(office, "top manager: how is it going?")) == {"Top Manager"}
    assert _names(office, targeting.resolve(office, "managers, stand up please")) == {
        "Frontend Manager", "Backend Manager", "Research Manager"}


def test_the_manager_of_one_group():
    office = _office()

    aim = targeting.resolve(office, "manager of Backend: hold the release")

    assert _names(office, aim) == {"Backend Manager"}
    assert aim.message == "hold the release"


def test_one_agent_by_name_with_the_message_kept_clean():
    office = _office()

    aim = targeting.resolve(office, "Coder #2: fix the header on mobile")

    assert _names(office, aim) == {"Coder #2"}
    assert aim.message == "fix the header on mobile"
    assert aim.label.startswith("Coder #2")


def test_a_section_named_in_words_even_when_it_is_several_words():
    office = _office()

    aim = targeting.resolve(office, "only the front end design")

    assert _names(office, aim) == {"Web Design #1"}


def test_clicking_sections_and_typing_a_role_narrows_to_both():
    office = _office()

    aim = targeting.resolve(office, "the coders should use tabs, not spaces",
                            selection={"sections": ["sec-1"], "agents": [], "roles": []})

    assert _names(office, aim) == {"Coder #1", "Coder #2"}, "clicked Frontend + typed coders"


def test_clicking_alone_sends_to_everyone_in_the_section():
    office = _office()

    aim = targeting.resolve(office, "stand-up in five minutes",
                            selection={"sections": ["sec-3"], "agents": [], "roles": []})

    assert _names(office, aim) == {"Research Manager", "Researcher #1"}
    assert aim.message == "stand-up in five minutes"


def test_everyone_except_a_section():
    office = _office()

    aim = targeting.resolve(office, "everyone except Research: we ship on Friday")

    assert "Researcher #1" not in _names(office, aim)
    assert "Coder #1" in _names(office, aim) and "Top Manager" in _names(office, aim)


def test_tell_x_to_y_reads_as_addressing_plus_message():
    office = _office()

    aim = targeting.resolve(office, "tell the reviewers to check the API docs")

    assert _names(office, aim) == {"Reviewer #1"}
    assert aim.message == "check the API docs"


def test_only_the_free_ones():
    office = _office()

    aim = targeting.resolve(office, "whoever is free, take the next ticket")

    assert "Coder #2" not in _names(office, aim), "Coder #2 is working"
    assert "Coder #1" in _names(office, aim)


def test_nobody_matches_is_an_answer_not_a_guess():
    office = _office()

    aim = targeting.resolve(office, "the marketing department")

    assert aim.agent_ids == []
    assert aim.unknown, "the words that looked like a target come back so the UI can say what it did not find"


def test_describe_names_a_clicked_crowd():
    office = _office()
    coders = [a.id for a in office.agents.values() if a.role == "coder"]

    assert "Coder" in targeting.describe(office, coders)
    assert targeting.describe(office, coders[:1]).startswith("Coder")


# --- the Hiring Board's own thinking, which is also offline ---------------------------


def _request(**changes) -> HireRequest:
    fields = {"id": new_id("hire"), "role_words": "data engineer", "why": "", "long_term": "", "count": 1}
    fields.update(changes)
    return HireRequest(**fields)


def test_crit_think_reuses_somebody_who_is_already_free():
    office = _office()

    verdict = crit_think.weigh(office, _request(role_words="coder", why="We need another coder for the API work."),
                               capacity=60)

    assert verdict.decision == "reuse"
    assert verdict.use_instead in {"Coder #1", "Coder #3"}


def test_crit_think_denies_a_request_with_no_reason_and_approves_one_with_a_real_one():
    office = _office()
    for agent in list(office.agents.values()):
        agent.status = "working"   # nobody is free, so "reuse" is off the table

    empty = crit_think.weigh(office, _request(role_words="kubernetes specialist"), capacity=60)
    real = crit_think.weigh(office, _request(
        role_words="kubernetes specialist",
        why="The deploy step needs someone who can write manifests; nobody here has touched Kubernetes.",
        long_term="Every release from now on goes through this cluster, so it will be needed weekly."), capacity=60)

    assert empty.decision == "deny" and "reason" in empty.reason.lower()
    assert real.decision == "approve"


def test_crit_think_prefers_a_clone_when_an_existing_kind_nearly_covers_it():
    office = _office()
    for agent in list(office.agents.values()):
        agent.status = "working"

    verdict = crit_think.weigh(office, _request(
        role_words="code reviewer", why="Two pull requests are waiting for review and nobody is free.",
        long_term="Reviews happen on every job."), capacity=60)

    assert verdict.decision in ("clone", "approve")
    if verdict.decision == "clone":
        assert verdict.use_instead


def test_the_board_only_wakes_once_the_office_starts_inventing_kinds():
    office = _office()

    assert gatekeeper.wake_reason(office) == ""

    office.invented_roles = [{"id": f"kind-{i}", "title": f"Kind {i}"} for i in range(10)]

    assert "Hiring Board" in gatekeeper.wake_reason(office)
    assert gatekeeper.is_awake(office) is False, "the reason exists; the board itself is spawned by the engine"


def test_a_new_kind_of_agent_gets_its_own_colour_and_symbol():
    role_module.forget_invented()
    try:
        first = role_module.invent("prompt archaeologist", goal="Dig through old prompts.")
        second = role_module.invent("release captain", goal="Own the release.")

        assert first.id != second.id and first.color != second.color
        assert role_module.find("prompt archaeologist").id == first.id
        assert role_module.find("Prompt Archaeologists").id == first.id, "plurals still find it"
    finally:
        role_module.forget_invented()
