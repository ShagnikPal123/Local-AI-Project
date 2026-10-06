"""Fast-response routing (ROADMAP W1-W4, T4, T5).

The fast path answers simple turns in one cheap call with no tools. Its danger is
routing a turn that genuinely needed tools, so most of these tests assert that a
question does NOT take the fast path.
"""

from unittest.mock import MagicMock, patch

import pytest

from chat_service import ChatService
from fast_response import (
    ESCALATION_SENTINEL,
    FastResponsePolicy,
    SpeedMode,
    wants_escalation,
)


@pytest.fixture
def policy():
    return FastResponsePolicy()


# --- turns that should be fast -------------------------------------------------

@pytest.mark.parametrize("message", [
    "hi",
    "hello there",
    "thanks!",
    "what is 2 + 2",
])
def test_simple_turns_take_the_fast_path(policy, message):
    assert policy.decide(message).fast is True


# --- turns that must NOT be fast ----------------------------------------------

@pytest.mark.parametrize("message", [
    # The reported staleness bug (D1). A tool-less path would answer from
    # parametric memory and be years out of date.
    "who is the president?",
    "who is the CEO of Apple",
    "who won the election",
    # live data
    "what is the latest news",
    "current stock price of NVDA",
    "what is the weather today",
    # code
    "fix this bug in my function",
    "why does this traceback happen",
    # machine actions
    "open my downloads folder",
    "take a screenshot",
    # multi-step reasoning
    "compare these two architectures",
    "walk me through the design step by step",
])
def test_turns_needing_tools_or_freshness_take_the_full_path(policy, message):
    decision = policy.decide(message)
    assert decision.fast is False, f"{message!r} wrongly took the fast path"


@pytest.mark.parametrize("message", [
    # Plan Null N2, the owner's own words: short enough for the fast path, which
    # has no tools, so the model said it could not send email.
    "can you send me an email?",
    "Send me an email. Just saying Hi",
    "send an email from me@example.com to me@example.com Hi as the message and subject",
    "check my inbox",
    "add lunch to my calendar",
    "remind me at 5",
    "make a new tab for my workouts",
    "remember that I like tea",
])
def test_actions_that_need_a_tool_take_the_full_path(policy, message):
    decision = policy.decide(message)
    assert decision.fast is False, f"{message!r} wrongly took the fast path"


@pytest.mark.parametrize("message", ["what is a table?", "tell me a joke", "good morning"])
def test_action_words_match_whole_words_only(policy, message):
    assert policy.decide(message).fast is True, f"{message!r} lost the fast path"


def test_long_input_takes_the_full_path(policy):
    assert policy.decide("a" * 400).fast is False


def test_code_fence_takes_the_full_path(policy):
    assert policy.decide("```python\nprint(1)\n```").fast is False


def test_empty_message_takes_the_full_path(policy):
    assert policy.decide("").fast is False


def test_analyzer_failure_falls_back_to_the_full_path(policy):
    """A classifier crash must not deny service, and must not risk a bad answer.

    Uses a message long enough to reach the analyzer — short ones short-circuit
    before it and are answered without consulting it at all.
    """
    message = "tell me something interesting about the ocean and its many depths"
    assert len(message) > 40
    with patch.object(policy.analyzer, "analyze", side_effect=RuntimeError("boom")):
        assert policy.decide(message).fast is False


def test_trivially_short_turns_skip_the_analyzer(policy):
    """Greetings must not pay for classification."""
    with patch.object(policy.analyzer, "analyze") as analyze:
        assert policy.decide("thanks!").fast is True
    analyze.assert_not_called()


# --- explicit overrides --------------------------------------------------------

def test_mode_fast_forces_the_fast_path(policy):
    assert policy.decide("compare these architectures", SpeedMode.FAST).fast is True


def test_mode_full_forces_the_full_path(policy):
    assert policy.decide("hi", SpeedMode.FULL).fast is False


def test_every_decision_carries_a_reason(policy):
    for message in ["hi", "who is the president?", ""]:
        assert policy.decide(message).reason


# --- escalation ----------------------------------------------------------------

