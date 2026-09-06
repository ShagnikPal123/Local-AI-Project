"""Accounts, roles, and invites (ROADMAP AA1-AA5).

Most of these are negative tests. A test proving an ordinary user *cannot* reach
an admin route is worth more than one proving an admin can.
"""

import json
import time

import pytest

from auth import (
    AuthError,
    AuthStore,
    Invite,
    Permission,
    Role,
    User,
    WeakPasswordError,
    has_permission,
    hash_password,
    invite_link,
    verify_password,
)

OWNER_EMAIL = "shagnikpal@gmail.com"
GOOD_PASSWORD = "a-long-enough-passphrase"


@pytest.fixture
def store(tmp_path):
    return AuthStore(tmp_path / "auth.json")


@pytest.fixture
def owner_token(store):
    store.bootstrap_owner(OWNER_EMAIL)
    store.set_password(OWNER_EMAIL, GOOD_PASSWORD)
    return store.authenticate(OWNER_EMAIL, GOOD_PASSWORD)


# --- password storage ----------------------------------------------------------

def test_password_round_trips():
    h, s = hash_password(GOOD_PASSWORD)
    assert verify_password(GOOD_PASSWORD, h, s) is True
    assert verify_password("wrong-password-entirely", h, s) is False


def test_same_password_gets_a_different_hash_each_time():
    """Per-user salt: identical passwords must not collide in the store."""
    h1, s1 = hash_password(GOOD_PASSWORD)
    h2, s2 = hash_password(GOOD_PASSWORD)
    assert s1 != s2 and h1 != h2


def test_plaintext_password_is_never_written_to_disk(store, tmp_path):
    store.bootstrap_owner(OWNER_EMAIL)
    store.set_password(OWNER_EMAIL, GOOD_PASSWORD)
    on_disk = (tmp_path / "auth.json").read_text(encoding="utf-8")
    assert GOOD_PASSWORD not in on_disk


def test_public_view_omits_every_secret(store):
    store.bootstrap_owner(OWNER_EMAIL)
    store.set_password(OWNER_EMAIL, GOOD_PASSWORD)
    public = store.get_user(OWNER_EMAIL).public()
    assert "password_hash" not in public
    assert "password_salt" not in public
    assert GOOD_PASSWORD not in json.dumps(public)


def test_malformed_stored_hash_fails_closed():
    assert verify_password(GOOD_PASSWORD, "not-hex", "also-not-hex") is False
    assert verify_password(GOOD_PASSWORD, "", "") is False


def test_short_password_is_rejected(store):
    store.bootstrap_owner(OWNER_EMAIL)
    with pytest.raises(WeakPasswordError):
        store.set_password(OWNER_EMAIL, "short")


# --- the bootstrap ships no credential -----------------------------------------

def test_owner_is_created_without_a_password(store):
    """Nothing in the repo may contain a working credential."""
    user = store.bootstrap_owner(OWNER_EMAIL)
    assert user.role is Role.OWNER
    assert user.has_password is False


def test_owner_cannot_sign_in_until_a_password_is_set(store):
    store.bootstrap_owner(OWNER_EMAIL)
    with pytest.raises(AuthError):
        store.authenticate(OWNER_EMAIL, "")


def test_only_one_owner_can_exist(store):
    store.bootstrap_owner(OWNER_EMAIL)
    with pytest.raises(AuthError):
        store.bootstrap_owner("someone-else@example.com")


def test_bootstrap_is_idempotent(store):
    first = store.bootstrap_owner(OWNER_EMAIL)
    assert store.bootstrap_owner(OWNER_EMAIL) is first


def test_email_is_case_insensitive(store):
    store.bootstrap_owner(OWNER_EMAIL)
    store.set_password(OWNER_EMAIL, GOOD_PASSWORD)
    assert store.authenticate("ShagnikPal@Gmail.COM", GOOD_PASSWORD)


# --- login does not leak whether an account exists ------------------------------

