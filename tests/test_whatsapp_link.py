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

    def turn(text, lane=None):
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


def test_the_phone_can_read_mail_and_email_only_the_owner(monkeypatch):
    """Gmail from WhatsApp: reading works at "chat" level; sending to other people still needs "full"."""
    from permissions import PermissionDenied

    for name, category in (("email_list", "email.read"), ("email_read", "email.read"), ("email_to_me", "email.send")):
        wa.phone_guard(name, category)
    for name in ("email_send", "email_reply"):
        with pytest.raises(PermissionDenied):
            wa.phone_guard(name, "email.send")


def test_email_to_me_only_ever_goes_to_the_owners_own_address(monkeypatch):
    import email_client

    sent = []
    monkeypatch.setattr(email_client, "list_accounts", lambda: [{"id": "a1", "address": "me@example.com"}])
    monkeypatch.setattr(email_client, "send_email", lambda to, subject, body, **kw: sent.append((to, subject, kw)) or
                        {"sent": True, "from": "me@example.com", "to": [to]})
    assert "me@example.com" in wa.tool_email_to_me("Notes", "the summary")
    assert sent[0][0] == "me@example.com" and sent[0][2]["allow_compose"] is False   # never a half-sent draft
    assert wa.tool_email_to_me("x", "y", account="stranger@example.com").startswith("Error")
    assert len(sent) == 1

    monkeypatch.setattr(email_client, "list_accounts", lambda: [])
    assert wa.tool_email_to_me("x", "y").startswith("Error: no email account is set up")


def test_email_to_me_reports_a_refusal_in_plain_words(monkeypatch):
    import email_client

    monkeypatch.setattr(email_client, "list_accounts", lambda: [{"id": "a1", "address": "me@example.com"}])

    def refuse(*_args, **_kwargs):
        raise email_client.EmailError("No way to send: add an email account with an app password.")

    monkeypatch.setattr(email_client, "send_email", refuse)
    assert wa.tool_email_to_me("x", "y").startswith("Not sent: No way to send")


# ---------------------------------------------------------------------------
# Lanes: other chats and avatars on the same line
# ---------------------------------------------------------------------------


class FakeChats:
    def __init__(self):
        self.items = [{"id": "c1", "title": "Trip to Lisbon", "preview": "Book the 9am train."},
                      {"id": "c2", "title": "Taxes 2026", "preview": ""}]

    def recent(self, limit=9):
        return self.items[:limit]

    def exists(self, chat_id):
        return any(c["id"] == chat_id for c in self.items)

    def title(self, chat_id):
        return next((c["title"] for c in self.items if c["id"] == chat_id), "")


class FakeAvatars:
    def __init__(self):
        self.items = {"a1": {"id": "a1", "name": "Mira", "does": "Watches the inbox", "enabled": True}}

    def list(self):
        return list(self.items.values())

    def get(self, avatar_id):
        return self.items.get(avatar_id)

    def find(self, name):
        wanted = name.strip().lstrip("@").lower()
        return next((a for a in self.items.values() if a["name"].lower() == wanted), None)

    def create(self, name, does):
        if not name.strip():
            raise ValueError("An avatar needs a name.")
        made = {"id": f"a{len(self.items) + 1}", "name": name, "does": does, "enabled": False}
        self.items[made["id"]] = made
        return made


@pytest.fixture
def lanes_line(line):
    line.chats, line.avatars = FakeChats(), FakeAvatars()
    line.turn_lanes = []
    inner = line._turn

    def turn(text, lane=None):
        line.turn_lanes.append(dict(lane or {}))
        return inner(text, lane=lane)

    line._turn = turn
    _pair(line)
    return line


def _last(link):
    return link.transport.sent()[-1]


def test_chats_lists_recent_chats_and_chat_n_continues_one(lanes_line):
    lanes_line.handle_incoming("/chats")
    assert "1. Trip to Lisbon" in _last(lanes_line) and lanes_line.state["listing"] == ["c1", "c2"]
    lanes_line.handle_incoming("/chat 1")
    assert "Continuing “Trip to Lisbon”" in _last(lanes_line) and "Book the 9am train." in _last(lanes_line)
    assert lanes_line.state["lane"] == {"kind": "chat", "id": "c1"}
    assert lanes_line.status()["linked_chats"] == ["c1"] and lanes_line.is_chat_linked("c1")
    lanes_line.handle_incoming("what time again?")
    assert lanes_line.turn_lanes[-1] == {"kind": "chat", "id": "c1"}
    assert _last(lanes_line).startswith(wa.REPLY_PREFIX + "*Trip to Lisbon*\n")      # the owner can tell where it came from


def test_a_vague_chat_name_never_lands_in_the_wrong_chat(lanes_line):
    lanes_line.handle_incoming("/chat nothing like it")
    assert "could not tell which chat" in _last(lanes_line)
    assert lanes_line.state["lane"] == {"kind": "general", "id": ""} and lanes_line.state["linked_chats"] == []


def test_avatar_switches_the_line_and_general_comes_back(lanes_line):
    lanes_line.handle_incoming("/avatars")
    assert "Mira" in _last(lanes_line)
    lanes_line.handle_incoming("/avatar mira")
    assert lanes_line.state["lane"] == {"kind": "avatar", "id": "a1"} and "I am Mira" in _last(lanes_line)
    lanes_line.handle_incoming("what is on today?")
    assert lanes_line.turn_lanes[-1] == {"kind": "avatar", "id": "a1"}
    assert _last(lanes_line).startswith(wa.REPLY_PREFIX + "*Mira*\n")
    lanes_line.handle_incoming("/where")
    assert "avatar Mira" in _last(lanes_line)
    lanes_line.handle_incoming("/general")
    lanes_line.handle_incoming("hello")
    assert lanes_line.turn_lanes[-1] == {"kind": "general", "id": ""}
    assert "*Mira*" not in _last(lanes_line)                                          # the main chat has no name tag


