"""Tests for chat service and tools."""

from unittest.mock import patch, MagicMock

import pytest

from chat_service import ChatService
from providers.base import ProviderError
from tools import ToolRegistry, ToolParam, builtin_get_time, builtin_list_tools


def test_tool_registry_register():
    """Test registering a tool."""
    registry = ToolRegistry()

    def dummy_tool(arg1: str) -> str:
        return f"Result: {arg1}"

    registry.register(
        name="dummy",
        description="A dummy tool",
        parameters=[
            ToolParam(
                name="arg1",
                param_type="string",
                description="An argument",
                required=True,
            )
        ],
        handler=dummy_tool,
    )

    assert "dummy" in registry.tools
    assert registry.get_tool("dummy") is not None


def test_tool_registry_call():
    """Test calling a tool."""
    registry = ToolRegistry()

    def add_tool(a: int, b: int) -> str:
        return str(a + b)

    registry.register(
        name="add",
        description="Add two numbers",
        parameters=[
            ToolParam(
                name="a", param_type="number", description="First number", required=True
            ),
            ToolParam(
                name="b", param_type="number", description="Second number", required=True
            ),
        ],
        handler=add_tool,
    )

    result = registry.call_tool("add", a=5, b=3)
    assert result == "8"


def test_tool_registry_call_nonexistent():
    """Test calling a non-existent tool."""
    registry = ToolRegistry()
    result = registry.call_tool("nonexistent")
    assert "not found" in result


def test_tool_registry_call_with_error():
    """Test calling a tool that raises an error."""
    registry = ToolRegistry()

    def error_tool() -> str:
        raise ValueError("Test error")

    registry.register(
        name="error",
        description="Error tool",
        parameters=[],
        handler=error_tool,
    )

    result = registry.call_tool("error")
    assert "Error calling tool" in result


def test_builtin_get_time():
    """Test the built-in get_time tool."""
    result = builtin_get_time()
    # Should return a date string in format YYYY-MM-DD HH:MM:SS
    assert len(result) >= 19  # "YYYY-MM-DD HH:MM:SS"


def test_builtin_list_tools():
    """Test the built-in list_tools tool."""
    result = builtin_list_tools()
    assert "Available tools" in result


@patch("chat_service.Router")
def test_chat_service_initialization(mock_router_class, tmp_path):
    """Test ChatService initialization with isolated memory."""
    service = ChatService(memory_path=str(tmp_path / "empty_memory.json"))
    assert service.conversation_history is not None
    # Base system prompt first, then permanent general knowledge context.
    assert service.conversation_history[0]["role"] == "system"
    assert "You are Nyx Ichos" in service.conversation_history[0]["content"]
    assert all(msg["role"] == "system" for msg in service.conversation_history)
    assert any("[General Knowledge]" in msg["content"] for msg in service.conversation_history)


@patch("chat_service.Router")
def test_chat_service_add_message(mock_router_class, tmp_path):
    """Test adding messages to chat history."""
    service = ChatService(memory_path=str(tmp_path / "empty_memory.json"))
    service.add_message("user", "Hello")
    service.add_message("assistant", "Hi there")

    history = service.get_history()
    assert len(history) == 2
    assert history[0]["content"] == "Hello"
    assert history[1]["content"] == "Hi there"


@patch("chat_service.Router")
def test_chat_service_clear_history(mock_router_class, tmp_path):
    """Test clearing conversation history."""
    service = ChatService(memory_path=str(tmp_path / "empty_memory.json"))
    service.add_message("user", "Hello")
    service.add_message("assistant", "Hi")

    service.clear_history()
    history = service.get_history()
    assert len(history) == 0


@patch("chat_service.Router")
def test_chat_service_custom_system_prompt(mock_router_class, tmp_path):
    """Test providing a custom system prompt."""
    custom_prompt = "You are a test assistant."
    service = ChatService(system_prompt=custom_prompt, memory_path=str(tmp_path / "empty_memory.json"))

    assert service.conversation_history[0]["content"] == custom_prompt


