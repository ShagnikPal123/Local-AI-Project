"""Tests for access_keys.py (signed beta/dev keys and their stores).

Every store access_keys.py touches is isolated to tmp_path here: the real
secret_store and the real access_public_keys.json / access_minted.json etc.
must never be written by a test run (AGENTS.md section 7, and the module's own
contract says as much for access_public_keys.json specifically).
"""

from __future__ import annotations

import json
import time

import pytest

import access_keys


# ---------------------------------------------------------------------------
# RFC 8032 section 7.1 test vectors 1-3 - pin the primitive itself, independent
# of anything this module does with it.
# ---------------------------------------------------------------------------

RFC_8032_VECTORS = [
    (
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "",
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8"
        "821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
    ),
    (
        "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        "72",
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085"
        "ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
    ),
    (
        "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
        "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
        "af82",
        "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18"
        "ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a",
    ),
]


@pytest.mark.parametrize("secret_hex,public_hex,message_hex,signature_hex", RFC_8032_VECTORS)
def test_rfc8032_public_key_matches(secret_hex, public_hex, message_hex, signature_hex):
    seed = bytes.fromhex(secret_hex)
    assert access_keys.ed25519_public_key(seed) == bytes.fromhex(public_hex)


@pytest.mark.parametrize("secret_hex,public_hex,message_hex,signature_hex", RFC_8032_VECTORS)
def test_rfc8032_signature_matches(secret_hex, public_hex, message_hex, signature_hex):
    seed = bytes.fromhex(secret_hex)
    message = bytes.fromhex(message_hex)
    assert access_keys.ed25519_sign(message, seed) == bytes.fromhex(signature_hex)


@pytest.mark.parametrize("secret_hex,public_hex,message_hex,signature_hex", RFC_8032_VECTORS)
def test_rfc8032_signature_verifies(secret_hex, public_hex, message_hex, signature_hex):
    public_key = bytes.fromhex(public_hex)
    message = bytes.fromhex(message_hex)
    signature = bytes.fromhex(signature_hex)
    assert access_keys.ed25519_verify(message, signature, public_key) is True


def test_a_flipped_message_byte_fails_verification():
    seed = bytes.fromhex(RFC_8032_VECTORS[1][0])
    public_key = bytes.fromhex(RFC_8032_VECTORS[1][1])
    signature = bytes.fromhex(RFC_8032_VECTORS[1][3])
    assert access_keys.ed25519_verify(b"\x73", signature, public_key) is False


def test_keypair_from_seed_round_trips():
    seed = bytes.fromhex(RFC_8032_VECTORS[0][0])
    public_key, returned_seed = access_keys.ed25519_keypair_from_seed(seed)
    assert returned_seed == seed
    assert public_key == bytes.fromhex(RFC_8032_VECTORS[0][1])


def test_a_seed_of_the_wrong_length_is_rejected():
    with pytest.raises(ValueError):
        access_keys.ed25519_keypair_from_seed(b"too-short")