def test_an_at_name_asks_one_avatar_once_without_switching(lanes_line):
    lanes_line.handle_incoming("@Mira what is on today?")
    assert lanes_line.turns[-1] == "what is on today?"                                 # the @Mira part is not sent on
    assert lanes_line.turn_lanes[-1] == {"kind": "avatar", "id": "a1"}
    assert lanes_line.state["lane"] == {"kind": "general", "id": ""}
    assert _last(lanes_line).startswith(wa.REPLY_PREFIX + "*Mira*\n")
    lanes_line.handle_incoming("@someone-else hi")                                       # not an avatar: ordinary text
    assert lanes_line.turns[-1] == "@someone-else hi" and lanes_line.turn_lanes[-1]["kind"] == "general"


def test_an_unknown_avatar_lists_the_real_ones(lanes_line):
    lanes_line.handle_incoming("/avatar Zed")
    assert "No avatar called" in _last(lanes_line) and "Mira" in _last(lanes_line)
    assert lanes_line.state["lane"]["kind"] == "general"


def test_newavatar_makes_one_and_moves_the_line_to_it(lanes_line):
    lanes_line.handle_incoming("/newavatar Orion: tracks my flights")
    made = lanes_line.avatars.find("Orion")
    assert made["does"] == "tracks my flights" and lanes_line.state["lane"] == {"kind": "avatar", "id": made["id"]}
    assert "switched off" in _last(lanes_line)
    lanes_line.handle_incoming("/newavatar nonsense")
    assert "Say it like this" in _last(lanes_line)
    lanes_line.avatars.create = lambda *_a: (_ for _ in ()).throw(ValueError("That is a lot of avatars."))
    lanes_line.handle_incoming("/newavatar Extra: one more")
    assert "Could not make that avatar: That is a lot of avatars." in _last(lanes_line)


def test_a_deleted_chat_or_avatar_sends_the_phone_back_to_the_main_chat(lanes_line):
    lanes_line.set_lane("avatar", "a1")
    del lanes_line.avatars.items["a1"]
    assert lanes_line.current_lane() == {"kind": "general", "id": ""}
    lanes_line.set_lane("chat", "c2")
    lanes_line.chats.items = []
    assert lanes_line.current_lane() == {"kind": "general", "id": ""}


def test_the_pc_can_connect_and_disconnect_a_chat(lanes_line):
    lanes_line.link_chat("c2")
    assert lanes_line.state["lane"] == {"kind": "chat", "id": "c2"} and lanes_line.is_chat_linked("c2")
    lanes_line.unlink_chat("c2")
    assert not lanes_line.is_chat_linked("c2") and lanes_line.state["lane"]["kind"] == "general"
    with pytest.raises(wa.WhatsAppError):
        lanes_line.link_chat("missing")
    with pytest.raises(wa.WhatsAppError):
        lanes_line.set_lane("avatar", "missing")


def test_new_starts_a_fresh_conversation_in_the_current_lane(lanes_line):
    lanes_line.state["chat_id"] = "abc"
    lanes_line.state["lane_chats"] = {"avatar:a1": "xyz"}
    lanes_line.set_lane("avatar", "a1")
    lanes_line.handle_incoming("/new")
    assert lanes_line.state["lane_chats"] == {} and lanes_line.state["chat_id"] == "abc"   # only Mira's chat was reset
    lanes_line.set_lane("general")
    lanes_line.handle_incoming("/new")
    assert lanes_line.state["chat_id"] == ""


def test_the_avatar_turn_runs_under_both_the_phone_guard_and_the_avatars_own(monkeypatch):
    from permissions import PermissionDenied

    seen = []
    both = wa._all_of([lambda name, cat: seen.append(("phone", name)) or wa.phone_guard(name, cat),
                       lambda name, cat: seen.append(("avatar", name))])
    both("web_search", "web")
    assert [who for who, _ in seen] == ["phone", "avatar"]
    with pytest.raises(PermissionDenied):
        both("run_command", "machine")                                   # the phone says no before the avatar is asked


def test_the_routes_show_the_badge_and_move_the_phone(lanes_line, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import routes_whatsapp

    app = FastAPI()
    app.include_router(routes_whatsapp.router)
    app.dependency_overrides[routes_whatsapp._owner] = lambda: object()
    monkeypatch.setattr(wa, "_LINK", lanes_line)
    client = TestClient(app)

    assert client.post("/api/whatsapp/link-chat", json={"chat_id": "c2"}).json()["linked_chats"] == ["c2"]
    listing = client.get("/api/whatsapp/chats").json()
    assert [(c["id"], c["whatsapp"]) for c in listing["chats"]] == [("c1", False), ("c2", True)]
    assert client.post("/api/whatsapp/lane", json={"kind": "avatar", "id": "a1"}).json()["lane_name"] == "Mira"
    assert client.post("/api/whatsapp/lane", json={"kind": "nonsense"}).status_code == 400
    assert client.post("/api/whatsapp/lane", json={"kind": "chat", "id": "missing"}).status_code == 409
    assert client.post("/api/whatsapp/link-chat", json={"chat_id": "c2", "linked": False}).json()["linked_chats"] == []
