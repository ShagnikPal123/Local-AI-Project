"""The notch keeps the page's voice state, never starts a window by itself, and carries Back to chat."""

import notch


def test_state_is_kept_and_cleaned():
    notch.set_state("speaking", "x" * 500, True)
    status = notch.status()
    assert status["state"] == "speaking" and status["voice"] is True and len(status["text"]) == 160
    notch.set_state("nonsense")
    assert notch.status()["state"] == "idle"


def test_it_is_off_until_started():
    assert notch.status()["running"] is False


def test_fullscreen_check_never_raises():
    import notch_window

    assert notch_window._fullscreen_app_running() in (True, False)


def test_back_to_chat_reaches_an_open_page(monkeypatch):
    import agent_events

    seen = []
    monkeypatch.setattr(agent_events.BUS, "subscriber_count", lambda _channel=None: 1)
    monkeypatch.setattr(agent_events, "publish_ui", lambda kind, **payload: seen.append((kind, payload)))
    assert notch.open_app("chat")["page_open"] is True
    assert seen == [("notch.open-tab", {"tab": "chat"})]


# ── The white box: the window is clipped to the shapes the page draws ─────────


def test_island_outline_has_square_top_rounded_bottom_and_two_ears():
    import notch_window

    island = notch_window._clean_shape({"kind": "island", "x": 14, "y": 0, "w": 184, "h": 32, "r": 14})
    steps = notch_window.region_plan([island])
    body, left_ear, left_cut, right_ear, right_cut = steps
    assert body[:2] == ("add", "round") and body[3] < 0  # rounding pushed above the window: square top corners
    assert body[2] == 15 and body[4] == 197 and body[5] == 31  # one pixel inside the page's soft edge
    assert left_ear == ("add", "rect", 0, 0, 15, 14) and right_ear == ("add", "rect", 197, 0, 212, 14)
    # Each cut is a circle centred on the ear's outer bottom corner.
    assert (left_cut[1] + left_cut[3]) / 2 == 0 and (left_cut[2] + left_cut[4]) / 2 == 14
    assert (right_cut[1] + right_cut[3]) / 2 == 212 and (right_cut[2] + right_cut[4]) / 2 == 14


def test_outline_scales_with_the_screen_and_skips_empty_shapes():
    import notch_window

    pill = notch_window._clean_shape({"kind": "box", "x": 10, "y": 6, "w": 30, "h": 30, "r": 15})
    empty = notch_window._clean_shape({"kind": "island", "x": 0, "y": 0, "w": 0, "h": 0, "r": 14})
    assert notch_window.region_plan([pill, empty], scale=2.0) == [("add", "round", 20, 12, 80, 72, 60, 60)]


def test_bad_shapes_from_the_page_are_ignored():
    import notch_window

    notch_window._shapes[:] = []
    notch_window.Bridge().set_shape([{"kind": "rocket", "x": "1", "w": 5, "h": 5}, "nope", {"x": "bad"}])
    assert notch_window._shapes == []  # one bad number drops the whole report
    notch_window.Bridge().set_shape([{"kind": "rocket", "x": "1", "w": 5, "h": 5}])
    assert notch_window._shapes == [{"kind": "box", "x": 1.0, "y": 0.0, "w": 5.0, "h": 5.0, "r": 0.0}]
    notch_window._shapes[:] = []


class _FakeGdi:
    """Records region calls instead of drawing (no Windows needed)."""

    def __init__(self):
        self.calls = []
        self.next = 0

    def _make(self, name, *args):
        self.next += 1
        self.calls.append((name, args, self.next))
        return self.next

    def __getattr__(self, name):
        return lambda *args: self._make(name, *args)


def test_region_is_built_and_handed_to_the_window(monkeypatch):
    import notch_window

    gdi, user = _FakeGdi(), _FakeGdi()
    monkeypatch.setattr(notch_window, "_scale", lambda _hwnd: 1.0)
    island = notch_window._clean_shape({"kind": "island", "x": 14, "y": 0, "w": 184, "h": 32, "r": 14})
    assert notch_window._apply_region(42, [island], gdi32=gdi, user=user)
    names = [c[0] for c in gdi.calls]
    assert names.count("CombineRgn") == 5 and names.count("DeleteObject") == 5  # parts freed, the total is not
    assert user.calls[-1][0] == "SetWindowRgn" and user.calls[-1][1][0] == 42
    # No shapes (an older page) → the clip is removed, not left stale.
    assert notch_window._apply_region(42, [], gdi32=gdi, user=user)
    assert user.calls[-1][1] == (42, None, True)
