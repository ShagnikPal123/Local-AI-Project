"""Permission-gated machine control (ROADMAP V1-V8).

The highest-risk surface in the product. Almost every test here is an attempt to
get through the gate, because that is what matters — a test showing a granted
capability works proves much less than one showing an ungranted one does not.
"""

import time

import pytest

from machine_control import (
    Capability,
    ConfirmationRequired,
    MachineControl,
    MachineControlError,
)


@pytest.fixture
def machine():
    return MachineControl()


# --- deny by default (V1) ----------------------------------------------------------

@pytest.mark.parametrize("capability", list(Capability))
def test_nothing_is_available_before_it_is_granted(machine, capability):
    with pytest.raises(MachineControlError):
        machine.check(capability, "read", "anything")


def test_a_grant_opens_exactly_one_capability(machine):
    machine.grant(Capability.FILES_READ, granted_by="owner@example.com")
    machine.check(Capability.FILES_READ, "read", "C:/Users/shagn/notes.txt")
    with pytest.raises(MachineControlError):
        machine.check(Capability.FILES_WRITE, "write", "C:/Users/shagn/notes.txt")


def test_a_grant_must_have_a_lifetime(machine):
    with pytest.raises(MachineControlError):
        machine.grant(Capability.DESKTOP, ttl_seconds=0)


def test_an_expired_grant_no_longer_authorises(machine):
    """A permission the user forgot they gave is one they did not really give."""
    machine.grant(Capability.DESKTOP, ttl_seconds=1)
    machine._grants[Capability.DESKTOP].expires_at = time.time() - 1
    with pytest.raises(MachineControlError) as excinfo:
        machine.check(Capability.DESKTOP, "screenshot")
    assert "not granted" in str(excinfo.value)


# --- scope narrows a grant (V5) -----------------------------------------------------

def test_a_scoped_grant_allows_inside_the_scope(machine):
    machine.grant(Capability.FILES_WRITE, scope="C:/Users/shagn/Projects/*")
    machine.check(Capability.FILES_WRITE, "write", "C:/Users/shagn/Projects/app/main.py")


def test_a_scoped_grant_refuses_outside_the_scope(machine):
    machine.grant(Capability.FILES_WRITE, scope="C:/Users/shagn/Projects/*")
    with pytest.raises(MachineControlError) as excinfo:
        machine.check(Capability.FILES_WRITE, "write", "C:/Users/shagn/Documents/taxes.pdf")
    assert "outside the granted scope" in str(excinfo.value)


def test_scope_matching_is_slash_agnostic(machine):
    """Windows paths arrive with backslashes; the scope should still hold."""
    machine.grant(Capability.FILES_WRITE, scope="C:/Users/shagn/Projects/*")
    machine.check(Capability.FILES_WRITE, "write", r"C:\Users\shagn\Projects\app\main.py")


# --- some things are never reachable ------------------------------------------------

@pytest.mark.parametrize("target", [
    "C:/Users/shagn/.ssh/id_rsa",
    "C:/Windows/System32/drivers/etc/hosts",
    "/etc/shadow",
    "C:/Users/shagn/project/.env.local",
    "C:/Users/shagn/project/auth.json",
])
def test_forbidden_targets_are_refused_even_with_a_full_grant(machine, target):
    """A capability the user cannot switch on is stronger than one they can."""
    machine.grant(Capability.FILES_READ)  # unscoped: the widest possible grant
    with pytest.raises(MachineControlError) as excinfo:
        machine.check(Capability.FILES_READ, "read", target)
    assert "off limits" in str(excinfo.value)


def test_a_forbidden_target_is_refused_before_the_grant_is_even_checked(machine):
    """Order matters: no grant can open one of these."""
    with pytest.raises(MachineControlError) as excinfo:
        machine.check(Capability.FILES_READ, "read", "/etc/shadow")
    assert "off limits" in str(excinfo.value)


# --- destructive actions need confirmation regardless (V7) ---------------------------

