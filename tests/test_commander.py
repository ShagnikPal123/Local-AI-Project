"""Commander: a delegator chat hands work to threads, each thread's status is read live, a full thread is restarted
fresh with a summary, and the owner's corrections teach the picker. The chat store, the turn pipeline and the model
catalog are fakes: no model calls, no network, no GPU."""

from types import SimpleNamespace

import pytest

import commander_pick


class FakeStore:
    def __init__(self):
        self.chats = {}
        self.n = 0

    def create(self, title=None, activate=True):
        if len(self.chats) >= 100:
            raise RuntimeError("Chat limit reached. Delete a chat before creating another.")
        self.n += 1
        chat_id = f"c{self.n}"
        self.chats[chat_id] = {"title": title or chat_id, "messages": []}
        return chat_id

    def exists(self, chat_id):
        return chat_id in self.chats

    def messages(self, chat_id):
        return list(self.chats.get(chat_id, {}).get("messages", []))

    def summaries(self):
        return [{"id": k, "title": v["title"]} for k, v in self.chats.items()]

    def say(self, chat_id, role, content):
        self.chats[chat_id]["messages"].append({"role": role, "content": content})


@pytest.fixture()
def world(tmp_path, monkeypatch):
    import commander as cm

    store = FakeStore()
    sent = []
    running = {}
    approvals = []
    monkeypatch.setattr(cm, "_path", lambda: tmp_path / "commander.json")
    monkeypatch.setattr(cm, "_store", lambda: store)

    def run(chat_id, text, provider, mode, role):
        sent.append({"chat_id": chat_id, "text": text, "provider": provider, "mode": mode, "role": role})
        store.say(chat_id, "user", text)
        return f"turn{len(sent)}"

    monkeypatch.setattr(cm, "_run", run)
    monkeypatch.setattr(cm, "_running", lambda chat_id: running.get(chat_id))
    monkeypatch.setattr(cm, "_approvals", lambda: approvals)
    monkeypatch.setattr(commander_pick, "PICKER", commander_pick.Picker(path=tmp_path / "picks.json"))
    monkeypatch.setattr(commander_pick, "model_for", lambda tier, **_: {
        "provider": "ollama", "model": f"{tier}-model", "label": f"Ollama · {tier}-model", "local": True, "why": "fits"})
    main = store.create("Main")
    cm.make_delegator(main)
    return SimpleNamespace(cm=cm, store=store, sent=sent, running=running, approvals=approvals, main=main)


def test_a_delegator_starts_a_thread_with_a_picked_model_and_a_full_brief(world):
    thread = world.cm.start_thread(world.main, "Login bug", "Fix the crash in the login function and add a test")
    assert thread["tier"] == "code" and thread["sector"] == "Fixes" and thread["provider"] == "ollama"
    assert thread["model"] == "code-model" and thread["why"]
    sent = world.sent[-1]
    assert sent["chat_id"] == thread["chat_id"] and sent["provider"] == "ollama"
    assert "Fix the crash" in sent["text"] and "Done:" in sent["text"] and "Waiting on you:" in sent["text"]
    assert world.store.chats[thread["chat_id"]]["title"] == "Login bug"


def test_only_a_delegator_hands_out_threads(world):
    other = world.store.create("Just a chat")
    with pytest.raises(world.cm.CommanderError):
        world.cm.start_thread(other, "x", "y")


def test_a_thread_cannot_become_a_commander(world):
    thread = world.cm.start_thread(world.main, "Docs", "Update the README")
    with pytest.raises(world.cm.CommanderError):
        world.cm.make_delegator(thread["chat_id"])


def test_effort_sets_how_hard_the_turn_works(world):
    world.cm.start_thread(world.main, "Quick", "What is 2 + 2?")
    assert world.sent[-1]["mode"] == "normal"
    world.cm.start_thread(world.main, "Big", "Fix it", effort="max")
    assert world.sent[-1]["mode"] == "cowork"


