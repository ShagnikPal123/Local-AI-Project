"""Notch looks (notch_looks.py): imported looks are data only, checked value by value, and can carry when the notch
opens. Nothing touches the owner's real settings."""

import json

import pytest

import notch_looks as nl


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    import equalize_assistant

    monkeypatch.setattr(nl, "STORE", tmp_path / "looks.json")
    monkeypatch.setattr(equalize_assistant, "STORE", tmp_path / "assistant.json")


def test_built_in_looks_and_the_default():
    state = nl.looks()
    assert state["active"]["id"] == "coucou" and {"midnight", "ember", "terminal"} <= {l["id"] for l in state["looks"]}
    for look in nl.BUILT_IN:
        assert nl.clean(look)["colors"] == {k: v.upper() for k, v in look["colors"].items()}  # built-ins pass their own check


def test_hostile_values_never_get_through():
    look = nl.clean({"name": "<script>Evil</script>", "colors": {"island": "#123456", "card": "red; background:url(x)",
                     "ink": "expression(alert(1))"}, "radius": {"closed": 999, "open": -4}, "width": 99999,
                     "font": "Comic Sans'; }", "css": "body{display:none}", "onload": "alert(1)"})
    assert look["name"] == "scriptEvil/script"
    assert look["colors"]["island"] == "#123456" and look["colors"]["card"] == nl.BUILT_IN[0]["colors"]["card"].upper()
    assert look["radius"] == {"closed": 24, "open": 0} and look["width"] == 760 and look["font"] == "system"
    assert "css" not in look and "onload" not in look


@pytest.mark.parametrize("raw", ["not json", "[]", {"colors": {"island": "#000000"}}, {"name": "No colours"}])
def test_unusable_files_are_refused(raw):
    with pytest.raises(ValueError):
        nl.clean(raw)


def test_import_switches_to_it_and_brings_its_activation():
    import equalize_assistant

    shared = json.dumps({"name": "Lazy", "colors": {"island": "#101820"},
                         "activation": {"open_on_hover": False, "autoclose_s": 3, "hover_delay_ms": 9000}})
    state = nl.import_look(shared)
    assert state["active"]["name"] == "Lazy"
    assert state["active"]["activation"] == {"open_on_hover": False, "autoclose_s": 5, "hover_delay_ms": 3000}
    notch = equalize_assistant.settings()["notch"]
    assert notch["open_on_hover"] is False and notch["autoclose_s"] == 5


def test_a_taken_id_gets_its_own_and_export_round_trips():
    state = nl.import_look({"id": "coucou", "name": "Copy", "colors": {"accent": "#FF00AA"}})
    mine = state["active"]
    assert mine["id"].startswith("coucou-") and mine["id"] != "coucou"
    exported = nl.export(mine["id"])
    assert exported["format"] == "ichos-notch-look/1" and "built_in" not in exported
    assert nl.clean(exported)["colors"]["accent"] == "#FF00AA"


def test_use_and_remove():
    mine = nl.import_look({"name": "Mine", "colors": {"island": "#222222"}})["active"]["id"]
    assert nl.use("ember")["active"]["id"] == "ember"
    nl.use(mine)
    assert nl.remove(mine)["active"]["id"] == "coucou"
    with pytest.raises(ValueError):
        nl.use("nope")
