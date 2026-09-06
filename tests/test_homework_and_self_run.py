"""Tests for HomeworkHelper and SelfRunningSupervisor."""

import pytest
import time
from homework_helper import HomeworkHelper
from self_running import SelfRunningSupervisor


def test_homework_helper_subject_detection():
    """Test classification of subjects from problem statements."""
    assert HomeworkHelper.detect_subject("Find the derivative of f(x) = 3x^2 + 5x") == "math"
    assert HomeworkHelper.detect_subject("Calculate the velocity and force of a 10kg mass") == "physics"
    assert HomeworkHelper.detect_subject("Balance the chemical reaction of HCl and NaOH") == "chemistry"
    assert HomeworkHelper.detect_subject("Explain the time complexity and Big O of binary tree traversal") == "computer_science"


def test_homework_helper_decomposition():
    """Test problem breakdown into steps and Socratic hints."""
    res = HomeworkHelper.decompose_problem("Solve for x: 2x + 10 = 20")
    assert res["subject"] == "math"
    assert len(res["recommended_steps"]) >= 4
    assert len(res["hints"]) >= 2
    assert "Socratic" in res["socratic_prompt"]


def test_self_running_supervisor():
    """Test registering tasks, status inspection, and background execution."""
    supervisor = SelfRunningSupervisor(heartbeat_interval=0.05)

    counter = {"runs": 0}

    def sample_task():
        counter["runs"] += 1

    supervisor.register_task(
        task_id="test_task_1",
        name="Sample Heartbeat Job",
        handler=sample_task,
        interval_seconds=0.05,
    )

    status = supervisor.status()
    assert status["task_count"] == 1
    assert status["running"] is False

    supervisor.start()
    assert supervisor.is_running() is True

    time.sleep(0.18)
    supervisor.stop()
    assert supervisor.is_running() is False
    assert counter["runs"] >= 1