def test_a_destructive_action_needs_confirmation_even_when_granted(machine):
    """A standing grant to write is not consent to delete."""
    machine.grant(Capability.FILES_WRITE)
    with pytest.raises(ConfirmationRequired):
        machine.check(Capability.FILES_WRITE, "delete", "C:/Users/shagn/notes.txt")


def test_a_confirmed_destructive_action_proceeds(machine):
    machine.grant(Capability.FILES_WRITE)
    machine.check(Capability.FILES_WRITE, "delete", "C:/Users/shagn/notes.txt", confirmed=True)


def test_confirmation_does_not_bypass_the_grant(machine):
    """Confirming something you were never allowed to do must still fail."""
    with pytest.raises(MachineControlError) as excinfo:
        machine.check(Capability.FILES_WRITE, "delete", "x", confirmed=True)
    assert "not granted" in str(excinfo.value)


def test_confirmation_does_not_bypass_a_forbidden_target(machine):
    machine.grant(Capability.FILES_WRITE)
    with pytest.raises(MachineControlError) as excinfo:
        machine.check(Capability.FILES_WRITE, "delete", "/etc/shadow", confirmed=True)
    assert "off limits" in str(excinfo.value)


def test_a_non_destructive_action_needs_no_confirmation(machine):
    machine.grant(Capability.DESKTOP)
    machine.check(Capability.DESKTOP, "screenshot")


# --- the kill switch (V8) -----------------------------------------------------------

def test_revoke_all_drops_everything(machine):
    machine.grant(Capability.FILES_READ)
    machine.grant(Capability.DESKTOP)
    machine.grant(Capability.BROWSER)

    assert machine.revoke_all(actor="owner@example.com") == 3
    assert machine.active_grants() == []
    for capability in (Capability.FILES_READ, Capability.DESKTOP, Capability.BROWSER):
        with pytest.raises(MachineControlError):
            machine.check(capability, "read", "x")


def test_revoking_one_capability_leaves_the_others(machine):
    machine.grant(Capability.FILES_READ)
    machine.grant(Capability.DESKTOP)
    assert machine.revoke(Capability.DESKTOP) is True
    machine.check(Capability.FILES_READ, "read", "x")
    with pytest.raises(MachineControlError):
        machine.check(Capability.DESKTOP, "screenshot")


def test_revoking_something_never_granted_reports_failure(machine):
    assert machine.revoke(Capability.BROWSER) is False


# --- the audit trail (V6) -------------------------------------------------------------

def test_an_allowed_action_is_logged(machine):
    machine.grant(Capability.DESKTOP)
    machine.check(Capability.DESKTOP, "screenshot", "screen.png")
    entry = machine.audit()[-1]
    assert entry["allowed"] is True
    assert entry["action"] == "screenshot"


def test_a_refused_action_is_also_logged(machine):
    """A trail that only records successes cannot answer 'what did it try to do'."""
    with pytest.raises(MachineControlError):
        machine.check(Capability.FILES_WRITE, "write", "secret.txt")
    entry = machine.audit()[-1]
    assert entry["allowed"] is False
    assert entry["reason"] == "no grant"


def test_refusals_can_be_isolated(machine):
    machine.grant(Capability.DESKTOP)
    machine.check(Capability.DESKTOP, "screenshot")
    with pytest.raises(MachineControlError):
        machine.check(Capability.FILES_WRITE, "write", "x")

    refused = machine.audit(refused_only=True)
    assert all(not e["allowed"] for e in refused)
    assert any(e["action"] == "write" for e in refused)


def test_grants_and_revocations_are_themselves_audited(machine):
    machine.grant(Capability.DESKTOP, granted_by="owner@example.com")
    machine.revoke_all(actor="owner@example.com")
    actions = [e["action"] for e in machine.audit()]
    assert "grant" in actions
    assert "revoke_all" in actions


def test_the_audit_trail_is_bounded(machine):
    machine.grant(Capability.DESKTOP)
    for _ in range(600):
        machine.check(Capability.DESKTOP, "screenshot")
    assert len(machine.audit(limit=1000)) <= 500


