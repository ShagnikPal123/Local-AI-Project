"""The Build studio (Request H4 + the 2026-09-15 follow-up): parts, the shared space, circuits, checks, AI."""

from __future__ import annotations

import json
import math
from types import SimpleNamespace

import pytest

import build_catalog
import design_studio as ds


@pytest.fixture()
def studio(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "_projects_path", lambda: tmp_path / "projects.json")
    monkeypatch.setattr(ds, "_library_path", lambda: tmp_path / "library.json")
    return ds


def _pins(part):
    return {pin["name"]: pin["id"] for pin in part["pins"]}


# --- validation ---------------------------------------------------------------


def test_a_model_s_junk_becomes_a_sane_part_or_a_clear_refusal():
    part = ds.clean_part({
        "name": "x" * 500,
        "kind": "spaceship",
        "color": "red",
        "features": [
            {"type": "box", "op": "cut", "size": {"w": "nan", "d": -4, "h": 1e12}, "at": ["a", 2]},
            {"type": "teapot"},
            "not a feature",
            {"type": "extrude", "profile": [[0, 0], [1, 1]]},  # two points is not an outline
            {"type": "cylinder", "sides": 6, "radial": {"count": 1}},
        ],
        "pins": [{"name": ""}, {"name": "VCC", "kind": "laser", "voltage": 9999}],
    })
    assert len(part["name"]) == 80 and part["kind"] == "mechanical" and part["color"] == "#9aa4b2"
    first, second = part["features"]
    # A tree that starts with a cut would be invisible, so the first shape is always added.
    assert first["op"] == "add"
    assert first["size"] == {"w": 20.0, "d": 20.0, "h": 5000.0}
    assert first["at"] == [0.0, 2.0, 0.0]
    assert second["sides"] == 6 and "radial" not in second
    assert part["pins"] == [{**part["pins"][0], "name": "VCC", "kind": "digital", "voltage": 600.0}]

    with pytest.raises(ds.BuildError):
        ds.clean_part({"features": [{"type": "teapot"}]})


def test_feature_count_is_capped_so_a_runaway_model_cannot_freeze_the_mesher():
    part = ds.clean_part({"features": [{"type": "sphere"} for _ in range(500)]})
    assert len(part["features"]) == ds.MAX_FEATURES


def test_bounds_are_per_axis_so_a_flat_board_is_flat():
    pi = ds.clean_part(build_catalog.expand("raspberry-pi-5"))
    width, height, depth = ds.part_bounds(pi)["size"]
    assert 84 < width < 90 and 55 < depth < 60 and height < 25

    turned = ds.clean_part({"features": [{"type": "box", "size": {"w": 100, "d": 10, "h": 2}, "rot": [0, 90, 0]}]})
    w, _h, d = ds.part_bounds(turned)["size"]
    assert w == pytest.approx(10, abs=0.01) and d == pytest.approx(100, abs=0.01)

    # Cuts never make a part bigger.
    holed = ds.clean_part({"features": [{"type": "box"}, {"type": "sphere", "op": "cut", "size": {"r": 500}}]})
    assert ds.part_bounds(holed)["size"] == [20.0, 20.0, 20.0]


def test_volume_estimate_is_the_right_order_of_magnitude():
    plate = ds.clean_part({"features": [
        {"type": "box", "size": {"w": 100, "d": 50, "h": 4}},
        {"type": "cylinder", "op": "cut", "size": {"r": 2, "h": 4}, "repeat": {"count": 4, "step": [20, 0, 0]}},
    ]})
    expected = 100 * 50 * 4 - 4 * math.pi * 4 * 4
    assert ds.part_volume(plate) == pytest.approx(expected, rel=1e-6)


