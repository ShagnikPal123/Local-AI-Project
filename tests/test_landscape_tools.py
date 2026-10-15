"""Opening a tab by whatever name the owner (or the model) uses.

Fixer Upper S39 (owner, 2026-10-13): "I ask for it to open a tab and it has issues … I ask for it to navigate me
to finances and it has an issue." ui_open_tab only matched an exact label, so "Finances" came back "No tab called".
"""

from __future__ import annotations

import pytest

import landscape_tools


@pytest.fixture
def opened(monkeypatch):
    events = []
    monkeypatch.setattr(landscape_tools, "_publish", lambda kind, **payload: events.append((kind, payload)))
    monkeypatch.setattr(landscape_tools, "_find_user_tab", lambda name: None)
    return events


@pytest.mark.parametrize("name", ["Finances", "finance", "the finances tab", "Finance page", "money", "stocks",
                                  "Trading", "trading"])
def test_every_name_for_the_money_tab_says_where_trading_went(opened, name):
    result = landscape_tools.tool_ui_open_tab(name)
    assert opened == [], result
    assert result == landscape_tools.MOVED["trading"] and "Ichos Trader" in result


@pytest.mark.parametrize("name, tab_id", [
    ("Orbits", "scheduled"), ("calendar", "scheduled"), ("Constellations", "projects"), ("projects", "projects"),
    ("Fractal", "design"), ("design studio", "design"), ("Quasars", "artifacts"), ("Predict", "predict"),
    ("research lab", "research"), ("settings", "settings"), ("Office & World", "office"), ("chat", "nyx"),
])
def test_tabs_added_since_and_their_old_names_open(opened, name, tab_id):
    landscape_tools.tool_ui_open_tab(name)
    assert opened == [("ui.open_tab", {"tab_id": tab_id})]


def test_an_unknown_name_says_so_and_lists_what_exists(opened, monkeypatch):
    monkeypatch.setattr(landscape_tools, "tool_ui_list_tabs", lambda: "Built-in tabs: Chat, Trading")
    result = landscape_tools.tool_ui_open_tab("bluetooth")
    assert result.startswith("No tab called 'bluetooth'") and "Trading" in result
    assert opened == []


def test_the_owners_own_tab_with_that_exact_name_wins(monkeypatch):
    events = []
    monkeypatch.setattr(landscape_tools, "_publish", lambda kind, **payload: events.append(payload))
    mine = type("Spec", (), {"tab_id": "my-money", "label": "Money"})()
    monkeypatch.setattr(landscape_tools, "_find_user_tab", lambda name: mine)
    assert landscape_tools.tool_ui_open_tab("Money") == "Opened the Money tab."
    assert events == [{"tab_id": "my-money"}]


def test_every_alias_points_at_a_real_tab_or_says_where_it_moved():
    real = set(landscape_tools.CORE_TABS) | set(landscape_tools.MOVED)
    assert set(landscape_tools.TAB_ALIASES.values()) <= real
