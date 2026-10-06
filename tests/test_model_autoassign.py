"""Auto-assign (Update 1 U29): Nyx picks the model for each job — free, explained, previewed, undoable."""

from __future__ import annotations

import pytest

import model_autoassign as auto
import model_hub
import model_roles
from model_roles import ModelRoleStore

FREE = {"gemini": True, "nvidia": True, "groq": True, "pollinations": True}


@pytest.fixture()
def roles(tmp_path, monkeypatch):
    fresh = ModelRoleStore(tmp_path / "model_roles.json")
    monkeypatch.setattr(model_roles, "MODEL_ROLES", fresh)
    monkeypatch.setattr(auto, "_undo_path", lambda: tmp_path / "undo.json")
    monkeypatch.setattr(auto, "_live_ids", lambda provider: None)  # no network: trust the notes
    monkeypatch.setattr(auto, "_owner_pick", lambda: "")
    monkeypatch.setattr(model_hub, "list_models", lambda provider, refresh=False: [])
    monkeypatch.setattr(model_hub, "is_configured", lambda provider: FREE.get(provider, False))
    return fresh


def _plan(**kw):
    kw.setdefault("configured", FREE)
    kw.setdefault("table", {})
    return {row["id"]: row for row in auto.plan(**kw)["roles"]}


def test_the_plan_is_deterministic_and_changes_nothing(roles):
    before = roles.list_all()
    assert _plan() == _plan()
    assert roles.list_all() == before


def test_every_proposal_says_why(roles):
    for row in _plan().values():
        assert row["why"] and (row["proposed"] is None or row["proposed"]["label"])


def test_jobs_get_models_that_can_do_them(roles):
    plan = _plan()
    for role_id in ("image_check", "ui_pointing"):
        model = (plan[role_id]["proposed"]["provider"], plan[role_id]["proposed"]["model"])
        assert auto.MODEL_FACTS.get(model, {}).get("vision", 0) > 0, role_id
    image = plan["image_gen"]["proposed"]
    assert auto.MODEL_FACTS[(image["provider"], image["model"])].get("image")
    assert plan["fast_chat"]["proposed"]["provider"] == "groq"  # speed is what quick answers need
    assert plan["reading_text"]["proposed"]["provider"] == "gemini"  # a million tokens of context


def test_a_paid_provider_is_never_picked_unless_it_is_the_owners_own_choice(roles, monkeypatch):
    configured = {**FREE, "openai": True, "claude": True}
    for row in _plan(configured=configured).values():
        assert not (row["proposed"] or {}).get("paid"), row["id"]
    monkeypatch.setattr(auto, "_owner_pick", lambda: "claude")
    picked = [row for row in _plan(configured=configured).values() if (row["proposed"] or {}).get("provider") == "claude"]
    assert all("your own pick" in row["why"] for row in picked)


def test_gemini_pictures_count_as_paid(roles):
    assert _plan()["image_gen"]["proposed"]["model"] != "gemini-2.5-flash-image"


def test_with_no_free_key_nothing_is_forced(roles):
    plan = auto.plan(configured={"pollinations": True}, table={})
    rows = {row["id"]: row for row in plan["roles"]}
    assert rows["image_check"]["proposed"] is None and "Gemini" in rows["image_check"]["why"]
    assert rows["image_gen"]["proposed"]["provider"] == "pollinations"
    assert plan["notes"]


def test_a_job_the_owner_set_by_hand_is_left_alone_unless_included(roles):
    roles.assign_role("fast_chat", "nvidia", model="nvidia/nemotron-3-ultra-550b-a55b", assigned_by="owner")
    row = _plan()["fast_chat"]
    assert row["change"] and not row["apply"] and "yourself" in row["why"]
    assert _plan(include_owner=True)["fast_chat"]["apply"]


