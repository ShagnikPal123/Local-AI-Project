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


# ── Approvals and question cards pop the notch open ──────────────────────────


class _FakeChats:
    def __init__(self, chats):
        self.chats = chats

    def summaries(self):
        return [{"id": cid, "title": c["title"], "updated_at": c["at"]} for cid, c in self.chats.items()]

    def messages(self, chat_id):
        return self.chats[chat_id]["messages"]


CARD = '```question\n{"question": "Which folder?", "options": [{"label": "Desktop"}, {"label": "Documents"}]}\n```'


def test_an_unanswered_question_card_is_waiting():
    store = _FakeChats({
        "a1": {"title": "Sort files", "at": "2026-10-14T10:00:00+00:00",
               "messages": [{"role": "user", "content": "sort"}, {"role": "assistant", "content": "Sure.\n" + CARD}]},
        "b2": {"title": "Answered", "at": "2026-10-14T09:59:00+00:00",
               "messages": [{"role": "assistant", "content": CARD}, {"role": "user", "content": "Desktop"}]},
        "c3": {"title": "Plain", "at": "2026-10-14T09:58:00+00:00", "messages": [{"role": "assistant", "content": "Hi"}]},
    })
    from datetime import datetime

    now = datetime.fromisoformat("2026-10-14T10:05:00+00:00").timestamp()
    items = notch.open_questions(store, now)
    assert [i["chat_id"] for i in items] == ["a1"]
    assert items[0]["title"] == "Which folder?" and items[0]["id"] == "q:a1:2" and len(items[0]["card"]["options"]) == 2
    # Hours later it is no longer news.
    assert notch.open_questions(store, now + notch.QUESTION_WINDOW_S + 600) == []


def test_waiting_merges_approvals_and_questions_newest_first(monkeypatch):
    import routes_equalize

    monkeypatch.setattr(routes_equalize, "needs_you", lambda: [{"kind": "approval", "id": "p1", "title": "Run it?", "since": 50}])
    monkeypatch.setattr(notch, "open_questions", lambda store=None, now=None: [{"kind": "question", "id": "q", "since": 90}])
    assert [i["id"] for i in notch.waiting()] == ["q", "p1"]

    def broken(*_a, **_k):
        raise RuntimeError("store missing")

    monkeypatch.setattr(notch, "open_questions", broken)
    assert [i["id"] for i in notch.waiting()] == ["p1"]  # one broken source never hides the others


# ── Waking opens the notch ───────────────────────────────────────────────────


def test_voice_switching_on_is_a_wake_but_staying_on_is_not():
    notch.set_state("idle", "", False)
    before = notch.status()["woke"]
    notch.set_state("listening", "", True)
    first = notch.status()["woke"]
    assert first > before
    notch.set_state("thinking", "hi", True)
    assert notch.status()["woke"] == first  # still on: no second wake
    notch.set_state("idle", "", False)


def test_a_heard_wake_phrase_opens_it_listening():
    state = notch.wake("phrase: wake up")
    assert state["state"] == "listening" and state["woke"] > 0 and state["source"] == "phrase: wake up"
    notch.set_state("idle")


# ── Hands-off: the sidebar asks through the notch, and voice is switched only when it needs to be ─────


def test_hands_off_asks_the_page_to_switch_voice_only_when_it_differs(monkeypatch):
    import agent_events

    sent = []
    monkeypatch.setattr(agent_events, "publish_ui", lambda kind, **payload: sent.append(kind))
    notch.set_state("idle", "", False)
    assert notch.hands_off(True) == {"on": True, "was": False} and sent == ["voice.toggle"]
    notch.set_state("listening", "", True)
    notch.hands_off(True)
    assert sent == ["voice.toggle"]  # already on: nothing to flip
    notch.hands_off(False)
    assert sent == ["voice.toggle", "voice.toggle"]
    notch.set_state("idle", "", False)


def test_typed_in_the_sidebar_reaches_the_notch():
    import pytest

    asked = notch.ask("  open my budget sheet  ")
    assert asked["text"] == "open my budget sheet" and notch.status()["ask"]["at"] == asked["at"]
    with pytest.raises(ValueError):
        notch.ask("   ")


def test_the_picked_tab_is_kept_for_the_sidebar(monkeypatch):
    import agent_events

    monkeypatch.setattr(agent_events.BUS, "subscriber_count", lambda _channel=None: 1)
    monkeypatch.setattr(agent_events, "publish_ui", lambda kind, **payload: None)
    notch.open_app("trading")
    assert notch.status()["tab"]["id"] == "trading" and notch.status()["tab"]["by"] == "you"


def test_the_sidebar_is_off_until_started():
    assert notch.sidebar_running() is False


# ── Dragging the notch along the top edge ─────────────────────────────────────


def test_drag_keeps_the_notch_on_screen_and_snaps_to_the_middle():
    import notch_window

    # 1920 px screen at 100%: the cursor grabbed the notch at its centre.
    assert notch_window.drag_offset(960 + 25, 0, 1920, 1.0, 640) == 0.0  # near the middle: back to the middle
    assert notch_window.drag_offset(960 + 300, 0, 1920, 1.0, 640) == 300
    assert notch_window.drag_offset(5000, 0, 1920, 1.0, 640) == 640  # (1920 - 640) / 2: the edge, not off screen
    # At 150 % the same CSS distance is 1.5x the device pixels; a grab right of centre is kept.
    assert notch_window.drag_offset(1440 + 450 + 30, 30, 2880, 1.5, 640) == 300


def test_a_locked_notch_does_not_start_a_drag(monkeypatch):
    import notch_window

    monkeypatch.setattr(notch_window, "_post", lambda path, body: None)
    bridge = notch_window.Bridge()
    bridge.set_lock(True)
    assert bridge.drag_start() is False and notch_window._drag["on"] is False
    bridge.set_lock(False)
    assert bridge.place()["locked"] is False
