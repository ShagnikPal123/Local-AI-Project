"""The technology tree, the economy, phased construction and the planet's own look — no models, no threads."""

from world import planet, sim, tech
from world.state import Building, World, phase_of


def _view(done=None):
    sections = [sim.SectionView(id="sec-hq", name="Head Office", purpose="Run the office", order=0),
                sim.SectionView(id="sec-mine", name="Data", purpose="Collect the dataset", order=1)]
    agents = [sim.AgentView(id="agt-top", name="Top", role="top-manager", kind="manager", section="sec-hq"),
              sim.AgentView(id="agt-d1", name="Miner", role="scraper", section="sec-mine")]
    return sim.OfficeView(sections=sections, agents=agents, done_by_section=done or {}, top_id="agt-top")


def test_every_tech_needs_only_cheaper_techs_and_the_ladder_reaches_hover_and_warp():
    for item in tech.TREE:
        for need in item["needs"]:
            assert tech.BY_ID[need]["cost"] < item["cost"], (item["id"], need)
    levels = sorted(t["transport"] for t in tech.TREE if "transport" in t)
    assert levels == list(range(len(tech.TRANSPORT_LEVELS)))

    world = World(id="w", name="W", seed=1)
    world.tech_points = 10_000
    tech.advance(world)
    assert len(world.researched) == len(tech.TREE)
    assert tech.TRANSPORT_LEVELS[tech.level(world)] == "Star lanes"


def test_research_is_earned_in_order_and_a_focus_makes_a_branch_cheaper():
    world = World(id="w", name="W", seed=1)
    tech.advance(world)
    assert set(world.researched) == set(tech.STARTING) and tech.level(world) == 0

    world.tech_points = 29
    tech.advance(world)
    assert tech.has(world, "carts") and not tech.has(world, "railways"), "railways cost 30"

    world.focus = "transport"
    new = tech.advance(world)
    assert [t["id"] for t in new] == ["railways"], "a quarter off: 23"
    assert tech.level(world) == 2 and "transit" in tech.unlocked_kinds(world)

    world.tech_points = 0
    tech.advance(world)
    assert tech.has(world, "railways"), "once discovered, never lost"


def test_the_labs_research_while_the_world_runs_and_it_counts_as_tech():
    world = World(id="w", name="W", seed=1)
    view = _view()
    assert tech.research_rate(world, 0, 1.0) == 0.0
    rate = tech.research_rate(world, 16, 1.0)
    assert 0.07 < rate < 0.09
    world.research = 12.6
    assert sim.tech_points(world, view) == 12


def test_building_goes_through_phases_and_waits_for_materials():
    world = World(id="w", name="W", seed=1)
    building = Building(bid=1, sector="sec-x", kind="office", floors=4, state="constructing", progress=0.0)
    world.buildings.append(building)
    world.stock["materials"] = 0.0
    phases = []
    view = sim.OfficeView()

    sim.grow(world, view, dt=1.0, build_rate=0.05)
    assert building.why == sim.WAITING and building.progress == 0.0

    world.stock["materials"] = 1000.0
    while building.state == "constructing":
        phases.append(phase_of(building))
        sim.grow(world, view, dt=1.0, build_rate=0.05)
    assert [p for i, p in enumerate(phases) if i == 0 or phases[i - 1] != p] == \
        ["survey", "foundation", "frame", "facade", "fit-out"]
    assert world.stock["materials"] < 1000.0 - sim.COST_BASE, "it used materials"
    assert building.why == ""


def test_power_and_transit_rise_once_their_technology_is_known():
    world = World(id="w", name="W", seed=1)
    view = _view(done={"sec-mine": 14})
    sim.sync_sectors(world, view)
    for _ in range(40):
        sim.grow(world, view, dt=60, build_rate=1.0)
    assert not any(b.kind in ("power", "transit") for b in world.buildings)

    world.tech_points = 40
    tech.advance(world)
    for _ in range(40):
        sim.grow(world, view, dt=60, build_rate=1.0)
    kinds = [b.kind for b in world.buildings if b.sector == "sec-mine" and b.state == "standing"]
    assert "power" in kinds and "transit" in kinds
    assert world.stock["energy"] > 0


def test_the_planet_is_the_same_for_a_seed_and_differs_between_seeds():
    first, again = planet.describe(42), planet.describe(42)
    assert first == again
    looks = {planet.describe(seed)["type"] for seed in range(1, 80)}
    assert len(looks) >= 6, "many kinds of planet"
    for seed in range(1, 40):
        body = planet.describe(seed)
        assert 1.0 <= body["radius"] <= 1.4 and len(body["land"]) == 3 and len(body["moons"]) <= 3
        assert all(c.startswith("#") and len(c) == 7 for c in body["land"] + body["sea"] + [body["air"]])
    assert planet.words(42).startswith(first["label"])


def test_growth_is_sampled_and_thinned_but_keeps_its_start():
    world = World(id="w", name="W", seed=1)
    for step in range(400):
        world.tech_points = step
        world.game_days = step
        world.sample_growth()
    assert len(world.growth) <= 160 and world.growth[0][1] == 0 and world.growth[-1][1] == 399