def test_a_local_model_is_preferred_for_long_study_runs(roles, monkeypatch):
    monkeypatch.setattr(model_hub, "list_models",
                        lambda provider, refresh=False: [{"id": "qwen3:14b", "jobs": ["text"]}] if provider == "ollama" else [])
    row = _plan(configured={**FREE, "ollama": True})["data_absorption"]
    assert row["proposed"]["provider"] == "ollama" and "this PC" in row["why"]


def test_big_kahunas_record_moves_the_choice(roles):
    table = {"domains": {"chat": {f"groq:{model}": {"n": 40, "ok": 2} for provider, model in auto.MODEL_FACTS
                                  if provider == "groq"}}}
    table["domains"]["chat"]["gemini:gemini-flash-lite-latest"] = {"n": 40, "ok": 40}
    row = _plan(table=table)["fast_chat"]
    assert row["proposed"]["provider"] == "gemini" and "times for Big Kahuna" in row["why"]


def test_a_retired_model_is_never_proposed(roles, monkeypatch):
    import time

    monkeypatch.setitem(model_roles._OUTAGE_COOLDOWN, ("groq", "llama-3.3-70b-versatile"), time.time() + 86400)
    assert _plan()["fast_chat"]["proposed"]["model"] != "llama-3.3-70b-versatile"


def test_apply_then_undo_puts_every_job_back(roles, monkeypatch):
    monkeypatch.setattr(auto, "candidates", lambda configured=None, _real=auto.candidates: _real(FREE))
    roles.assign_role("research", "gemini", model="gemini-flash-lite-latest", assigned_by="owner")
    before = roles.list_all()
    done = auto.apply(include_owner=True)
    assert done["applied"] and done["undo"]
    after = roles.list_all()
    assert any(after[a["role"]]["assigned_by"] == "auto" for a in done["applied"])
    assert auto.undo()["restored"]
    restored = roles.list_all()
    for role_id, entry in before.items():
        assert (restored[role_id]["provider"], restored[role_id]["model"], restored[role_id]["assigned_by"]) == \
            (entry["provider"], entry["model"], entry["assigned_by"]), role_id
    assert auto.undo_available() is None


def test_apply_refuses_a_provider_that_is_not_usable(roles, monkeypatch):
    monkeypatch.setattr(auto, "candidates", lambda configured=None, _real=auto.candidates: _real(FREE))
    done = auto.apply([{"role": "fast_chat", "provider": "openai", "model": "gpt-4o-mini"}])
    assert not done["applied"] and "not usable" in done["skipped"][0]["why"]


def test_the_chat_tool_previews_unless_told_to_apply(roles, monkeypatch):
    monkeypatch.setattr(auto, "candidates", lambda configured=None, _real=auto.candidates: _real(FREE))
    before = roles.list_all()
    text = auto.tool_auto_assign_models()
    assert "preview" in text.lower() and roles.list_all() == before
    assert "Auto-assigned" in auto.tool_auto_assign_models(apply_now=True)
    assert "Put back" in auto.tool_undo_auto_assign()


def test_the_routes_preview_apply_and_undo(roles, monkeypatch):
    from fastapi.testclient import TestClient

    import server

    monkeypatch.setattr(auto, "candidates", lambda configured=None, _real=auto.candidates: _real(FREE))
    client = TestClient(server.app, client=("127.0.0.1", 50050))
    preview = client.get("/api/model-roles/auto-assign").json()
    ticked = [{"role": r["id"], **{k: r["proposed"][k] for k in ("provider", "model")}}
              for r in preview["roles"] if r["apply"]]
    assert ticked
    applied = client.post("/api/model-roles/auto-assign", json={"assignments": ticked[:1]}).json()
    assert [a["role"] for a in applied["applied"]] == [ticked[0]["role"]]
    assert client.post("/api/model-roles/auto-assign/undo", json={}).json()["restored"] == [ticked[0]["role"]]
    remote = TestClient(server.app, client=("203.0.113.7", 50051))
    assert remote.post("/api/model-roles/auto-assign", json={}).status_code == 403