def test_every_catalog_part_expands_validates_and_keeps_its_pins():
    ids = [entry["id"] for entry in build_catalog.listing()]
    assert len(ids) == len(set(ids)) >= 20
    for catalog_id in ids:
        entry = build_catalog.CATALOG[catalog_id]
        part = ds.clean_part(build_catalog.expand(catalog_id))
        assert part["source"] == "catalog" and part["catalog_id"] == catalog_id
        assert len(part["features"]) == len(entry["features"]), catalog_id
        assert len(part["pins"]) == len(entry.get("pins", [])), catalog_id
        assert all(size > 0 for size in ds.part_bounds(part)["size"]), catalog_id
        assert "Nominal" in part["summary"]


def test_the_pi_header_is_in_physical_pin_order():
    pins = ds.clean_part(build_catalog.expand("raspberry-pi-5"))["pins"]
    assert [p["name"] for p in pins[:6]] == ["1 3V3", "2 5V", "3 GPIO2 SDA", "4 5V", "5 GPIO3 SCL", "6 GND"]
    # Odd pins share a row, even pins the other, 2.54 mm apart.
    assert pins[0]["at"][2] != pins[1]["at"][2]
    assert pins[2]["at"][0] - pins[0]["at"][0] == pytest.approx(2.54)


def test_search_finds_a_part_by_how_someone_would_say_it():
    assert build_catalog.search("raspberry pi 5")[0]["id"] == "raspberry-pi-5"
    assert any(hit["id"] == "fan-40mm" for hit in build_catalog.search("cooling fan"))


# --- the shared space -----------------------------------------------------------


def test_placed_parts_sit_on_the_plate_beside_each_other(studio):
    project = studio.create_project("AI box")
    for catalog_id in ("raspberry-pi-5", "fan-40mm", "psu-5v-5a", "breadboard-830"):
        project, _part, _placement = studio.use_catalog_part(project["id"], catalog_id)
    boxes = [studio.placement_box(project, p) for p in project["placements"]]
    assert all(box["min"][1] == pytest.approx(0.0, abs=0.01) for box in boxes)
    checks = studio.check_project(project)
    assert not [c for c in checks if "overlap" in c["message"] or "below the base" in c["message"]], checks


def test_the_same_catalog_part_twice_is_one_definition_two_placements(studio):
    project = studio.create_project("Fans")
    project, first, _ = studio.use_catalog_part(project["id"], "fan-40mm")
    project, second, _ = studio.use_catalog_part(project["id"], "fan-40mm")
    assert first["id"] == second["id"]
    assert len(project["parts"]) == 1 and len(project["placements"]) == 2
    assert studio.bom(project)["lines"][0]["quantity"] == 2


def test_outside_the_space_and_overlaps_are_reported(studio):
    project = studio.create_project("Crowded")
    project, part = studio.save_part(project["id"], {"features": [{"type": "box", "size": {"w": 50, "d": 50, "h": 50}}]})
    project, a = studio.place_part(project["id"], part["id"], at=[0, 25, 0])
    project, b = studio.place_part(project["id"], part["id"], at=[10, 25, 0])
    project, c = studio.place_part(project["id"], part["id"], at=[400, 25, 0])
    messages = [f["message"] for f in studio.check_project(project)]
    assert any("overlap" in m for m in messages)
    assert any("sticks out" in m for m in messages)

    # Bolted together on purpose: the overlap becomes a note, not a warning.
    project, _joint = studio.add_joint(project["id"], a["id"], b["id"], "screw")
    overlap = [f for f in studio.check_project(project) if "overlap" in f["message"]]
    assert overlap and overlap[0]["level"] == "info"


def test_deleting_a_part_removes_its_placements_joints_and_wires(studio):
    project = studio.create_project("Cascade")
    project, psu, psu_at = studio.use_catalog_part(project["id"], "psu-5v-5a")
    project, fan, fan_at = studio.use_catalog_part(project["id"], "fan-40mm")
    project, _ = studio.connect(project["id"], psu_at["id"], _pins(psu)["5V out"], fan_at["id"], _pins(fan)["+5V"])
    project, _ = studio.add_joint(project["id"], psu_at["id"], fan_at["id"])
    project = studio.delete_part(project["id"], fan["id"])
    assert [p["id"] for p in project["parts"]] == [psu["id"]]
    assert len(project["placements"]) == 1 and project["joints"] == []
    assert all(pt["placement"] != fan_at["id"] for net in project["nets"] for pt in net["points"])


