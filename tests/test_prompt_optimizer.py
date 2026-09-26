"""Prompt optimizer: the sensor keeps simple things simple, the checker never lets a rewrite lose anything."""

from __future__ import annotations

import json

import pytest

import prompt_optimizer as po


@pytest.fixture()
def optimizer(tmp_path):
    replies = {"text": ""}

    def model_fn(prompt, system="", timeout=8):
        if not replies["text"]:
            raise RuntimeError("offline")
        return replies["text"], "stub · model"

    opt = po.PromptOptimizer(settings_path=tmp_path / "po.json", model_fn=model_fn)
    return opt, replies


@pytest.mark.parametrize("text", ["what time is it", "open notepad", "hi", "set volume to 30%", "What is the capital of France?",
                                  "play some lofi music", "thanks!"])
def test_simple_requests_are_left_exactly_alone(optimizer, text):
    opt, _ = optimizer
    result = opt.optimize(text)
    assert result.mode == "keep" and result.model_text == text and not result.changed


@pytest.mark.parametrize("text, category", [("make this all", "make"), ("build me a website for my bakery", "make"),
                                            ("fix it", "fix"), ("research the best budget laptops", "research")])
def test_short_big_tasks_expand_offline_with_context(optimizer, text, category):
    opt, _ = optimizer
    result = opt.optimize(text, {"recent_topic": "the landing page hero in site/index.html", "tab": "Chat"})
    assert result.mode == "expand" and result.engine == "rules" and result.changed
    assert result.optimized.startswith(f"Goal: {text}")
    assert po._DELIVERABLES[category] in result.optimized
    assert result.model_text.startswith(text + "\n\n<optimized_request")
    assert "the owner's own words win" in result.model_text


def test_long_request_is_polished_keeping_every_specific(optimizer):
    opt, _ = optimizer
    text = ("I want you to basically redesign the settings page. It must keep the dark theme and dont remove the voices "
            "section. The page is frontend/src/panels/SettingsPanel.tsx and should load in under 200ms. Make sure the "
            "toggles are 44px tall with Apple style switches and sticky section headers while scrolling. Include keyboard "
            "navigation for every control so people without a mouse can use it fully, and never show raw JSON anywhere.")
    result = opt.optimize(text)
    assert result.mode == "polish" and result.checks["passed"]
    for span in ("SettingsPanel.tsx", "200ms", "44px", "dont remove the voices", "never show raw JSON"):
        assert span in result.optimized
    assert "basically" not in result.optimized


def test_online_rewrite_used_when_it_passes_the_checker(optimizer):
    opt, replies = optimizer
    replies["text"] = json.dumps({"optimized": "Goal: Build a website for the bakery “Rise & Shine”. Constraint: do not use purple.",
                                  "assumptions": ["a full site, not one page"]})
    result = opt.optimize("build me a website for my bakery called Rise & Shine, dont use purple")
    assert result.engine == "stub · model" and "do not use purple" in result.optimized
    assert result.assumptions == ["a full site, not one page"]


def test_online_rewrite_that_drops_a_negation_or_specific_falls_back(optimizer):
    opt, replies = optimizer
    replies["text"] = json.dumps({"optimized": "Goal: Build a colourful bakery website with purple accents."})
    result = opt.optimize("build me a website for my bakery called Rise & Shine, dont use purple")
    assert result.engine == "rules" and "online rewrite rejected" in result.assumptions[0]
    assert "Rise & Shine" in result.optimized


def test_checker_flags_answering_and_losses():
    report = po.check("email bob@x.com the 3 files by 5pm, don't cc Sam Lee", "Sure! Here is the email.", "polish")
    assert not report["passed"]
    notes = " ".join(report["notes"])
    assert "lost" in notes and "answering" in notes and "don't" in notes


def test_disabled_does_nothing_but_preview_still_works(optimizer):
    opt, _ = optimizer
    opt.update_settings(enabled=False)
    assert opt.optimize("make this all").mode == "keep"
    assert opt.optimize("make this all", force=True).mode == "expand"


def test_thumbs_down_makes_the_sensor_conservative(optimizer):
    opt, _ = optimizer
    for i in range(3):
        result = opt.optimize("make this better", turn_id=f"t{i}")
        assert result.mode == "expand"
        assert opt.feedback(f"t{i}", -1)
    assert opt.optimize("make this better").mode == "keep"
    assert "marked unhelpful" in opt.optimize("make this better").reason


def test_turn_sends_the_overlay_but_stores_the_owners_words(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    import turn_runner

    opt = po.PromptOptimizer(settings_path=tmp_path / "po.json", model_fn=lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(po, "OPTIMIZER", opt)
    service = MagicMock()
    service.conversation_history = [{"role": "assistant", "content": "Here is the hero section draft."}]
    events = []
    runner = turn_runner.TurnRunner(service, "make this all", sink=events.append)
    text = runner._optimize_prompt("make this all", [], "")
    assert text.startswith("make this all\n\n<optimized_request") and "Here is the hero section draft." in text
    optimized = [e for e in events if e["type"] == "prompt.optimized"][0]
    assert optimized["mode"] == "expand" and optimized["original"] == "make this all" and "model_text" not in optimized
