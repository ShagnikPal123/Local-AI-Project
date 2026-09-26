"""Self-patching: exact edits, sandbox tests, apply-only-on-green, exact rollback (on a throwaway project)."""

from __future__ import annotations

import json

import pytest

import self_patch


@pytest.fixture()
def project(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    (root / "tests").mkdir(parents=True)
    (root / "greet.py").write_bytes(b'def greet(name):\r\n    return "hi " + name\r\n')
    (root / "tests" / "test_greet.py").write_text("import greet\n\ndef test_greet():\n    assert greet.greet('a').startswith('hi')\n")
    (root / "permissions.py").write_text("ALLOW = False\n")
    monkeypatch.setattr(self_patch, "data_path", lambda rel: (tmp_path / "data" / rel).parent.mkdir(parents=True, exist_ok=True) or tmp_path / "data" / rel)
    return root


def _model(edits, summary="Greets politely"):
    return lambda prompt, **kw: json.dumps({"summary": summary, "edits": edits})


CHANGE = {"id": "c1", "title": "Greet politely", "description": "Say hello", "target": "greet.py"}


def test_protected_and_unknown_targets_are_refused(project):
    with pytest.raises(self_patch.PatchError, match="protected"):
        self_patch.resolve_target("permissions.py", project)
    with pytest.raises(self_patch.PatchError, match="No module"):
        self_patch.resolve_target("nope.py", project)
    with pytest.raises(self_patch.PatchError):
        self_patch.resolve_target("../outside.py", project)


def test_edits_must_match_exactly_once_and_compile():
    source = "a = 1\nb = 1\n"
    with pytest.raises(self_patch.PatchError, match="appears 0 times"):
        self_patch.apply_edits(source, [{"old": "c = 1", "new": "c = 2"}])
    with pytest.raises(self_patch.PatchError, match="appears 2 times"):
        self_patch.apply_edits(source, [{"old": "= 1", "new": "= 2"}])
    with pytest.raises(self_patch.PatchError, match="does not compile"):
        self_patch.apply_edits(source, [{"old": "a = 1", "new": "a = ("}])
    with pytest.raises(self_patch.PatchError, match="limit is 1"):
        self_patch.apply_edits(source, [{"old": "a = 1\nb = 1\n", "new": "x = 1\ny = 2\nz = 3\n"}], max_changed_lines=1)
    assert self_patch.apply_edits(source, [{"old": "b = 1", "new": "b = 2"}]) == "a = 1\nb = 2\n"


def test_green_tests_apply_the_edit_keeping_crlf_and_rollback_restores_bytes(project, tmp_path):
    seen = {}

    def runner(sandbox, selected, full, timeout):
        seen.update(selected=selected, full=full, patched=(sandbox / "greet.py").read_bytes())
        return True, "1 passed"

    original = (project / "greet.py").read_bytes()
    result = self_patch.implement(CHANGE, model_fn=_model([{"old": 'return "hi " + name', "new": 'return "hi there " + name'}]),
                                  root=project, sandbox=tmp_path / "box", test_runner=runner)
    assert result.ok, result.error
    assert seen["selected"] == ["test_greet.py"] and not seen["full"]
    assert b'"hi there "' in seen["patched"] and b"\r\n" in seen["patched"]
    assert (project / "greet.py").read_bytes() == b'def greet(name):\r\n    return "hi there " + name\r\n'
    assert (tmp_path / "box" / "greet.py").read_bytes() == original  # sandbox mirrors live code again
    assert "+    return \"hi there \" + name" in result.diff
    assert "Restored greet.py" in self_patch.rollback("c1", project)
    assert (project / "greet.py").read_bytes() == original
    with pytest.raises(self_patch.PatchError, match="already rolled back"):
        self_patch.rollback("c1", project)


def test_red_tests_leave_the_live_file_alone(project, tmp_path):
    original = (project / "greet.py").read_bytes()
    result = self_patch.implement(CHANGE, model_fn=_model([{"old": 'return "hi " + name', "new": "return 42"}]),
                                  root=project, sandbox=tmp_path / "box", test_runner=lambda *a: (False, "1 failed"))
    assert not result.ok and "Tests failed" in result.error
    assert (project / "greet.py").read_bytes() == original


def test_rollback_refuses_when_the_file_changed_since(project, tmp_path):
    self_patch.implement(CHANGE, model_fn=_model([{"old": 'return "hi " + name', "new": 'return "yo " + name'}]),
                         root=project, sandbox=tmp_path / "box", test_runner=lambda *a: (True, "ok"))
    (project / "greet.py").write_text("# owner edited this\n")
    with pytest.raises(self_patch.PatchError, match="changed since"):
        self_patch.rollback("c1", project)


def test_model_can_decline(project, tmp_path):
    result = self_patch.implement(CHANGE, model_fn=_model([], summary="skip: already fine"), root=project,
                                  sandbox=tmp_path / "box", test_runner=lambda *a: (True, "ok"))
    assert not result.ok and result.error == "skip: already fine"


def test_real_pytest_runs_in_the_sandbox(project, tmp_path):
    box = self_patch.sync_sandbox(project, tmp_path / "box")
    passed, output = self_patch.run_tests(box, ["test_greet.py"], full=False, timeout=120)
    assert passed, output


def test_failures_that_exist_without_the_edit_are_not_blamed_on_it(project, tmp_path):
    """Owner, 2026-09-16: approved changes kept failing on tests that were already red."""
    calls = []

    def runner(sandbox, selected, full, timeout):
        edited = b"hello" in (sandbox / "greet.py").read_bytes()
        calls.append(edited)
        return False, "FAILED tests/test_other.py::test_old - boom\n1 failed, 3 passed"

    result = self_patch.implement(CHANGE, model_fn=_model([{"old": 'return "hi " + name', "new": 'return "hi hello " + name'}]),
                                  root=project, sandbox=tmp_path / "box", test_runner=runner)
    assert result.ok, result.error
    assert calls == [True, False], "the same tests ran again on the unedited sandbox"
    assert result.already_failing == ["tests/test_other.py::test_old"]
    assert b"hi hello" in (project / "greet.py").read_bytes()


def test_a_new_failure_still_blocks_and_names_it(project, tmp_path):
    def runner(sandbox, selected, full, timeout):
        if b"42" in (sandbox / "greet.py").read_bytes():
            return False, "FAILED tests/test_greet.py::test_greet - assert\nFAILED tests/test_other.py::test_old\n2 failed"
        return False, "FAILED tests/test_other.py::test_old\n1 failed"

    result = self_patch.implement(CHANGE, model_fn=_model([{"old": 'return "hi " + name', "new": "return 42"}]),
                                  root=project, sandbox=tmp_path / "box", test_runner=runner)
    assert not result.ok and "New failures: tests/test_greet.py::test_greet" in result.error


def test_prepare_leaves_the_live_file_until_commit(project, tmp_path):
    original = (project / "greet.py").read_bytes()
    prepared = self_patch.prepare(CHANGE, model_fn=_model([{"old": 'return "hi " + name', "new": 'return "hey " + name'}]),
                                  root=project, sandbox=tmp_path / "box", test_runner=lambda *a: (True, "ok"))
    assert prepared.ok and "+    return \"hey \" + name" in prepared.diff
    assert (project / "greet.py").read_bytes() == original
    assert self_patch.commit(prepared, project).ok
    assert b'"hey "' in (project / "greet.py").read_bytes()


def test_a_retry_carries_the_previous_error_to_the_model(project, tmp_path):
    prompts = []

    def model(prompt, **kw):
        prompts.append(prompt)
        return json.dumps({"summary": "skip: x", "edits": []})

    self_patch.prepare(CHANGE, model_fn=model, root=project, sandbox=tmp_path / "box",
                       feedback="Edit 1's search text appears 0 times")
    assert "appears 0 times" in prompts[0]
