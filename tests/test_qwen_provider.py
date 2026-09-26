"""Qwen on Alibaba Cloud Model Studio as a built-in provider (Request R17)."""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import model_hub
from providers.qwen_provider import DEFAULT_BASE_URL, QwenProvider, chat_url_from


def _ok(text: str) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.headers = {}
    response.json.return_value = {"choices": [{"message": {"content": text}}]}
    return response


def test_base_urls_are_completed_and_full_endpoints_left_alone():
    assert chat_url_from("") == DEFAULT_BASE_URL + "/chat/completions"
    assert chat_url_from("https://dashscope-us.aliyuncs.com/compatible-mode/v1/") == \
        "https://dashscope-us.aliyuncs.com/compatible-mode/v1/chat/completions"
    full = "https://ws1.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1/chat/completions"
    assert chat_url_from(full) == full


def test_available_only_with_a_key():
    with patch("providers.compat.SETTINGS") as settings:
        settings.qwen_api_key = ""
        assert QwenProvider().is_available() is False
        settings.qwen_api_key = "sk-qwen-test"
        assert QwenProvider().is_available() is True


def test_chat_goes_to_the_region_saved_with_the_key():
    with patch("providers.compat.SETTINGS") as compat_settings, patch("providers.qwen_provider.SETTINGS") as settings, \
            patch("providers.compat.requests.post", return_value=_ok("Hello from Qwen")) as post:
        compat_settings.qwen_api_key = "sk-qwen-test"
        compat_settings.qwen_model = ""
        settings.qwen_base_url = "https://dashscope-us.aliyuncs.com/compatible-mode/v1"
        reply = QwenProvider().chat([{"role": "user", "content": "hi"}])
    assert reply == "Hello from Qwen"
    assert post.call_args[0][0] == "https://dashscope-us.aliyuncs.com/compatible-mode/v1/chat/completions"
    assert post.call_args[1]["json"]["model"] == "qwen-plus"
    assert post.call_args[1]["headers"]["Authorization"] == "Bearer sk-qwen-test"


def test_dashscope_key_name_is_read_too(monkeypatch):
    import config

    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-from-dashscope-name")
    monkeypatch.setenv("QWEN_BASE_URL", "https://dashscope-us.aliyuncs.com/compatible-mode/v1")
    fresh = config.load_settings()
    assert fresh.qwen_api_key == "sk-from-dashscope-name"
    assert fresh.qwen_base_url.startswith("https://dashscope-us")


def test_router_knows_qwen_and_keeps_it_out_of_free_only_fallback():
    from router import Router

    with patch("router.is_online", return_value=False), patch(
        "providers.ollama_provider.OllamaProvider.is_available", return_value=False
    ):
        router = Router(web_access=False)
    assert "qwen" in router.providers
    assert "qwen_available" in router.get_status()
    with patch("router.SETTINGS") as settings, patch("model_choice.allowed_paid", return_value=[]):
        settings.preferred_online_provider = "gemini"
        settings.free_only = True
        assert "qwen" not in router._online_order()


def test_key_pool_and_model_hub_name_the_same_key():
    import key_pool

    assert key_pool.key_name_for("qwen") == "QWEN_API_KEY"
    assert "qwen" in model_hub.known_providers()
    assert model_hub.default_model("qwen") == "qwen-plus"
    assert model_hub.default_model("qwen", "vision") == "qwen-vl-plus"


def test_model_hub_calls_qwen_at_the_saved_address(monkeypatch):
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen.update(url=url, model=json["model"])
        return _ok("OK")

    monkeypatch.setattr(model_hub, "api_key_for", lambda provider: "sk-qwen-test-123456")
    monkeypatch.setattr(model_hub, "_qwen_chat_url", lambda: "https://dashscope-us.aliyuncs.com/compatible-mode/v1/chat/completions")
    monkeypatch.setattr(model_hub.requests, "post", fake_post)
    reply = model_hub.complete("qwen", "", "Reply OK", max_tokens=5)
    assert reply.text == "OK" and reply.model == "qwen-plus"
    assert seen["url"].startswith("https://dashscope-us.aliyuncs.com/")


@pytest.fixture()
def client():
    import server

    return TestClient(server.app, client=("127.0.0.1", 50021))


def test_keys_tab_lists_qwen_with_its_region_field_and_no_secret(client, monkeypatch):
    monkeypatch.setattr(model_hub, "api_key_for", lambda provider: "sk-qwen-abcdefgh12345678" if provider == "qwen" else "")
    body = client.get("/api/keys").json()
    qwen = next(p for p in body["providers"] if p["provider"] == "qwen")
    assert qwen["configured"] and qwen["last4"] == "5678"
    assert [f["name"] for f in qwen["fields"]] == ["api_key", "base_url"]
    assert qwen["signup_url"].startswith("https://modelstudio.console.alibabacloud.com")
    assert "sk-qwen-abcdefgh12345678" not in json.dumps(body)


def test_saving_a_qwen_key_checks_the_address(client, monkeypatch):
    saved = {}
    monkeypatch.setattr("secret_store.set_keys", lambda name, values: saved.__setitem__(name, list(values)))
    assert client.post("/api/keys/qwen", json={}).status_code == 400
    assert client.post("/api/keys/qwen", json={"api_key": "sk-qwen-12345678", "base_url": "https://evil.example.com/v1"}).status_code == 400
    ok = client.post("/api/keys/qwen", json={"api_key": "sk-qwen-12345678",
                                            "base_url": "https://dashscope-us.aliyuncs.com/compatible-mode/v1"})
    assert ok.status_code == 200, ok.text
    assert saved["QWEN_API_KEY"] == ["sk-qwen-12345678"]
    assert saved["QWEN_BASE_URL"] == ["https://dashscope-us.aliyuncs.com/compatible-mode/v1"]
    assert "sk-qwen-12345678" not in ok.text


def test_switch_model_tool_accepts_qwen(monkeypatch):
    import tools
    from config import SETTINGS

    monkeypatch.setattr(SETTINGS, "preferred_online_provider", "gemini")
    monkeypatch.setattr(SETTINGS, "qwen_model", "qwen-plus")
    monkeypatch.setattr("model_choice.remember", lambda *a, **k: None)
    message = tools.builtin_switch_model(provider="qwen", model="qwen-max")
    assert "qwen" in message and SETTINGS.preferred_online_provider == "qwen" and SETTINGS.qwen_model == "qwen-max"
