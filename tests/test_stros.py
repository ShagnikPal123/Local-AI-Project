"""Stros: finds leaks without echoing them, ignores placeholders, and only probes this PC (stros.py)."""

import pytest

import stros

FAKE_KEY = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"          # built in pieces so this file is not itself a leak


def test_finds_keys_and_personal_details_and_masks_them():
    text = f'key = "{FAKE_KEY}"\nmail me at jane.doe@mail-test.org\nC:\\Users\\janedoe\\Desktop\\x'
    kinds = {f["kind"] for f in stros.scan_text("a.py", text)}
    assert {"api key", "email address", "local user path"} <= kinds
    assert all(FAKE_KEY not in str(f) for f in stros.scan_text("a.py", text)), "findings must not hold the secret"


def test_placeholders_and_docs_are_not_findings():
    text = 'OPENAI_API_KEY=your-key-here-xxxxxxxxxxxxxxxxxxxx\nsee user@example.com\nC:\\Users\\<you>\\x\nAPI_KEY = os.getenv("X")'
    assert stros.scan_text("README.md", text) == []


def test_diff_only_looks_at_added_lines():
    diff = (f"+++ b/new.py\n+token = '{FAKE_KEY}'\n"
            f"--- a/old.py\n-old = '{FAKE_KEY}'\n context {FAKE_KEY}\n")
    found = stros.scan_diff(diff)
    assert [f["file"] for f in found] == ["new.py"]


def test_tree_scan_skips_build_folders(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text(f"k='{FAKE_KEY}'", encoding="utf-8")
    (tmp_path / "bad.py").write_text(f"k='{FAKE_KEY}'", encoding="utf-8")
    assert [f["file"] for f in stros.scan_tree(tmp_path)] == ["bad.py"]


def test_route_probe_reports_open_routes_and_refuses_other_hosts():
    answers = {"/api/chats": 401, "/api/health": 200, "/api/secret": 200}
    out = stros.probe_routes("http://127.0.0.1:8000", list(answers), allowed_open=["/api/health"],
                             get=lambda url: answers["/" + url.split("/", 3)[3]])
    assert [r["route"] for r in out["exposed"]] == ["/api/secret"] and out["checked"] == 3
    with pytest.raises(ValueError):
        stros.probe_routes("https://example.org", ["/x"], get=lambda u: 200)