# --- circuits -------------------------------------------------------------------


def test_connecting_into_a_wire_joins_that_net(studio):
    project = studio.create_project("Rails")
    project, psu, psu_at = studio.use_catalog_part(project["id"], "psu-5v-5a")
    project, pi, pi_at = studio.use_catalog_part(project["id"], "raspberry-pi-5")
    project, fan, fan_at = studio.use_catalog_part(project["id"], "fan-40mm")
    project, first = studio.connect(project["id"], psu_at["id"], _pins(psu)["5V out"], pi_at["id"], _pins(pi)["2 5V"])
    project, second = studio.connect(project["id"], fan_at["id"], _pins(fan)["+5V"], psu_at["id"], _pins(psu)["5V out"])
    assert first["id"] == second["id"]
    assert len(project["nets"]) == 1 and len(project["nets"][0]["points"]) == 3
    assert project["nets"][0]["kind"] == "power" and project["nets"][0]["voltage"] == 5.0


def test_a_short_two_drivers_and_mixed_voltages_are_errors(studio):
    project = studio.create_project("Mistakes")
    project, psu, psu_at = studio.use_catalog_part(project["id"], "psu-5v-5a")
    project, buck, buck_at = studio.use_catalog_part(project["id"], "buck-lm2596")
    project, pi, pi_at = studio.use_catalog_part(project["id"], "raspberry-pi-5")

    # 5 V straight into ground on the same supply.
    project, _ = studio.connect(project["id"], psu_at["id"], _pins(psu)["5V out"], psu_at["id"], _pins(psu)["GND out"])
    # The buck's 5 V output onto the Pi's 3.3 V rail...
    project, _ = studio.connect(project["id"], buck_at["id"], _pins(buck)["OUT+"], pi_at["id"], _pins(pi)["1 3V3"])
    # ...and then the supply's output onto that same rail: two drivers, mixed voltages.
    project, _ = studio.connect(project["id"], pi_at["id"], _pins(pi)["1 3V3"], buck_at["id"], _pins(buck)["OUT+"])
    project, _ = studio.connect(project["id"], psu_at["id"], _pins(psu)["5V out"], pi_at["id"], _pins(pi)["1 3V3"])

    findings = studio.check_project(project)
    errors = [f["message"] for f in findings if f["level"] == "error"]
    assert any("short" in m for m in errors), findings
    assert any("outputs driving" in m for m in errors), findings
    assert any("mixes" in f["message"] for f in findings), findings
    assert findings[0]["level"] == "error"  # errors sort first


def test_a_supply_that_is_too_small_is_reported(studio):
    project = studio.create_project("Hungry")
    project, cell, cell_at = studio.use_catalog_part(project["id"], "lipo-2000")
    project, servo, _ = studio.use_catalog_part(project["id"], "servo-sg90")
    for _ in range(3):
        project, _extra, extra_at = studio.use_catalog_part(project["id"], "servo-sg90")
        project, _ = studio.connect(project["id"], cell_at["id"], _pins(cell)["B+"], extra_at["id"], _pins(servo)["+5V (red)"])
    messages = [f["message"] for f in studio.check_project(project)]
    assert any("mA of load" in m for m in messages), messages


def test_floating_required_pins_and_a_missing_supply_are_pointed_out(studio):
    project = studio.create_project("Floating")
    project, _led, led_at = studio.use_catalog_part(project["id"], "led-5mm")
    findings = studio.check_project(project)
    assert any(f["where"].get("id") == led_at["id"] and "needs" in f["message"] for f in findings)
    assert any("supplies power" in f["message"] for f in findings)


