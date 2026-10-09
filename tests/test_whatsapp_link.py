"""The WhatsApp line: pairing, the PC tie, who may reach Nyx, and where answers go — without WhatsApp itself."""

from __future__ import annotations

import time

import pytest

import whatsapp_link as wa
from whatsapp_worker.worker import accepts


class FakeTransport:
    def __init__(self) -> None:
        self.on_event = lambda _event: None
        self.calls = []
        self.running = False

    def alive(self) -> bool:
        return self.running

    def request(self, op, timeout=60, **args):
        self.calls.append((op, args))
        if op == "start":
            self.running = True
        return {"id": f"m{len(self.calls)}"}

    def close(self) -> None:
        self.running = False

    def sent(self):
        return [args["text"] for op, args in self.calls if op == "send"]


@pytest.fixture
def line(tmp_path, monkeypatch):
    monkeypatch.setattr(wa, "data_path", lambda name: tmp_path / name)
    monkeypatch.setattr(wa, "sdk_installed", lambda: True)
    monkeypatch.setattr(wa, "device_fingerprint", lambda: "pc-a")
    monkeypatch.setattr(wa, "pc_name", lambda: "DESKTOP-A")
    turns = []

    def turn(text):
        turns.append(text)
        return f"**Answer** to {text}"

    link = wa.WhatsAppLink(transport=FakeTransport(), turn=turn, state_path=tmp_path / "whatsapp" / "link.json")
    link.turns = turns
    return link


def _pair(link, mode="self", nyx=""):
    link.begin_pairing("+44 7700 900123", mode, nyx)
    link._on_event({"event": "pair_code", "code": "ABCD-EFGH"})
    assert link.status()["pair_code"] == "ABCD-EFGH"
    link._on_event({"event": "connected", "me": wa.digits(nyx) or "447700900123"})
    deadline = time.time() + 5
    while time.time() < deadline and not (link.state["status"] == "linked" and link.transport.sent()):
        time.sleep(0.01)


def test_pairing_asks_whatsapp_for_a_code_for_the_right_number_and_ties_the_pc(line):
    _pair(line)
    start = [args for op, args in line.transport.calls if op == "start"][0]
    assert start["pair_phone"] == "447700900123"
    assert start["allow"] == {"mode": "self", "owner": "447700900123", "reply_prefix": wa.REPLY_PREFIX}
    status = line.status()
    assert status["status"] == "linked" and status["connected"] and status["pc"] == "DESKTOP-A"
    assert status["phone"] == "+44•••123"                     # the number is never sent back whole
    assert line.state["device"] == "pc-a"
    assert "Linked to DESKTOP-A" in line.transport.sent()[0]


def test_a_separate_number_for_nyx_pairs_that_number_and_answers_the_owner(line):
    _pair(line, mode="number", nyx="+1 555 010 0199")
    start = [args for op, args in line.transport.calls if op == "start"][0]
    assert start["pair_phone"] == "15550100199"
    assert start["allow"]["owner"] == "447700900123"
    assert [args["to"] for op, args in line.transport.calls if op == "send"] == ["447700900123"]


def test_bad_numbers_and_same_number_are_refused(line):
    with pytest.raises(wa.WhatsAppError):
        line.begin_pairing("07700 900123", "self")             # no country code
    with pytest.raises(wa.WhatsAppError):
        line.begin_pairing("+44 7700 900123", "number", "+44 7700 900123")


def test_a_link_copied_to_another_pc_is_refused(line, monkeypatch, tmp_path):
    _pair(line)
    (tmp_path / "whatsapp" / "session.sqlite3").write_text("keys")
    monkeypatch.setattr(wa, "device_fingerprint", lambda: "pc-b")
    assert line.status()["status"] == "moved"
    with pytest.raises(wa.WhatsAppError):
        line.send("hello")
    line.handle_incoming("are you there?")
    assert line.turns == []                                     # nothing answered from the wrong PC
    fresh = wa.WhatsAppLink(transport=FakeTransport(), state_path=tmp_path / "whatsapp" / "link.json")
    assert fresh.start_if_ready() is False
    assert "made on DESKTOP-A" in fresh.last_error


def test_a_text_from_the_phone_becomes_a_turn_and_the_answer_goes_back(line):
    _pair(line)
    line.handle_incoming("what's on today?")
    assert line.turns == ["what's on today?"]
    reply = line.transport.sent()[-1]
    assert reply.startswith(wa.REPLY_PREFIX) and "*Answer* to what's on today?" in reply
    assert [entry["dir"] for entry in line.status()["log"]][-2:] == ["in", "out"]


def test_shortcuts_from_the_phone(line):
    _pair(line)
    line.state["chat_id"] = "abc"
    line.handle_incoming("/new")
    assert line.state["chat_id"] == ""
    line.handle_incoming("/pause")
    assert line.state["enabled"] is False
    line.handle_incoming("hello?")
    assert line.turns == []                                     # paused: no answers until resumed on the PC


