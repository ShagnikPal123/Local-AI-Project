"""Self-approval (WS15): the owner's switch, off by default, and a log of every change Ichos approved itself."""

import pytest

import self_approval


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(self_approval, "data_path", lambda name: tmp_path / name)


def test_off_by_default_and_the_switch_sticks():
    assert self_approval.enabled() is False
    self_approval.set_enabled(True)
    assert self_approval.enabled() is True


def test_every_self_approval_is_logged_newest_first():
    self_approval.record("c1", "Faster startup", "cuts 2 s")
    self_approval.record("c2", "Fix typo", "obvious")
    items = self_approval.log()
    assert [i["change_id"] for i in items] == ["c2", "c1"]
    assert items[1]["reason"] == "cuts 2 s" and items[0]["status"] == "gone"


def test_autopilot_runs_auto_approve_while_the_switch_is_on(monkeypatch, tmp_path):
    import improve_autopilot

    assert improve_autopilot._self_approval_on() is False
    self_approval.set_enabled(True)
    assert improve_autopilot._self_approval_on() is True
