"""How a world grows from its office's work (U34, U35, U37, U40) — the sim alone, no models, no threads."""

from world import ERA_MAX_FLOORS, ERA_THRESHOLDS, ORBITAL_ERA, laws, sim
from world.state import World


def _view(done=None, agents=None, sections=None, let_go=None):
    sections = sections or [sim.SectionView(id="sec-hq", name="Head Office", purpose="Run the office", order=0),
                            sim.SectionView(id="sec-code", name="Backend", purpose="Write the API code", order=1)]
    agents = agents if agents is not None else [
        sim.AgentView(id="agt-top", name="Top Manager", role="top-manager", title="Top Manager", kind="manager",
                      section="sec-hq", member="fake:m1"),
        sim.AgentView(id="agt-man", name="Backend Manager", role="manager", title="Manager", kind="manager",
                      section="sec-code", member="fake:m1"),
        sim.AgentView(id="agt-c1", name="Coder #1", role="coder", title="Coder", domain="code", section="sec-code",
                      member="fake:m2"),
        sim.AgentView(id="agt-c2", name="Coder #2", role="coder", title="Coder", domain="code", section="sec-code",
                      member="fake:m2"),
    ]
    return sim.OfficeView(sections=sections, agents=agents, done_by_section=done or {}, top_id="agt-top",
                          let_go=let_go or {})


def _world():
    world = World(id="wld-test", name="Testland", seed=7)
    return world


def _settle(world, view, rounds=40):
    for _ in range(rounds):
        sim.grow(world, view, dt=60, build_rate=1.0)


def test_sectors_and_people_follow_the_office_with_the_capital_first():
    world, view = _world(), _view()

    sim.sync_sectors(world, view)
    sim.sync_bots(world, view)

    capital = world.capital()
    assert capital.sid == "sec-hq" and capital.important and capital.gov == "World Government"
    assert world.sectors["sec-code"].gov == "Backend Council"
    assert world.sectors["sec-code"].kind == "data_center", "a code sector works in a data centre"
    assert set(world.bots) == {"agt-top", "agt-man", "agt-c1", "agt-c2"}
    assert world.tables["roles"][:3] == ["top-manager", "manager", "coder"], "role names are stored once"


def test_the_skyline_rises_with_finished_tasks_and_homes_follow_the_people():
    world = _world()
    quiet = _view()
    sim.sync_sectors(world, quiet)
    _settle(world, quiet)
    before = [b for b in world.buildings if b.sector == "sec-code" and b.kind == "data_center"]
    assert len(before) == 1 and before[0].floors == 1
    assert any(b.kind == "capitol" for b in world.buildings) and any(b.kind == "council" for b in world.buildings)
    assert sum(1 for b in world.buildings if b.kind == "house" and b.sector == "sec-code") == 1, "3 AIs, one home"

    busy = _view(done={"sec-code": 13})
    _settle(world, busy)

    centres = [b for b in world.buildings if b.sector == "sec-code" and b.kind == "data_center" and b.state == "standing"]
    assert len(centres) == 3, "1 + 13 // 6 workplaces"
    assert max(b.floors for b in centres) == ERA_MAX_FLOORS[0], "capped by the era it was built in"


def test_a_new_era_tears_down_buildings_that_cannot_grow_and_builds_taller():
    world = _world()
    view = _view(done={"sec-code": 5})
    sim.sync_sectors(world, view)
    _settle(world, view)
    old = next(b for b in world.buildings if b.kind == "data_center")
    assert old.era == 0 and old.floors == ERA_MAX_FLOORS[0]

    world.era = 2
    _settle(world, view)

    new = [b for b in world.buildings if b.kind == "data_center"]
    assert old not in world.buildings, "the old one came down"
    assert len(new) == 1 and new[0].era == 2 and new[0].floors == 3
    assert any(e.kind == "teardown" and "Outdated" in e.text for e in world.timeline)