def test_long_answers_are_split_and_markdown_becomes_whatsapp(line):
    assert wa.to_whatsapp("## Plan\n**bold** and [site](https://x.dev)") == "*Plan*\n*bold* and site (https://x.dev)"
    parts = wa.chunks(("word " * 2000).strip(), size=1000)
    assert len(parts) > 1 and all(len(part) <= 1000 for part in parts)


def test_unlink_signs_out_and_forgets_the_line(line):
    _pair(line)
    line.unlink()
    assert ("logout", {}) in line.transport.calls
    assert line.status()["status"] == "unpaired" and line.state["phone"] == ""


def test_the_worker_only_forwards_the_owners_own_line():
    me = {"user": "447700900123", "lid": "99887766"}
    own = {"mode": "self", "owner": "447700900123", "reply_prefix": wa.REPLY_PREFIX}
    self_chat = {"chat": "447700900123", "sender": "447700900123", "from_me": True, "group": False}
    assert accepts(self_chat, own, me, set(), "1", "hi Nyx")
    assert accepts({**self_chat, "chat": "99887766"}, own, me, set(), "1", "hi")      # self chat by LID
    assert not accepts({**self_chat, "chat": "15550100199"}, own, me, set(), "1", "hi friend")  # the owner texting someone else
    assert not accepts({**self_chat, "from_me": False}, own, me, set(), "1", "hi")
    assert not accepts(self_chat, own, me, {"1"}, "1", "Nyx's own reply")
    assert not accepts(self_chat, own, me, set(), "2", wa.REPLY_PREFIX + "Nyx's reply")

    number = {"mode": "number", "owner": "447700900123", "reply_prefix": wa.REPLY_PREFIX}
    from_owner = {"chat": "447700900123", "sender": "447700900123", "from_me": False, "group": False}
    assert accepts(from_owner, number, me, set(), "3", "hello")
    assert accepts({**from_owner, "sender": "5544", "sender_alt": "447700900123"}, number, me, set(), "3", "hi")
    assert not accepts({**from_owner, "sender": "15550100199"}, number, me, set(), "3", "spam")
    assert not accepts({**from_owner, "group": True}, number, me, set(), "3", "group chatter")


def test_the_phone_guard_blocks_the_pc_but_allows_talking(monkeypatch):
    from permissions import PermissionDenied

    wa.phone_guard("web_search", "web")
    wa.phone_guard("whatsapp_send", "whatsapp")
    with pytest.raises(PermissionDenied):
        wa.phone_guard("run_command", "machine")
    with pytest.raises(PermissionDenied):
        wa.phone_guard("trading_order", "trading")


def test_linkpreview_s_stray_tests_package_is_removed_only_when_it_is_theirs(tmp_path, monkeypatch):
    import sysconfig

    monkeypatch.setattr(sysconfig, "get_paths", lambda: {"purelib": str(tmp_path)})
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "__init__.py").write_text("")
    assert wa.remove_stray_tests() is False, "nobody's record names it: left alone"
    record = tmp_path / "linkpreview-0.12.1.dist-info"
    record.mkdir()
    (record / "RECORD").write_text("linkpreview/__init__.py,,\ntests/__init__.py,,\n")
    assert wa.remove_stray_tests() is True and not (tmp_path / "tests").exists()



def test_the_reader_thread_never_waits_on_a_send(line, monkeypatch):
    """The welcome text after pairing used to be sent from the helper's reader thread, which then waited for a reply
    only it could read."""
    slow = []

    def request(op, timeout=60, **args):
        line.transport.calls.append((op, args))
        if op == "send":
            slow.append(op)
            time.sleep(1.0)
        if op == "start":
            line.transport.running = True
        return {}

    monkeypatch.setattr(line.transport, "request", request)
    line.begin_pairing("+44 7700 900123")
    started = time.time()
    line._on_event({"event": "connected", "me": "447700900123"})
    assert time.time() - started < 0.5
    deadline = time.time() + 5
    while not slow and time.time() < deadline:
        time.sleep(0.01)
    assert slow, "the welcome text is still sent, just not from the reader thread"


def test_office_notices_only_when_switched_on_and_never_to_anyone_else(line, monkeypatch):
    _pair(line)
    monkeypatch.setattr(wa, "_LINK", line)
    before = len(line.transport.sent())
    assert wa.notify("office", "Office done") is False, "off until the owner switches it on"
    line.update(notify_office=True)
    assert line.status()["notify"]["office"] is True
    assert wa.notify("office", "Office “Site” — done: Landing page") is True
    deadline = time.time() + 5
    while len(line.transport.sent()) == before and time.time() < deadline:
        time.sleep(0.01)
    sends = [args for op, args in line.transport.calls if op == "send"]
    assert "Landing page" in sends[-1]["text"] and sends[-1]["to"] == "447700900123"
    assert wa.notify("world", "x") is False
    line.connected = False
    assert wa.notify("office", "while offline") is False
