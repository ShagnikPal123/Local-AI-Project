"""The model lineup (Fixer Upper S14, S5): the owner's names, the effort levels, and the plan each pick produces.

No model, network or GPU is touched: the light-model picker and the learned effort chooser are passed in as fakes,
and the saved pick lives in a temp folder.
"""

from __future__ import annotations

import pytest

import model_lineup as lineup


@pytest.fixture(autouse=True)
def _temp_store(monkeypatch, tmp_path):
    monkeypatch.setattr(lineup, "data_path", lambda name: tmp_path / name)


def _no_light(_max_gb):
    return None


def _keep_default(_message, _model_id, default):
    return default, ""


# --- the names are the owner's, in his order ---------------------------------------------------------


def test_every_family_has_the_owners_names_in_order():
    names = {f.id: [m.name for m in f.models] for f in lineup.FAMILIES}
    assert names["pico"] == ["Pulse", "Echo", "Harmonic", "Resonance", "Overtone"]
    assert names["monolith"] == ["Argon", "Boron", "Carbon", "Silicon", "Xenon"]
    assert names["crescendo"] == ["Photon", "Azure", "Radiance", "Nexus", "Abyss", "Eclipse"]
    assert names["zencode"] == ["Bit", "Byte", "Decimal", "Giga", "Exa"]


def test_three_levels_then_the_specialists():
    data = lineup.catalog()
    assert [f["name"] for f in data["levels"]] == ["Pico", "Monolith", "Crescendo"]
    assert [f["used_for"] for f in data["levels"]] == ["Lighter work", "General", "Power-hungry work"]
    assert [f["name"] for f in data["specialists"]] == ["Zencode"]
    assert data["main_model"] == "Big Kahuna"


def test_effort_goes_low_to_aleph():
    assert [e.id for e in lineup.EFFORTS] == ["low", "mid", "normal", "high", "higher", "super", "aleph"]
    assert lineup.effort("aleph").name == "Aleph"


def test_model_ids_never_clash_with_provider_names():
    providers = {"ollama", "identity0", "gemini", "groq", "nvidia", "claude", "openai", "kimi", "deepseek",
                 "perplexity", "qwen", "auto"}
    ids = {m.id for f in lineup.FAMILIES for m in f.models} | {f.id for f in lineup.FAMILIES}
    assert not ids & providers
    assert len(ids) == sum(len(f.models) for f in lineup.FAMILIES) + len(lineup.FAMILIES)


def test_labels_read_family_then_model():
    assert lineup.label("CARBON") == "Monolith · Carbon"
    assert lineup.label("pico") == "Pico · Auto"
    assert lineup.label("gemini") == ""
    assert lineup.is_lineup_id(" Eclipse ") and not lineup.is_lineup_id("gemini")


# --- the pick is remembered ------------------------------------------------------------------------------


def test_pick_and_effort_survive_a_restart():
    assert lineup.state()["pick"] == "" and lineup.state()["effort"] == "auto"
    lineup.save_pick("Carbon")
    lineup.save_effort("high")
    assert lineup.state()["pick"] == "carbon"
    assert lineup.state()["effort"] == "high"
    assert lineup.catalog()["pick_label"] == "Monolith · Carbon"


def test_unknown_names_are_refused_not_saved():
    with pytest.raises(ValueError):
        lineup.save_pick("gemini")
    with pytest.raises(ValueError):
        lineup.save_effort("ludicrous")
    assert lineup.state()["pick"] == ""


def test_a_broken_file_reads_as_auto(tmp_path):
    (tmp_path / "model_lineup.json").write_text("{not json", encoding="utf-8")
    assert lineup.state() == {"pick": "", "effort": "auto",
                              "surfaces": {"whatsapp": {"model": "", "effort": ""}, "voice": {"model": "", "effort": ""}}}


def test_switch_target_only_takes_lineup_names():
    assert lineup.switch_target("gemini") is None
    answer = lineup.switch_target("Nexus")
    assert answer == {"kind": "lineup", "model": "nexus", "preferred": "nexus", "label": "Crescendo · Nexus"}
    assert lineup.state()["pick"] == "nexus"


def test_a_surface_follows_the_chat_unless_it_has_its_own_pick():
    lineup.save_pick("carbon")
    assert lineup.surface_pick("whatsapp") == "carbon"
    lineup.save_surface("whatsapp", "echo", "mid")
    assert lineup.surface_pick("whatsapp") == "echo"
    assert lineup.surface_effort("whatsapp") == "mid"
    assert lineup.surface_pick("voice") == "carbon"
    with pytest.raises(ValueError):
        lineup.save_surface("fax", "echo")


# --- what a pick does to a turn ----------------------------------------------------------------------------


def test_monolith_and_crescendo_are_led_by_big_kahuna():
    for model_id in ("carbon", "radiance"):
        plan = lineup.resolve(model_id, "auto", "hello", light_picker=_no_light, effort_chooser=_keep_default)
        assert plan.prefer == "identity0"


def test_a_models_size_sets_its_default_effort():
    expected = {"argon": "low", "boron": "normal", "carbon": "high", "silicon": "higher", "xenon": "super"}
    for model_id, effort_id in expected.items():
        plan = lineup.resolve(model_id, "auto", "hi", light_picker=_no_light, effort_chooser=_keep_default)
        assert plan.effort == effort_id and plan.effort_auto


