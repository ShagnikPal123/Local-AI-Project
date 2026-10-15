"""Rules and laws (WS15): numbered and nested, the AI slider, owner laws untouchable by the AI, tools refused."""

import pytest

import rules_laws
from tools import ToolParam, ToolRegistry


def test_laws_are_numbered_by_nesting_and_removal_lifts_children():
    first = rules_laws.add_law("Be honest")
    second = rules_laws.add_law("Money")
    child = rules_laws.add_law("No trades over 100", parent=second["id"])
    case = rules_laws.add_law("A 150 trade was refused", parent=child["id"], kind="case")
    numbers = {law["id"]: law["number"] for law in rules_laws.numbered()}
    assert numbers == {first["id"]: "1", second["id"]: "2", child["id"]: "2.1", case["id"]: "2.1.1"}
    rules_laws.remove_law(child["id"])
    assert {law["id"]: law["number"] for law in rules_laws.numbered()}[case["id"]] == "2.1"


def test_the_slider_decides_what_the_ai_may_do():
    rules_laws.set_autonomy(0)
    with pytest.raises(rules_laws.LawError):
        rules_laws.add_law("Mine", author="ai")
    rules_laws.set_autonomy(20)
    suggested = rules_laws.add_law("Ask before email", author="ai")
    assert suggested["status"] == "suggested" and rules_laws.turn_context("ichos") == ""
    rules_laws.approve(suggested["id"])
    assert "Ask before email" in rules_laws.turn_context("ichos")
    rules_laws.set_autonomy(50)
    own = rules_laws.add_law("Short answers", author="ai")
    assert own["status"] == "in_force"
    with pytest.raises(rules_laws.LawError):
        rules_laws.update_law(own["id"], by="ai", text="changed")
    rules_laws.set_autonomy(90)
    assert rules_laws.update_law(own["id"], by="ai", text="changed")["text"] == "changed"
    assert rules_laws.remove_law(own["id"], by="ai")


def test_the_ai_never_touches_the_owners_laws():
    rules_laws.set_autonomy(100)
    owners = rules_laws.add_law("Owner's law")
    with pytest.raises(rules_laws.LawError):
        rules_laws.update_law(owners["id"], by="ai", text="x")
    with pytest.raises(rules_laws.LawError):
        rules_laws.remove_law(owners["id"], by="ai")


def test_laws_bind_only_their_bots_and_a_suspended_parent_suspends_its_children():
    parent = rules_laws.add_law("For Mia", applies_to="mia")
    rules_laws.add_law("Mia's detail", parent=parent["id"], applies_to="mia")
    assert "For Mia" in rules_laws.turn_context(["av_1", "Mia"]) and rules_laws.turn_context("ichos") == ""
    rules_laws.update_law(parent["id"], status="suspended")
    assert rules_laws.turn_context("mia") == ""


def test_a_law_can_forbid_a_tool_at_the_choke_point():
    rules_laws.add_law("No adding", block_tools="ad*")
    registry = ToolRegistry()
    registry.register(name="add", description="Add", handler=lambda a, b: str(a + b), parameters=[
        ToolParam(name="a", param_type="number", description="a", required=True),
        ToolParam(name="b", param_type="number", description="b", required=True)])
    result = registry.call_tool("add", a=1, b=2)
    assert "law 1" in result and "No adding" in result


def test_routes_and_the_ai_tool():
    from fastapi.testclient import TestClient

    import intelligence_tools
    import server

    client = TestClient(server.app, client=("127.0.0.1", 50123))
    state = client.put("/api/laws", json={"autonomy": 10}).json()
    assert state["level"] == "suggest"
    assert "waits for the owner's approval" in intelligence_tools.tool_make_law("Be brief")
    law = client.get("/api/laws").json()["laws"][0]
    assert client.post(f"/api/laws/{law['id']}/approve").json()["laws"][0]["status"] == "in_force"
    assert client.post("/api/laws", json={"title": ""}).status_code == 400
    assert client.delete(f"/api/laws/{law['id']}").json()["laws"] == []
