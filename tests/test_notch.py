"""The notch keeps the page's voice state and never starts a window by itself."""

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
    assert notch._fullscreen_app_running() in (True, False)
