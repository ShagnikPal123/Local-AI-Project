"""Tests for LocalStorage, SessionStore, and CustomDatabase."""

import pytest
import time
from storage import LocalStorage, SessionStore, CustomDatabase


def test_local_storage_crud_and_ttl(tmp_path):
    """Test setting, getting, deleting, and TTL expiration in LocalStorage."""
    store_file = tmp_path / "local_store.json"
    ls = LocalStorage(storage_path=store_file)

    # Simple set & get
    ls.set_item("theme", "dark")
    assert ls.get_item("theme") == "dark"

    # Keys list
    assert "theme" in ls.keys()

    # TTL expiration
    ls.set_item("temp_token", "12345", ttl_seconds=0.1)
    assert ls.get_item("temp_token") == "12345"
    time.sleep(0.15)
    assert ls.get_item("temp_token") is None

    # Remove
    assert ls.remove_item("theme") is True
    assert ls.get_item("theme") is None


def test_session_store_cookies_and_tokens():
    """Test cookie storage and session token verification."""
    ss = SessionStore(session_ttl_seconds=3600.0)

    token = ss.create_session(user_id="alice", metadata={"role": "admin"})
    assert token is not None

    session = ss.get_session(token)
    assert session is not None
    assert session["user_id"] == "alice"
    assert session["metadata"]["role"] == "admin"

    # Cookie
    ss.set_cookie("session_id", token, secure=True)
    assert ss.get_cookie("session_id") == token


def test_custom_database_crud(tmp_path):
    """Test document collection insertions, queries, updates, and deletes in CustomDatabase."""
    db_file = tmp_path / "test_db.json"
    db = CustomDatabase(db_path=db_file)

    users = db.collection("users")

    # Insert single
    u1_id = users.insert({"name": "Nyx", "role": "assistant", "active": True})
    assert u1_id is not None

    # Insert many
    users.insert_many([
        {"name": "Alice", "role": "dev", "active": True},
        {"name": "Bob", "role": "tester", "active": False},
    ])

    assert users.count() == 3

    # Find one
    nyx_doc = users.find_one({"name": "Nyx"})
    assert nyx_doc is not None
    assert nyx_doc["role"] == "assistant"

    # Find with query
    active_users = users.find({"active": True})
    assert len(active_users) == 2

    # Update
    updated_count = users.update({"name": "Bob"}, {"active": True})
    assert updated_count == 1
    assert users.find_one({"name": "Bob"})["active"] is True

    # Delete
    del_count = users.delete({"name": "Bob"})
    assert del_count == 1
    assert users.count() == 2
