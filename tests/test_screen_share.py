"""Screen Share (Request R10): it sees only what the owner shares, and acts only one approved step at a time."""

import json
import time

import pytest
from fastapi.testclient import TestClient

import screen_share
from screen_share import NeedsCloud, ScreenShare, ScreenShareError


class FakeControl:
    """Records what would have happened to the real mouse and keyboard."""

    IS_WINDOWS = True

    class ComputerAborted(RuntimeError):
        pass

    class ComputerError(RuntimeError):
        pass

    def __init__(self):
        self.calls = []

    def point_at(self, x, y, label=""):
        self.calls.append(("point", x, y, label))
        return x, y

    def click(self, x, y, button="left", double=False, label=""):
        self.calls.append(("click", x, y, double))
        return x, y

    def type_text(self, text, label=""):
        self.calls.append(("type", text))
        return len(text)

    def press_keys(self, combo, repeat=1):
        self.calls.append(("keys", combo))
        return combo

    def scroll(self, amount, x=None, y=None, horizontal=False):
        self.calls.append(("scroll", amount, x, y))

    def focus_window(self, name):
        self.calls.append(("focus", name))

    def abort(self, reason="Stopped"):
        self.calls.append(("abort", reason))


# The shared screen sits at (100, 50) and is 2000×1000; the model saw it as 1600×800.
GEOMETRY = {"x": 100, "y": 50, "w": 2000, "h": 1000, "iw": 1600, "ih": 800}


def make(step=None, answer="Here.", local="qwen2.5vl:7b", reply=None):
    control = FakeControl()
    seen = []

    def looker(image, prompt, allow_cloud):
        seen.append({"prompt": prompt, "allow_cloud": allow_cloud})
        text = reply if reply is not None else json.dumps({"answer": answer, "step": step, "done": False})
        return text, "test model", bool(local)

    share = ScreenShare(control=control, looker=looker, capture=lambda source, max_width: (b"jpeg", dict(GEOMETRY)),
                        local_model=lambda: local)
    share.seen = seen
    return share, control


def test_nothing_is_seen_before_sharing_starts():
    share, _control = make()
    with pytest.raises(ScreenShareError):
        share.frame()
    with pytest.raises(ScreenShareError):
        share.ask("what is this?")
    assert share.state()["sharing"] is False


def test_show_me_only_points_and_never_touches_the_mouse():
    share, control = make(step={"kind": "click", "target": "Save", "point": {"x": 250, "y": 500}, "why": "saves it"})
    share.start({"kind": "screen", "index": 0}, "show")
    state = share.ask("how do I save this?")
    step = state["step"]
    assert step["kind"] == "click" and step["hands_on"] is True
    with pytest.raises(ScreenShareError, match="Show Me"):
        share.act(step["id"], "do")
    share.act(step["id"], "show")
    assert control.calls == [("point", 600, 550, "Save")]          # 100 + 0.25×2000, 50 + 0.5×1000
    assert share.state()["step"]["shown"] is True                   # still waiting: showing is not doing
    share.act(step["id"], "mine")
    assert share.state()["step"] is None
    assert not [c for c in control.calls if c[0] in ("click", "type", "keys", "scroll")]


def test_ask_first_does_exactly_one_approved_step():
    share, control = make(step={"kind": "click", "target": "Save", "point": {"x": 250, "y": 500}})
    share.start({"kind": "screen", "index": 0}, "ask")
    step = share.ask("save it")["step"]
    share.act(step["id"], "do")
    assert ("click", 600, 550, False) in control.calls
    assert share.state()["step"] is None
    with pytest.raises(ScreenShareError):
        share.act(step["id"], "do")                                  # a step runs once


def test_it_never_types_secrets():
    share, control = make(step={"kind": "type", "target": "Password field", "point": [300, 300], "text": "hunter2"})
    share.start({"kind": "screen", "index": 0}, "ask")
    step = share.ask("log me in")["step"]
    assert step["blocked"]
    with pytest.raises(ScreenShareError, match="never types"):
        share.act(step["id"], "do")
    assert control.calls == []
    card = screen_share.vet_step({"kind": "type", "target": "Notes", "text": "4111 1111 1111 1111"}, pace="ask",
                                 geometry=GEOMETRY)
    assert card["blocked"]
    long_text = screen_share.vet_step({"kind": "type", "target": "Notes", "text": "x" * 5000}, pace="ask", geometry=GEOMETRY)
    assert len(long_text["text"]) == screen_share.MAX_TYPE and not long_text["blocked"]


def test_only_simple_keys():
    def keys(combo):
        return screen_share.vet_step({"kind": "keys", "keys": combo}, pace="ask", geometry=GEOMETRY)

    assert keys("Control + S")["keys"] == "ctrl+s" and not keys("Control + S")["blocked"]
    assert keys("shift+tab")["blocked"] == ""
    for risky in ("win+r", "alt+f4", "ctrl+alt+delete", "ctrl+enter", "ctrl+shift+esc"):
        assert keys(risky)["blocked"], risky


def test_irreversible_steps_are_marked_and_old_steps_expire():
    share, _control = make(step={"kind": "click", "target": "Send", "point": [900, 900], "why": "sends the email"})
    share.start({"kind": "screen", "index": 0}, "ask")
    step = share.ask("send it")["step"]
    assert step["caution"] is True
    share._session["step"]["created"] = time.time() - screen_share.STEP_TTL_SECONDS - 1
    with pytest.raises(ScreenShareError, match="two minutes"):
        share.act(step["id"], "do")


