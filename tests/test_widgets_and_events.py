"""HUD widgets and the system event log (ROADMAP DD6-DD12)."""

import json

import pytest

from event_log import EventLevel, EventLog
from widgets import WidgetStore, WidgetType


# --- event log ----------------------------------------------------------------------

@pytest.fixture
def log():
    return EventLog(capacity=5)


def test_events_are_recorded_newest_last(log):
    log.record("first")
    log.record("second")
    messages = [e["message"] for e in log.tail()]
    assert messages == ["first", "second"]


def test_the_log_is_bounded(log):
    """An unbounded log in a long-running local process is a slow memory leak."""
    for i in range(20):
        log.record(f"event {i}")
    assert len(log.tail(limit=100)) == 5
    assert log.tail()[-1]["message"] == "event 19"


def test_total_recorded_counts_beyond_the_buffer(log):
    for i in range(20):
        log.record(f"event {i}")
    assert log.snapshot()["total_recorded"] == 20


def test_events_can_be_filtered_by_level(log):
    log.record("fine", level=EventLevel.OK)
    log.record("bad", level=EventLevel.ERROR)
    assert [e["message"] for e in log.tail(level=EventLevel.ERROR)] == ["bad"]


def test_each_event_carries_a_readable_time(log):
    log.record("something")
    assert ":" in log.tail()[0]["time"]


def test_logging_never_raises_on_bad_input(log):
    """Logging must not be able to break the thing it is observing."""
    log.record(None)          # type: ignore[arg-type]
    log.record("x" * 10_000)  # oversized
    assert len(log.tail()) == 2


def test_oversized_messages_are_truncated(log):
    log.record("x" * 10_000)
    assert len(log.tail()[0]["message"]) <= 240


# --- widget store ---------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    return WidgetStore(tmp_path / "widgets.json")


def test_a_fresh_store_installs_a_sensible_default_layout(store):
    types = [w["type"] for w in store.list_widgets()]
    assert "system" in types and "agents" in types


def test_widgets_can_be_added_and_removed(store):
    widget = store.add(WidgetType.FINANCE, "Markets")
    assert any(w["id"] == widget.widget_id for w in store.list_widgets())
    assert store.remove(widget.widget_id) is True
    assert not any(w["id"] == widget.widget_id for w in store.list_widgets())


def test_removing_an_unknown_widget_reports_failure(store):
    assert store.remove("nope") is False


def test_a_tab_widget_requires_a_target(store):
    """A widget bound to nothing is a blank box, not a feature."""
    with pytest.raises(ValueError):
        store.add(WidgetType.TAB)


def test_a_prompt_widget_requires_a_target(store):
    with pytest.raises(ValueError):
        store.add(WidgetType.PROMPT, config={"target": "   "})


def test_a_bound_widget_keeps_its_target(store):
    widget = store.add(WidgetType.TAB, "Models", {"target": "models"})
    assert widget.as_dict()["config"]["target"] == "models"


def test_reordering_changes_the_order(store):
    ids = [w["id"] for w in store.list_widgets()]
    reordered = store.reorder(list(reversed(ids)))
    assert [w["id"] for w in reordered] == list(reversed(ids))


def test_reordering_keeps_widgets_not_named_in_the_request(store):
    ids = [w["id"] for w in store.list_widgets()]
    result = store.reorder([ids[-1]])
    assert len(result) == len(ids)


def test_layout_persists_across_restarts(tmp_path):
    """A user's arrangement must survive the app closing."""
    path = tmp_path / "widgets.json"
    first = WidgetStore(path)
    first.add(WidgetType.FINANCE, "Markets")
    saved = [w["type"] for w in first.list_widgets()]

    second = WidgetStore(path)
    assert [w["type"] for w in second.list_widgets()] == saved


def test_a_corrupt_layout_file_falls_back_to_defaults(tmp_path):
    """The user loses their arrangement, not the application."""
    path = tmp_path / "widgets.json"
    path.write_text("{ this is not json", encoding="utf-8")
    store = WidgetStore(path)
    assert len(store.list_widgets()) == 4


def test_an_unreadable_entry_does_not_discard_the_whole_layout(tmp_path):
    path = tmp_path / "widgets.json"
    path.write_text(json.dumps({"widgets": [
        {"id": "good", "type": "system", "title": "System", "position": 0},
        {"id": "bad", "type": "not_a_real_type", "position": 1},
    ]}), encoding="utf-8")
    store = WidgetStore(path)
    types = [w["type"] for w in store.list_widgets()]
    assert types == ["system"]


def test_reset_restores_the_default_layout(store):
    store.add(WidgetType.FINANCE, "Markets")
    assert len(store.reset()) == 4


def test_available_types_flag_which_need_a_target(store):
    needs = {t["type"] for t in store.available_types() if t["needs_target"]}
    assert needs == {"tab", "prompt"}


def test_every_available_type_is_described(store):
    assert all(t["description"].strip() for t in store.available_types())