def test_logging_never_raises_into_the_caller(machine):
    """An audit failure must not become a way to perform an unlogged action."""
    machine.grant(Capability.DESKTOP)
    machine.check(Capability.DESKTOP, "x" * 5000, "y" * 5000)


# --- the non-raising helper -------------------------------------------------------------

def test_is_allowed_reports_without_raising(machine):
    assert machine.is_allowed(Capability.DESKTOP, "screenshot") is False
    machine.grant(Capability.DESKTOP)
    assert machine.is_allowed(Capability.DESKTOP, "screenshot") is True


def test_is_allowed_still_respects_forbidden_targets(machine):
    machine.grant(Capability.FILES_READ)
    assert machine.is_allowed(Capability.FILES_READ, "read", "/etc/shadow") is False


# --- the snapshot the UI renders ----------------------------------------------------------

def test_the_snapshot_reports_what_is_granted(machine):
    machine.grant(Capability.DESKTOP)
    snapshot = machine.snapshot()
    granted = {c["id"] for c in snapshot["capabilities"] if c["granted"]}
    assert granted == {"desktop"}


def test_the_snapshot_names_destructive_actions_and_forbidden_targets(machine):
    snapshot = machine.snapshot()
    assert "delete" in snapshot["destructive_actions"]
    assert any(".ssh" in p for p in snapshot["forbidden_targets"])


# --- the hosted build must not contain these routes at all (ROADMAP BB12) -------------

from unittest.mock import patch

from fastapi.testclient import TestClient

import server
import server_auth
from auth import AuthStore
from deploy_mode import DeployMode, current_mode, describe, is_route_available


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setenv("NYX_MODE", "hosted")


@pytest.fixture
def api(tmp_path, monkeypatch):
    fresh = AuthStore(tmp_path / "auth.json")
    monkeypatch.setattr(server_auth, "AUTH_STORE", fresh)
    monkeypatch.setattr(server, "AUTH_STORE", fresh)
    return TestClient(server.app)


def test_local_is_the_default(monkeypatch):
    """A hosted build that thinks it is local is a breach; the reverse is a nuisance."""
    monkeypatch.delenv("NYX_MODE", raising=False)
    assert current_mode() is DeployMode.LOCAL


def test_an_unrecognised_mode_falls_back_to_local(monkeypatch):
    monkeypatch.setenv("NYX_MODE", "banana")
    assert current_mode() is DeployMode.LOCAL


@pytest.mark.parametrize("path", [
    "/api/machine",
    "/api/machine/grant",
    "/api/machine/revoke",
    "/api/overlay/restore",
])
def test_dangerous_routes_are_absent_from_a_hosted_build(hosted, path):
    assert is_route_available(path) is False


@pytest.mark.parametrize("path", [
    "/api/chat", "/api/health", "/api/skills", "/api/tabs", "/api/agents",
])
def test_ordinary_routes_survive_in_a_hosted_build(hosted, path):
    assert is_route_available(path) is True


@pytest.mark.parametrize("path", [
    "/api/machine",
    "/api/machine/grant",
    "/api/overlay/restore",
])
def test_a_hosted_build_returns_404_not_403(api, hosted, path):
    """404 so a probe cannot even confirm the capability exists here."""
    response = api.get(path) if path == "/api/machine" else api.post(path, json={})
    assert response.status_code == 404


def test_a_local_build_still_exposes_machine_control(api, monkeypatch):
    monkeypatch.delenv("NYX_MODE", raising=False)
    # 401/403 means the route exists and is gated — not 404.
    assert api.get("/api/machine").status_code in (401, 403)


def test_health_reports_what_this_build_can_do(api, hosted):
    build = api.get("/api/health").json()["build"]
    assert build["mode"] == "hosted"
    assert build["machine_control"] is False


def test_describe_is_honest_about_a_local_build(monkeypatch):
    monkeypatch.delenv("NYX_MODE", raising=False)
    assert describe()["machine_control"] is True