def test_status_is_read_live(world):
    cm = world.cm
    thread = cm.start_thread(world.main, "Report", "Write the weekly report")
    chat = thread["chat_id"]
    world.running[chat] = SimpleNamespace(turn_id="t1", status="Reading files")
    assert cm.view(cm.get(thread["id"]))["status"] == "working"
    assert cm.view(cm.get(thread["id"]))["line"] == "Reading files"

    world.approvals.append({"id": "a1", "turn_id": "t1", "summary": "Send an email to the team"})
    seen = cm.view(cm.get(thread["id"]))
    assert seen["status"] == "needs_you" and seen["kind"] == "approval" and "email" in seen["line"]

    world.approvals.clear()
    del world.running[chat]
    world.store.say(chat, "assistant", "I drafted it.\n\nDone: the weekly report is in reports/week.md")
    seen = cm.view(cm.get(thread["id"]))
    assert seen["status"] == "idle" and seen["line"] == "the weekly report is in reports/week.md"

    world.store.say(chat, "assistant", "Almost there.\nWaiting on you: say which week to cover")
    assert cm.view(cm.get(thread["id"]))["status"] == "needs_you"


def test_an_unanswered_question_card_needs_the_owner(world):
    thread = world.cm.start_thread(world.main, "Colours", "Pick a palette")
    card = '```question\n{"question": "Which palette?", "options": [{"label": "Warm"}, {"label": "Cool"}]}\n```'
    world.store.say(thread["chat_id"], "assistant", f"Two good ones.\n{card}")
    seen = world.cm.view(world.cm.get(thread["id"]))
    assert seen["status"] == "needs_you" and seen["kind"] == "question" and seen["line"] == "Which palette?"
    world.store.say(thread["chat_id"], "user", "Warm")
    assert world.cm.view(world.cm.get(thread["id"]))["status"] == "idle"


def test_the_board_groups_like_the_threads_panel(world):
    cm = world.cm
    a = cm.start_thread(world.main, "A", "Write the weekly report")
    b = cm.start_thread(world.main, "B", "Write the monthly report")
    c = cm.start_thread(world.main, "C", "Write the yearly report")
    world.store.say(a["chat_id"], "assistant", "Waiting on you: which numbers?")
    cm.resolve_thread(b["id"])
    cm.pin_thread(c["id"])
    board = cm.board(delegator=world.main)
    groups = {g["id"]: [t["title"] for t in g["threads"]] for g in board["groups"]}
    assert groups["pinned"] == ["C"] and groups["needs_you"] == ["A"] and groups["resolved"] == ["B"]
    assert [g["label"] for g in board["groups"]] == ["Pinned", "Needs you", "Working", "Idle", "Resolved"]
    assert board["needs_you"] == 1 and board["total"] == 3


def test_follow_ups_go_to_the_same_thread(world):
    thread = world.cm.start_thread(world.main, "Report", "Write the weekly report")
    world.cm.message_thread("report", "Add a chart too", delegator=world.main)
    assert world.sent[-1]["chat_id"] == thread["chat_id"] and world.sent[-1]["text"] == "Add a chart too"


def test_a_working_thread_is_not_interrupted(world):
    thread = world.cm.start_thread(world.main, "Report", "Write the weekly report")
    world.running[thread["chat_id"]] = SimpleNamespace(turn_id="t", status="Writing")
    with pytest.raises(world.cm.CommanderError):
        world.cm.message_thread(thread["id"], "More")


def test_a_full_thread_starts_fresh_with_a_summary(world, monkeypatch):
    cm = world.cm
    thread = cm.start_thread(world.main, "Report", "Write the weekly report")
    world.store.say(thread["chat_id"], "assistant", "Wrote the draft in reports/week.md. Done: draft ready")
    monkeypatch.setattr(cm, "_measure", lambda messages, provider, model: {"used": 90_000, "window": 100_000, "share": 0.9})
    fresh = cm.message_thread(thread["id"], "Now add the sales numbers")
    assert fresh["id"] != thread["id"] and fresh["refreshed_from"] == thread["id"]
    assert fresh["title"] == "Report (fresh)" and fresh["model"] == thread["model"]
    opening = world.sent[-1]["text"]
    assert opening.startswith("[Fresh start]") and "90% full" in opening
    assert "Wrote the draft" in opening and "Now: Now add the sales numbers" in opening
    old = cm.get(thread["id"])
    assert old["resolved"] and old["refreshed_to"] == fresh["id"]