def test_the_slider_overrides_the_size():
    plan = lineup.resolve("xenon", "mid", "hi", light_picker=_no_light, effort_chooser=_keep_default)
    assert plan.effort == "mid" and not plan.effort_auto
    assert plan.speed == "auto" and plan.thinking is False and plan.max_steps == 12


def test_low_is_jev_speed_and_aleph_is_the_limit():
    low = lineup.resolve("", "low")
    assert low.speed == "fast" and low.ultrafast and low.consult == "off" and low.max_steps == 6
    aleph = lineup.resolve("", "aleph")
    assert aleph.speed == "full" and aleph.consult == "always" and aleph.max_steps == 64
    assert aleph.upgrade_mode == "auto"


def test_normal_effort_changes_nothing():
    plan = lineup.resolve("", "normal")
    assert (plan.speed, plan.thinking, plan.optimizer, plan.consult, plan.max_steps) == ("auto", None, None, None, None)
    assert plan.prefer is None


def test_pico_answers_quick_turns_from_the_light_model_and_tools_from_big_kahuna():
    asked = []

    def light(max_gb):
        asked.append(max_gb)
        return "ollama", "qwen3:1.7b", "light model qwen3:1.7b (1.4 GB)"

    plan = lineup.resolve("echo", "auto", "hi", light_picker=light, effort_chooser=_keep_default)
    assert asked == [3.5]
    assert (plan.fast_prefer, plan.fast_model) == ("ollama", "qwen3:1.7b")
    assert plan.prefer == "identity0"
    assert "light model qwen3:1.7b (1.4 GB)" in plan.describe()


def test_pico_without_a_light_model_still_answers():
    plan = lineup.resolve("pulse", "auto", "hi", light_picker=_no_light, effort_chooser=_keep_default)
    assert plan.fast_prefer is None and plan.prefer == "identity0"


def test_zencode_uses_the_code_role_and_never_the_toolless_path(monkeypatch):
    monkeypatch.setattr(lineup, "_code_role", lambda: ("nvidia", "some-coder"))
    plan = lineup.resolve("bit", "auto", "fix this", light_picker=_no_light, effort_chooser=_keep_default)
    assert (plan.prefer, plan.prefer_model) == ("nvidia", "some-coder")
    assert plan.effort == "low" and plan.speed == "auto"


def test_a_familys_auto_picks_a_size_from_the_message(monkeypatch):
    monkeypatch.setattr(lineup, "_complexity", lambda message: "complex" if "architecture" in message else "simple")
    quick = lineup.resolve("monolith", "auto", "hi", light_picker=_no_light, effort_chooser=_keep_default)
    deep = lineup.resolve("monolith", "auto", "design the architecture", light_picker=_no_light,
                          effort_chooser=_keep_default)
    assert quick.model_id == "argon" and deep.model_id == "carbon"
    assert "Monolith Auto picked Argon" in quick.describe()


def test_pico_auto_falls_back_to_the_nearest_size(monkeypatch):
    monkeypatch.setattr(lineup, "_complexity", lambda message: "parallel")
    plan = lineup.resolve("pico", "auto", "x", light_picker=_no_light, effort_chooser=_keep_default)
    assert plan.model_id == "resonance"


def test_abyss_lets_learning_pick_the_effort():
    seen = []

    def chooser(message, model_id, default):
        seen.append((model_id, default))
        return "higher", "learned: requests like this needed Higher"

    plan = lineup.resolve("abyss", "auto", "x", light_picker=_no_light, effort_chooser=chooser)
    assert seen == [("abyss", "normal")]
    assert plan.effort == "higher" and "learned" in plan.describe()


def test_a_bad_learned_answer_falls_back_to_normal():
    plan = lineup.resolve("boron", "auto", "x", light_picker=_no_light,
                          effort_chooser=lambda *_: ("warp-speed", ""))
    assert plan.effort == "normal"


def test_unknown_picks_never_stop_a_turn():
    plan = lineup.resolve("not-a-model", "nonsense")
    assert plan.model_id == "" and plan.effort == "normal"


def test_plan_for_turn_leaves_a_hand_picked_provider_alone():
    assert lineup.plan_for_turn("gemini", "hi") is None
    lineup.save_effort("high")
    plan = lineup.plan_for_turn("gemini", "hi")
    assert plan is not None and plan.prefer is None and plan.effort == "high"


def test_plan_for_turn_with_auto_and_auto_effort_is_todays_behaviour():
    assert lineup.plan_for_turn("", "hi") is None
    assert lineup.plan_for_turn(None, "hi") is None


def test_whatsapp_gets_its_own_pick_when_the_turn_has_none(monkeypatch):
    monkeypatch.setattr(lineup, "_default_light_picker", _no_light)
    monkeypatch.setattr(lineup, "_default_effort_chooser", _keep_default)
    lineup.save_surface("whatsapp", "boron", "mid")
    plan = lineup.plan_for_turn(None, "hi", surface="whatsapp")
    assert plan.model_id == "boron" and plan.effort == "mid"


# --- the picker's routes ---------------------------------------------------------------------------------


def test_the_lineup_routes_save_and_refuse_unknown_names():
    from fastapi import HTTPException

    import routes_models

    assert routes_models.model_lineup_catalog()["pick"] == ""
    saved = routes_models.model_lineup_save(routes_models.LineupPick(pick="xenon", effort="aleph"))
    assert saved["pick"] == "xenon" and saved["effort"] == "aleph" and saved["pick_label"] == "Monolith · Xenon"
    with pytest.raises(HTTPException):
        routes_models.model_lineup_save(routes_models.LineupPick(pick="gpt-99"))