def test_disconnect_removes_one_pin_or_the_whole_net(studio):
    project = studio.create_project("Unwire")
    project, psu, psu_at = studio.use_catalog_part(project["id"], "psu-5v-5a")
    project, fan, fan_at = studio.use_catalog_part(project["id"], "fan-40mm")
    project, pi, pi_at = studio.use_catalog_part(project["id"], "raspberry-pi-5")
    project, net = studio.connect(project["id"], psu_at["id"], _pins(psu)["5V out"], fan_at["id"], _pins(fan)["+5V"])
    project, net = studio.connect(project["id"], psu_at["id"], _pins(psu)["5V out"], pi_at["id"], _pins(pi)["2 5V"])
    project = studio.disconnect(project["id"], net["id"], fan_at["id"], _pins(fan)["+5V"])
    assert len(project["nets"][0]["points"]) == 2
    project = studio.disconnect(project["id"], net["id"])
    assert project["nets"] == []


def test_wrong_pins_are_refused_with_a_sentence(studio):
    project = studio.create_project("Refusals")
    project, fan, fan_at = studio.use_catalog_part(project["id"], "fan-40mm")
    with pytest.raises(ds.BuildError, match="no pin"):
        studio.connect(project["id"], fan_at["id"], "nope", fan_at["id"], _pins(fan)["GND"])
    with pytest.raises(ds.BuildError, match="same pin"):
        studio.connect(project["id"], fan_at["id"], _pins(fan)["GND"], fan_at["id"], _pins(fan)["GND"])


# --- saving and reusing ---------------------------------------------------------


def test_a_saved_part_can_be_dropped_into_another_build(studio):
    first = studio.create_project("Where it was drawn")
    first, bracket = studio.save_part(first["id"], {"name": "Bracket", "material": "PETG", "features": [
        {"type": "box", "size": {"w": 40, "d": 20, "h": 3}},
        {"type": "cylinder", "op": "cut", "size": {"r": 1.7, "h": 3}, "at": [-15, 0, 0], "mirror": ["x"]},
    ]})
    saved = studio.library_save(bracket)
    assert [p["name"] for p in studio.library()] == ["Bracket"]
    studio.library_save(bracket)  # re-saving the same part does not make a second copy
    assert len(studio.library()) == 1

    second = studio.create_project("Where it is used")
    second, copied, placement = studio.use_library_part(second["id"], saved["id"])
    assert copied["id"] != bracket["id"] and copied["features"][1]["mirror"] == ["x"]
    assert placement["part_id"] == copied["id"]
    report = studio.print_report(second)
    assert report[0]["name"] == "Bracket" and report[0]["fits"] and report[0]["grams"] > 0


def test_tutorials_keep_only_steps_with_something_to_say():
    tutorial = ds.clean_tutorial({"steps": [
        {"title": "", "body": ""},
        {"title": "Base", "body": "Start here.", "focus": {"kind": "placement", "id": "pl1"}, "tips": ["a", "", "b"]},
        {"body": "No title still counts.", "focus": {"kind": "rocket"}},
    ]})
    assert [s["title"] for s in tutorial["steps"]] == ["Base", "Step"]
    assert tutorial["steps"][0]["tips"] == ["a", "b"] and tutorial["steps"][1]["focus"]["kind"] == "none"
    assert ds.clean_tutorial({"steps": []}) is None


def test_projects_survive_a_reload_and_delete_cleanly(studio):
    project = studio.create_project("Persist", "Keep it")
    studio.update_project(project["id"], space={"width": 220, "depth": 220, "height": 250}, name="Renamed")
    reloaded = studio.get_project(project["id"])
    assert reloaded["name"] == "Renamed" and reloaded["space"]["height"] == 250
    assert studio.list_projects()["active"] == project["id"]
    assert studio.delete_project(project["id"]) and studio.get_project(project["id"]) is None


