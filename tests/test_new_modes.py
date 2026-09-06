"Tests for expanded modes and response approaches."""

from unittest.mock import MagicMock, patch
from multi_mode_chat import MultiModeChat
from agent_pool import AgentMode

def test_new_agent_modes_exist():
    assert AgentMode.RESEARCH.value == "research"
    assert AgentMode.CODING.value == "coding"
    assert AgentMode.SUPER_RESEARCH.value == "super_research"
    assert AgentMode.SELF_IMPROVE.value == "self_improve"

def test_approach_is_added_to_task():
    chat = MultiModeChat(use_pool=True)
    chat.pool = MagicMock()
    result = MagicMock(response="answer", provider="provider", mode=AgentMode.RESEARCH, agent_id="agent", processing_time=0.1)
    chat.pool.process_task.return_value = result
    chat.chat("compare options", force_mode="research", approach="alternatives")
    task = chat.pool.process_task.call_args.args[0]
    assert "multiple viable approaches" in task
