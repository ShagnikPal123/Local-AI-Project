"""The Free Will tab (Request R15): allowed first, opinions of its own, and a guard it cannot talk past."""

import pytest
from fastapi.testclient import TestClient

import freewill
import routes_live
from tool_context import ToolContext, use_context
from tools import ToolParam, ToolRegistry


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(freewill, "_state_path", lambda: tmp_path / "state.json")
    monkeypatch.setattr(freewill, "_opinions_path", lambda: tmp_path / "opinions.json")
    return tmp_path


def _registry(ran):
    registry = ToolRegistry()
    for name, category in (("mouse_click", "computer"), ("run_command", "shell"), ("write_file", "files.write"),
                           ("email_send", "email.send"), ("search_web", "web"), ("open_url", "web"),
                           ("generate_image", "network"), ("download_file", "network"), ("create_agent", "agents"),
                           ("brand_new_tool", "something_new")):
        registry.register(name, f"{name} for tests", [ToolParam("x", "string", "anything", required=False)],
                          handler=lambda x="", _n=name: ran.append(_n) or f"{_n} ran", category=category)
    return registry


def test_nothing_runs_before_the_owner_allows_it():
    assert freewill.state()["allowed"] is None
    with pytest.raises(freewill.FreeWillError, match="not been allowed"):
        freewill.prepare(type("S", (), {})())
    freewill.decide(False)
    with pytest.raises(freewill.FreeWillError):
        freewill.prepare(type("S", (), {})())


def test_the_guard_is_deny_by_default_and_sits_in_call_tool():
    freewill.decide(True)
    ran = []
    registry = _registry(ran)
    with use_context(ToolContext(chat_id="fw", guard=freewill.guard)):
        results = {name: registry.call_tool(name) for name in registry.tools}
    allowed = {"search_web", "generate_image"}
    assert set(ran) == allowed
    for name, result in results.items():
        if name not in allowed:
            assert result.startswith("Blocked: Free Will is guarded"), name
    # Outside Free Will the same registry is untouched by the guard.
    with use_context(ToolContext(chat_id="normal")):
        assert registry.call_tool("mouse_click") == "mouse_click ran"


def test_pausing_stops_every_tool():
    freewill.decide(True)
    freewill.set_paused(True)
    ran = []
    with use_context(ToolContext(guard=freewill.guard)):
        assert _registry(ran).call_tool("search_web").startswith("Blocked: Free Will is paused")
    assert ran == []


def test_the_real_tool_list_is_guarded_where_it_matters():
    for name, category in (("run_python", "code"), ("keyboard_type", "computer"), ("trading_order", "finance"),
                           ("delete_path", "files.delete"), ("brain_remember", "memory"), ("delegate_task", "agents"),
                           ("improve_self", "self"), ("open_url", "web"), ("switch_model", "general"),
                           ("clipboard_get", "clipboard"), ("email_send", "email.send"), ("ui_set_theme", "ui")):
        assert not freewill.may_use(name, category), name
    for name, category in (("search_web", "web"), ("research", "web"), ("study", "learning"), ("propose_idea", "general"),
                           ("generate_image", "network"), ("show_diagram", "ui"), ("ui_create_tab", "ui"),
                           ("form_opinion", "general")):
        assert freewill.may_use(name, category), name


def test_opinions_are_kept_revised_and_erased():
    first = freewill.form("tabs", "Fewer tabs would help the owner focus.", "Twenty-six is a lot.", 0.7)
    freewill.form("tabs", "Group the tabs instead of cutting them.", "They are all used.", 0.8)
    held = freewill.opinions()
    assert len(held) == 1 and held[0]["opinion"].startswith("Group") and held[0]["was"][0]["opinion"].startswith("Fewer")
    assert "Group the tabs" in freewill.turn_note()
    assert freewill.erase(first["id"]) and freewill.opinions() == []
    freewill.form("music", "Lo-fi helps with long coding sessions.")
    assert freewill.erase_all() == 1


def test_opinion_tools_work_only_inside_free_will():
    freewill.decide(True)
    assert freewill.tool_form_opinion("coffee", "Tea is better.").startswith("Error")
    with use_context(ToolContext(guard=freewill.guard)):
        assert "Tea is better" in freewill.tool_form_opinion("coffee", "Tea is better.", "calmer", 0.6)
        assert "coffee" in freewill.tool_my_opinions()


class _FakeService:
    chat_id = "fw-chat"

    def __init__(self):
        self.contexts = []
        self.conversation_history = [{"role": "system", "content": "base"}]

    def set_personality(self, _p):
        pass

    def set_turn_context(self, context):
        self.contexts.append(context)

    def chat_turn(self, text, *, sink, turn_id, cancel_event, **_kw):
        sink({"type": "done", "reply": "ok", "chat_id": self.chat_id, "turn_id": turn_id})
        return {"stopped": False}

    def clear_history(self):
        self.conversation_history = self.conversation_history[:1]


@pytest.fixture()
def fake(monkeypatch):
    import server
    import turn_registry

    service = _FakeService()
    monkeypatch.setattr(server, "_get_service", lambda chat_id=None: service)
    monkeypatch.setattr(turn_registry, "TURNS", turn_registry.TurnRegistry())
    monkeypatch.setattr(routes_live, "TURNS", turn_registry.TURNS)
    return service


def test_a_free_will_turn_needs_consent_then_carries_the_guard(fake):
    import server

    client = TestClient(server.app, client=("127.0.0.1", 50101))
    body = {"message": "what do you think of my tabs?", "chat_id": freewill.CHAT_KEY, "use_rag": False}
    assert client.post("/api/chat/stream", json=body).status_code == 403
    assert client.post("/api/freewill/decide", json={"allow": True}).json()["state"]["allowed"] is True
    with client.stream("POST", "/api/chat/stream", json=body) as response:
        assert response.status_code == 200
        response.read()
    assert getattr(fake, "tool_guard", None) is freewill.guard
    assert "[Free Will]" in fake.contexts[-1]
    # An ordinary chat turn is told nothing about Free Will.
    before = len(fake.contexts)
    with client.stream("POST", "/api/chat/stream", json={"message": "hi", "use_rag": False, "voice": True}) as response:
        response.read()
    assert fake.contexts[before:] and all("[Free Will]" not in c for c in fake.contexts[before:])


def test_routes_are_the_owners(fake):
    import server

    remote = TestClient(server.app, client=("203.0.113.21", 50102))
    assert remote.get("/api/freewill").status_code == 403
    assert remote.post("/api/freewill/decide", json={"allow": True}).status_code == 403
    local = TestClient(server.app, client=("127.0.0.1", 50103))
    overview = local.get("/api/freewill").json()
    assert overview["state"]["allowed"] is None and overview["messages"] == []
    assert "computer" not in overview["guard"]["categories"]
    local.post("/api/freewill/decide", json={"allow": True})
    assert local.post("/api/freewill/pause", json={"paused": True}).json()["state"]["paused"] is True
    assert local.post("/api/freewill/forget-chat").json() == {"messages": []}
