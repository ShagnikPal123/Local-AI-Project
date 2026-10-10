"""The government as its own district, its branches and ministries, and the Assembly's vote — no models, no threads."""

import gzip
import json
import types

from world import civics, laws, sim, tech
from world.state import GOV_SID, Building, Sector, World


def _view():
    sections = [sim.SectionView(id="sec-hq", name="Head Office", purpose="Run the office", order=0),
                sim.SectionView(id="sec-code", name="Backend", purpose="Write the API code", order=1),
                sim.SectionView(id="sec-lab", name="Research", purpose="Study the market", order=2)]
    agents = [
        sim.AgentView(id="agt-top", name="Top Manager", role="top-manager", title="Top Manager", kind="manager",
                      section="sec-hq", rank=3),
        sim.AgentView(id="agt-man", name="Backend Manager", role="manager", title="Manager", kind="manager",
                      section="sec-code", rank=2),
        sim.AgentView(id="agt-res", name="Research Lead", role="researcher", title="Researcher", kind="manager",
                      section="sec-lab", rank=2),
        sim.AgentView(id="agt-c1", name="Coder #1", role="coder", title="Coder", domain="code", section="sec-code"),
        sim.AgentView(id="agt-c2", name="Coder #2", role="coder", title="Coder", domain="code", section="sec-code"),
        sim.AgentView(id="agt-f1", name="Analyst", role="finance-analyst", title="Finance Analyst", domain="finance",
                      section="sec-hq"),
    ]
    return sim.OfficeView(sections=sections, agents=agents, done_by_section={}, top_id="agt-top")


def _world():
    world = World(id="wld-civ", name="Civica", seed=11)
    view = _view()
    sim.sync_sectors(world, view)
    sim.sync_bots(world, view)
    tech.advance(world)
    return world, view


def test_the_government_sits_in_its_own_district_and_no_sector_is_its_seat():
    world, view = _world()

    assert civics.ensure(world) is True and civics.ensure(world) is False
    lat, lon = civics.location(world)
    assert (lat, lon) == (civics.SEAT_LAT, civics.SEAT_LON)
    assert all(civics._angle(lat, lon, s.lat, s.lon) > 20 for s in world.sectors.values()), "sectors sit elsewhere"
    for _ in range(20):
        sim.grow(world, view, dt=60, build_rate=1.0)
    district = {b.kind for b in world.buildings if b.sector == GOV_SID}
    assert {"capitol", "chancellery", "ministry"} <= district
    assert "court" not in district, "the High Court opens with written law"
    assert not any(b.kind == "capitol" and b.sector != GOV_SID for b in world.buildings)


def test_seats_come_from_the_office_one_per_sector_and_ministers_fit_their_ministry():
    world, view = _world()

    assert civics.seat(world, view) is True
    gov = world.government
    assert gov["head"] == "agt-top", "the top manager leads the Chancellery"
    assert gov["seats"] == {"sec-hq": "agt-f1", "sec-code": "agt-man", "sec-lab": "agt-res"}
    assert gov["justices"] == [], "no court before written law"
    assert set(gov["ministers"]) == {"works", "science"}

    world.tech_points = 30
    tech.advance(world)
    civics.seat(world, view)
    assert len(gov["justices"]) == 2, "the two left who hold no other seat"
    assert {"treasury", "transport"} <= set(gov["opened"])
    assert any(e.kind == "ministry" and "Treasury" in e.text for e in world.timeline)
    assert civics.seat(world, view) is False, "nothing changed"

    snap = civics.snapshot(world)
    branches = {b["key"]: b for b in snap["branches"]}
    assert branches["executive"]["members"][0]["name"] == "Top Manager"
    assert {m["seat"] for m in branches["legislature"]["members"]} == {"Head Office", "Backend", "Research"}
    assert branches["judiciary"]["open"]
    assert next(m for m in snap["ministries"] if m["key"] == "treasury")["stock"]["materials"] >= 0


def test_the_assembly_votes_on_government_laws_and_a_no_majority_rejects_one(monkeypatch):
    world, view = _world()
    civics.seat(world, view)

    law = laws.propose(world, "Every report names its sources.", by=civics.signer(world))
    tally = civics.vote(world, law)
    again = World(id="x", name="x", seed=world.seed)
    assert tally["yes"] + tally["no"] + tally["abstain"] == 3
    assert law.votes == f"{tally['yes']}-{tally['no']}-{tally['abstain']}"
    assert any(e.kind == "vote" for e in world.timeline)
    assert again.seed == world.seed

    monkeypatch.setattr(civics, "_stable", lambda text: types.SimpleNamespace(random=lambda: 0.99))
    refused = laws.propose(world, "Every task is reviewed twice before it is handed in.", by=civics.signer(world))
    civics.vote(world, refused)
    assert refused.status == "rejected" and "voted it down" in refused.note
    assert world.government["last_vote"]["passed"] is False


def test_a_format_1_world_loses_its_capital_and_gets_a_district(tmp_path):
    world = World(id="wld-old", name="Oldtown", seed=3)
    world.sectors["sec-a"] = Sector(sid="sec-a", name="Head Office", lat=18.0, lon=0.0, important=True,
                                    gov="World Government")
    world.buildings.append(Building(bid=1, sector="sec-a", kind="capitol", state="standing", progress=1.0))
    raw = world.to_compact()
    raw["f"] = 1
    raw.pop("GV")
    back = World.from_compact(json.loads(json.dumps(raw)))

    sector = back.sectors["sec-a"]
    assert not sector.important and sector.gov == "Head Office Council"
    assert back.buildings[0].kind == "council"
    assert civics.ensure(back) is True
    lat, lon = civics.location(back)
    assert civics._angle(lat, lon, 18.0, 0.0) > 20, "the old capital's place is taken, so the district moves"


def test_government_buildings_keep_their_district_through_the_file():
    world, view = _world()
    for _ in range(20):
        sim.grow(world, view, dt=60, build_rate=1.0)
    back = World.from_compact(json.loads(gzip.decompress(gzip.compress(json.dumps(world.to_compact()).encode()))))
    assert {b.kind for b in back.buildings if b.sector == GOV_SID} == {b.kind for b in world.buildings
                                                                       if b.sector == GOV_SID}
    assert {b.tag for b in back.buildings if b.kind == "ministry"} == {"works", "science"}
