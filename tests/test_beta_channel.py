"""Beta updates: only published releases with a matching checksum install, personal data is never touched (Request G2)."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

import beta_channel
import file_guard


class _Response:
    def __init__(self, payload=None, content=b"", status_code=200):
        self._payload, self.content, self.status_code = payload, content, status_code

    def json(self):
        return self._payload


class _GitHub:
    def __init__(self, archive: bytes, sha: str, tag: str = "beta-2026.09.20.1"):
        self.archive, self.sha, self.tag = archive, sha, tag

    def get(self, url, timeout=0, headers=None):
        if url.endswith("per_page=20"):
            return _Response([
                {"tag_name": "v2026.01.01", "prerelease": False, "draft": False, "assets": []},
                {"tag_name": self.tag, "prerelease": True, "draft": False, "body": "Notes tab and trading.",
                 "assets": [{"name": "NyxIchos-beta.zip", "browser_download_url": "zip"},
                            {"name": "release.json", "browser_download_url": "manifest"}]},
            ])
        if url == "manifest":
            return _Response({"sha256": self.sha})
        return _Response(content=self.archive)


def _zip(files: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, text in files.items():
            bundle.writestr(f"NyxIchos/{name}", text)
    return buffer.getvalue()


@pytest.fixture()
def install(tmp_path, monkeypatch):
    project = tmp_path / "install"
    project.mkdir()
    (project / "VERSION").write_text("2026.09.15.0", encoding="utf-8")
    (project / "server.py").write_text("old server", encoding="utf-8")
    (project / "chats.json").write_text('{"mine": true}', encoding="utf-8")
    data = tmp_path / "data"
    monkeypatch.setattr(beta_channel, "data_path", lambda name: data / name)
    monkeypatch.setattr(beta_channel, "PROJECT", project)
    monkeypatch.setattr(beta_channel, "is_git_checkout", lambda project=None: False)
    return project


def test_a_newer_beta_release_is_found_downloaded_verified_and_applied_without_touching_personal_data(install):
    archive = _zip({"server.py": "new server", "chats.json": '{"overwritten": true}', "notes_store.py": "new file"})
    github = _GitHub(archive, hashlib.sha256(archive).hexdigest())

    status = beta_channel.check(github)
    assert status["available"] and status["latest"]["version"] == "2026.09.20.1"
    beta_channel.download(github)
    result = beta_channel.apply_staged(install)

    assert result["ok"] and (install / "server.py").read_text(encoding="utf-8") == "new server"
    assert (install / "notes_store.py").exists()
    assert json.loads((install / "chats.json").read_text(encoding="utf-8")) == {"mine": True}
    assert (install / "VERSION").read_text(encoding="utf-8") == "2026.09.20.1"

    beta_channel.rollback(install)
    assert (install / "server.py").read_text(encoding="utf-8") == "old server"


def test_a_download_that_does_not_match_its_checksum_is_refused(install):
    archive = _zip({"server.py": "tampered"})
    with pytest.raises(beta_channel.UpdateError, match="checksum"):
        beta_channel.download(_GitHub(archive, "0" * 64))
    assert beta_channel.staged() is None
    assert (install / "server.py").read_text(encoding="utf-8") == "old server"


def test_zip_entries_cannot_escape_the_install_folder(install, tmp_path, monkeypatch):
    archive = _zip({"../outside.txt": "nope", "ok.py": "fine"})
    github = _GitHub(archive, hashlib.sha256(archive).hexdigest())

    # The download refuses it outright now (file_guard reads the entry names).
    with pytest.raises(beta_channel.UpdateError, match="outside the folder"):
        beta_channel.download(github)

    # And if such an archive ever reached the disk anyway, unpacking still
    # keeps every file inside the install folder.
    monkeypatch.setattr("file_guard.check_file", lambda *a, **k: file_guard.Verdict(name="update.zip"))
    beta_channel.download(github)
    beta_channel.apply_staged(install)
    assert not (tmp_path / "outside.txt").exists() and (install / "ok.py").exists()


def test_settings_status_follows_a_release_from_download_to_roll_back(install):
    """Settings → Updates reads this without a network call (Request G2)."""
    archive = _zip({"server.py": "new server"})
    github = _GitHub(archive, hashlib.sha256(archive).hexdigest())

    before = beta_channel.status()
    assert before["install_kind"] == "zip" and before["staged"] is None and not before["can_roll_back"]
    beta_channel.set_channel("stable")
    assert beta_channel.status()["channel"] == "stable"
    beta_channel.set_channel("beta")

    beta_channel.download(github)
    assert beta_channel.status()["staged"]["version"] == "2026.09.20.1"

    beta_channel.apply_staged(install)
    after = beta_channel.status()
    assert after["staged"] is None and after["last_apply"]["ok"] and after["can_roll_back"]


def test_the_status_route_is_owner_only_and_offline(monkeypatch):
    from fastapi.testclient import TestClient
    import server

    monkeypatch.setattr(beta_channel, "latest_release", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    response = TestClient(server.app, client=("127.0.0.1", 50005)).get("/api/updates/status")
    assert response.status_code == 200, response.text
    assert {"channel", "local_version", "install_kind", "staged", "last_apply", "can_roll_back"} <= set(response.json())
