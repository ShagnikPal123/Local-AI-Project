"""The scoreboard checks answers mechanically and records every run as it was."""

from identity0 import evaluate


def test_checks_grade_without_any_model():
    items = {i["q"]: i["check"] for i in evaluate.SUITES["core"]}
    assert items["What is 17 times 23? Answer with the number."]("It is 391.") == 1.0
    assert items["What is 17 times 23? Answer with the number."]("About 400") == 0.0
    assert items["Reply with exactly three words describing the sea."]("Vast, deep, blue.") == 1.0
    add = items["Write a Python function named add that returns the sum of two numbers."]
    assert add("```python\ndef add(a, b):\n    return a + b\n```") == 1.0 and add("def add(:") == 0.0
    weather = items["What's the weather in Chicago right now?"]
    assert weather('<tool_call>{"name": "get_weather", "arguments": {"city": "Chicago"}}</tool_call>') == 1.0


def test_a_run_is_scored_and_lands_on_the_scoreboard():
    def perfect(member, messages, **kwargs):
        q = messages[-1]["content"]
        canned = {"capital of France": "Paris", "17 times 23": "391"}
        return {"ok": True, "ms": 5, "text": next((v for k, v in canned.items() if k in q), "")}

    row = evaluate.run("ollama:fake", limit=7, complete=perfect)
    assert row["n"] == 7 and 0 < row["score"] < 1 and row["by_category"]["facts"] > 0
    board = evaluate.scoreboard()
    assert board[0]["member"] == "ollama:fake" and "details" not in board[0]


def test_a_scoreboard_run_teaches_the_competence_table(monkeypatch):
    """The exam is the one signal that needs no judge: what it shows should not have to be relearned."""
    from identity0 import competence, evaluate, members

    def answer(member, messages, **kwargs):
        question = messages[-1]["content"]
        good = "def add(a, b):\n    return a + b" if "add" in question else "def is_even(n):\n    return n % 2 == 0"
        return {"member": member, "text": good, "ok": True, "ms": 10}

    evaluate.run("ollama:coder", "core", complete=answer)
    table = competence.table()["domains"]
    assert table["code"]["ollama:coder"]["exam"] == 1.0, "the code questions were answered perfectly"
    assert table["knowledge"]["ollama:coder"]["exam"] == 0.0, "the fact questions were not"

    coder = members.Member("ollama:coder", "ollama", "coder", True, True, False, "coder")
    other = members.Member("ollama:other", "ollama", "other", True, True, False, "other")
    assert competence.rank("code", [other, coder])[0].id == "ollama:coder"
