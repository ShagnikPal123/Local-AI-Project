"""The hands-off sidebar's window: where it sits for a saved place, and where it docks when it is let go.

The window itself needs Windows and WebView2; these check the arithmetic that decides its spot, which is the part
that goes wrong (off screen, wrong side, wrong size at 150 %).
"""

import sidebar_window as sw


def test_a_docked_sidebar_sits_just_off_its_edge():
    assert sw.spot({"edge": "right", "y": 96}, 1920, 1080, 264, 600, 1.0) == (1920 - 264 - 12, 96)
    assert sw.spot({"edge": "left", "y": 96}, 1920, 1080, 264, 600, 1.0) == (12, 96)
    # At 150 % the window and the gap are 1.5x as many device pixels.
    assert sw.spot({"edge": "right", "y": 100}, 2880, 1620, 264, 600, 1.5) == (2880 - 396 - 18, 150)


def test_a_sidebar_never_lands_off_screen():
    assert sw.spot({"edge": "free", "x": 5000, "y": 5000}, 1920, 1080, 264, 600, 1.0) == (1920 - 264, 1080 - 600)
    assert sw.spot({"edge": "free", "x": -50, "y": -50}, 1920, 1080, 264, 600, 1.0) == (0, 0)


def test_letting_go_near_a_side_docks_it_and_elsewhere_floats():
    assert sw.dropped(20, 200, 1920, 1080, 264, 600, 1.0) == {"edge": "left", "y": 200}
    assert sw.dropped(1920 - 264 - 30, 200, 1920, 1080, 264, 600, 1.0) == {"edge": "right", "y": 200}
    assert sw.dropped(700, 200, 1920, 1080, 264, 600, 1.0) == {"edge": "free", "x": 700, "y": 200}
    # Saved in CSS pixels, so the spot survives a change of display scale.
    assert sw.dropped(1050, 300, 2880, 1620, 264, 600, 1.5) == {"edge": "free", "x": 700, "y": 200}


def test_a_locked_sidebar_does_not_start_a_drag(monkeypatch):
    monkeypatch.setattr(sw, "_save", lambda changes: None)
    bridge = sw.Bridge()
    bridge.set_lock(True)
    assert bridge.drag_start() is False
    assert bridge.place()["locked"] is True
    bridge.set_lock(False)
