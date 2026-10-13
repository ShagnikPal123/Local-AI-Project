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
