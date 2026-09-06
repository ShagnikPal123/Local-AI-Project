"""Overlay store, checkpoints, and self-revival (ROADMAP F1, F2, F3, AA10).

The property this layer exists for: the agent can change the app, but only by
adding a layer above it. It cannot reach the floor it stands on.
"""

import json

import pytest

from overlay import OverlayError, OverlayStore


@pytest.fixture
def overlay(tmp_path):
    return OverlayStore(tmp_path / "overlay.json")


# --- applying and reverting ----------------------------------------------------------

def test_an_unset_target_falls_through_to_the_shipped_default(overlay):
    assert overlay.get("settings", default="shipped") == "shipped"
    assert overlay.is_overridden("settings") is False


def test_applying_a_change_overrides_the_default(overlay):
    overlay.apply("settings", {"padding": 4}, change_id="c1", applied_by="owner@example.com")
    assert overlay.get("settings", default="shipped") == {"padding": 4}
    assert overlay.is_overridden("settings") is True


def test_reverting_returns_to_the_shipped_behaviour(overlay):
    """Reverting is deleting a layer, not un-editing a file."""
    overlay.apply("settings", {"padding": 4})
    assert overlay.revert("settings") is True
    assert overlay.get("settings", default="shipped") == "shipped"


def test_reverting_something_never_applied_reports_failure(overlay):
    assert overlay.revert("never-set") is False


def test_clearing_returns_everything_to_shipped(overlay):
    overlay.apply("a", 1)
    overlay.apply("b", 2)
    overlay.clear()
    assert overlay.list_entries() == []


# --- the agent cannot reach the floor it stands on --------------------------------------

@pytest.mark.parametrize("target", [
    "../server.py",
    "..\\auth.py",
    "some/path",
    "some\\path",
    "../../etc/passwd",
])
def test_a_target_that_escapes_the_overlay_is_refused(overlay, target):
    """The overlay is a flat namespace of app keys, not a filesystem path."""
    with pytest.raises(OverlayError):
        overlay.apply(target, "anything")


def test_an_empty_target_is_refused(overlay):
    with pytest.raises(OverlayError):
        overlay.apply("   ", "anything")


# --- checkpoints (F2) --------------------------------------------------------------------

def test_applying_takes_a_checkpoint_first(overlay):
    """There must always be a known-good state, including when the change breaks."""
    overlay.apply("settings", {"padding": 4})
    assert len(overlay.list_checkpoints()) >= 1


def test_reverting_also_checkpoints(overlay):
    overlay.apply("settings", {"padding": 4})
    before = len(overlay.list_checkpoints())
    overlay.revert("settings")
    assert len(overlay.list_checkpoints()) > before


def test_checkpoints_are_bounded(overlay):
    """A long-lived install must not accumulate snapshots forever."""
    for i in range(30):
        overlay.apply(f"target{i}", i)
    assert len(overlay.list_checkpoints()) <= 20


# --- self code revival (F3) ----------------------------------------------------------------

def test_a_bad_change_can_be_undone_by_restoring(overlay):
    overlay.apply("settings", {"good": True})
    overlay.apply("settings", {"broken": True})

    # The checkpoint taken before the second apply holds the good state.
    checkpoints = overlay.list_checkpoints()
    overlay.restore(checkpoints[0]["id"])
    assert overlay.get("settings") == {"good": True}


def test_restore_latest_returns_to_the_most_recent_checkpoint(overlay):
    overlay.apply("settings", {"good": True})
    overlay.apply("settings", {"broken": True})
    overlay.restore_latest()
    assert overlay.get("settings") == {"good": True}


def test_restoring_with_no_checkpoints_fails_clearly(overlay):
    with pytest.raises(OverlayError):
        overlay.restore_latest()


def test_restoring_an_unknown_checkpoint_fails_clearly(overlay):
    with pytest.raises(OverlayError):
        overlay.restore("not-a-real-checkpoint")


def test_a_corrupt_checkpoint_does_not_wipe_the_overlay(overlay):
    overlay.apply("settings", {"live": True})
    bad = overlay.checkpoint_dir / "corrupt.json"
    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(OverlayError):
        overlay.restore("corrupt")
    assert overlay.get("settings") == {"live": True}


# --- persistence ---------------------------------------------------------------------------

def test_the_overlay_survives_a_restart(tmp_path):
    path = tmp_path / "overlay.json"
    first = OverlayStore(path)
    first.apply("settings", {"padding": 4})

    second = OverlayStore(path)
    assert second.get("settings") == {"padding": 4}


def test_a_corrupt_overlay_file_falls_back_to_shipped_behaviour(tmp_path):
    """Losing overrides is recoverable; refusing to start is not."""
    path = tmp_path / "overlay.json"
    path.write_text("{ not json", encoding="utf-8")
    store = OverlayStore(path)
    assert store.list_entries() == []
    assert store.get("settings", default="shipped") == "shipped"


def test_an_unreadable_entry_does_not_discard_the_rest(tmp_path):
    path = tmp_path / "overlay.json"
    path.write_text(json.dumps({"entries": [
        {"target": "good", "value": 1},
        {"novalidtarget": True},
    ]}), encoding="utf-8")
    store = OverlayStore(path)
    assert [e["target"] for e in store.list_entries()] == ["good"]


def test_the_snapshot_reports_entries_and_checkpoints(overlay):
    overlay.apply("settings", {"padding": 4})
    snapshot = overlay.snapshot()
    assert snapshot["count"] == 1
    assert snapshot["checkpoints"]


def test_checkpoint_ordering_is_deterministic_within_one_second(overlay):
    """Filenames carry only whole seconds; ordering must not depend on the suffix.

    This is the case that matters most — rapid successive changes are exactly
    when someone reaches for "restore the latest".
    """
    for i in range(6):
        overlay.apply("settings", {"step": i})

    checkpoints = overlay.list_checkpoints()
    timestamps = [c["created_at"] for c in checkpoints]
    assert timestamps == sorted(timestamps, reverse=True)

    overlay.restore_latest()
    assert overlay.get("settings") == {"step": 4}
