"""Collab (Request K): what a tester can send, secret checks, talking to the site, and the site's own functions."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import beta_collab
from paths import PROJECT_DIR


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(beta_collab, "data_path", lambda rel: tmp_path / rel)
    monkeypatch.setattr(beta_collab, "_key", lambda: "NYX1-test.key")
    beta_collab._FEED_CACHE.update(at=0.0, data=None)
    return tmp_path


class Reply:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload

    def json(self):
        return self._payload


def test_site_address_defaults_and_must_be_https(sandbox):
    assert beta_collab.config()["site_url"] == beta_collab.DEFAULT_SITE
    assert beta_collab.save_config(site_url="https://beta.example.com/")["site_url"] == "https://beta.example.com"
    with pytest.raises(beta_collab.CollabError):
        beta_collab.save_config(site_url="http://evil.example.com")


def test_a_secret_inside_a_change_is_never_sent(sandbox, monkeypatch):
    posted = []
    monkeypatch.setattr(beta_collab, "_files_for", lambda cid: [{"path": "voice.py", "content": "KEY = 'nvapi-" + "a" * 30 + "'"}])
    monkeypatch.setattr("requests.post", lambda *a, **k: posted.append(1))
    with pytest.raises(beta_collab.CollabError, match="secret"):
        beta_collab.send(["improve:x"], "Leaky")
    assert posted == []
    assert beta_collab.scan_texts([{"path": "a.json", "content": "key NYX1-abc.def"}])


def test_send_posts_files_with_the_key_and_remembers_it(sandbox, monkeypatch):
    seen = {}

    def post(url, json=None, timeout=0):
        seen.update(url=url, body=json)
        return Reply(200, {"ok": True, "kind": "change", "number": 12, "url": "https://github.com/o/r/pull/12"})

    monkeypatch.setattr(beta_collab, "_files_for", lambda cid: [{"path": "community/tabs/budget.json", "content": "{}"}])
    monkeypatch.setattr("requests.post", post)
    result = beta_collab.send(["tab:t1"], "Budget tab", "A tab for money")
    assert result["number"] == 12 and seen["url"].endswith("/api/collab/submit")
    assert seen["body"]["key"] == "NYX1-test.key" and seen["body"]["kind"] == "tab"
    assert seen["body"]["files"] == [{"path": "community/tabs/budget.json", "content": "{}"}]
    assert beta_collab.config()["sent"][-1]["number"] == 12


def test_site_errors_come_back_in_words(sandbox, monkeypatch):
    monkeypatch.setattr("requests.post", lambda *a, **k: Reply(401, {"ok": False, "error": "This access key has expired."}))
    with pytest.raises(beta_collab.CollabError, match="expired"):
        beta_collab.send_feedback("Crash", "It crashed")


def test_candidates_never_include_personal_data(sandbox, monkeypatch):
    import self_patch

    monkeypatch.setattr(self_patch, "applied_changes", lambda: {"c1": {"file": "voice.py", "summary": "Calmer", "applied_at": 5}})
    items = beta_collab.candidates()
    assert any(i["id"] == "improve:c1" and i["files"] == ["voice.py"] for i in items)
    for item in items:
        for path in item["files"]:
            assert not any(word in path for word in ("chats.json", "memory.json", ".env", ".secrets", "uploads/"))


def test_a_tab_is_shared_without_its_edit_history_or_uploaded_picture(sandbox, monkeypatch):
    import dynamic_tabs

    class Spec:
        def as_dict(self):
            return {"id": "t1", "label": "My Budget", "blocks": [], "edits": [{"x": 1}],
                    "background": {"kind": "image", "image": "/api/uploads/abcd1234", "dim": 0.3}}

    monkeypatch.setattr(dynamic_tabs.TAB_STORE, "get", lambda tab_id: Spec())
    files = beta_collab._files_for("tab:t1")
    data = json.loads(files[0]["content"])
    assert files[0]["path"] == "community/tabs/my-budget.json" and "edits" not in data and "image" not in data["background"]


def test_routes_are_owner_only_except_the_feed(sandbox, monkeypatch):
    import server
    from fastapi.testclient import TestClient

    monkeypatch.setattr("requests.get", lambda *a, **k: Reply(200, {"items": [{"id": "pr-1"}], "counts": {"total": 1}}))
    local = TestClient(server.app, client=("127.0.0.1", 50111))
    assert local.get("/api/collab/status").json()["collab_url"].endswith("/collab/")
    assert local.get("/api/collab/feed").json()["counts"]["total"] == 1
    remote = TestClient(server.app, client=("203.0.113.7", 1))
    assert remote.get("/api/collab/candidates").status_code in (401, 403)
    for method, path in (("post", "/api/collab/send"), ("put", "/api/collab/config")):
        assert getattr(remote, method)(path, json={"title": "x", "ids": ["a"]}).status_code in (401, 403)


def test_vercel_env_carries_public_keys_only(monkeypatch, tmp_path):
    (tmp_path / "access_public_keys.json").write_text(json.dumps({"keys": [{"kid": "k1", "public_key": "ab" * 32}]}))
    monkeypatch.setattr(beta_collab, "PROJECT_DIR", tmp_path)
    assert json.loads(beta_collab.vercel_env()) == {"k1": "ab" * 32}


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_the_site_functions_pass_their_own_tests():
    result = subprocess.run(["node", "--test", "site/api/_lib/collab.test.mjs"], cwd=PROJECT_DIR, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-1000:]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_a_key_signed_by_nyx_verifies_on_the_site(tmp_path):
    """Nyx signs keys in pure-Python Ed25519; the site verifies with Node's crypto — they must agree."""
    import access_keys

    seed = bytes(range(32))
    public = access_keys.ed25519_public_key(seed)
    payload = json.dumps({"exp": 0, "iat": 1, "id": "k-1", "kid": "kid1", "name": "Ada", "role": "beta"},
                         separators=(",", ":"), sort_keys=True).encode()
    key = f"NYX1-{access_keys._b64u_encode(payload)}.{access_keys._b64u_encode(access_keys.ed25519_sign(payload, seed))}"
    script = tmp_path / "check.mjs"
    lib = (PROJECT_DIR / "site" / "api" / "_lib" / "collab.js").as_uri()
    script.write_text(f"import {{ verifyKey }} from '{lib}';\n"
                      f"console.log(JSON.stringify(verifyKey({json.dumps(key)}, {{ NYX_ACCESS_PUBLIC_KEYS: JSON.stringify({{ kid1: '{public.hex()}' }}) }})));\n")
    result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"id": "k-1", "name": "Ada", "role": "beta"}


class TextReply(Reply):
    """A page that is not JSON at all, like Vercel's plain-text 404."""

    def json(self):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


def test_a_site_without_the_feed_says_what_it_answered_not_that_it_was_unreachable(sandbox, monkeypatch):
    monkeypatch.setattr("requests.get", lambda *a, **k: TextReply(404, None))
    with pytest.raises(beta_collab.CollabError, match="answered 404"):
        beta_collab.feed()
    monkeypatch.setattr("requests.get", lambda *a, **k: Reply(200, ["not", "a", "feed"]))
    with pytest.raises(beta_collab.CollabError, match="answered 200"):
        beta_collab.feed(force=True)
