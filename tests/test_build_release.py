"""The download's secret scan: public digests pass, real-looking keys still stop the build."""

from __future__ import annotations

import build_release

EICAR = "275a021bbfb6489e54d471899f7db9d1663fc695ec2fe2a2c4538aabf651fd0f"


def _scan(tmp_path, monkeypatch, name: str, text: str):
    monkeypatch.setattr(build_release, "PROJECT", tmp_path)
    (tmp_path / name).write_text(text, encoding="utf-8")
    return build_release.scan_for_secrets([name])


def test_the_eicar_digest_is_not_a_credential(tmp_path, monkeypatch):
    assert _scan(tmp_path, monkeypatch, "guard.py", f'_EICAR_SHA256 = "{EICAR}"\n') == []


def test_a_real_looking_hex_token_next_to_it_still_stops_the_build(tmp_path, monkeypatch):
    token = "9f" * 32
    findings = _scan(tmp_path, monkeypatch, "notes.md", f"{EICAR}\nobsidian key {token}\n")
    assert len(findings) == 1 and findings[0].endswith(token[-4:])


def test_owner_data_never_ships():
    for name in ("chats.json", "memory.json", ".env.local", ".secrets.json", "logs/engine.log", "site/index.html",
                 "AI_HANDOFF/01_GOALS.md"):
        assert build_release._excluded(name), name
    assert not build_release._excluded("server.py")
