"""Predict: framing, personas, rounds that move the swarm, events, report, chat — and failures that pause, not crash."""

import json

import pytest


@pytest.fixture()
def predict(tmp_path, monkeypatch):
    import predict as module

    monkeypatch.setattr(module, "_dir", lambda: tmp_path)
    monkeypatch.setattr(module, "_publish", lambda job: None)
    return module


def swarm_ask(convert_to="o1"):
    calls = []

    def ask(prompt, tokens):
        calls.append(prompt)
        if "prepare a forecasting simulation" in prompt:
            return json.dumps({"outcomes": [{"id": "x", "label": "Rain"}, {"id": "y", "label": "Sun"}],
                               "entities": [{"id": "e1", "name": "Weather office", "kind": "org"}], "relations": []})
        if prompt.startswith("Create "):
            n = int(prompt.split()[1])
            return json.dumps([{"name": f"P{i}", "role": "farmer", "traits": "careful", "lean": "o2", "confidence": 0.6}
                               for i in range(n)])
        if prompt.startswith("Simulate round"):
            ids = [line.split(":")[0].strip("- ").strip() for line in prompt.splitlines() if line.startswith("- a")]
            return json.dumps([{"id": i, "post": "Clouds are coming.", "lean": convert_to, "confidence": 0.9} for i in ids])
        if prompt.startswith("Summarise"):
            return "Everyone now expects rain."
        if "report analyst" in prompt:
            return "## Prediction\nRain, 80%."
        return "In character."
    return ask, calls


def test_a_quick_run_frames_populates_simulates_and_reports(predict):
    ask, calls = swarm_ask()
    job = predict.start("Will it rain tomorrow?", [{"kind": "text", "value": "Forecast notes"}], "quick", ask=ask, background=False)
    full = predict.load(job["id"])
    assert full["status"] == "done" and [o["label"] for o in full["outcomes"]] == ["Rain", "Sun"]
    assert len(full["agents"]) == 12 and full["round"] == 6
    assert full["probabilities"][0]["o2"] > 0.9 and full["probabilities"][-1]["o1"] > 0.9   # the swarm moved
    assert "Rain" in full["report"] and full["feed"]
    assert len(calls) <= predict.estimate_calls("quick")


def test_events_reach_the_next_round(predict):
    ask, calls = swarm_ask()
    job = predict.start("Q?", [], "quick", ask=lambda p, t: "{}", background=False)
    predict.inject(job["id"], "A storm warning is issued")
    assert predict.load(job["id"])["events"][0]["text"] == "A storm warning is issued"
    with pytest.raises(ValueError):
        predict.inject(job["id"], "  ")


def test_a_failing_model_marks_the_run_failed_with_a_reason(predict):
    def boom(prompt, tokens):
        raise RuntimeError("no model")
    job = predict.start("Q?", [], "quick", ask=boom, background=False)
    full = predict.load(job["id"])
    assert full["status"] == "failed" and "no model" in full["note"]


def test_chat_with_an_agent_and_the_analyst(predict):
    ask, _ = swarm_ask()
    job = predict.start("Will it rain?", [], "quick", ask=ask, background=False)
    assert predict.chat(job["id"], "a1", "Why?", ask=ask) == "In character."
    assert predict.chat(job["id"], "report", "How sure?", ask=lambda p, t: "Fairly.") == "Fairly."
    with pytest.raises(KeyError):
        predict.chat(job["id"], "a999", "?", ask=ask)


def test_bad_input(predict, tmp_path):
    with pytest.raises(ValueError):
        predict.start("  ", [], "quick", background=False)
    with pytest.raises(ValueError):
        predict.start("Q?", [], "galaxy", background=False)
    assert "not found" in predict.read_seed("path", str(tmp_path / "nope.txt"))["text"]
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"0" * 1000)
    assert "cannot transcribe" in predict.read_seed("path", str(video))["text"]


def test_recover_marks_a_running_job_paused(predict):
    job = predict.start("Q?", [], "quick", ask=lambda p, t: "{}", background=False)
    full = predict.load(job["id"])
    full["status"] = "running"
    predict._save(full)
    predict.recover()
    assert predict.load(job["id"])["status"] == "paused"
