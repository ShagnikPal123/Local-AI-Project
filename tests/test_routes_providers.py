"""Tests for routes_providers.py — the UI's way to hand the app an API key.

Mirrors the isolation of tests/test_routes_access.py: a loopback TestClient
exercises the unclaimed-install owner path, a claimed store exercises the
session gate, and the real secret store is replaced with an in-memory dict so
no test ever touches ``.secrets.json``, the OS keyring, or the network.

The NVIDIA NIM case is covered explicitly: it is the free provider the owner
asked to have reachable from the app (keys from https://build.nvidia.com/models),
and its whole chain — preset, key add, live reload, availability — has to work
end to end.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import config
import provider_specs
import providers.custom
import secret_store
import server
import server_auth
from auth import AuthStore

OWNER = "shagnikpal@gmail.com"
PASSWORD = "a-long-enough-passphrase"

_PROVIDER_ENV_KEYS = (
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "PERPLEXITY_API_KEY", "GEMINI_API_KEY",
    "KIMI_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY", "NVIDIA_API_KEY",
)


@pytest.fixture(autouse=True)
def isolated_secret_store(monkeypatch):
    """In-memory stand-in for the OS keyring / .secrets.json.

    Three layers of isolation, because keys reach providers three ways:

    * ``os.environ`` — config.py loaded the developer's real .env.local at
      import, so the provider env vars are blanked (an early run without this
      made a real Gemini API call from a "missing key" test).
    * ``SETTINGS`` fields — built from that same environment at import; saved
      and zeroed here, restored after the test.
    * ``secret_store`` — replaced with a dict, and ``config``'s imported
      ``get_keys`` binding repointed at it so ``reload_keys`` sees the fake.
    """
    fake: dict[str, list[str]] = {}

    for name in _PROVIDER_ENV_KEYS:
        monkeypatch.setenv(name, "")

    monkeypatch.setattr(secret_store, "get_keys", lambda name: list(fake.get(name, [])))
    monkeypatch.setattr(config, "get_keys", lambda name: list(fake.get(name, [])))

    def fake_set_keys(name, keys):
        values = [k for k in keys if k and k.strip()]
        fake[name] = values
        return values

    monkeypatch.setattr(secret_store, "set_keys", fake_set_keys)

    def fake_add_key(name, key):
        return fake_set_keys(name, [*fake.get(name, []), key])

    monkeypatch.setattr(secret_store, "add_key", fake_add_key)

    saved = {
        field.name: getattr(config.SETTINGS, field.name)
        for field in config.fields(config.Settings)
        if field.name.endswith("_api_key")
    }
    for value in saved.values():
        setattr(config.SETTINGS, value.__class__.__name__ and "", "")  # pragma: no cover
    for name in saved:
        setattr(config.SETTINGS, name, "")

    yield fake

    for name, value in saved.items():
        setattr(config.SETTINGS, name, value)


@pytest.fixture(autouse=True)
def no_ollama_probe(monkeypatch):
    """Listing Ollama probes the loopback port; these tests decide its answer instead."""
    import routes_providers

    monkeypatch.setattr(routes_providers, "_ollama_running", lambda: False)


@pytest.fixture
def store(tmp_path, monkeypatch):
    fresh = AuthStore(path=tmp_path / "auth.json")
    monkeypatch.setattr(server_auth, "AUTH_STORE", fresh)
    monkeypatch.setattr(server, "AUTH_STORE", fresh)
    return fresh


@pytest.fixture
def loopback_client(store):
    """Reports a loopback host — the unclaimed install's owner path."""
    return TestClient(server.app, client=("127.0.0.1", 51234))


def _claim(store) -> None:
    store.bootstrap_owner(OWNER)
    store.set_password(OWNER, PASSWORD)


def _login(client, email=OWNER, password=PASSWORD) -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- listing -------------------------------------------------------------------


