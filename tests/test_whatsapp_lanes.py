"""The words of the WhatsApp lanes: shortcuts, @mentions, the chat list, and who is speaking. No WhatsApp, no avatars."""

from __future__ import annotations

import whatsapp_lanes as lanes

CHATS = [
    {"id": "c1", "title": "Trip to Lisbon", "preview": "Book the 9am train."},
    {"id": "c2", "title": "Taxes 2026", "preview": ""},
    {"id": "c3", "title": "Trip ideas", "preview": ""},
]


def test_only_known_shortcuts_are_commands():
    assert lanes.parse("/chats") == lanes.Command("chats", "")
    assert lanes.parse("  /Chat 2 ") == lanes.Command("chat", "2")
    assert lanes.parse("/avatar Mira") == lanes.Command("avatar", "Mira")
    assert lanes.parse("/home/me/file.txt is where it is") is None       # a path is talk, not a shortcut
    assert lanes.parse("what is /chats") is None


def test_an_at_name_splits_off_the_question():
    assert lanes.split_mention("@Mira what is on today?") == ("Mira", "what is on today?")
    assert lanes.split_mention("@mira: remind me at 5") == ("mira", "remind me at 5")
    assert lanes.split_mention("hello @Mira") is None
    assert lanes.split_mention("@Mira") is None                         # nothing to ask


def test_a_new_avatar_needs_a_name_and_a_job():
    assert lanes.split_new_avatar("Mira: watches my inbox") == ("Mira", "watches my inbox")
    assert lanes.split_new_avatar("Mira - watches my inbox") == ("Mira", "watches my inbox")
    assert lanes.split_new_avatar("Mira") is None
    assert lanes.split_new_avatar(": no name") is None


def test_the_chat_list_is_numbered_and_marks_where_you_are():
    text, ids = lanes.format_chats(CHATS, current_id="c2", linked=["c1"])
    assert ids == ["c1", "c2", "c3"]
    assert "1. Trip to Lisbon (on WhatsApp)" in text and "2. Taxes 2026 (talking here now)" in text
    assert lanes.format_chats([])[1] == []


def test_a_number_means_the_last_list_and_words_must_match_one_chat():
    listing = ["c3", "c1"]
    assert lanes.pick_chat("1", listing, CHATS)["id"] == "c3"
    assert lanes.pick_chat("2", listing, CHATS)["id"] == "c1"
    assert lanes.pick_chat("3", listing, CHATS) is None                 # past the end of what was shown
    assert lanes.pick_chat("taxes", listing, CHATS)["id"] == "c2"
    assert lanes.pick_chat("trip", listing, CHATS) is None              # two chats say "trip": do not guess
    assert lanes.pick_chat("c1", listing, CHATS)["id"] == "c1"
    assert lanes.pick_chat("", listing, CHATS) is None


def test_replies_outside_the_main_chat_carry_the_speaker():
    assert lanes.tag("Mira", "Done.") == "*Mira*\nDone."
    assert lanes.tag("", "Done.") == "Done."
    assert lanes.is_general(None) and lanes.is_general(lanes.lane()) and not lanes.is_general(lanes.lane("avatar", "a1"))
    assert lanes.lane("nonsense", "x") == {"kind": "general", "id": ""}


def test_avatars_are_listed_with_the_current_one_marked():
    avatars = [{"id": "a1", "name": "Mira", "does": "Watches the inbox", "enabled": True},
               {"id": "a2", "name": "Orion", "does": "", "enabled": False}]
    text = lanes.format_avatars(avatars, "a1")
    assert "• Mira — Watches the inbox ← talking to now" in text and "• Orion, off" in text
    assert "newavatar" in lanes.format_avatars([])
