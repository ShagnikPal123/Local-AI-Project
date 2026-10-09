"""One small file per world (U40): compact on disk, exact when read back, never destroyed."""

import gzip
import json

import pytest

from world import genome, store
from world.state import Bot, Building, Grave, Law, Project, Sector, War, World


@pytest.fixture
def root(tmp_path):
    store.use_root(tmp_path / "worlds")
    yield tmp_path / "worlds"
    store.use_root(None)


def _big_world(bots=300):
    world = World(id="wld-big", name="Big world", goal="Build a whole product", seed=3)
    for index in range(12):
        sid = f"sec-{index:02d}"
        world.sectors[sid] = Sector(sid=sid, name=f"Sector {index}", lat=index, lon=-index, kind="lab",
                                    gov=f"Sector {index} Council", important=index == 0)
    world.tables["roles"] = ["top-manager", "manager", "coder", "researcher"]
    world.tables["members"] = ["fake:m1", "fake:m2"]
    for index in range(bots):
        code = genome.encode(generation=index % 3, role=index % 4, rank=index % 3 - 1, model=index % 2, skills=[1, 2, 5])
        world.bots[f"agt-{index:05d}"] = Bot(aid=f"agt-{index:05d}", code=code, born_day=index / 10,
                                             name=f"Coder #{index}", role="Coder", sector=f"sec-{index % 12:02d}",
                                             state="asleep" if index % 5 == 0 else "awake")
    for index in range(200):
        world.buildings.append(Building(bid=index + 1, sector=f"sec-{index % 12:02d}", kind="lab", floors=index % 9 + 1,
                                        era=index % 3, plot=index % 20, state="standing", progress=1.0))
    world.laws.append(Law(lid=1, text="Every report names its sources.", status="enforced", sector=""))
    world.wars.append(War(wid="war-1", a="sec-01", b="sec-02", a_stance="Use a queue", b_stance="Use a cron job",
                          reason="How jobs run", cases={"a": "Queues scale."}))
    world.graves.append(Grave(gid=1, aid="agt-gone", name="Old Coder", role="Coder", sector="Sector 1", born_day=1,
                              died_day=40, epitaph="Idle for three jobs.", code=genome.encode(generation=0, role=2)))
    world.projects.append(Project(n=1, title="Survey", status="done", summary="Wrote the plan."))
    for index in range(600):
        world.log("note", f"Something happened, number {index}.")
    return world


def test_a_300_bot_world_is_one_small_file_that_reads_back_exactly(root):
    world = _big_world()

    path = store.save(world)

    assert path.parent == root and path.suffix == ".world" and list(root.glob("*.world")) == [path]
    assert path.stat().st_size < 40_000, f"{path.stat().st_size} bytes"
    raw = json.loads(gzip.decompress(path.read_bytes()))
    assert isinstance(raw["B"][0], list), "rows are arrays, not named records"
    assert len(raw["E"]) == 400, "the timeline is capped"

    back = store.load(world.id)
    assert back.bots["agt-00007"].code == world.bots["agt-00007"].code
    assert back.bots["agt-00005"].state == "asleep" and back.bots["agt-00007"].sector == "sec-07"
    assert back.buildings[5].floors == world.buildings[5].floors and back.buildings[5].sector == "sec-05"
    assert back.wars[0].a == "sec-01" and back.wars[0].cases == {"a": "Queues scale."}
    assert back.graves[0].epitaph == "Idle for three jobs." and back.laws[0].status == "enforced"
    assert back.sectors["sec-00"].important and back.tables["roles"][2] == "coder"


def test_a_running_world_comes_back_paused_and_says_why(root):
    world = _big_world(bots=3)
    world.status = "running"
    world.projects.append(Project(n=2, title="Build", status="running"))
    store.save(world)

    back = store.load(world.id)

    assert back.status == "paused" and "Resume" in back.note
    assert back.projects[-1].status == "stopped"


def test_the_lobby_lists_worlds_and_deleting_moves_the_file_to_trash(root):
    first = World(id="wld-one", name="First")
    second = World(id="wld-two", name="Second")
    store.save(first)
    store.save(second)

    names = {row["name"] for row in store.worlds()}
    assert names == {"First", "Second"}

    where = store.trash("wld-one")

    assert "/.trash/" in where.replace("\\", "/") and (root / ".trash").exists()
    assert {row["name"] for row in store.worlds()} == {"Second"}


def test_names_are_made_safe_for_windows_and_never_collide(root):
    a = World(id="wld-a", name='Moon: base / "one"')
    b = World(id="wld-b", name='Moon: base / "one"')

    store.save(a)
    store.save(b)

    assert a.name == "Moon base one" and b.name == "Moon base one (2)"
    store.rename(a, "Lunar")
    assert store.load("wld-a").name == "Lunar"