def test_list_providers_masks_keys_and_names_nvidia(loopback_client):
    response = loopback_client.get("/api/providers")
    assert response.status_code == 200
    body = response.json()

    names = {p["name"] for p in body["providers"]}
    assert {"gemini", "groq", "nvidia", "claude", "openai"} <= names
    for entry in body["providers"]:
        assert set(entry) >= {"name", "configured", "last4"}
        assert "api_key" not in entry and "key" not in entry


def test_nvidia_offers_its_signup_link(loopback_client):
    body = loopback_client.get("/api/providers").json()
    nvidia = next(p for p in body["providers"] if p["name"] == "nvidia")
    assert nvidia["signup_url"] == "https://build.nvidia.com/models"
    assert nvidia["free"] is True


def test_list_includes_free_presets_not_already_builtin(loopback_client):
    body = loopback_client.get("/api/providers").json()
    preset_names = {p["name"] for p in body["presets"]}
    builtin = {"ollama", "gemini", "groq", "nvidia", "claude", "openai", "kimi", "deepseek", "perplexity"}
    assert preset_names and not (preset_names & builtin)


# --- gating ----------------------------------------------------------------------


def test_add_key_requires_owner_once_claimed(store):
    _claim(store)
    client = TestClient(server.app)
    response = client.post("/api/providers/nvidia/key", json={"api_key": "nvapi-" + "x" * 20})
    assert response.status_code == 401


def test_add_key_works_on_an_unclaimed_local_install(loopback_client):
    response = loopback_client.post("/api/providers/nvidia/key", json={"api_key": "nvapi-" + "x" * 20})
    assert response.status_code == 200
    body = response.json()
    assert body["stored"] is True
    assert body["applied_live"] is True


def test_remove_and_test_are_owner_actions_too(store):
    _claim(store)
    client = TestClient(server.app)
    assert client.post("/api/providers/gemini/test").status_code == 401
    assert client.delete("/api/providers/gemini/key").status_code == 401


# --- key lifecycle -----------------------------------------------------------------


def test_add_key_stores_and_masks(loopback_client, isolated_secret_store):
    key = "nvapi-" + "y" * 20
    response = loopback_client.post("/api/providers/nvidia/key", json={"api_key": key})
    assert response.status_code == 200
    assert response.json()["last4"] == key[-4:]
    assert key not in response.text
    assert isolated_secret_store["NVIDIA_API_KEY"] == [key]


def test_added_key_is_visible_in_the_list_and_live(loopback_client):
    key = "nvapi-" + "z" * 20
    assert loopback_client.post("/api/providers/nvidia/key", json={"api_key": key}).status_code == 200

    body = loopback_client.get("/api/providers").json()
    nvidia = next(p for p in body["providers"] if p["name"] == "nvidia")
    assert nvidia["configured"] is True
    assert nvidia["last4"] == key[-4:]


def test_add_key_rejects_unknown_provider(loopback_client):
    response = loopback_client.post("/api/providers/not-a-provider/key", json={"api_key": "x" * 20})
    assert response.status_code == 404


def test_add_key_rejects_an_empty_or_tiny_key(loopback_client):
    assert loopback_client.post("/api/providers/nvidia/key", json={"api_key": ""}).status_code == 400
    assert loopback_client.post("/api/providers/nvidia/key", json={"api_key": "abc"}).status_code == 400


def test_ollama_needs_no_key(loopback_client):
    response = loopback_client.post("/api/providers/ollama/key", json={"api_key": "x" * 20})
    assert response.status_code == 400
    assert "locally" in response.json()["detail"]


def test_ollama_counts_as_configured_exactly_when_it_is_running(loopback_client, monkeypatch):
    """No key to hold, so a running Ollama must not be listed as "(no key)" / "(not running)"."""
    import routes_providers

    def ollama():
        body = loopback_client.get("/api/providers").json()
        return next(p for p in body["providers"] if p["name"] == "ollama")

    monkeypatch.setattr(routes_providers, "_ollama_running", lambda: True)
    assert ollama()["configured"] is True
    monkeypatch.setattr(routes_providers, "_ollama_running", lambda: False)
    assert ollama()["configured"] is False


