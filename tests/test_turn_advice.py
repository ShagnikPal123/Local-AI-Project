"""A message typed while Nyx answers: queue, interrupt, run alongside or branch (Request G12)."""

from turn_advice import advise, rule_advice

RUNNING = "Write a Python script that renames every photo in my Downloads folder by date"


def test_corrections_interrupt_and_follow_ups_queue():
    assert rule_advice("no, only the jpg files instead", RUNNING)["mode"] == "interrupt"
    assert rule_advice("then zip them and put the zip on my desktop", RUNNING)["mode"] == "queue"


def test_unrelated_tasks_run_alongside_and_alternatives_branch():
    assert rule_advice("what's the weather in Tokyo tomorrow", RUNNING)["mode"] == "parallel"
    assert rule_advice("what if we tried renaming the photos by location", RUNNING)["mode"] == "branch"


def test_every_answer_carries_a_reason_and_rules_work_offline():
    result = advise("then email it to me", RUNNING, use_model=False)
    assert result["mode"] == "queue" and result["source"] == "rules" and result["reason"]


def test_additions_fold_into_the_running_task_unless_it_stopped_listening():
    """Active speech: "also…" / "make sure…" adds to the task running now instead of waiting for it."""
    assert rule_advice("also make sure the photos keep their original names in a log", RUNNING)["mode"] == "fold"
    assert rule_advice("don't forget the png files", RUNNING)["mode"] == "fold"
    assert advise("also do the png files", RUNNING, use_model=False)["mode"] == "fold"
    assert advise("also do the png files", RUNNING, use_model=False, listening=False)["mode"] == "queue"
