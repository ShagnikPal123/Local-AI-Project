"""Computer control: every real input is replaced — nothing moves, clicks or types here."""

from __future__ import annotations

import io
import time

import pytest
from fastapi.testclient import TestClient

import computer_control as cc
import cursor_overlay
from tools import ToolRegistry

pytestmark = pytest.mark.skipif(not cc.IS_WINDOWS, reason="Win32 input structures")


@pytest.fixture()
def desk(monkeypatch):
    """A fake 2560×1600 desktop with a fake cursor, input log, overlay log and event log."""
    fresh = cc._State()
    fresh.watcher = object()  # never start the real watcher thread in tests
    monkeypatch.setattr(cc, "STATE", fresh)
    cursor = {"pos": (1000, 800)}
    sent, moves, overlay, events = [], [], [], []

    def set_cursor(x, y):
        cursor["pos"] = (x, y)
        moves.append((x, y))

    monkeypatch.setattr(cc, "_send", lambda inputs: sent.append(list(inputs)))
    monkeypatch.setattr(cc, "_set_cursor", set_cursor)
    monkeypatch.setattr(cc, "_get_cursor", lambda: cursor["pos"])
    monkeypatch.setattr(cc, "_key_down", lambda vk: False)
    monkeypatch.setattr(cc, "_overlay_send", overlay.append)
    monkeypatch.setattr(cc, "screen_bounds", lambda max_age=3.0: {"left": 0, "top": 0, "width": 2560, "height": 1600,
                                                                   "monitors": [{"x": 0, "y": 0, "width": 2560, "height": 1600, "primary": True}]})
    monkeypatch.setattr(cc, "_publish", lambda type_, **payload: events.append({"type": type_, **payload}))
    monkeypatch.setattr(cc.time, "sleep", lambda s: None)
    return {"cursor": cursor, "sent": sent, "moves": moves, "overlay": overlay, "events": events, "state": fresh}


def _keys(batch):
    return [(i.ki.wVk, i.ki.wScan, i.ki.dwFlags) for i in batch]


def test_key_names_parse_and_unknown_ones_are_explained():
    assert cc.parse_keys("Ctrl + Shift + S") == [0x11, 0x10, 0x53]
    assert cc.parse_keys("alt+f4") == [0x12, 0x73]
    with pytest.raises(cc.ComputerError, match="Unknown key 'hyper'"):
        cc.parse_keys("hyper+x")


def test_shortcut_holds_modifiers_around_the_key(desk):
    cc.press_keys("ctrl+shift+s")
    assert _keys(desk["sent"][0]) == [(0x11, 0, 0), (0x10, 0, 0), (0x53, 0, 0), (0x53, 0, 2), (0x10, 0, 2), (0x11, 0, 2)]
    cc.press_keys("left")
    assert _keys(desk["sent"][1]) == [(0x25, 0, 1), (0x25, 0, 3)]  # arrows are extended keys


def test_typing_sends_unicode_including_emoji_and_enter(desk):
    assert cc.type_text("hé\n🙂") == 4
    flat = [k for batch in desk["sent"] for k in _keys(batch)]
    assert (0, ord("h"), 4) in flat and (0, ord("é"), 6) in flat
    assert (0x0D, 0, 0) in flat
    assert (0, 0xD83D, 4) in flat and (0, 0xDE42, 4) in flat  # surrogate pair
    assert desk["events"][-1]["type"] == "computer.action" and desk["events"][-1]["kind"] == "type"


def test_click_glides_visibly_then_clicks_and_announces(desk):
    cc.click(1500, 300, label="Clicking Save")
    assert len(desk["moves"]) > 5 and desk["moves"][-1] == (1500, 300)  # glided, not teleported
    assert [m.mi.dwFlags for m in desk["sent"][0]] == [0x0002, 0x0004]
    ops = [c["op"] for c in desk["overlay"]]
    assert ops[:2] == ["move", "click"] and desk["overlay"][0]["label"] == "Clicking Save"
    action = desk["events"][-1]
    assert action == {**action, "type": "computer.action", "kind": "click", "x": 1500, "y": 300, "label": "Clicking Save"}


def test_targets_are_clamped_and_never_hit_the_failsafe_corner(desk):
    assert cc.glide(-50, -50) == (3, 3)
    assert cc.glide(9999, 9999) == (2559, 1599)


def test_uneven_monitors_snap_targets_and_find_the_reachable_corner(desk, monkeypatch):
    # This PC: a 2560×1600 laptop at (0,0) and a taller 2560×1967 screen to its right, 367 px higher.
    layout = {"left": 0, "top": -367, "width": 5120, "height": 1967,
              "monitors": [{"x": 0, "y": 0, "width": 2560, "height": 1600, "primary": True},
                           {"x": 2560, "y": -367, "width": 2560, "height": 1967, "primary": False}]}
    monkeypatch.setattr(cc, "screen_bounds", lambda max_age=3.0: layout)
    # (0,-367) is dead space the pointer never reaches; both screens' own top-left corners are real stops.
    assert cc.failsafe_corners(layout) == [(0, 0), (2560, -367)]
    assert cc._clamp(100, -200) == (100, 0)  # dead zone above the laptop → its top edge
    assert cc._clamp(-10, -10) == (3, 3)  # never onto the failsafe corner
    assert cc._clamp(3000, -300) == (3000, -300)  # really on the tall screen
    desk["cursor"]["pos"] = (0, 0)
    assert cc.tool_keyboard_keys("enter").startswith("Stopped:")