def test_the_online_model_needs_permission_for_the_session():
    share, _control = make(step=None, local="")
    share.start({"kind": "screen", "index": 0}, "show")
    with pytest.raises(NeedsCloud):
        share.ask("what is on my screen?")
    share.set_cloud(True)
    share.ask("what is on my screen?")
    assert share.seen[-1]["allow_cloud"] is True
    share.stop()
    share.start({"kind": "screen", "index": 0}, "show")               # a new session asks again
    with pytest.raises(NeedsCloud):
        share.ask("and now?")


def test_sharing_stops_by_itself_when_nobody_is_looking():
    share, _control = make()
    share.start({"kind": "screen", "index": 0}, "show")
    share._session["seen"] = time.monotonic() - screen_share.IDLE_STOP_SECONDS - 1
    state = share.state()
    assert state["sharing"] is False and "15 quiet minutes" in state["ended"]


def test_a_plain_reply_is_still_an_answer_and_the_goal_carries_on():
    share, _control = make(reply="The total in B12 is wrong because the range stops at B10.")
    share.start({"kind": "screen", "index": 0}, "show")
    state = share.ask("why is my total wrong?")
    assert state["step"] is None and "range stops at B10" in state["messages"][-1]["text"]
    share.ask("", next_step=True)
    assert 'working on: "why is my total wrong?"' in share.seen[-1]["prompt"]


def test_points_as_pixels_or_boxes_are_mapped():
    assert screen_share.norm_point({"x": 250, "y": 500}) == (0.25, 0.5)      # what the prompt asks for
    assert screen_share.norm_point([500, 250]) == (0.25, 0.5)                # Gemini's [y, x]
    assert screen_share.norm_point([250, 500], order="xy") == (0.25, 0.5)    # Qwen's [x, y]
    assert screen_share.norm_point([600, 1200], 1600, 800) == (0.75, 0.75)   # pixels, from a local model
    assert screen_share.norm_point([100, 200, 300, 400]) == (0.3, 0.2)       # a box → its centre
    assert screen_share.norm_point([5000, 5000], 1600, 800) is None
    assert screen_share.norm_point("middle") is None
    qwen = screen_share.vet_step({"kind": "click", "target": "B8", "point_2d": [250, 500]}, pace="ask", geometry=GEOMETRY)
    assert qwen["point"] == [0.25, 0.5]


def test_it_picks_a_local_model_that_can_see():
    by_name = lambda name: None  # noqa: E731 - an Ollama too old to report capabilities
    assert screen_share.local_vision_model(["llama3.1:8b", "gemma3:1b", "qwen2.5vl:7b"], by_name) == "qwen2.5vl:7b"
    assert screen_share.local_vision_model(["gemma3:1b", "llama3.1:8b"], by_name) == ""
    assert screen_share.local_vision_model(["gemma3:4b"], by_name) == "gemma3:4b"
    # Ollama's own capability list wins over the name: qwen3.5 sees though its name does not say so.
    reported = {"qwen3.5:9b": ["completion", "vision", "tools", "thinking"], "llava:7b": ["completion"],
                "llama3.1:8b": ["completion", "tools"]}
    assert screen_share.local_vision_model(list(reported), reported.get) == "qwen3.5:9b"
    assert screen_share.local_vision_model(["llama3.1:8b"], reported.get) == ""


def test_a_local_model_gets_a_grid_and_the_owner_does_not():
    from io import BytesIO

    from PIL import Image

    picture = BytesIO()
    Image.new("RGB", (400, 300), "white").save(picture, "JPEG")
    gridded = screen_share.grid_overlay(picture.getvalue())
    assert gridded != picture.getvalue() and Image.open(BytesIO(gridded)).size == (400, 300)
    assert screen_share.grid_overlay(b"not a picture") == b"not a picture"
    local, _ = make(step=None, local="qwen3.5:9b")
    local.start({"kind": "screen", "index": 0}, "show")
    local.ask("what is this?")
    assert screen_share.GRID_NOTE in local.seen[-1]["prompt"]
    online, _ = make(step=None, local="")
    online.start({"kind": "screen", "index": 0}, "show")
    online.set_cloud(True)
    online.ask("what is this?")
    assert screen_share.GRID_NOTE not in online.seen[-1]["prompt"]


def test_routes_are_owner_only_but_anyone_may_stop(monkeypatch):
    import server

    share, _control = make()
    monkeypatch.setattr(screen_share, "SHARE", share)
    local = TestClient(server.app, client=("127.0.0.1", 50071))
    remote = TestClient(server.app, client=("203.0.113.9", 50072))
    assert remote.get("/api/screen").status_code == 403
    assert remote.get("/api/screen/frame").status_code == 403
    assert remote.post("/api/screen/start", json={"source": {"kind": "screen", "index": 0}}).status_code == 403
    assert local.get("/api/screen/frame").status_code == 409            # not sharing
    assert local.post("/api/screen/start", json={"source": {"kind": "screen", "index": 0}}).json()["sharing"] is True
    frame = local.get("/api/screen/frame")
    assert frame.status_code == 200 and frame.headers["content-type"] == "image/jpeg"
    assert local.post("/api/screen/stop").json()["sharing"] is False
