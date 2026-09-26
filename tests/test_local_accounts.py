"""Accounts: each keeps its own chats, memory and files; passwords guard them; Nyx is told what one is for."""

from __future__ import annotations

import json

import pytest

import local_accounts
import paths


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A clean data directory, working in Main."""
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    monkeypatch.setattr(paths, "ACTIVE_ACCOUNT", paths.MAIN_ACCOUNT)
    local_accounts._FAILS.clear()
    yield tmp_path
    local_accounts._FAILS.clear()


# --- where files go -----------------------------------------------------------------------


def test_main_keeps_everything_where_it_always_was(home):
    assert paths.data_path("chats.json") == home / "chats.json"
    assert paths.data_path("notes/notes.json") == home / "notes" / "notes.json"


def test_another_account_gets_its_own_chats_memory_and_files_but_shares_keys_and_settings(home, monkeypatch):
    monkeypatch.setattr(paths, "ACTIVE_ACCOUNT", "nis")
    own = home / "accounts" / "nis"
    for name in ("chats.json", "memory.json", "internal_chats.json", "notes/notes.json", "brain/brain.db",
                 "uploads/2026-09/a.png", "research", "learning/turns.jsonl", "offices", "chats.backup-1.json"):
        assert paths.data_path(name) == own / name, name
    for name in (".secrets.json", "auth.json", "model_choice.json", "trading/settings.json", "skills.json",
                 "tabs.json", "kahuna/state.json", "accounts/index.json", "logs/engine.log"):
        assert paths.data_path(name) == home / name, name


def test_the_account_that_opens_is_read_from_the_index_and_bad_values_fall_back_to_main(home, monkeypatch):
    monkeypatch.delenv("NYX_ACCOUNT", raising=False)
    index = home / "accounts" / "index.json"
    index.parent.mkdir(parents=True)
    index.write_text(json.dumps({"active": "nis", "accounts": [{"id": "nis", "name": "NIS"}]}), encoding="utf-8")
    assert paths._resolve_active_account() == "nis"
    index.write_text(json.dumps({"active": "ghost", "accounts": [{"id": "nis"}]}), encoding="utf-8")
    assert paths._resolve_active_account() == paths.MAIN_ACCOUNT          # not a known account
    index.write_text(json.dumps({"active": "../escape", "accounts": [{"id": "../escape"}]}), encoding="utf-8")
    assert paths._resolve_active_account() == paths.MAIN_ACCOUNT          # never a path outside accounts/
    index.write_text("not json", encoding="utf-8")
    assert paths._resolve_active_account() == paths.MAIN_ACCOUNT


# --- making, changing, switching, removing -------------------------------------------------------


def test_create_names_the_account_and_gives_it_a_folder(home):
    made = local_accounts.create("NIS", "IB schoolwork")
    assert made["id"] == "nis" and made["name"] == "NIS" and not made["locked"] and not made["running"]
    assert (home / "accounts" / "nis" / "README.txt").read_text(encoding="utf-8").count("IB schoolwork") == 1
    assert local_accounts.create("My School!")["id"] == "my-school"
    listing = local_accounts.list_accounts()
    assert [a["name"] for a in listing["accounts"]] == ["Main", "NIS", "My School!"]
    assert listing["running"] == "main" and not listing["switch_pending"]


@pytest.mark.parametrize("name", ["", "   ", "nis", "MAIN", "x" * 41, "bell\x07name"])
def test_create_refuses_empty_duplicate_long_or_odd_names(home, name):
    local_accounts.create("NIS")
    with pytest.raises(local_accounts.AccountError):
        local_accounts.create(name)


def test_a_password_is_optional_but_short_ones_are_refused(home):
    with pytest.raises(local_accounts.AccountError):
        local_accounts.create("Short", password="abc")
    made = local_accounts.create("Private", password="hunter22")
    assert made["locked"]
    stored = json.loads((home / "accounts" / "index.json").read_text(encoding="utf-8"))
    record = next(r for r in stored["accounts"] if r["id"] == made["id"])
    assert "hunter22" not in json.dumps(stored) and record["password_hash"] and record["password_salt"]


def test_switching_into_a_locked_account_needs_its_password(home):
    local_accounts.create("Private", password="hunter22")
    with pytest.raises(local_accounts.PasswordError):
        local_accounts.switch("private")
    with pytest.raises(local_accounts.PasswordError):
        local_accounts.switch("private", "wrong-one")
    result = local_accounts.switch("private", "hunter22")
    assert result["restart_needed"] and result["account"]["opens_next"]
    assert local_accounts.list_accounts()["switch_pending"]
    back = local_accounts.switch("main")                     # back to the open one: no restart, no password
    assert not back["restart_needed"] and not local_accounts.list_accounts()["switch_pending"]


def test_too_many_wrong_passwords_lock_the_account_for_a_while(home):
    local_accounts.create("Private", password="hunter22")
    for _ in range(local_accounts.MAX_FAILS):
        with pytest.raises(local_accounts.PasswordError):
            local_accounts.switch("private", "nope-nope")
    with pytest.raises(local_accounts.PasswordError, match="Too many"):
        local_accounts.switch("private", "hunter22")        # even the right one waits out the lockout


def test_editing_a_locked_account_needs_its_password_and_can_change_or_drop_it(home):
    local_accounts.create("Private", "old purpose", password="hunter22")
    with pytest.raises(local_accounts.PasswordError):
        local_accounts.update("private", purpose="new")
    changed = local_accounts.update("private", password="hunter22", name="Diary", purpose="new purpose",
                                    new_password="better-pass")
    assert changed["name"] == "Diary" and changed["purpose"] == "new purpose" and changed["locked"]
    with pytest.raises(local_accounts.PasswordError):
        local_accounts.update("private", password="hunter22", remove_password=True)
    opened = local_accounts.update("private", password="better-pass", remove_password=True)
    assert not opened["locked"]


def test_remove_moves_the_folder_aside_and_never_touches_main_or_the_open_account(home, monkeypatch):
    local_accounts.create("NIS")
    (home / "accounts" / "nis" / "chats.json").write_text("{}", encoding="utf-8")
    with pytest.raises(local_accounts.AccountError):
        local_accounts.remove("main")
    monkeypatch.setattr(paths, "ACTIVE_ACCOUNT", "nis")
    with pytest.raises(local_accounts.AccountError):
        local_accounts.remove("nis")
    monkeypatch.setattr(paths, "ACTIVE_ACCOUNT", paths.MAIN_ACCOUNT)
    result = local_accounts.remove("nis")
    assert not (home / "accounts" / "nis").exists()
    kept = list((home / "accounts" / "_removed").iterdir())
    assert len(kept) == 1 and (kept[0] / "chats.json").exists() and result["kept_at"] == str(kept[0])
    assert [a["id"] for a in local_accounts.list_accounts()["accounts"]] == ["main"]


# --- what Nyx is told -------------------------------------------------------------------------


def test_nothing_is_said_while_there_is_only_main_with_no_purpose(home):
    assert local_accounts.purpose_note() == ""


def test_the_open_account_and_its_purpose_reach_the_model(home, monkeypatch):
    local_accounts.create("NIS", "IB Physics and Chemistry; keep answers exam-focused")
    monkeypatch.setattr(paths, "ACTIVE_ACCOUNT", "nis")
    note = local_accounts.purpose_note()
    assert '"NIS"' in note and "exam-focused" in note and "separate" in note

    from chat_service import ChatService

    monkeypatch.setattr(local_accounts, "purpose_note", lambda: "ACCOUNT-NOTE-MARKER")
    service = ChatService(memory_path=str(home / "memory-test.json"))
    assert "## This account\nACCOUNT-NOTE-MARKER" in service._default_system_prompt()