def test_the_owners_correction_teaches_the_picker(world):
    cm = world.cm
    thread = cm.start_thread(world.main, "Newsletter", "Draft the club newsletter")
    changed = cm.set_pick(thread["id"], tier="heavy", effort="high")
    assert changed["tier"] == "heavy" and changed["model"] == "heavy-model" and changed["source"] == "owner"
    nxt = cm.start_thread(world.main, "Newsletter again", "Draft the club newsletter for June")
    assert nxt["tier"] == "heavy" and nxt["source"] == "learned"


def test_bad_picks_are_refused(world):
    thread = world.cm.start_thread(world.main, "X", "Do the thing")
    with pytest.raises(world.cm.CommanderError):
        world.cm.set_pick(thread["id"], tier="huge")


def test_moving_a_commander_chat_into_a_project_takes_its_threads(world):
    thread = world.cm.start_thread(world.main, "X", "Do the thing")
    world.cm.move_to_project(world.main, "pr-1")
    assert world.cm.get(thread["id"])["project_id"] == "pr-1"
    assert world.cm.threads(project_id="pr-1")[0]["id"] == thread["id"]


def test_a_project_gets_one_main_chat(world):
    first = world.cm.delegator_for_project("pr-9", "Moon base")
    assert world.cm.delegator_for_project("pr-9", "Moon base") == first
    assert world.store.chats[first]["title"] == "Moon base · Commander" and world.cm.is_delegator(first)


def test_the_brief_lists_threads_and_uses_the_zone_prefix(world):
    import command_zone

    world.cm.start_thread(world.main, "Login bug", "Fix the login crash")
    brief = command_zone.brief_for_chat(world.main)
    assert brief.startswith(command_zone.BRIEF_PREFIX) and "Login bug" in brief and "start_thread" in brief
    other = world.store.create("plain")
    assert command_zone.brief_for_chat(other) == ""


def test_tools_only_work_in_a_delegator_chat(world, monkeypatch):
    cm = world.cm
    monkeypatch.setattr(cm, "_context", lambda: (world.main, "owner"))
    said = cm.tool_start_thread("Login bug", "Fix the crash in login")
    assert said.startswith("Started") and world.sent[-1]["role"] == "owner"
    assert "Login bug" in cm.tool_list_threads()
    assert cm.tool_message_thread("login bug", "Also check logout").startswith("Sent to")
    assert "Also check logout" in cm.tool_read_thread("Login bug")
    assert cm.tool_resolve_thread("Login bug").startswith("Resolved")
    monkeypatch.setattr(cm, "_context", lambda: ("somewhere-else", "owner"))
    assert cm.tool_start_thread("x", "y").startswith("Error")


def test_attention_covers_every_chat(world):
    plain = world.store.create("Holiday plans")
    world.store.say(plain, "assistant", '```question\n{"question": "Beach or city?", "options": ["Beach", "City"]}\n```')
    busy = world.store.create("Code chat")
    world.running[busy] = SimpleNamespace(turn_id="t9", status="Running tests")
    rows = {r["title"]: r for r in world.cm.attention()}
    assert rows["Holiday plans"]["status"] == "needs_you" and rows["Holiday plans"]["label"] == "Needs you"
    assert rows["Code chat"]["status"] == "working"
    assert "Main" not in rows  # idle chats are left out


def test_settings_round_trip(world):
    assert world.cm.settings()["divisions_in_chat"] is False
    assert world.cm.save_settings(divisions_in_chat=True)["divisions_in_chat"] is True
