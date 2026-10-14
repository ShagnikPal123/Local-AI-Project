"""Pictures and files over WhatsApp, both ways — the helper's media handling, the safety checks, and the link's use of them.

No WhatsApp, no network: the helper's client is a fake and the files are tiny temporary ones.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import whatsapp_files as files
import whatsapp_link as wa
import whatsapp_worker.worker as worker
from tests.test_whatsapp_link import FakeAvatars, FakeChats, FakeTransport, _pair  # noqa: F401  (shared fakes)

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x9a\xa0\xa0\x00\x00\x00\x00IEND\xaeB`\x82")


# -- the helper ------------------------------------------------------------------------------------------------


class _Part:
    """Stands in for one protobuf file field: ListFields() is empty when the field is unset."""

    def __init__(self, **fields):
        self.__dict__.update(fields)
        self._set = bool(fields)

    def ListFields(self):
        return [("x", 1)] if self._set else []


def test_the_helper_recognises_what_kind_of_file_a_message_carries():
    document = SimpleNamespace(imageMessage=_Part(), documentMessage=_Part(fileName="report.pdf", mimetype="application/pdf",
                                                                           fileLength=2048),
                               videoMessage=_Part(), audioMessage=_Part())
    assert worker.media_info(document) == {"kind": "document", "mime": "application/pdf", "name": "report.pdf", "size": 2048}
    photo = SimpleNamespace(imageMessage=_Part(mimetype="image/jpeg", fileLength=10), documentMessage=_Part(),
                            videoMessage=_Part(), audioMessage=_Part())
    assert worker.media_info(photo)["kind"] == "image"
    plain = SimpleNamespace(imageMessage=_Part(), documentMessage=_Part(), videoMessage=_Part(), audioMessage=_Part())
    assert worker.media_info(plain) == {}


def test_a_picture_with_no_caption_still_counts_but_an_empty_text_does_not():
    me = {"user": "447700900123", "lid": ""}
    allow = {"mode": "number", "owner": "447700900123", "reply_prefix": wa.REPLY_PREFIX}
    source = {"chat": "447700900123", "sender": "447700900123", "from_me": False, "group": False}
    assert worker.accepts(source, allow, me, set(), "1", "", has_media=True)
    assert not worker.accepts(source, allow, me, set(), "2", "   ")
    assert not worker.accepts({**source, "group": True}, allow, me, set(), "3", "", has_media=True)
    assert not worker.accepts({**source, "sender": "15550100199"}, allow, me, set(), "4", "", has_media=True)
    self_mode = {"mode": "self", "owner": "447700900123", "reply_prefix": wa.REPLY_PREFIX}
    own = {"chat": "447700900123", "sender": "447700900123", "from_me": True, "group": False}
    assert not worker.accepts(own, self_mode, me, set(), "5", wa.REPLY_PREFIX + "report.pdf", has_media=True)  # Nyx's own file


def test_a_file_from_the_phone_gets_a_fresh_safe_name_inside_the_inbox(tmp_path, monkeypatch):
    name = worker.inbox_name({"name": "../../etc/passwd", "kind": "document"})
    assert "/" not in name and "\\" not in name and name.endswith("-etc_passwd")
    monkeypatch.setattr(worker, "_allow", {"inbox": str(tmp_path / "inbox")})

    class Client:
        def download_any(self, _message, path):
            Path(path).write_bytes(b"hello")

    saved = worker._save_media(Client(), object(), {"kind": "document", "name": "a b.txt", "mime": "text/plain", "size": 5})
    assert Path(saved["path"]).parent == tmp_path / "inbox" and saved["size"] == 5 and "error" not in saved
    big = worker._save_media(Client(), object(), {"kind": "video", "name": "x.mp4", "size": worker.MAX_MEDIA_BYTES + 1})
    assert "too big" in big["error"] and "path" not in big

    class Broken:
        def download_any(self, *_args):
            raise OSError("no")

    assert "download failed" in worker._save_media(Broken(), object(), {"kind": "image", "size": 1})["error"]
    monkeypatch.setattr(worker, "_allow", {})
    assert worker._save_media(Client(), object(), {"kind": "image"})["error"] == "no inbox"


def test_send_file_goes_out_as_the_right_kind_and_never_from_a_url(tmp_path, monkeypatch):
    calls = []

    class Client:
        def send_image(self, to, path, caption=None):
            calls.append(("image", to, caption))
            return SimpleNamespace(ID="m1")

        def send_video(self, to, path, caption=None):
            calls.append(("video", to, caption))
            return SimpleNamespace(ID="m2")

        def send_document(self, to, path, caption=None, filename=None):
            calls.append(("document", to, caption, filename))
            return SimpleNamespace(ID="m3")

    monkeypatch.setattr(worker, "_client", Client())
    monkeypatch.setattr(worker, "_sent_ids", set())
    target = tmp_path / "plan.pdf"
    target.write_bytes(b"%PDF-1.4")
    assert worker._handle("send_file", {"to": "+44 7700 900123", "path": str(target), "kind": "document",
                                       "caption": "🌙 plan"}) == {"id": "m3"}
    assert calls[-1] == ("document", "447700900123", "🌙 plan", "plan.pdf")
    assert worker._handle("send_file", {"to": "447700900123", "path": str(target), "kind": "image"}) == {"id": "m1"}
    assert worker._sent_ids == {"m3", "m1"}                              # so the line ignores its own file coming back
    with pytest.raises(RuntimeError):
        worker._handle("send_file", {"to": "447700900123", "path": "https://example.com/x.png", "kind": "image"})
    with pytest.raises(RuntimeError):
        worker._handle("send_file", {"to": "", "path": str(target)})


# -- the safety checks -----------------------------------------------------------------------------------------


def test_what_may_go_to_the_phone(tmp_path, monkeypatch):
    ok = tmp_path / "notes.txt"
    ok.write_text("fine to send")
    resolved, size = files.check_outgoing(ok)
    assert resolved == str(ok.resolve()) and size == len("fine to send")

    with pytest.raises(files.FileRefused, match="no file"):
        files.check_outgoing(tmp_path / "missing.txt")
    with pytest.raises(files.FileRefused, match="folder"):
        files.check_outgoing(tmp_path)
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    with pytest.raises(files.FileRefused, match="empty"):
        files.check_outgoing(empty)
    monkeypatch.setattr(files, "MAX_SEND_BYTES", 4)
    with pytest.raises(files.FileRefused, match="MB"):
        files.check_outgoing(ok)


def test_a_protected_file_or_a_disguised_program_is_never_sent(tmp_path):
    secret = tmp_path / ".env.local"
    secret.write_text("GEMINI_API_KEY=not-a-real-key")
    with pytest.raises(files.FileRefused, match="protected"):
        files.check_outgoing(secret)
    disguised = tmp_path / "holiday.png"
    disguised.write_bytes(b"MZ\x90\x00" + b"\x00" * 200)               # a Windows program wearing a picture's name
    with pytest.raises(files.FileRefused, match="file check"):
        files.check_outgoing(disguised)


def test_files_are_shown_the_way_whatsapp_can_show_them():
    assert [files.kind_for(n) for n in ("a.JPG", "b.png", "c.mp4", "d.pdf", "e.mp3", "f")] == \
        ["image", "image", "video", "document", "document", "document"]


def test_picture_links_in_an_answer_become_pictures_not_text():
    reply = "Here it is.\n\n![Sunset](/api/uploads/0123456789abcdef)\n![Again](/api/uploads/0123456789abcdef)\n\nHope you like it."
    text, ids = files.split_pictures(reply)
    assert ids == ["0123456789abcdef"] and "api/uploads" not in text and text.startswith("Here it is.")
    assert files.split_pictures("no pictures") == ("no pictures", [])
    assert files.split_pictures("![x](https://example.com/a.png)")[1] == []        # only Nyx's own uploads are lifted


def test_the_turn_is_told_when_files_came_with_the_words():
    assert files.incoming_text("what is this?", 0, []) == "what is this?"
    assert "sent 1 file(s)" in files.incoming_text("what is this?", 1, ["image"])
    assert files.incoming_text("", 2, ["image", "document"]).startswith("[The owner sent 2 file(s)")


def test_incoming_files_are_checked_kept_and_removed_from_the_inbox(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    photo = inbox / "p.png"
    photo.write_bytes(PNG)
    program = inbox / "run.png"
    program.write_bytes(b"MZ\x90\x00" + b"\x00" * 300)
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("not from the helper")
    items = [{"kind": "image", "name": "p.png", "mime": "image/png", "path": str(photo)},
             {"kind": "image", "name": "run.png", "mime": "image/png", "path": str(program)},
             {"kind": "document", "name": "elsewhere.txt", "path": str(outside)},
             {"kind": "video", "name": "big.mp4", "error": "too big (30 MB; the limit is 25 MB)"}]
    kept, notes = files.keep_incoming(items, inbox)
    assert len(kept) == 1
    import uploads

    assert uploads.get_upload(kept[0])["name"] == "p.png"
    assert not photo.exists() and not program.exists()                   # nothing is left lying in the inbox
    assert outside.exists(), "a path outside the inbox is ignored, never read or deleted"
    assert any("did not keep run.png" in n for n in notes)
    assert any("elsewhere.txt after it arrived" in n for n in notes)
    assert any("big.mp4" in n and "too big" in n for n in notes)


# -- the link --------------------------------------------------------------------------------------------------


@pytest.fixture
def phone(tmp_path, monkeypatch):
    monkeypatch.setattr(wa, "data_path", lambda name: tmp_path / name)
    monkeypatch.setattr(wa, "sdk_installed", lambda: True)
    monkeypatch.setattr(wa, "device_fingerprint", lambda: "pc-a")
    monkeypatch.setattr(wa, "pc_name", lambda: "DESKTOP-A")
    seen = []

    def turn(text, lane=None, attachments=None):
        seen.append({"text": text, "attachments": list(attachments or [])})
        return turn.reply

    turn.reply = "Looks like a tiny test picture."
    link = wa.WhatsAppLink(transport=FakeTransport(), turn=turn, state_path=tmp_path / "whatsapp" / "link.json",
                           chats=FakeChats(), avatars=FakeAvatars())
    link.seen, link.turn_fn = seen, turn
    _pair(link)
    return link


def _sends(link):
    return [args for op, args in link.transport.calls if op == "send_file"]


def test_a_picture_from_the_phone_reaches_the_turn_as_an_attachment(phone, tmp_path):
    inbox = tmp_path / "whatsapp" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    photo = inbox / "x.png"
    photo.write_bytes(PNG)
    phone.handle_incoming("", [{"kind": "image", "name": "x.png", "mime": "image/png", "path": str(photo)}])
    assert len(phone.seen) == 1 and len(phone.seen[0]["attachments"]) == 1
    assert "sent 1 file(s)" in phone.seen[0]["text"]
    assert "tiny test picture" in phone.transport.sent()[-1]
    assert [e["dir"] for e in phone.status()["log"]][-2:] == ["in", "out"]


def test_a_file_that_fails_the_check_is_explained_and_no_turn_runs(phone, tmp_path):
    inbox = tmp_path / "whatsapp" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    program = inbox / "x.png"
    program.write_bytes(b"MZ\x90\x00" + b"\x00" * 300)
    phone.handle_incoming("", [{"kind": "image", "name": "x.png", "mime": "image/png", "path": str(program)}])
    assert phone.seen == [] and "did not keep x.png" in phone.transport.sent()[-1]


def test_a_shortcut_sent_with_a_file_ignores_the_file(phone, tmp_path):
    inbox = tmp_path / "whatsapp" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    photo = inbox / "x.png"
    photo.write_bytes(PNG)
    phone.handle_incoming("/where", [{"kind": "image", "name": "x.png", "path": str(photo)}])
    assert phone.seen == [] and not photo.exists()


def test_pictures_the_ai_made_go_to_the_phone_as_pictures(phone):
    import uploads

    record = uploads.save_upload(PNG, "sunset.png", "image/png")
    phone.turn_fn.reply = f"Done, here is your sunset.\n\n![Sunset](/api/uploads/{record['id']})"
    phone.handle_incoming("draw a sunset")
    assert "api/uploads" not in phone.transport.sent()[-1]
    sent = _sends(phone)
    assert len(sent) == 1 and sent[0]["kind"] == "image" and sent[0]["to"] == "447700900123"
    assert sent[0]["caption"].startswith(wa.REPLY_PREFIX)               # so the line ignores its own picture


def test_a_reply_that_is_only_a_picture_sends_no_empty_text(phone):
    import uploads

    record = uploads.save_upload(PNG, "sunset.png", "image/png")
    before = len(phone.transport.sent())
    phone.turn_fn.reply = f"![Sunset](/api/uploads/{record['id']})"
    phone.handle_incoming("draw a sunset")
    assert len(phone.transport.sent()) == before and len(_sends(phone)) == 1


def test_the_pc_can_send_a_file_to_the_phone_and_only_to_the_phone(phone, tmp_path):
    doc = tmp_path / "plan.txt"
    doc.write_text("the plan")
    result = phone.send_file(str(doc), "the plan for tomorrow")
    assert result["kind"] == "document" and result["to"] == "+44•••123"
    sent = _sends(phone)[0]
    assert sent["to"] == "447700900123" and sent["caption"] == wa.REPLY_PREFIX + "the plan for tomorrow"
    secret = tmp_path / ".env.local"
    secret.write_text("KEY=x")
    with pytest.raises(wa.WhatsAppError, match="protected"):
        phone.send_file(str(secret))
    assert len(_sends(phone)) == 1
    phone.connected = False
    with pytest.raises(wa.WhatsAppError, match="not connected"):
        phone.send_file(str(doc))


def test_the_send_file_tool_says_what_happened(phone, monkeypatch, tmp_path):
    monkeypatch.setattr(wa, "_LINK", phone)
    doc = tmp_path / "plan.txt"
    doc.write_text("the plan")
    assert "Sent plan.txt to the owner's phone" in wa.tool_send_file(str(doc))
    assert wa.tool_send_file(str(tmp_path / "nope.txt")).startswith("Not sent: There is no file")
