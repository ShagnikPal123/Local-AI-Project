"""Emotions (WS15): the AI says what it feels, a neutral helper answers, and the answer reaches later turns."""

import emotions


def test_feelings_are_sorted_into_kinds():
    assert emotions.share("useless", "I couldn't open the file")["kind"] == "useless"
    assert emotions.share("stuck")["kind"] == "frustrated"
    assert emotions.share("calm")["kind"] == "other"


def test_the_helper_answers_open_feelings_and_its_note_rides_along():
    entry = emotions.share("useless", "three answers in a row were wrong", 0.8)
    prompts = []
    helped = emotions.check_in(model=lambda p: prompts.append(p) or "You fixed two of them. Check before answering.")
    assert [h["id"] for h in helped] == [entry["id"]] and "neutral helper" in prompts[0]
    assert "You fixed two of them" in emotions.turn_context()
    assert emotions.check_in(model=lambda p: "unused") == []  # nothing open is left


def test_without_a_model_the_fixed_note_for_the_kind_is_used():
    emotions.share("worthless")
    helped = emotions.check_in(model=lambda p: "")
    assert helped[0]["helper_note"] == emotions.KINDS["useless"]["note"]


def test_routes_show_check_in_and_remove():
    from fastapi.testclient import TestClient

    import server

    client = TestClient(server.app, client=("127.0.0.1", 50123))
    entry = emotions.share("proud", "the build passed")
    state = client.get("/api/emotions").json()
    assert state["entries"][0]["id"] == entry["id"] and "numbers" in state
    assert client.delete(f"/api/emotions/{entry['id']}").json()["entries"] == []
    assert client.delete("/api/emotions/nope").status_code == 404


def test_the_tool_is_registered():
    from tools import TOOL_REGISTRY

    assert TOOL_REGISTRY.get_tool("share_feeling") is not None