def test_unknown_and_wrong_password_give_the_same_error(store):
    store.bootstrap_owner(OWNER_EMAIL)
    store.set_password(OWNER_EMAIL, GOOD_PASSWORD)
    with pytest.raises(AuthError) as unknown:
        store.authenticate("nobody@example.com", GOOD_PASSWORD)
    with pytest.raises(AuthError) as wrong:
        store.authenticate(OWNER_EMAIL, "definitely-the-wrong-one")
    assert str(unknown.value) == str(wrong.value)


# --- permissions: deny by default ----------------------------------------------

def test_owner_has_every_permission():
    assert all(has_permission(Role.OWNER, p) for p in Permission)


@pytest.mark.parametrize("permission", [
    Permission.MODIFY_BASE_AI,
    Permission.GRANT_ADMIN,
    Permission.MACHINE_CONTROL,
])
def test_admin_cannot_do_owner_only_things(permission):
    assert has_permission(Role.ADMIN, permission) is False


@pytest.mark.parametrize("role", [Role.BETA, Role.USER])
@pytest.mark.parametrize("permission", [
    Permission.VIEW_ADMIN,
    Permission.PUBLISH_CHANGES,
    Permission.MODIFY_BASE_AI,
    Permission.INVITE_TESTERS,
    Permission.MACHINE_CONTROL,
])
def test_non_admins_get_nothing_privileged(role, permission):
    assert has_permission(role, permission) is False


def test_machine_control_is_owner_only():
    """The most dangerous capability in the product."""
    for role in (Role.ADMIN, Role.BETA, Role.USER):
        assert has_permission(role, Permission.MACHINE_CONTROL) is False
    assert has_permission(Role.OWNER, Permission.MACHINE_CONTROL) is True


# --- sessions ------------------------------------------------------------------

def test_bad_token_resolves_to_nobody(store):
    assert store.resolve_session("not-a-real-token") is None
    assert store.resolve_session("") is None


def test_expired_session_is_rejected(store, owner_token):
    store.sessions[owner_token] = (OWNER_EMAIL, time.time() - 1)
    assert store.resolve_session(owner_token) is None


def test_logout_invalidates_the_token(store, owner_token):
    store.logout(owner_token)
    assert store.resolve_session(owner_token) is None


def test_require_rejects_an_anonymous_caller(store):
    with pytest.raises(AuthError):
        store.require("", Permission.VIEW_ADMIN)


# --- invites -------------------------------------------------------------------

def test_owner_can_invite_a_beta_tester(store, owner_token):
    invite = store.create_invite(owner_token, Role.BETA)
    user = store.redeem_invite(invite.token, "tester@example.com", GOOD_PASSWORD)
    assert user.role is Role.BETA
    assert user.invited_by == OWNER_EMAIL


def test_an_invite_is_single_use(store, owner_token):
    invite = store.create_invite(owner_token, Role.BETA)
    store.redeem_invite(invite.token, "first@example.com", GOOD_PASSWORD)
    with pytest.raises(AuthError):
        store.redeem_invite(invite.token, "second@example.com", GOOD_PASSWORD)


def test_an_expired_invite_is_rejected(store, owner_token):
    invite = store.create_invite(owner_token, Role.BETA, ttl_seconds=-1)
    with pytest.raises(AuthError):
        store.redeem_invite(invite.token, "late@example.com", GOOD_PASSWORD)


def test_an_email_pinned_invite_rejects_a_different_address(store, owner_token):
    invite = store.create_invite(owner_token, Role.BETA, email="intended@example.com")
    with pytest.raises(AuthError):
        store.redeem_invite(invite.token, "someone-else@example.com", GOOD_PASSWORD)


def test_a_beta_tester_cannot_invite_anyone(store, owner_token):
    invite = store.create_invite(owner_token, Role.BETA)
    store.redeem_invite(invite.token, "tester@example.com", GOOD_PASSWORD)
    tester_token = store.authenticate("tester@example.com", GOOD_PASSWORD)
    with pytest.raises(AuthError):
        store.create_invite(tester_token, Role.BETA)


