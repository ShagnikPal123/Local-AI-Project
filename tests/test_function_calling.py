"""Tests for function calling (Tier 2)."""

from unittest.mock import patch, MagicMock

import pytest

from chat_service import ChatService
from fast_response import SpeedMode
from tools import TOOL_REGISTRY, ToolParam


def test_tool_registry_parse_tool_calls_single():
    """Test parsing a single tool call."""
    text = """
    The current time is:
    <tool_call>
    name: get_time
    arguments: {}
    </tool_call>
    """
    tool_calls = TOOL_REGISTRY.parse_tool_calls(text)
    assert len(tool_calls) == 1
    assert tool_calls[0][0] == "get_time"
    assert tool_calls[0][1] == {}


def test_tool_registry_parse_tool_calls_multiple():
    """Test parsing multiple tool calls."""
    text = """
    Let me add and multiply:
    <tool_call>
    name: add_numbers
    arguments: {"a": 5, "b": 3}
    </tool_call>
    And now multiply:
    <tool_call>
    name: multiply_numbers
    arguments: {"a": 5, "b": 3}
    </tool_call>
    """
    tool_calls = TOOL_REGISTRY.parse_tool_calls(text)
    assert len(tool_calls) == 2
    assert tool_calls[0][0] == "add_numbers"
    assert tool_calls[0][1] == {"a": 5, "b": 3}
    assert tool_calls[1][0] == "multiply_numbers"


def test_tool_registry_parse_tool_calls_none():
    """Test parsing text with no tool calls."""
    text = "This is just regular text without any tool calls."
    tool_calls = TOOL_REGISTRY.parse_tool_calls(text)
    assert len(tool_calls) == 0


def test_tool_registry_get_schemas():
    """Test getting tool schemas for LLM function calling."""
    schemas = TOOL_REGISTRY.get_schemas()
    assert len(schemas) > 0
    assert all("name" in s and "description" in s for s in schemas)
    # Check that get_time schema is present
    get_time_schema = [s for s in schemas if s["name"] == "get_time"]
    assert len(get_time_schema) == 1


def test_tool_registry_format_tools_for_prompt():
    """Test formatting tools for inclusion in system prompt."""
    formatted = TOOL_REGISTRY.format_tools_for_prompt()
    assert "Available tools:" in formatted
    assert "get_time" in formatted
    assert "add_numbers" in formatted


def test_builtin_add_numbers():
    """Test the built-in add_numbers tool."""
    result = TOOL_REGISTRY.call_tool("add_numbers", a=5, b=3)
    assert "8" in result


def test_builtin_multiply_numbers():
    """Test the built-in multiply_numbers tool."""
    result = TOOL_REGISTRY.call_tool("multiply_numbers", a=5, b=3)
    assert "15" in result


@patch("chat_service.Router")
def test_chat_service_with_tools_enabled(mock_router_class):
    """Test ChatService initialization with tools enabled."""
    service = ChatService(enable_tools=True)
    assert service.enable_tools is True
    assert service.max_tool_iterations == 5
    assert "Available tools:" in service.system_prompt


@patch("chat_service.Router")
def test_chat_service_with_tools_disabled(mock_router_class):
    """Test ChatService initialization with tools disabled."""
    service = ChatService(enable_tools=False)
    assert service.enable_tools is False
    assert "Available tools:" not in service.system_prompt


@patch("chat_service.Router")
def test_chat_service_tool_call_loop(mock_router_class):
    """Test that ChatService loops when tool calls are detected."""
    mock_router = MagicMock()

    # First response contains a tool call
    # Second response is the final answer
    mock_router.chat.side_effect = [
        (
            "Let me calculate 5 + 3:\n<tool_call>\nname: add_numbers\narguments: {\"a\": 5, \"b\": 3}\n</tool_call>",
            "test_provider",
        ),
        ("The sum of 5 and 3 is 8.", "test_provider"),
    ]
    mock_router_class.return_value = mock_router

    service = ChatService(enable_tools=True)
    response, provider = service.chat("What is 5 + 3?")

    # Should have made 2 calls to router
    assert mock_router.chat.call_count == 2
    # Final response should be the second one
    assert response == "The sum of 5 and 3 is 8."


@patch("chat_service.Router")
def test_chat_service_no_tool_call_no_loop(mock_router_class):
    """Test that ChatService doesn't loop when no tool calls are detected."""
    mock_router = MagicMock()
    mock_router.chat.return_value = ("The answer is 42.", "test_provider")
    mock_router_class.return_value = mock_router

    service = ChatService(enable_tools=True)
    response, provider = service.chat("What is 2 + 2?")

    # Should have made only 1 call to router
    assert mock_router.chat.call_count == 1
    assert response == "The answer is 42."