def test_remove_key_forgets_it(loopback_client, isolated_secret_store):
    key = "nvapi-" + "w" * 20
    loopback_client.post("/api/providers/nvidia/key", json={"api_key": key})
    response = loopback_client.delete("/api/providers/nvidia/key")
    assert response.status_code == 200
    assert isolated_secret_store["NVIDIA_API_KEY"] == []

    body = loopback_client.get("/api/providers").json()
    nvidia = next(p for p in body["providers"] if p["name"] == "nvidia")
    assert nvidia["configured"] is False


def test_added_key_reaches_the_live_settings_object(loopback_client):
    """The whole point of reload_keys(): usable on the very next turn."""
    key = "nvapi-" + "q" * 20
    loopback_client.post("/api/providers/nvidia/key", json={"api_key": key})
    assert config.SETTINGS.nvidia_api_key == key


def test_test_endpoint_reports_a_missing_key_honestly(loopback_client):
    response = loopback_client.post("/api/providers/gemini/test")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "No API key" in body["detail"]


def test_test_endpoint_never_returns_the_key(loopback_client, monkeypatch):
    from providers.base import ProviderError

    key = "nvapi-secret-value-123456"
    loopback_client.post("/api/providers/nvidia/key", json={"api_key": key})

    def boom(provider, key_arg, timeout_seconds):
        raise ProviderError(f"HTTP 401: bad key {key_arg}")

    # probe_provider lives in providers.custom; the route imports it lazily
    # from there, so patching the module attribute is what the route sees.
    monkeypatch.setattr(providers.custom, "_probe_compatible", boom)

    response = loopback_client.post("/api/providers/nvidia/test")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert key not in response.text


# --- Request H8: several keys per provider, alerts, models you add yourself -------------------


def test_a_second_key_can_be_added_listed_masked_and_removed_alone(loopback_client, isolated_secret_store):
    first = loopback_client.post("/api/keys/groq/pool", json={"api_key": "gsk-first-000011112222"})
    assert first.status_code == 200, first.text
    second = loopback_client.post("/api/keys/groq/pool", json={"api_key": "gsk-second-00003333aaaa"})
    body = second.json()
    assert [k["last4"] for k in body["keys"]] == ["2222", "aaaa"]
    assert "gsk-" not in second.text
    assert loopback_client.post("/api/keys/groq/pool", json={"api_key": "gsk-second-00003333aaaa"}).status_code == 409

    fingerprint = body["keys"][0]["fingerprint"]
    left = loopback_client.delete(f"/api/keys/groq/pool/{fingerprint}").json()
    assert [k["last4"] for k in left["keys"]] == ["aaaa"]
    assert isolated_secret_store["GROQ_API_KEY"] == ["gsk-second-00003333aaaa"]


def test_remote_callers_cannot_touch_keys(store):
    remote = TestClient(server.app, client=("203.0.113.9", 4000))
    _claim(store)
    assert remote.get("/api/keys/alerts").status_code in (401, 403)
    assert remote.post("/api/keys/groq/pool", json={"api_key": "gsk-remote-000011112222"}).status_code in (401, 403)
    assert remote.post("/api/custom-models", json={"name": "x", "company": "openai", "model": "m"}).status_code in (401, 403)


