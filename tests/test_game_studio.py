"""Game Studio: a game is validated data, the tab plays it, Unity gets fixed C# plus JSON (Request H5)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import game_studio
import spec_ai


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(game_studio, "_path", lambda: tmp_path / "games" / "games.json")


@pytest.fixture()
def client():
    import server

    return TestClient(server.app, client=("127.0.0.1", 50004))


def _fake_model(monkeypatch, *replies):
    queue = list(replies)
    calls = []

    def ask(system, prompt, **_kwargs):
        calls.append(prompt)
        return queue.pop(0)

    monkeypatch.setattr(spec_ai, "ask_json", ask)
    return calls


def test_validation_keeps_only_the_grammar():
    game = game_studio.validate_game({
        "title": "Test", "kind": "4d", "template": "mmo",
        "player": {"speed": 999, "jump": -3, "max_jumps": 9, "colour": "red; background:url(x)"},
        "enemies": [{"id": "bat", "name": "Bat", "behaviour": "teleport", "health": 10_000}],
        "abilities": [{"id": "wings", "name": "Wings", "gives": "fly_forever"}],
        "rooms": [
            {"id": "a", "tiles": ["#<script>#", "#P..X..D#", "#########"],
             "spawns": [{"enemy": "bat", "x": 3, "y": 1}, {"enemy": "dragon", "x": 2, "y": 1}],
             "items": [{"kind": "ability", "ability": "wings", "x": 4, "y": 1},
                       {"kind": "ability", "ability": "missing", "x": 5, "y": 1}],
             "doors": [{"to": "b", "x": 7, "y": 1}, {"to": "a", "x": 1, "y": 1}, {"to": "nowhere", "x": 2, "y": 1}]},
            {"id": "b", "tiles": ["####", "#P.#", "####"]},
        ],
    })
    assert game["kind"] == "2d" and game["template"] == "metroidvania"
    assert game["player"]["speed"] == 30 and game["player"]["jump"] == 4 and game["player"]["max_jumps"] == 3
    assert game["player"]["colour"] == "#a594ff"
    assert game["enemies"][0]["behaviour"] == "patrol" and game["enemies"][0]["health"] == 200
    assert game["abilities"][0]["gives"] == "none"
    room = game["rooms"][0]
    assert all(set(row) <= game_studio.TILES for row in room["tiles"])
    assert len({len(row) for row in room["tiles"]}) == 1
    assert [spawn["enemy"] for spawn in room["spawns"]] == ["bat"]
    assert [item["ability"] for item in room["items"]] == ["wings"]
    assert [door["to"] for door in room["doors"]] == ["b"]


def test_a_new_game_is_playable_straight_away():
    game = game_studio.create("Hollow Depths")
    assert len(game["rooms"]) == 2
    first, second = game["rooms"]
    assert any("P" in row for row in first["tiles"])
    assert first["doors"][0]["to"] == second["id"] and second["doors"][0]["to"] == first["id"]
    assert game_studio.games()[0]["title"] == "Hollow Depths"


def test_the_model_designs_data_and_code_it_sends_is_just_text(monkeypatch):
    game = game_studio.create("Knightfall", kind="3d")
    _fake_model(monkeypatch, {
        "title": "Knightfall", "kind": "2d", "onLoad": "fetch('http://evil')",
        "player": {"name": "Knight", "dash": True},
        "enemies": [{"id": "husk", "name": "Husk", "behaviour": "chaser"}],
        "rooms": [{"id": "crossroads", "name": "Crossroads", "tiles": ["#######", "#P....#", "#######"],
                   "spawns": [{"enemy": "husk", "x": 4, "y": 1}], "script": "import os"}],
    })
    designed = game_studio.design(game["id"], "a sad knight")
    assert designed["kind"] == "3d", "the owner picked 3D; the model does not get to change it"
    assert "onLoad" not in designed and "script" not in designed["rooms"][0]
    assert designed["rooms"][0]["spawns"][0]["enemy"] == "husk"
    assert game_studio.get(game["id"])["player"]["name"] == "Knight"


def test_a_design_with_no_playable_room_is_refused(monkeypatch):
    game = game_studio.create("Empty")
    _fake_model(monkeypatch, {"title": "Empty", "rooms": [{"tiles": []}]}, {"title": "Empty", "rooms": []})
    with pytest.raises(game_studio.GameError):
        game_studio.design(game["id"], "nothing")
    assert len(game_studio.get(game["id"])["rooms"]) == 2, "a failed design leaves the game as it was"


def test_a_new_room_is_connected_both_ways(monkeypatch):
    game = game_studio.create("Rooms")
    last = game["rooms"][-1]["id"]
    _fake_model(monkeypatch, {"rooms": [{"id": "shaft", "name": "The shaft",
                                         "tiles": ["#....#", "#D..P#", "######"],
                                         "doors": [{"to": last, "x": 1, "y": 1}]}]})
    grown = game_studio.add_room(game["id"], "a tall shaft")
    shaft = grown["rooms"][-1]
    assert shaft["id"] == "shaft" and shaft["doors"][0]["to"] == last
    previous = next(room for room in grown["rooms"] if room["id"] == last)
    assert any(door["to"] == "shaft" for door in previous["doors"])


def test_unity_export_is_fixed_csharp_plus_the_spec_as_json(monkeypatch):
    game = game_studio.update(game_studio.create("Unity Test")["id"],
                              {"notes": "public class Evil : MonoBehaviour { void Start() { System.IO.File.Delete(\"x\"); } }"})
    files = {item["path"]: item["text"] for item in game_studio.unity_files(game["id"])}
    assert set(files) == {
        "Assets/UnityTest/NyxLevel.json", "Assets/UnityTest/README.md",
        "Assets/UnityTest/Scripts/GameSpec.cs", "Assets/UnityTest/Scripts/LevelBuilder.cs",
        "Assets/UnityTest/Scripts/PlayerController2D.cs", "Assets/UnityTest/Scripts/EnemyController.cs",
    }
    for path, text in files.items():
        if path.endswith(".cs"):
            assert "Evil" not in text, "nothing a model or owner typed is written into C#"
    assert json.loads(files["Assets/UnityTest/NyxLevel.json"])["title"] == "Unity Test"

    written = []
    import code_workspace

    monkeypatch.setattr(code_workspace, "create_file", lambda path, text="": written.append(path))
    result = game_studio.export_to_folder(game["id"], "C:/Games/Proj/")
    assert result["files"] and written[0].startswith("C:/Games/Proj/Assets/UnityTest/")


def test_routes_create_edit_and_delete(client):
    made = client.post("/api/games", json={"title": "Route Game", "kind": "2d"})
    assert made.status_code == 200, made.text
    game = made.json()["game"]
    assert client.get("/api/games").json()["games"][0]["id"] == game["id"]
    edited = client.patch(f"/api/games/{game['id']}", json={"changes": {"player": {"speed": 500}}})
    assert edited.status_code == 200 and edited.json()["game"]["player"]["speed"] == 30
    assert client.get(f"/api/games/{game['id']}/unity").json()["files"]
    assert client.delete(f"/api/games/{game['id']}").status_code == 200
    assert client.get(f"/api/games/{game['id']}").status_code == 404


def test_the_chat_can_make_a_game(monkeypatch):
    from tools import ToolRegistry
    import routes_game

    registry = ToolRegistry()
    routes_game.register_game_tools(registry)
    text = registry.tools["game_create"].handler(title="Chat Game", kind="3d")
    assert "Chat Game" in text and "Game Studio" in text
    assert game_studio.games()[0]["kind"] == "3d"
    assert "Chat Game" in registry.tools["game_list"].handler()


def test_json_is_pulled_out_of_a_chatty_reply():
    assert spec_ai.json_from('Sure! ```json\n{"a": 1}\n``` hope that helps')["a"] == 1
    assert spec_ai.json_from('Here: {"rooms": []} done')["rooms"] == []
    with pytest.raises(spec_ai.SpecAIError):
        spec_ai.json_from("no json here")


def test_a_failing_model_hands_over_to_the_next_one(monkeypatch):
    """NVIDIA answered 503 to a live design on 2026-09-16; the next configured model must get the job."""
    import model_hub

    monkeypatch.setattr(spec_ai, "candidates", lambda: [("nvidia", "n"), ("gemini", "g")])
    asked = []

    def complete(provider, model, prompt, **_kwargs):
        asked.append(provider)
        if provider == "nvidia":
            raise model_hub.ModelCallError("nvidia answered 503: Service temporarily overloaded")
        return model_hub.ModelReply(text='{"rooms": []}', provider=provider, model=model, ms=1, usage={})

    monkeypatch.setattr(model_hub, "complete", complete)
    assert spec_ai.ask_json("system", "prompt", timeout=60) == {"rooms": []}
    assert asked == ["nvidia", "gemini"]


def test_when_every_model_fails_the_reason_is_said_and_no_half_game_is_left(monkeypatch):
    import model_hub

    monkeypatch.setattr(spec_ai, "candidates", lambda: [("nvidia", "n")])
    monkeypatch.setattr(model_hub, "complete", lambda *a, **k: (_ for _ in ()).throw(model_hub.ModelCallError("503 overloaded")))
    with pytest.raises(game_studio.GameError) as refused:
        game_studio.create_designed("Cavern", "a glowing cave")
    assert "503 overloaded" in str(refused.value)
    assert game_studio.games() == []


def test_common_shapes_from_a_model_still_make_a_playable_game(monkeypatch):
    game = game_studio.create("Shapes")
    _fake_model(monkeypatch, {"game": {"title": "Shapes", "levels": [
        {"id": "cave", "name": "Cave", "map": [list("#######"), list("#.....#"), list("#######")]},
    ]}})
    designed = game_studio.design(game["id"], "a cave")
    room = designed["rooms"][0]
    assert room["id"] == "cave" and room["tiles"][0] == "#######"
    assert any("P" in row for row in room["tiles"]), "a start is placed on open ground when the model forgets one"


def test_an_unusable_first_answer_gets_one_corrective_retry(monkeypatch):
    game = game_studio.create("Retry")
    calls = _fake_model(monkeypatch, {"title": "Retry", "rooms": [{"tiles": "......"}]},
                        {"title": "Retry", "rooms": [{"id": "ok", "tiles": ["#####", "#P..#", "#####"]}]})
    designed = game_studio.design(game["id"], "anything")
    assert designed["rooms"][0]["id"] == "ok"
    assert len(calls) == 2 and "no usable room" in calls[1]
