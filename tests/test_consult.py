"""Second opinions on heavy requests (Requests H2 and H6), and the agent settings that control them."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

import consult


def test_only_hard_requests_count_as_heavy():
    assert not consult.is_heavy("what time is it in Tokyo?")
    assert not consult.is_heavy("switch to nvidia")
    assert consult.is_heavy("Design the architecture for a multiplayer game server and compare the trade-offs of each approach")
    assert consult.is_heavy("Please think hard about this one: why does my loop never end?")


def test_seats_ask_the_same_model_fresh_and_the_strongest_other_model_that_can_answer(monkeypatch):
    available = {"gemini": False, "nvidia": True, "groq": True}
    monkeypatch.setattr(consult, "_available", lambda name: available.get(name, False))
    monkeypatch.setattr(consult, "_default_model", lambda name: f"{name}-default")

    seats = consult.seats("groq", "llama-3.3", "both")
    assert [(s["kind"], s["provider"]) for s in seats] == [("same", "groq"), ("other", "nvidia")]
    assert [s["kind"] for s in consult.seats("groq", "", "same")] == ["same"]
    # Gemini is the consultant of choice for hard questions when it can answer and is not the owner's pick.
    available["gemini"] = True
    assert consult.seats("nvidia", "", "other")[0]["provider"] == "gemini"
    assert consult.seats("gemini", "", "other")[0]["provider"] == "nvidia"


def test_consult_collects_notes_in_parallel_and_drops_slow_or_failing_seats(monkeypatch):
    import model_hub

    monkeypatch.setattr(consult, "_available", lambda name: name in ("nvidia",))
    monkeypatch.setattr(consult, "_default_model", lambda name: "")

    def complete(provider, model, prompt, system="", max_tokens=0, timeout=0):
        if provider == "groq":
            return SimpleNamespace(text="- check the base case\n- verify with a test")
        time.sleep(3)
        return SimpleNamespace(text="too late")

    monkeypatch.setattr(model_hub, "complete", complete)
    heard = []
    notes = consult.consult("debug my recursion", primary="groq", models="both", budget=1.0, on_note=heard.append)
    assert [n["kind"] for n in notes] == ["same"] and heard == notes
    context = consult.as_context(notes)
    assert context.startswith(consult.PREFIX) and "check the base case" in context


def test_agent_purpose_and_consult_settings_are_validated_and_saved(tmp_path, monkeypatch):
    import agent_runtime

    monkeypatch.setattr(agent_runtime, "_custom_agents_path", lambda: tmp_path / "custom_agents.json")
    monkeypatch.setattr(agent_runtime, "_overrides_path", lambda: tmp_path / "agent_overrides.json")
    with agent_runtime._roster_lock:
        agent_runtime._roster_cache["agents"] = None

    props = agent_runtime.create_subagent({"name": "Price Scout", "goal": "Compare laptop prices",
                                           "purpose": "Find the best deal under $900", "consult": "always",
                                           "consult_with": ["Researcher"], "consult_models": "other"})
    assert props["purpose"] == "Find the best deal under $900"
    assert (props["consult"], props["consult_with"], props["consult_models"]) == ("always", ["Researcher"], "other")
    with pytest.raises(ValueError):
        agent_runtime.update_agent("Price Scout", {"consult": "sometimes"})
    with pytest.raises(ValueError):
        agent_runtime.update_agent("Price Scout", {"consult_with": ["Nobody Here"]})
    names = [a["name"] for a in agent_runtime.all_agent_details()]
    assert "Price Scout" in names and "Researcher" in names

    assert agent_runtime.remove_custom_agent("Price Scout")
    assert not agent_runtime.remove_custom_agent("Researcher")  # built-in agents cannot be deleted
    assert "Price Scout" not in json.dumps(json.loads((tmp_path / "custom_agents.json").read_text(encoding="utf-8")))
    with agent_runtime._roster_lock:
        agent_runtime._roster_cache["agents"] = None


def test_the_create_agent_tool_applies_the_model_the_user_asked_for(tmp_path, monkeypatch):
    import agent_runtime

    monkeypatch.setattr(agent_runtime, "_custom_agents_path", lambda: tmp_path / "custom_agents.json")
    monkeypatch.setattr(agent_runtime, "_overrides_path", lambda: tmp_path / "agent_overrides.json")
    monkeypatch.setattr(agent_runtime, "_router", lambda: SimpleNamespace(providers={"nvidia": object(), "gemini": object()}))
    with agent_runtime._roster_lock:
        agent_runtime._roster_cache["agents"] = None

    from tools import ToolRegistry

    registry = ToolRegistry()
    agent_runtime.register_agent_tools(registry)
    reply = registry.call_tool("create_agent", name="Scout", goal="Research prices", provider="nvidia", consult="heavy")
    assert reply.startswith("Created") and "nvidia" in reply
    assert agent_runtime.agent_properties("Scout")["provider"] == "nvidia"
    agent_runtime.remove_custom_agent("Scout")
    with agent_runtime._roster_lock:
        agent_runtime._roster_cache["agents"] = None