def test_a_model_added_by_name_company_and_key_joins_the_providers(loopback_client, isolated_secret_store):
    added = loopback_client.post("/api/custom-models", json={
        "name": "My Mistral", "company": "mistral", "model": "mistral-small-latest",
        "api_key": "mst-key-000011112222", "use": "writing", "use_note": "long emails"})
    assert added.status_code == 200, added.text
    spec = added.json()["model"]
    assert spec["name"] == "my-mistral" and spec["chat_url"].startswith("https://api.mistral.ai/")
    assert spec["api_key_name"] == "CUSTOM_MY_MISTRAL_API_KEY" and "use: writing" in spec["notes"]
    assert isolated_secret_store["CUSTOM_MY_MISTRAL_API_KEY"] == ["mst-key-000011112222"]
    assert "mst-key" not in added.text

    listing = loopback_client.get("/api/custom-models").json()
    assert [m["name"] for m in listing["models"]] == ["my-mistral"]
    assert any(c["id"] == "openrouter" for c in listing["companies"])
    assert loopback_client.post("/api/custom-models", json={"name": "x", "company": "other", "model": "m"}).status_code == 400

    assert loopback_client.delete("/api/custom-models/my-mistral").status_code == 200
    assert isolated_secret_store["CUSTOM_MY_MISTRAL_API_KEY"] == []


# --- Request J5: the "Chat completions URL" box works ------------------------------------------------


def test_chat_url_accepts_base_addresses_and_local_servers(loopback_client, isolated_secret_store):
    import routes_key_pool

    assert routes_key_pool.normalize_chat_url("https://api.x.ai/v1/") == "https://api.x.ai/v1/chat/completions"
    assert routes_key_pool.normalize_chat_url("localhost:1234") == "http://localhost:1234/v1/chat/completions"
    assert routes_key_pool.normalize_chat_url("https://h.example/v1/chat/completions") == "https://h.example/v1/chat/completions"

    local = loopback_client.post("/api/custom-models", json={
        "name": "LM Studio", "company": "other", "model": "qwen2.5-7b-instruct", "chat_url": "http://localhost:1234/v1"})
    assert local.status_code == 200, local.text
    spec = local.json()["model"]
    assert spec["chat_url"] == "http://localhost:1234/v1/chat/completions" and spec["allow_local"] is True
    assert spec["api_key_name"] == "", "a local server needs no key"

    override = loopback_client.post("/api/custom-models", json={
        "name": "Groq EU", "company": "groq", "model": "llama-3.3-70b-versatile", "api_key": "gsk-eu-000011112222",
        "chat_url": "https://eu.api.groq.example/openai/v1"})
    assert override.status_code == 200, override.text
    assert override.json()["model"]["chat_url"] == "https://eu.api.groq.example/openai/v1/chat/completions"


def test_check_lists_models_and_sends_one_token(loopback_client, monkeypatch):
    import requests

    calls = []

    class Reply:
        def __init__(self, status, payload):
            self.status_code, self._payload, self.ok, self.text = status, payload, status == 200, str(payload)

        def json(self):
            return self._payload

    monkeypatch.setattr(requests, "get", lambda url, **kw: calls.append(("GET", url)) or Reply(200, {"data": [{"id": "m-1"}, {"id": "m-2"}]}))
    monkeypatch.setattr(requests, "post", lambda url, **kw: calls.append(("POST", url, kw["json"]["max_tokens"])) or Reply(200, {"choices": []}))
    body = loopback_client.post("/api/custom-models/check", json={"company": "other", "chat_url": "https://api.example.com/v1",
                                                                  "api_key": "sk-test-000011112222"}).json()
    assert body["ok"] and body["models"] == ["m-1", "m-2"] and body["model"] == "m-1"
    assert calls == [("GET", "https://api.example.com/v1/models"), ("POST", "https://api.example.com/v1/chat/completions", 1)]
    assert "sk-test" not in str(body)
    bad = loopback_client.post("/api/custom-models/check", json={"company": "other", "chat_url": "http://api.example.com/v1"}).json()
    assert not bad["ok"] and "https" in bad["detail"]


def test_check_says_when_nothing_answers(loopback_client, monkeypatch):
    import requests

    def refuse(url, **kw):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(requests, "get", refuse)
    body = loopback_client.post("/api/custom-models/check", json={"company": "other", "chat_url": "localhost:1234"}).json()
    assert not body["ok"] and body["local"] and "Nothing answered at http://localhost:1234/v1" in body["detail"]