def test_an_admin_cannot_invite_another_admin(store, owner_token):
    """Only the owner grows the admin set."""
    invite = store.create_invite(owner_token, Role.ADMIN)
    store.redeem_invite(invite.token, "admin@example.com", GOOD_PASSWORD)
    admin_token = store.authenticate("admin@example.com", GOOD_PASSWORD)
    with pytest.raises(AuthError):
        store.create_invite(admin_token, Role.ADMIN)


def test_nobody_can_be_invited_as_owner(store, owner_token):
    with pytest.raises(AuthError):
        store.create_invite(owner_token, Role.OWNER)


def test_invite_link_is_shareable():
    assert invite_link("https://nyx.example.com/", "abc123") == (
        "https://nyx.example.com/join?invite=abc123"
    )


# --- role changes ---------------------------------------------------------------

def test_owner_can_promote_a_tester_to_admin(store, owner_token):
    invite = store.create_invite(owner_token, Role.BETA)
    store.redeem_invite(invite.token, "tester@example.com", GOOD_PASSWORD)
    promoted = store.grant_role(owner_token, "tester@example.com", Role.ADMIN)
    assert promoted.role is Role.ADMIN


def test_an_admin_cannot_promote_anyone(store, owner_token):
    invite = store.create_invite(owner_token, Role.ADMIN)
    store.redeem_invite(invite.token, "admin@example.com", GOOD_PASSWORD)
    admin_token = store.authenticate("admin@example.com", GOOD_PASSWORD)
    beta = store.create_invite(owner_token, Role.BETA)
    store.redeem_invite(beta.token, "tester@example.com", GOOD_PASSWORD)
    with pytest.raises(AuthError):
        store.grant_role(admin_token, "tester@example.com", Role.ADMIN)


def test_the_owner_role_cannot_be_taken_away(store, owner_token):
    with pytest.raises(AuthError):
        store.grant_role(owner_token, OWNER_EMAIL, Role.USER)


# --- persistence ----------------------------------------------------------------

def test_accounts_survive_a_restart(tmp_path):
    path = tmp_path / "auth.json"
    first = AuthStore(path)
    first.bootstrap_owner(OWNER_EMAIL)
    first.set_password(OWNER_EMAIL, GOOD_PASSWORD)

    second = AuthStore(path)
    assert second.authenticate(OWNER_EMAIL, GOOD_PASSWORD)


def test_sessions_do_not_survive_a_restart(tmp_path):
    """A restart logging everyone out is the safe default here."""
    path = tmp_path / "auth.json"
    first = AuthStore(path)
    first.bootstrap_owner(OWNER_EMAIL)
    first.set_password(OWNER_EMAIL, GOOD_PASSWORD)
    token = first.authenticate(OWNER_EMAIL, GOOD_PASSWORD)

    assert AuthStore(path).resolve_session(token) is None


def test_a_corrupt_store_does_not_crash_startup(tmp_path):
    path = tmp_path / "auth.json"
    path.write_text("{ this is not json", encoding="utf-8")
    assert AuthStore(path).users == {}


# --- Google sign-in --------------------------------------------------------------

def test_google_signin_requires_an_existing_invited_account(store):
    with pytest.raises(AuthError):
        store.authenticate_google("stranger@example.com", "google-subject-123")


def test_google_signin_binds_the_subject_on_first_use(store, owner_token):
    invite = store.create_invite(owner_token, Role.BETA)
    store.redeem_invite(invite.token, "tester@example.com")
    store.authenticate_google("tester@example.com", "google-subject-123")
    assert store.get_user("tester@example.com").google_subject == "google-subject-123"


def test_google_signin_rejects_a_mismatched_subject(store, owner_token):
    invite = store.create_invite(owner_token, Role.BETA)
    store.redeem_invite(invite.token, "tester@example.com")
    store.authenticate_google("tester@example.com", "google-subject-123")
    with pytest.raises(AuthError):
        store.authenticate_google("tester@example.com", "a-different-subject")