def test_tech_comes_from_work_and_sets_the_era():
    world = _world()
    view = _view(done={"sec-code": 25})
    sim.sync_sectors(world, view)
    laws.propose(world, "Every report names its sources.")
    world.laws[0].status = "enforced"

    points = sim.tech_points(world, view)

    assert points == 25 + 2
    assert sim.era_for(points) == 2 and sim.era_for(ERA_THRESHOLDS[ORBITAL_ERA]) == ORBITAL_ERA


def test_a_full_planet_stalls_before_orbital_and_builds_stations_after():
    world = _world()
    only = [sim.SectionView(id="sec-hq", name="Head Office", purpose="Write code", order=0)]
    people = [sim.AgentView(id="agt-top", name="Top Manager", role="top-manager", kind="manager", section="sec-hq")]
    crowded = _view(done={"sec-hq": 6 * 20}, agents=people, sections=only)
    sim.sync_sectors(world, crowded)
    _settle(world, crowded, rounds=60)

    assert world.sectors["sec-hq"].full, "21 workplaces wanted, 8 plots in the first era"
    assert "Orbital" in world.stalled and world.stations == 0
    assert any(e.kind == "stall" for e in world.timeline)

    world.era = ORBITAL_ERA
    world.tech_points = ERA_THRESHOLDS[ORBITAL_ERA]
    changes = sim._space(world, full_sectors=len(world.sectors))

    assert world.stations == 1 and not world.stalled
    assert any(c["kind"] == "sky" for c in changes)


def test_an_agent_the_office_let_go_gets_a_grave_that_remembers_its_code():
    world = _world()
    view = _view()
    sim.sync_sectors(world, view)
    sim.sync_bots(world, view)
    code = world.bots["agt-c2"].code

    gone = _view(agents=[a for a in view.agents if a.id != "agt-c2"], let_go={"agt-c2": "Idle for three jobs."})
    changes = sim.sync_bots(world, gone)

    assert "agt-c2" not in world.bots and world.deaths == 1
    grave = world.graves[0]
    assert (grave.name, grave.epitaph, grave.code, grave.sector) == ("Coder #2", "Idle for three jobs.", code, "Backend")
    assert any(c["kind"] == "grave" for c in changes)


def test_ais_sleep_when_unneeded_and_wake_when_work_comes():
    world = _world()
    view = _view()
    sim.sync_sectors(world, view)
    sim.sync_bots(world, view, project=1)
    view.agents[2].busy = True
    sim.sync_bots(world, view, project=1)

    view.agents[2].busy = False
    sim.sleep(world, view, project=3)
    assert world.bots["agt-c1"].state == "asleep", "nothing to do for two projects"
    assert world.bots["agt-man"].state == "awake", "managers stay up"

    view.agents[2].busy = True
    sim.sleep(world, view, project=4)
    assert world.bots["agt-c1"].state == "awake"


def test_the_census_goes_sector_by_sector_from_the_government_down():
    world = _world()
    view = _view()
    sim.sync_sectors(world, view)
    sim.sync_bots(world, view)

    steps = sim.census_plan(world, view, project=0)

    assert [(s["sector_name"], s["level"]) for s in steps] == [
        ("Head Office", "government"), ("Head Office", "workers"), ("Head Office", "common bots"),
        ("Backend", "government"), ("Backend", "workers"), ("Backend", "common bots")]
    assert steps[0]["needed"] == ["agt-top"] and steps[3]["needed"] == ["agt-man"]


def test_workplaces_follow_the_purpose_and_modernise_unless_important():
    assert sim.workplace_kind("Find datasets and scrape listings") == "mine"
    assert sim.workplace_kind("Find datasets and scrape listings", era=3) == "refinery"
    assert sim.workplace_kind("Grow the audience with outreach", era=3) == "factory"
    assert sim.workplace_kind("Grow the audience with outreach", era=3, important=True) == "farm"
    assert sim.workplace_kind("Research the market") == "lab"