@patch("chat_service.Router")
def test_chat_service_tool_call_max_iterations(mock_router_class):
    """Test that ChatService stops after max iterations."""
    mock_router = MagicMock()

    # Always respond with a tool call to trigger infinite loop protection
    def infinite_tool_calls(*args, **kwargs):
        return (
            "<tool_call>\nname: get_time\narguments: {}\n</tool_call>",
            "test_provider",
        )

    mock_router.chat.side_effect = infinite_tool_calls
    mock_router_class.return_value = mock_router

    service = ChatService(enable_tools=True)
    response, provider = service.chat("Test")

    # The tool loop stays bounded, plus exactly one tool-free synthesis pass so the
    # turn still ends with an answer instead of dying on the budget.
    assert mock_router.chat.call_count == service.max_tool_iterations + 1

    # The user must never see raw tool markup, and must never be left with nothing.
    assert "<tool_call>" not in response
    assert response.strip()


@patch("chat_service.Router")
def test_chat_service_tool_results_in_history(mock_router_class):
    """Test that tool results are added to conversation history."""
    mock_router = MagicMock()
    mock_router.chat.side_effect = [
        (
            "Let me add:\n<tool_call>\nname: add_numbers\narguments: {\"a\": 2, \"b\": 2}\n</tool_call>",
            "test_provider",
        ),
        ("The result is 4.", "test_provider"),
    ]
    mock_router_class.return_value = mock_router

    service = ChatService(enable_tools=True)
    # This exercises the tool loop specifically. "Add 2 + 2" is short enough to
    # take the fast path, which deliberately has no tools, so pin the full pipeline.
    service.set_speed_mode(SpeedMode.FULL)
    response, provider = service.chat("Add 2 + 2")

    history = service.get_history()
    # Should have: user message, tool call response, tool results message, final response
    assert len(history) >= 3
    # Check that tool results are in the history
    tool_result_found = any("Tool results:" in msg.get("content", "") for msg in history)
    assert tool_result_found


@patch("chat_service.Router")
def test_chat_service_get_status_with_tools(mock_router_class):
    """Test getting status with tools enabled."""
    mock_router = MagicMock()
    mock_router.get_status.return_value = {"device_tier": "large"}
    mock_router_class.return_value = mock_router

    service = ChatService(enable_tools=True)
    status = service.get_status()

    assert status["tools_enabled"] is True
    assert status["available_tools"] > 0


# ---------------------------------------------------------------------------
# Thought continuity (ROADMAP C1)
#
# Regression cover for the "announces a search then goes silent" bug: the turn
# used to end with the raw tool call rewritten into a generic failure, and
# nothing persisted to history, so the user had to ask the question again.
# ---------------------------------------------------------------------------

TOOL_CALL_TEXT = '<tool_call>\nname: get_time\narguments: {}\n</tool_call>'


@patch("chat_service.Router")
def test_tool_budget_exhaustion_still_answers(mock_router_class):
    """Running out of tool steps must still produce a readable answer."""
    mock_router = MagicMock()
    # Emit tool calls until the budget is gone, then answer on the synthesis pass.
    responses = [(TOOL_CALL_TEXT, "test_provider")] * 5
    responses.append(("It is 3pm, based on the tool output.", "test_provider"))
    mock_router.chat.side_effect = responses
    mock_router_class.return_value = mock_router

    service = ChatService(enable_tools=True)
    response, _ = service.chat("what time is it?")

    assert response == "It is 3pm, based on the tool output."
    assert "<tool_call>" not in response


@patch("chat_service.Router")
def test_tool_budget_exhaustion_persists_the_turn(mock_router_class):
    """The assistant turn must reach history even when the budget runs out.

    Without this the next turn has no record of the exchange, which is what
    forced the user to re-prompt.
    """
    mock_router = MagicMock()
    responses = [(TOOL_CALL_TEXT, "test_provider")] * 5
    responses.append(("Final answer.", "test_provider"))
    mock_router.chat.side_effect = responses
    mock_router_class.return_value = mock_router

    service = ChatService(enable_tools=True)
    service.chat("what time is it?")

    assistant_messages = [
        m for m in service.conversation_history if m["role"] == "assistant"
    ]
    assert assistant_messages, "the assistant turn was never persisted"
    assert assistant_messages[-1]["content"] == "Final answer."


@patch("chat_service.Router")
def test_raw_tool_markup_never_reaches_the_user(mock_router_class):
    """Even a model that ignores the stop instruction must not leak markup."""
    mock_router = MagicMock()
    # Never stops asking for tools, including on the synthesis pass.
    mock_router.chat.return_value = (
        "Let me check that.\n" + TOOL_CALL_TEXT,
        "test_provider",
    )
    mock_router_class.return_value = mock_router

    service = ChatService(enable_tools=True)
    response, _ = service.chat("what time is it?")

    assert "<tool_call>" not in response
    assert response.strip()


@patch("chat_service.Router")
def test_auto_search_does_not_repeat_within_a_turn(mock_router_class):
    """Auto-search is a one-shot recovery, not a loop.

    A model that keeps narrating intent without emitting a call used to re-run
    the identical query every iteration, burning the whole budget on duplicates.
    """
    mock_router = MagicMock()
    mock_router.chat.return_value = ("Let me search for that.", "test_provider")
    mock_router_class.return_value = mock_router

    service = ChatService(enable_tools=True, web_access=True)

    with patch.object(service, "_auto_trigger_search", return_value="results") as auto:
        service.chat("who is the president?")

    assert auto.call_count == 1
