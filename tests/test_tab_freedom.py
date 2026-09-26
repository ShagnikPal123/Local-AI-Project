"""Tabs you can really change: backgrounds, text boxes, trackers, timers, AI tasks, games (Request H16)."""

from __future__ import annotations

import pytest

from dynamic_tabs import TabSpecError, TabStore, build_spec


def test_new_blocks_are_validated_data_with_safe_defaults():
    spec = build_spec("Study", [
        {"type": "timer", "title": "Focus", "config": {"minutes": 9999, "mode": "pomodoro", "ai_prompt": "Quiz me on what I studied"}},
        {"type": "tracker", "title": "Hours", "config": {"unit": "h", "goal": "20"}},
        {"type": "ai_task", "title": "News", "config": {"prompt": "3 headlines", "every_minutes": 2}},
        {"type": "competition", "title": "Duel", "config": {"game": "chess"}},
        {"type": "game", "title": "Break", "config": {"game": "snake"}},
        {"type": "chart", "title": "Grades", "config": {}},
        {"type": "list", "title": "Readings", "config": {"items": ["Ch 1", "Ch 2"]}},
    ])
    configs = {b.type.value: b.config for b in spec.blocks}
    assert configs["timer"] == {"mode": "pomodoro", "minutes": 600, "ai_prompt": "Quiz me on what I studied"}
    assert configs["tracker"]["goal"] == 20 and configs["tracker"]["kind"] == "number"
    assert configs["ai_task"]["every_minutes"] == 0          # under 5 minutes means "only when asked"
    assert configs["competition"]["game"] == "tictactoe"     # unknown games fall back to a shipped one
    assert configs["chart"]["chart"]["type"] == "bar"
    assert configs["list"]["items"] == ["Ch 1", "Ch 2"]


def test_backgrounds_and_text_boxes_accept_pictures_colours_and_gradients_but_never_css():
    ok = build_spec("Game", [{"type": "game", "title": "Snake"}],
                    background={"kind": "image", "value": "/api/uploads/abc123", "dim": 2},
                    theme={"surface": "glass", "font": "mono", "text": "#EAFFEA", "radius": 99})
    assert ok.background == {"kind": "image", "value": "/api/uploads/abc123", "dim": 0.9, "blur": 0}
    assert ok.theme == {"surface": "glass", "font": "mono", "text": "#EAFFEA", "radius": 28}
    assert build_spec("G", [{"type": "text"}], background={"kind": "gradient", "colors": ["#101820", "#FEE715"]}).background["angle"] == 135
    for bad in ({"kind": "image", "value": "javascript:alert(1)"}, {"kind": "image", "value": "url(x) ; color:red"},
                {"kind": "color", "value": "red; position:fixed"}, {"kind": "video", "value": "x"}):
        with pytest.raises(TabSpecError):
            build_spec("Bad", [{"type": "text"}], background=bad)
    with pytest.raises(TabSpecError):
        build_spec("Bad", [{"type": "text"}], theme={"text": "expression(alert(1))"})


def test_background_and_theme_survive_updates_and_reloads(tmp_path):
    store = TabStore(path=tmp_path / "tabs.json")
    spec = store.create(build_spec("Arcade", [{"type": "game", "title": "Memory", "config": {"game": "memory"}}]))
    updated = store.update(spec.tab_id, request="neon arcade look",
                           background={"kind": "gradient", "colors": ["#0B0033", "#FF00AA"]}, theme={"surface": "clear"})
    assert "background changed" in updated.edits[-1].summary and "text boxes restyled" in updated.edits[-1].summary
    again = TabStore(path=tmp_path / "tabs.json").get(spec.tab_id)
    assert again.background["colors"] == ["#0B0033", "#FF00AA"] and again.theme == {"surface": "clear"}


def test_the_model_may_propose_backgrounds_and_themes():
    from tab_editor import parse_edit_reply

    changes = parse_edit_reply('{"background": {"kind": "color", "value": "#112233"}, "theme": {"font": "rounded"}, "script": "x"}')
    assert set(changes) == {"background", "theme"}
