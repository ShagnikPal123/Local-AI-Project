"""The leak sweep catches keys and personal details in added lines, and leaves ordinary code alone.

The fake secrets are glued together at run time so this file never holds one whole: otherwise the
sweep would (rightly) stop the push that adds this very test.
"""

from __future__ import annotations

import leak_sweep


def _diff(path: str, *lines: str) -> str:
    body = "\n".join("+" + line for line in lines)
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n{body}\n"


def test_a_provider_key_is_caught_and_masked():
    key = "sk-" + "ant-" + "a1B2" * 8
    found = leak_sweep.scan_diff(_diff("cfg.py", f'KEY = "{key}"'))
    assert any(f.kind == "Anthropic key" for f in found)
    assert all(key not in str(f) for f in found)


def test_a_personal_email_phone_and_user_path_are_caught():
    email = "someone" + "@" + "gmail.com"
    phone = "(415) " + "555-" + "0134"
    path = "C:" + "\\Users\\" + "alex" + "\\Desktop"
    kinds = {f.kind for f in leak_sweep.scan_diff(_diff("notes.md", email, phone, path))}
    assert {"Email address", "Phone number", "Local path with a user name"} <= kinds


def test_robot_addresses_and_placeholders_pass():
    found = leak_sweep.scan_diff(_diff(
        "a.py", "Co-Authored-By: Claude <noreply" + "@anthropic.com>", 'api_key = "your_key_here_please"',
        "token = os.environ.get('ICHOS_TOKEN', '')", "x = 1234567"))
    assert found == []


def test_a_secret_file_and_a_picture_are_flagged():
    diff = _diff(".env", "A=1") + _diff("shots/screen.png", "binary")
    kinds = [f.kind for f in leak_sweep.scan_diff(diff)]
    assert "Secret file" in kinds and "New picture" in kinds


def test_only_added_lines_are_scanned():
    email = "someone" + "@" + "gmail.com"
    diff = f"--- a/x.md\n+++ b/x.md\n@@ -1,1 +1,1 @@\n-{email}\n+nothing here\n"
    assert leak_sweep.scan_diff(diff) == []