def test_escalation_sentinel_is_detected():
    assert wants_escalation(ESCALATION_SENTINEL) is True
    assert wants_escalation("a normal answer") is False


@pytest.mark.parametrize("reply", [
    # Real fast-path replies from the owner's chats (2026-09-21).
    "I cannot send emails or access external systems like email services. I'm an AI text assistant "
    "without capabilities to communicate with email servers or your personal accounts.",
    "I cannot send emails directly as this tool isn't available in my current interface.",
    "I don't have access to your calendar.",
    "Sorry, I'm unable to open files on your computer.",
])
def test_a_fast_reply_that_says_it_cannot_act_escalates(reply):
    assert wants_escalation(reply) is True


@pytest.mark.parametrize("reply", [
    "Hello! How can I help you today?",
    "I can't wait to hear how it goes.",
    "2 + 2 is 4.",
    "You can open the file from the menu.",
])
def test_ordinary_fast_replies_do_not_escalate(reply):
    assert wants_escalation(reply) is False


# --- integration with ChatService ---------------------------------------------

@patch("chat_service.Router")
def test_fast_path_answers_in_one_call(mock_router_class):
    mock_router = MagicMock()
    mock_router.chat.return_value = ("Hello!", "test_provider")
    mock_router_class.return_value = mock_router

    service = ChatService(enable_tools=True)
    response, _ = service.chat("hi")

    assert response == "Hello!"
    assert mock_router.chat.call_count == 1


@patch("chat_service.Router")
def test_fast_path_sends_a_lean_prompt(mock_router_class):
    """The whole point: skip the ~8KB tool-schema system prompt."""
    mock_router = MagicMock()
    mock_router.chat.return_value = ("Hello!", "test_provider")
    mock_router_class.return_value = mock_router

    service = ChatService(enable_tools=True)
    service.chat("hi")

    sent = mock_router.chat.call_args[0][0]
    assert len(sent) == 2  # system + user, nothing else
    assert sum(len(m["content"]) for m in sent) < 1000
    assert len(service.system_prompt) > 4000  # the full one is still much larger


@patch("chat_service.Router")
def test_fast_path_still_says_which_account_it_works_in(mock_router_class, monkeypatch):
    """The account's purpose rides along like the personality does: short turns are most of them."""
    import local_accounts

    monkeypatch.setattr(local_accounts, "purpose_note", lambda: "ACCOUNT-NOTE-MARKER")
    mock_router = MagicMock()
    mock_router.chat.return_value = ("Hello!", "test_provider")
    mock_router_class.return_value = mock_router

    ChatService(enable_tools=True).chat("hi")

    sent = mock_router.chat.call_args[0][0]
    assert [m["role"] for m in sent] == ["system", "system", "user"]
    assert sent[1]["content"] == "[This account]\nACCOUNT-NOTE-MARKER"


@patch("chat_service.Router")
def test_fast_path_escalates_when_the_model_asks(mock_router_class):
    """A model that says it needs tools must get the full pipeline, same turn."""
    mock_router = MagicMock()
    mock_router.chat.side_effect = [
        (ESCALATION_SENTINEL, "test_provider"),
        ("The real answer.", "test_provider"),
    ]
    mock_router_class.return_value = mock_router

    service = ChatService(enable_tools=True)
    response, _ = service.chat("hi")

    assert response == "The real answer."
    assert mock_router.chat.call_count == 2


@patch("chat_service.Router")
def test_escalation_leaves_no_trace_of_the_abandoned_attempt(mock_router_class):
    mock_router = MagicMock()
    mock_router.chat.side_effect = [
        (ESCALATION_SENTINEL, "test_provider"),
        ("The real answer.", "test_provider"),
    ]
    mock_router_class.return_value = mock_router

    service = ChatService(enable_tools=True)
    service.chat("hi")

    assert not any(
        ESCALATION_SENTINEL in m.get("content", "")
        for m in service.conversation_history
    )


@patch("chat_service.Router")
def test_fast_path_is_on_by_default(mock_router_class):
    """Auto is the default; no setting change should be needed."""
    mock_router_class.return_value = MagicMock()
    assert ChatService(enable_tools=True).speed_mode is SpeedMode.AUTO
