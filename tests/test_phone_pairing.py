"""Phone pairing key: lives one minute, works once, cannot be guessed in bulk, and the token is stored only as a hash.

A fake clock stands in for time, and the device list is written to a temp folder, so nothing waits or touches the
real data folder.
"""

from __future__ import annotations

import json

import pytest

import phone_pairing as pp


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def phones(tmp_path, clock):
    return pp.PhoneBook(path=tmp_path / "phones.json", clock=clock)


def test_key_is_short_readable_and_leaves_no_trace_on_disk(phones, tmp_path):
    made = phones.mint()
    assert len(pp.clean_key(made["key"])) == pp.KEY_LENGTH
    assert made["expires_in"] == 60
    assert all(ch in pp.ALPHABET + "-" for ch in made["key"])
    assert not (tmp_path / "phones.json").exists()          # nothing is written until a phone connects


def test_correct_key_gives_a_token_and_stores_only_its_hash(phones, tmp_path):
    key = phones.mint()["key"]
    got = phones.redeem(key, "Pixel", "192.168.1.20")
    assert got["device"]["name"] == "Pixel"
    stored = (tmp_path / "phones.json").read_text(encoding="utf-8")
    assert got["token"] not in stored and "token_hash" in stored
    assert phones.authenticate(got["token"])["name"] == "Pixel"
    assert phones.authenticate("not-the-token") is None


def test_key_can_be_typed_loosely(phones):
    key = phones.mint()["key"]
    assert phones.redeem(key.lower().replace("-", " "), "Phone", "a")["token"]


def test_key_works_only_once(phones):
    key = phones.mint()["key"]
    phones.redeem(key, "First", "a")
    with pytest.raises(pp.PairingError):
        phones.redeem(key, "Second", "b")
    assert len(phones.devices()) == 1


def test_key_expires_after_a_minute(phones, clock):
    key = phones.mint()["key"]
    assert phones.key_seconds_left() == 60
    clock.now += 59
    assert phones.key_seconds_left() >= 1
    clock.now += 2
    assert phones.key_seconds_left() == 0
    with pytest.raises(pp.PairingError):
        phones.redeem(key, "Late", "a")
    assert phones.devices() == []


def test_new_key_replaces_the_old_one(phones):
    old = phones.mint()["key"]
    new = phones.mint()["key"]
    with pytest.raises(pp.PairingError):
        phones.redeem(old, "Old", "a")
    assert phones.redeem(new, "New", "a")["token"]


def test_no_key_means_nothing_connects(phones):
    with pytest.raises(pp.PairingError):
        phones.redeem("AAAA-AAAA", "Phone", "a")


def test_wrong_keys_are_rationed_per_phone_and_overall(phones, clock):
    phones.mint()
    for _ in range(pp.TRIES_PER_SOURCE):
        with pytest.raises(pp.PairingError, match="wrong or has run out"):
            phones.redeem("BBBB-BBBB", "x", "10.0.0.5")
    with pytest.raises(pp.PairingError, match="Too many"):
        phones.redeem("BBBB-BBBB", "x", "10.0.0.5")
    # another address is limited by the overall cap, which a swarm of addresses cannot get around
    for n in range(pp.TRIES_OVERALL - pp.TRIES_PER_SOURCE):
        with pytest.raises(pp.PairingError):
            phones.redeem("BBBB-BBBB", "x", f"10.0.1.{n}")
    with pytest.raises(pp.PairingError, match="Too many"):
        phones.redeem("BBBB-BBBB", "x", "10.0.2.1")
    clock.now += 61                                          # a minute later the limit lifts
    key = phones.mint()["key"]
    assert phones.redeem(key, "Phone", "10.0.0.5")["token"]


def test_a_wrong_guess_does_not_burn_the_real_key(phones):
    key = phones.mint()["key"]
    with pytest.raises(pp.PairingError):
        phones.redeem("CCCC-CCCC", "x", "a")
    assert phones.redeem(key, "Mine", "b")["token"]


def test_revoke_takes_the_phone_back(phones):
    token = phones.redeem(phones.mint()["key"], "Phone", "a")
    device_id = token["device"]["id"]
    assert phones.revoke(device_id) is True
    assert phones.authenticate(token["token"]) is None
    assert phones.revoke(device_id) is False


def test_phone_limit(phones):
    for n in range(pp.MAX_DEVICES):
        phones.redeem(phones.mint()["key"], f"Phone {n}", "a")
    with pytest.raises(pp.PairingError, match="already connected"):
        phones.redeem(phones.mint()["key"], "One more", "a")


def test_idle_phone_must_pair_again(phones, clock):
    token = phones.redeem(phones.mint()["key"], "Phone", "a")["token"]
    clock.now += pp.TOKEN_IDLE_SECONDS + 5
    assert phones.authenticate(token) is None
    assert phones.devices() == []


def test_corrupt_device_file_is_treated_as_empty(tmp_path, clock):
    path = tmp_path / "phones.json"
    path.write_text("{not json", encoding="utf-8")
    book = pp.PhoneBook(path=path, clock=clock)
    assert book.devices() == []
    assert book.redeem(book.mint()["key"], "Phone", "a")["token"]
    assert json.loads(path.read_text(encoding="utf-8"))[0]["name"] == "Phone"