@patch("chat_service.Router")
def test_chat_service_chat(mock_router_class, tmp_path):
    """Test sending a message and getting a response."""
    mock_router = MagicMock()
    mock_router.chat.return_value = ("Hello there!", "test_provider")
    mock_router_class.return_value = mock_router

    service = ChatService(memory_path=str(tmp_path / "empty_memory.json"))
    response, provider = service.chat("Hello")

    assert response == "Hello there!"
    assert provider == "test_provider"
    # Message should be added to history
    history = service.get_history()
    assert len(history) == 2  # user message + assistant response


@patch("chat_service.Router")
def test_chat_service_get_status(mock_router_class, tmp_path):
    """Test getting service status."""
    mock_router = MagicMock()
    mock_router.get_status.return_value = {"device_tier": "large"}
    mock_router_class.return_value = mock_router

    service = ChatService(memory_path=str(tmp_path / "empty_memory.json"))
    status = service.get_status()

    assert "router_status" in status
    assert "conversation_length" in status


@patch("chat_service.Router")
def test_chat_service_offline_fallback_reports_the_real_reason(mock_router_class, tmp_path):
    """A routing failure must say what failed, not guess a topic.

    This previously returned a cheerful topic-matched sentence that looked like a
    normal answer, so a missing API key was indistinguishable from a real reply.
    The router's diagnostic is the single most useful thing we have; it must
    reach the user.
    """
    mock_router = MagicMock()
    mock_router.chat.side_effect = ProviderError("gemini: 401 invalid key | ollama: refused")
    mock_router_class.return_value = mock_router

    service = ChatService(memory_path=str(tmp_path / "empty_memory.json"))
    response, provider = service.chat("How do I debug a Python error?")

    assert provider == "offline"
    # The actual cause, passed through verbatim.
    assert "401 invalid key" in response
    assert "ollama" in response.lower()
    # And something the user can act on.
    assert ".env.local" in response
    # It must not masquerade as an answer to the question that was asked.
    assert "isolate the likely root cause" not in response


def test_offline_topical_fallback_when_no_reason_is_known(tmp_path):
    """Without a routing diagnostic, the topical courtesy replies still apply."""
    service = ChatService.__new__(ChatService)

    response, provider = ChatService._offline_response(service, "How do I debug a Python error?")
    assert provider == "offline"
    assert "offline" in response.lower()
    assert "debug" in response.lower()


def test_directive_preamble_does_not_hijack_the_offline_branch(tmp_path):
    """Regression guard for the "same answer to everything" bug.

    The CLI prepends "[MULTI-APPROACH PROTOCOL: AUTO]" to every message. The old
    matcher used unanchored substring tests, so "app" matched inside "approach"
    and every question — whatever it was — returned the "let's build it step by
    step" sentence. "hi" matching inside "this" produced the greeting reply.
    """
    from chat_service import split_directives

    preamble = (
        "[MULTI-APPROACH PROTOCOL: AUTO]\n"
        "1. Analyze requirements, invariants, and edge cases.\n"
        "2. Formulate the cleanest, most maintainable solution.\n"
        "3. Double-check for edge cases, performance, security, and test verification.\n\n"
    )
    service = ChatService.__new__(ChatService)

    directives, question = split_directives(preamble + "what is 2+2?")
    assert "MULTI-APPROACH" in directives
    assert question == "what is 2+2?"

    response, _ = ChatService._offline_response(service, question)
    assert "build this step by step" not in response

    # "hi" inside "this" must not select the greeting branch either.
    _, question = split_directives(preamble + "summarize this document")
    response, _ = ChatService._offline_response(service, question)
    assert "Hello!" not in response

    # A genuine request to build something still reaches the build branch.
    response, _ = ChatService._offline_response(service, "help me build an app")
    assert "build this step by step" in response
