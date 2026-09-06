"""Tests for the dynamic auto multi-approach system."""

from approaches import APPROACHES, build_multi_approach_prompt, get_approach, try_approaches


def test_get_approach_defaults_to_auto():
    appr = get_approach("auto")
    assert appr.name == "auto"
    assert "strategy" in appr.instruction.lower()

    # Unknown approaches gracefully default to auto
    unknown = get_approach("nonexistent_approach")
    assert unknown.name == "auto"


def test_build_multi_approach_prompt():
    prompt = build_multi_approach_prompt("Write a binary search function in Python", "auto")
    assert "MULTI-APPROACH PROTOCOL: AUTO" in prompt
    assert "Write a binary search function" in prompt


def test_try_approaches_executes_fallback():
    calls = []

    def mock_solver(text: str) -> str:
        calls.append(text)
        if len(calls) == 1:
            raise ValueError("First approach failed")
        return "Success on second approach"

    result, used_approach = try_approaches("Test task", mock_solver, ["step_by_step", "direct"])
    assert result == "Success on second approach"
    assert used_approach == "direct"
    assert len(calls) == 2