# ---------------------------------------------------------------------------
# Store isolation: every persistent path the module touches is redirected to
# tmp_path, and the signing seed lives in a fake in-memory secret_store so a
# test run never creates a real key.
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Redirect every access_keys store (and secret_store) into tmp_path."""

    monkeypatch.setattr(access_keys, "data_path", lambda name: tmp_path / name)
    monkeypatch.setattr(access_keys, "project_path", lambda name: tmp_path / name)

    fake_secrets: dict[str, list[str]] = {}

    def fake_get_keys(name):
        return list(fake_secrets.get(name, []))

    def fake_set_keys(name, keys):
        values = [k for k in keys if k]
        fake_secrets[name] = values
        return values

    monkeypatch.setattr(access_keys.secret_store, "get_keys", fake_get_keys)
    monkeypatch.setattr(access_keys.secret_store, "set_keys", fake_set_keys)

    # access_public_keys.json ships with `{"keys": []}`; start each test from
    # that same shape rather than a missing file, matching the shipped state.
    (tmp_path / "access_public_keys.json").write_text(
        json.dumps({"keys": []}), encoding="utf-8"
    )
    return tmp_path


def test_ensure_signing_key_is_idempotent(isolated):
    first = access_keys.ensure_signing_key()
    second = access_keys.ensure_signing_key()
    assert first == second
    assert len(bytes.fromhex(first["public_key"])) == 32

    public_keys = json.loads((isolated / "access_public_keys.json").read_text())
    assert len(public_keys["keys"]) == 1
    assert public_keys["keys"][0]["kid"] == first["kid"]


def test_ensure_signing_key_never_returns_the_seed(isolated):
    identity = access_keys.ensure_signing_key()
    assert "seed" not in identity
    assert "private" not in json.dumps(identity)


def test_mint_and_verify_round_trip(isolated):
    minted = access_keys.mint("beta", "Ada Tester", email="ada@example.com", days=30, actor="owner")
    assert minted["key"].startswith("NYX1-")
    payload = access_keys.verify(minted["key"])
    assert payload["role"] == "beta"
    assert payload["name"] == "Ada Tester"
    assert payload["id"] == minted["id"]
    assert "nyx://redeem?key=" in minted["redeem_link"]
    assert minted["key"] in minted["invite_text"]


def test_mint_rejects_an_unknown_role(isolated):
    with pytest.raises(access_keys.AccessKeyError):
        access_keys.mint("superuser", "Someone")


def test_mint_rejects_an_empty_name(isolated):
    with pytest.raises(access_keys.AccessKeyError):
        access_keys.mint("beta", "   ")


def test_a_never_expiring_key_has_exp_zero(isolated):
    minted = access_keys.mint("dev", "Perma Dev", days=0)
    assert minted["payload"]["exp"] == 0
    assert access_keys.verify(minted["key"])["exp"] == 0


def test_a_tampered_payload_fails_as_bad_signature(isolated):
    minted = access_keys.mint("beta", "Eve")
    prefix, sig_part = minted["key"].split(".", 1)
    header, payload_b64 = prefix.split("-", 1)
    payload_bytes = access_keys._b64u_decode(payload_b64)
    payload = json.loads(payload_bytes)
    payload["role"] = "dev"  # tamper: try to escalate the role
    tampered_b64 = access_keys._b64u_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    tampered_key = f"{header}-{tampered_b64}.{sig_part}"

    with pytest.raises(access_keys.AccessKeyError, match="signature"):
        access_keys.verify(tampered_key)


def test_a_malformed_key_is_rejected(isolated):
    for bad in ["", "not-a-key", "NYX1-onlyonepart", "NYX1-a.b.c"]:
        with pytest.raises(access_keys.AccessKeyError):
            access_keys.verify(bad)


def test_an_expired_key_is_rejected(isolated):
    minted = access_keys.mint("beta", "Expired Tester", days=1)
    prefix, sig_part = minted["key"].split(".", 1)
    header, payload_b64 = prefix.split("-", 1)
    payload = json.loads(access_keys._b64u_decode(payload_b64))
    payload["exp"] = int(time.time()) - 3600
    seed = access_keys._load_seed()
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = access_keys.ed25519_sign(payload_bytes, seed)
    expired_key = f"{header}-{access_keys._b64u_encode(payload_bytes)}.{access_keys._b64u_encode(signature)}"

    with pytest.raises(access_keys.AccessKeyError, match="expired"):
        access_keys.verify(expired_key)


def test_a_revoked_key_is_rejected(isolated):
    minted = access_keys.mint("dev", "Revoke Me")
    access_keys.verify(minted["key"])  # valid before revocation
    access_keys.revoke(minted["id"], actor="owner")
    with pytest.raises(access_keys.AccessKeyError, match="revoked"):
        access_keys.verify(minted["key"])


def test_an_unknown_kid_is_rejected(isolated):
    minted = access_keys.mint("beta", "Someone")
    # Wipe the public key file: the kid embedded in the key no longer resolves.
    (isolated / "access_public_keys.json").write_text(json.dumps({"keys": []}), encoding="utf-8")
    with pytest.raises(access_keys.AccessKeyError, match="unknown"):
        access_keys.verify(minted["key"])


def test_redeem_records_the_key_locally_and_status_reflects_it(isolated):
    minted = access_keys.mint("beta", "Redeemer")
    access_keys.redeem(minted["key"])
    result = access_keys.status(owner=False)
    assert result["level"] == "beta"
    assert result["features"]["feedback"] is True
    assert result["features"]["developer_panel"] is False
    assert any(k["id"] == minted["id"] and k["valid"] for k in result["keys"])


def test_dev_outranks_beta_in_status(isolated):
    beta = access_keys.mint("beta", "Beta One")
    dev = access_keys.mint("dev", "Dev One")
    access_keys.redeem(beta["key"])
    access_keys.redeem(dev["key"])
    result = access_keys.status(owner=False)
    assert result["level"] == "dev"
    assert result["features"]["developer_panel"] is True


def test_owner_flag_wins_regardless_of_keys(isolated):
    result = access_keys.status(owner=True)
    assert result["level"] == "owner"
    assert all(result["features"].values())


def test_standard_level_has_no_features(isolated):
    result = access_keys.status(owner=False)
    assert result["level"] == "standard"
    assert not any(result["features"].values())


def test_revoking_a_redeemed_key_drops_its_status_validity(isolated):
    minted = access_keys.mint("beta", "Later Revoked")
    access_keys.redeem(minted["key"])
    access_keys.revoke(minted["id"], actor="owner")
    result = access_keys.status(owner=False)
    assert result["level"] == "standard"
    entry = next(k for k in result["keys"] if k["id"] == minted["id"])
    assert entry["valid"] is False


def test_list_minted_reports_minted_keys(isolated):
    access_keys.mint("beta", "One")
    access_keys.mint("dev", "Two")
    listed = access_keys.list_minted()
    assert len(listed["keys"]) == 2
    assert {k["name"] for k in listed["keys"]} == {"One", "Two"}


def test_mint_response_never_contains_the_signing_seed(isolated):
    minted = access_keys.mint("beta", "Someone")
    seed_hex = access_keys.secret_store.get_keys(access_keys._SIGNING_KEY_NAME)[0]
    assert seed_hex not in json.dumps(minted)
    listed = access_keys.list_minted()
    assert seed_hex not in json.dumps(listed)


# --- applications ------------------------------------------------------------


def test_submit_application_then_list(isolated):
    app = access_keys.submit_application("Grace", "grace@example.com", "beta", reason="curious")
    assert app["status"] == "pending"
    listed = access_keys.list_applications()
    assert len(listed["applications"]) == 1


def test_submit_application_rejects_a_bad_email(isolated):
    with pytest.raises(access_keys.AccessKeyError):
        access_keys.submit_application("Grace", "not-an-email", "beta")


def test_submit_application_rejects_a_bad_role(isolated):
    with pytest.raises(access_keys.AccessKeyError):
        access_keys.submit_application("Grace", "grace@example.com", "admin")


def test_resubmitting_a_pending_application_updates_it_rather_than_duplicating(isolated):
    access_keys.submit_application("Grace", "grace@example.com", "beta", reason="first")
    access_keys.submit_application("Grace", "grace@example.com", "dev", reason="second")
    listed = access_keys.list_applications()["applications"]
    assert len(listed) == 1
    assert listed[0]["role"] == "dev"
    assert listed[0]["reason"] == "second"


def test_decide_application_approve_mints_a_key(isolated):
    app = access_keys.submit_application("Grace", "grace@example.com", "beta")
    decision = access_keys.decide_application(app["id"], approve=True, actor="owner", days=10)
    assert decision["application"]["status"] == "approved"
    assert decision["mint"] is not None
    payload = access_keys.verify(decision["mint"]["key"])
    assert payload["role"] == "beta"


def test_decide_application_reject_does_not_mint(isolated):
    app = access_keys.submit_application("Grace", "grace@example.com", "beta")
    decision = access_keys.decide_application(app["id"], approve=False, actor="owner")
    assert decision["application"]["status"] == "rejected"
    assert decision["mint"] is None


def test_deciding_an_already_decided_application_is_rejected(isolated):
    app = access_keys.submit_application("Grace", "grace@example.com", "beta")
    access_keys.decide_application(app["id"], approve=True, actor="owner")
    with pytest.raises(access_keys.AccessKeyError):
        access_keys.decide_application(app["id"], approve=True, actor="owner")


def test_deciding_an_unknown_application_is_rejected(isolated):
    with pytest.raises(access_keys.AccessKeyError):
        access_keys.decide_application("nope", approve=True, actor="owner")


# --- feature flags and audit --------------------------------------------------


def test_feature_flags_get_and_set(isolated):
    assert access_keys.get_flags() == {}
    updated = access_keys.set_flags({"labs_v2": True}, actor="owner")
    assert updated == {"labs_v2": True}
    assert access_keys.get_flags() == {"labs_v2": True}


def test_audit_entries_are_appended_and_readable(isolated):
    access_keys.audit("owner", "mint", "abc123", "role=beta")
    access_keys.audit("owner", "revoke", "abc123", "")
    entries = access_keys.read_audit(limit=10)
    assert len(entries) == 2
    # Newest first.
    assert entries[0]["action"] == "revoke"
    assert entries[1]["action"] == "mint"
    assert all("secret" not in json.dumps(e) for e in entries)


def test_audit_never_leaks_the_signing_seed(isolated):
    access_keys.mint("beta", "Someone")
    seed_hex = access_keys.secret_store.get_keys(access_keys._SIGNING_KEY_NAME)[0]
    entries = access_keys.read_audit(limit=50)
    assert seed_hex not in json.dumps(entries)