# --- the AI side, with a scripted model ----------------------------------------


class ScriptedModel:
    """Answers in order; records every prompt so tests can see what was asked."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def run(self, role, prompt, **kwargs):
        self.prompts.append((role, prompt))
        answer = self.answers.pop(0) if self.answers else "{}"
        return SimpleNamespace(text=answer if isinstance(answer, str) else json.dumps(answer), label="Test model")


@pytest.fixture()
def model(monkeypatch):
    import model_roles

    scripted = ScriptedModel()
    monkeypatch.setattr(model_roles.MODEL_ROLES, "run", scripted.run)
    return scripted


def test_draw_part_validates_whatever_the_model_sends(model):
    import build_ai

    model.answers.append("Sure! ```json\n" + json.dumps({"part": {"name": "Clip", "features": [
        {"type": "wedge", "size": {"w": 10, "d": 5, "h": 8}, "note": "The hook."},
        {"type": "banana"},
    ]}}) + "\n```")
    result = build_ai.draw_part("a small clip")
    assert result["part"]["name"] == "Clip" and len(result["part"]["features"]) == 1
    assert result["part"]["source"] == "ai" and result["model"] == "Test model"
    assert model.prompts[0][0] == "build_studio" and "Y UP" in model.prompts[0][1]


def test_the_tutorial_points_only_at_things_that_exist(studio, model):
    import build_ai

    project = studio.create_project("Explain me")
    project, pi, pi_at = studio.use_catalog_part(project["id"], "raspberry-pi-5")
    model.answers.append({"title": "Build", "steps": [
        {"title": "The Pi", "body": "The brain.", "focus": {"kind": "placement", "id": pi_at["id"]}},
        {"title": "By part id", "body": "Same thing.", "focus": {"kind": "part", "id": pi["id"]}},
        {"title": "Imaginary", "body": "Does not exist.", "focus": {"kind": "placement", "id": "ghost"}},
        {"title": "General", "body": "No focus."},
    ]})
    tutorial = build_ai.tutorial_for(project)["tutorial"]
    assert [s["title"] for s in tutorial["steps"]] == ["The Pi", "By part id", "General"]
    assert tutorial["steps"][1]["focus"] == {"kind": "placement", "id": pi_at["id"], "part_id": pi["id"]}


def test_wiring_proposals_resolve_pin_names_and_drop_the_rest(studio, model):
    import build_ai

    project = studio.create_project("Wire me")
    project, psu, psu_at = studio.use_catalog_part(project["id"], "psu-5v-5a")
    project, fan, fan_at = studio.use_catalog_part(project["id"], "fan-40mm")
    model.answers.append({"connections": [
        {"from": {"placement": psu_at["id"], "pin": "5v out"}, "to": {"placement": fan_at["id"], "pin": "+5V"}, "name": "Fan power"},
        {"from": {"placement": psu_at["id"], "pin": "GND out"}, "to": {"placement": fan_at["id"], "pin": "gnd"}},
        {"from": {"placement": "ghost", "pin": "x"}, "to": {"placement": fan_at["id"], "pin": "PWM"}},
    ], "notes": "Add a flyback diode if you swap in a motor."})
    result = build_ai.wiring_for(project)
    assert [c["name"] for c in result["connections"]][0] == "Fan power"
    assert len(result["connections"]) == 2 and "diode" in result["notes"]
    # Proposals are not applied until the owner says so.
    assert studio.get_project(project["id"])["nets"] == []


def test_an_apparatus_job_writes_into_the_build_phase_by_phase(studio, model, monkeypatch, tmp_path):
    import build_ai

    monkeypatch.setattr(build_ai, "_jobs_path", lambda: tmp_path / "jobs.json")
    monkeypatch.setattr("agent_events.publish_ui", lambda *a, **k: None)
    project = studio.create_project("Containment")
    model.answers.extend([
        {"understanding": "A ventilated box for a Pi.", "structure": ["a base plate"], "electronics": ["a pi", "a fan"],
         "space_mm": {"width": 250, "depth": 250, "height": 200}},
        {"picks": [{"catalog_id": "raspberry-pi-5", "quantity": 1}, {"catalog_id": "fan-40mm", "quantity": 1},
                   {"catalog_id": "not-real", "quantity": 3}], "missing": ["thermal pad"]},
        {"name": "Base plate", "features": [{"type": "box", "size": {"w": 200, "d": 150, "h": 4}}]},
        {"placements": []},
        {"connections": []},
        {"steps": [{"title": "Start", "body": "Lay the plate down."}]},
        "**Will it work** Probably.",
    ])
    job = {"id": "job1", "project_id": project["id"], "brief": "containment for the AI", "state": "running",
           "phase": "plan", "phase_label": "", "progress": 0.0, "message": "", "steps": [], "started_at": 1e12,
           "ended_at": 0.0, "budget_minutes": 30, "model": ""}
    build_ai._put_job(job)
    build_ai._STOPS["job1"] = __import__("threading").Event()
    build_ai._work("job1", build_ai._STOPS["job1"])

    finished = build_ai._get_job("job1")
    assert finished["state"] == "done", finished["message"]
    built = studio.get_project(project["id"])
    assert {p["name"] for p in built["parts"]} >= {"Raspberry Pi 5 (8 GB)", "40 mm fan", "Base plate"}
    assert built["space"]["height"] == 200 and built["tutorial"]["steps"][0]["title"] == "Start"
    assert any("Could not wire" in s["text"] for s in finished["steps"])  # no connections is reported, not hidden


def test_a_job_interrupted_by_a_restart_says_so(monkeypatch, tmp_path):
    import build_ai

    monkeypatch.setattr(build_ai, "_jobs_path", lambda: tmp_path / "jobs.json")
    monkeypatch.setattr("agent_events.publish_ui", lambda *a, **k: None)
    build_ai._put_job({"id": "old", "project_id": "p", "brief": "x", "state": "running", "phase": "parts",
                       "progress": 0.3, "message": "", "steps": []})
    assert build_ai.jobs_for("p")[0]["state"] == "interrupted"


# --- routes -----------------------------------------------------------------------


def test_the_routes_build_a_wired_project_end_to_end(studio, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import routes_build
    import server_auth

    app = FastAPI()
    app.include_router(routes_build.router)
    app.dependency_overrides[server_auth.require_session] = lambda: None
    client = TestClient(app)

    created = client.post("/api/build/projects", json={"name": "Route test"}).json()
    project_id = created["project"]["id"]
    psu = client.post(f"/api/build/projects/{project_id}/place", json={"catalog_id": "psu-5v-5a"}).json()
    fan = client.post(f"/api/build/projects/{project_id}/place", json={"catalog_id": "fan-40mm"}).json()
    wired = client.post(f"/api/build/projects/{project_id}/connect", json={
        "from_placement": psu["placement"]["id"], "from_pin": _pins(psu["part"])["5V out"],
        "to_placement": fan["placement"]["id"], "to_pin": _pins(fan["part"])["+5V"],
    })
    assert wired.status_code == 200
    body = wired.json()
    assert len(body["project"]["nets"]) == 1 and "checks" in body and "bom" in body and "bounds" in body

    refused = client.post(f"/api/build/projects/{project_id}/place", json={"catalog_id": "warp-drive"})
    assert refused.status_code == 400 and "catalog" in refused.json()["detail"]
    unknown = client.post(f"/api/build/projects/{project_id}/ask", json={"action": "teleport"})
    assert unknown.status_code == 400
    assert client.get("/api/build/projects/nope").status_code == 404
    assert len(client.get("/api/build/catalog").json()["parts"]) >= 20