def test_user_slamming_the_mouse_into_the_corner_stops_everything(desk):
    desk["cursor"]["pos"] = (0, 0)  # the user did this, not Nyx
    result = cc.tool_mouse_click(x=500, y=500)
    assert result.startswith("Stopped:") and "took over" in result
    assert desk["sent"] == []
    assert any(e["type"] == "computer.state" and e.get("stopped") for e in desk["events"])
    desk["cursor"]["pos"] = (900, 900)
    assert cc.tool_keyboard_type("more").startswith("Stopped:")  # still refused right after


def test_abort_expires_for_a_later_turn(desk):
    cc.abort("Stop pressed")
    assert cc.tool_keyboard_keys("enter").startswith("Stopped:")
    desk["state"].aborted_at = time.monotonic() - cc.ABORT_REFUSAL_SECONDS - 1
    desk["state"].aborted_turn = "old-turn"
    assert cc.tool_keyboard_keys("enter") == "Pressed enter."


def test_abort_mid_drag_still_releases_the_button(desk, monkeypatch):
    calls = {"n": 0}
    real_check = cc._check_abort

    def check():
        calls["n"] += 1
        if calls["n"] == 30:
            cc.abort("Esc pressed three times")
        real_check()

    monkeypatch.setattr(cc, "_check_abort", check)
    with pytest.raises(cc.ComputerAborted):
        cc.drag(100, 100, 900, 900)
    flags = [i.mi.dwFlags for batch in desk["sent"] for i in batch]
    assert flags == [0x0002, 0x0004]  # pressed, and released despite the abort


def test_escape_three_times_is_detected_but_nyx_own_escape_is_not():
    counter = cc.EscCounter()
    presses = [(True, 1.0), (False, 1.1), (True, 1.3), (False, 1.4), (True, 1.6)]
    assert [counter.feed(d, t) for d, t in presses] == [False, False, False, False, True]
    slow = cc.EscCounter()
    assert not any(slow.feed(d, t) for d, t in [(True, 1), (False, 2), (True, 3), (False, 4), (True, 5)])
    own = cc.EscCounter()
    assert not any(own.feed(d, t, ignore_until=9) for d, t in presses)


def test_scroll_sends_signed_wheel_notches(desk):
    cc.scroll(-3, 400, 400)
    wheel = [i.mi for batch in desk["sent"] for i in batch]
    assert len(wheel) == 3 and all(m.dwFlags == 0x0800 and m.mouseData == (-120 & 0xFFFFFFFF) for m in wheel)


def test_grid_and_cursor_are_drawn_in_screen_coordinates():
    from PIL import Image

    image = Image.new("RGB", (800, 600), (0, 0, 0))
    out = cc.annotate(image, origin=(1000, 0), cursor=(1400, 300), grid=True)
    assert out.getpixel((201, 300))[0] > 200 or out.getpixel((200, 300))[0] > 200  # grid line at screen x=1200
    assert out.getpixel((403, 310)) == (139, 92, 246)  # AI cursor at screen 1400,300


def test_find_on_screen_maps_the_model_point_back_to_the_desktop(desk, monkeypatch):
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (1600, 1000)).save(buffer, "JPEG")
    monkeypatch.setattr(cc, "screenshot_jpeg", lambda **k: (buffer.getvalue(), 1600 / 2560, (-1920, 0)))
    monkeypatch.setattr("vision.locate_point", lambda image, mime, description: (0.5, 0.25))
    assert cc.find_on_screen("Send button") == (-1920 + 1280, 400)


def test_tools_register_with_contract_categories():
    registry = ToolRegistry()
    cc.register_computer_tools(registry)
    categories = {t.name: t.category for t in registry.list_tools()}
    assert {n: categories[n] for n in ("screen_view", "mouse_click", "keyboard_type", "keyboard_keys")} == \
        dict.fromkeys(("screen_view", "mouse_click", "keyboard_type", "keyboard_keys"), "computer")
    assert categories["list_windows"] == categories["focus_window"] == categories["window_action"] == "windows"


def test_routes_state_and_stop_open_screenshot_owner_only(desk):
    import server

    local = TestClient(server.app, client=("127.0.0.1", 50041))
    assert local.get("/api/computer/state").json()["screen"]["width"] == 2560
    stopped = local.post("/api/computer/stop").json()
    assert stopped["stopped"] == "Stop pressed"
    remote = TestClient(server.app, client=("203.0.113.9", 50042))
    assert remote.get("/api/computer/screenshot").status_code == 403
    assert remote.post("/api/computer/overlay", json={"enabled": False}).status_code == 403


def test_overlay_commands_are_validated():
    assert cursor_overlay.parse_command('{"op":"move","x":"12","y":34,"label":"Hi","ms":99999}') == \
        {"op": "move", "x": 12, "y": 34, "label": "Hi", "ms": 2000, "button": "left"}
    assert cursor_overlay.parse_command('{"op":"explode"}') is None
    assert cursor_overlay.parse_command("not json") is None
    assert cursor_overlay.parse_command('{"op":"click","x":1}') is None
    assert cursor_overlay.ease_out(0) == 0 and cursor_overlay.ease_out(1) == 1 and cursor_overlay.ease_out(0.5) > 0.5
