"""Model roles: the owner names a model for a job, Nyx uses exactly it and says so."""

from __future__ import annotations

import base64
import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient

import model_hub
import model_roles
from model_hub import ModelCallError, ModelReply, GeneratedImage
from model_roles import ModelRoleStore, RoleError
from tool_context import ToolContext, use_context


@pytest.fixture()
def store(tmp_path, monkeypatch):
    fresh = ModelRoleStore(tmp_path / "model_roles.json")
    monkeypatch.setattr(model_roles, "MODEL_ROLES", fresh)
    monkeypatch.setattr(model_hub, "is_configured", lambda provider: provider in ("gemini", "nvidia", "pollinations"))
    return fresh


# --- AWS signing -------------------------------------------------------------------


def test_sigv4_signing_key_matches_the_aws_documented_example():
    key = model_hub.sigv4_signing_key("wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", "20120215", "us-east-1", "iam")
    assert key.hex() == "f4780e2d9f65fa895f9c67b32ce1baf0b0d8a43505a000a1a9e090d414db404d"


def test_sigv4_headers_are_deterministic_and_cover_the_body():
    moment = dt.datetime(2026, 9, 14, 12, 0, 0, tzinfo=dt.timezone.utc)
    url = "https://bedrock-runtime.us-east-1.amazonaws.com/model/amazon.nova-lite-v1%3A0/converse"
    kwargs = dict(region="us-east-1", service="bedrock", access_key="AKIAEXAMPLE", secret_key="secret", now=moment)
    first = model_hub.sigv4_headers("POST", url, b'{"a":1}', **kwargs)
    again = model_hub.sigv4_headers("POST", url, b'{"a":1}', **kwargs)
    other = model_hub.sigv4_headers("POST", url, b'{"a":2}', **kwargs)
    assert first == again
    assert first["Authorization"] != other["Authorization"]
    assert first["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIAEXAMPLE/20260914/us-east-1/bedrock/aws4_request")
    assert first["X-Amz-Date"] == "20260914T120000Z"
    assert "secret" not in json.dumps(first)


# --- one model, exactly ----------------------------------------------------------------


class _Response:
    def __init__(self, status=200, payload=None, content=b"", headers=None, text=""):
        self.status_code = status
        self._payload = payload
        self.content = content
        self.headers = headers or {}
        self.text = text or json.dumps(payload or {})

    def json(self):
        return self._payload


def test_openai_compatible_vision_call_sends_image_parts_and_names_the_model(monkeypatch):
    sent = {}
    monkeypatch.setattr(model_hub, "api_key_for", lambda provider: "nvapi-test-key-123456")

    def fake_post(url, headers=None, json=None, timeout=None, **_kw):
        sent.update(url=url, headers=headers, json=json)
        return _Response(payload={"choices": [{"message": {"content": "A red square and a blue circle."}}]})

    monkeypatch.setattr(model_hub.requests, "post", fake_post)
    reply = model_hub.complete("nvidia", "meta/llama-3.2-11b-vision-instruct", "What is this?",
                               images=[(b"\x89PNG fake", "image/png")])
    assert reply.text == "A red square and a blue circle."
    assert reply.model == "meta/llama-3.2-11b-vision-instruct"
    assert sent["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    parts = sent["json"]["messages"][-1]["content"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_errors_never_carry_the_key(monkeypatch):
    key = "nvapi-super-secret-value"
    monkeypatch.setattr(model_hub, "api_key_for", lambda provider: key)
    monkeypatch.setattr(model_hub.requests, "post",
                        lambda *a, **k: _Response(status=401, text=f"bad key {key}"))
    with pytest.raises(ModelCallError) as error:
        model_hub.complete("nvidia", "x", "hi")
    assert key not in str(error.value)


def test_nvidia_image_generation_polls_a_queued_job(monkeypatch):
    monkeypatch.setattr(model_hub, "api_key_for", lambda provider: "nvapi-test-key-123456")
    image = base64.b64encode(b"\x89PNG\r\n\x1a\nrest").decode()
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None, **_kw):
        calls.append(("post", url, json))
        return _Response(status=202, headers={"NVCF-REQID": "req-1"})

    def fake_get(url, headers=None, timeout=None, **_kw):
        calls.append(("get", url, None))
        return _Response(payload={"artifacts": [{"base64": image, "finishReason": "SUCCESS"}]})

    monkeypatch.setattr(model_hub.requests, "post", fake_post)
    monkeypatch.setattr(model_hub.requests, "get", fake_get)
    result = model_hub.generate_image("nvidia", "black-forest-labs/flux.1-schnell", "a crystal", "512x512")
    assert result.mime == "image/png"
    assert calls[0][2]["width"] == 768  # snapped into FLUX's allowed range
    assert calls[1][1].endswith("/status/req-1")


# --- roles --------------------------------------------------------------------------------


def test_assigning_a_role_persists_and_is_announced(store, tmp_path):
    entry = store.assign_role("image check", "nvidia", "meta/llama-3.2-11b-vision-instruct", announced_label="NVIDIA Vision")
    assert entry["provider"] == "nvidia" and entry["label"] == "NVIDIA Vision"
    reloaded = ModelRoleStore(tmp_path / "model_roles.json")
    assert reloaded.get_role("image_check")["model"] == "meta/llama-3.2-11b-vision-instruct"
    assert "NVIDIA Vision" in reloaded.summary_for_prompt()


def test_a_changed_model_does_not_keep_the_default_label(store, tmp_path):
    (tmp_path / "model_roles.json").write_text(json.dumps({"reading_text": {"provider": "aws", "model": "amazon.nova-lite-v1:0"}}))
    loaded = ModelRoleStore(tmp_path / "model_roles.json")
    assert loaded.get_role("reading_text")["label"].startswith("AWS")


def test_unknown_providers_and_bad_names_are_refused(store):
    with pytest.raises(RoleError):
        store.assign_role("image_check", "not-a-provider")
    with pytest.raises(RoleError):
        store.assign_role("!!", "gemini")


def test_reset_restores_builtins_and_removes_custom_roles(store):
    store.assign_role("image_check", "nvidia")
    store.assign_role("translation", "gemini", job="text")
    assert store.reset_role("image_check")["provider"] == "gemini"
    assert store.reset_role("translation") is None
    assert store.get_role("translation") == {}


def test_run_uses_the_assigned_model_and_emits_the_role(store, monkeypatch):
    store.assign_role("image_check", "nvidia", "meta/llama-3.2-11b-vision-instruct", announced_label="NVIDIA Vision")
    asked = []

    def fake_complete(provider, model, prompt, **kw):
        asked.append((provider, model))
        return ModelReply(text="a cat", provider=provider, model=model, ms=12)

    monkeypatch.setattr(model_hub, "complete", fake_complete)
    events = []
    with use_context(ToolContext(sink=events.append)):
        run = store.run("image_check", "what is it?", images=[(b"x", "image/png")])
    assert asked == [("nvidia", "meta/llama-3.2-11b-vision-instruct")]
    assert run.announcement().startswith("[NVIDIA Vision")
    assert any(e["type"] == "model.role" and e["provider"] == "nvidia" for e in events)


def test_a_failing_model_falls_back_openly(store, monkeypatch):
    store.assign_role("image_check", "nvidia", "vision-x")

    def fake_complete(provider, model, prompt, **kw):
        if provider == "nvidia":
            raise ModelCallError("nvidia (vision-x) answered 503: busy")
        return ModelReply(text="a dog", provider=provider, model=model, ms=5)

    monkeypatch.setattr(model_hub, "complete", fake_complete)
    run = store.run("image_check", "?", images=[(b"x", "image/png")])
    assert run.provider == "gemini" and run.fell_back
    assert "unavailable" in run.announcement() and "503" in run.announcement()


def test_a_retired_model_moves_to_the_providers_current_default(store, monkeypatch):
    store.assign_role("code_generation", "nvidia", "some/retired-model")
    calls = []

    def fake_complete(provider, model, prompt, **kw):
        calls.append((provider, model))
        if model == "some/retired-model":
            raise ModelCallError("nvidia (some/retired-model) answered 410: has reached its end of life")
        return ModelReply(text="ok", provider=provider, model=model, ms=5)

    monkeypatch.setattr(model_hub, "complete", fake_complete)
    run = store.run("code_generation", "hi")
    assert (run.provider, run.model) == ("nvidia", model_hub.default_model("nvidia", "text"))
    assert run.fell_back and "410" in run.note
    calls.clear()
    store.run("code_generation", "again")
    assert calls[0] == ("nvidia", model_hub.default_model("nvidia", "text"))  # the retired one is skipped for a day
    assert model_roles._OUTAGE_COOLDOWN[("nvidia", "some/retired-model")] - __import__("time").time() > 3600


def test_no_fallback_means_the_error_is_about_that_model(store, monkeypatch):
    monkeypatch.setattr(model_hub, "complete", lambda *a, **k: (_ for _ in ()).throw(ModelCallError("no key")))
    with pytest.raises(ModelCallError) as error:
        store.run("reading_text", "hi", allow_fallback=False)
    assert "no key" in str(error.value)


def test_image_generation_falls_back_to_the_free_provider(store, monkeypatch):
    def fake_generate(provider, model, prompt, size="1024x1024", timeout=180):
        if provider != "pollinations":
            raise ModelCallError(f"{provider} is down")
        return GeneratedImage(b"\xff\xd8\xffjpeg", "image/jpeg", provider, model, 40)

    monkeypatch.setattr(model_hub, "generate_image", fake_generate)
    image, run = store.generate("a crystal")
    assert run.provider == "pollinations" and run.fell_back
    assert image.mime == "image/jpeg"


# --- tools -----------------------------------------------------------------------------------


def test_analyze_image_names_the_model_in_its_result(store, monkeypatch, tmp_path):
    from PIL import Image

    import media_tools

    path = tmp_path / "shot.png"
    Image.new("RGB", (20, 20), (200, 0, 0)).save(path)
    monkeypatch.setattr(model_hub, "complete",
                        lambda provider, model, prompt, **kw: ModelReply("a red square", provider, model, 9))
    store.assign_role("image_check", "nvidia", "meta/llama-3.2-11b-vision-instruct", announced_label="NVIDIA Vision")
    result = media_tools.tool_analyze_image(str(path))
    assert result.startswith("[NVIDIA Vision")
    assert "a red square" in result


def test_read_document_uses_the_reading_model(store, monkeypatch, tmp_path):
    import media_tools

    doc = tmp_path / "notes.txt"
    doc.write_text("Quarterly revenue was 42 million.", encoding="utf-8")
    prompts = []

    def fake_complete(provider, model, prompt, **kw):
        prompts.append(prompt)
        return ModelReply("Revenue: 42 million.", provider, model, 7)

    monkeypatch.setattr(model_hub, "complete", fake_complete)
    store.assign_role("reading_text", "gemini", "gemini-flash-lite-latest", announced_label="Gemini Reader")
    result = media_tools.tool_read_document(str(doc), "What was revenue?")
    assert result.startswith("[Gemini Reader")
    assert "42 million" in prompts[0]


def test_set_model_purpose_tool_reports_the_assignment(store):
    import media_tools

    message = media_tools.tool_set_model_purpose("image_check", "nvidia", "meta/llama-3.2-11b-vision-instruct")
    assert "now uses" in message and store.get_role("image_check")["assigned_by"] == "assistant"


# --- HTTP ----------------------------------------------------------------------------------------


@pytest.fixture()
def client(store):
    import server

    return TestClient(server.app, client=("127.0.0.1", 50011))


def test_keys_listing_has_no_secret_values(client, monkeypatch):
    monkeypatch.setattr(model_hub, "api_key_for", lambda provider: "nvapi-abcdefgh12345678" if provider == "nvidia" else "")
    body = client.get("/api/keys").json()
    nvidia = next(p for p in body["providers"] if p["provider"] == "nvidia")
    assert nvidia["configured"] and nvidia["last4"] == "5678"
    assert nvidia["signup_url"] == "https://build.nvidia.com/models"
    assert "nvapi-abcdefgh12345678" not in json.dumps(body)


def test_roles_can_be_set_and_reset_over_http(client):
    put = client.put("/api/model-roles/reading_text", json={"provider": "aws", "model": "amazon.nova-lite-v1:0"})
    assert put.status_code == 200 and put.json()["role"]["provider"] == "aws"
    listed = {r["id"]: r for r in client.get("/api/model-roles").json()["roles"]}
    assert listed["reading_text"]["model"] == "amazon.nova-lite-v1:0"
    assert client.delete("/api/model-roles/reading_text").json()["role"]["provider"] == "gemini"
    assert client.put("/api/model-roles/x", json={"provider": "nope"}).status_code == 400


def test_role_writes_are_refused_from_another_machine(store):
    import server

    remote = TestClient(server.app, client=("203.0.113.5", 50012))
    assert remote.put("/api/model-roles/image_check", json={"provider": "nvidia"}).status_code == 403
    assert remote.post("/api/keys/nvidia", json={"api_key": "nvapi-12345678"}).status_code == 403


def test_aws_key_ids_are_sanity_checked(client, monkeypatch):
    saved = {}
    monkeypatch.setattr("secret_store.set_keys", lambda name, values: saved.setdefault(name, list(values)))
    assert client.post("/api/keys/aws", json={"access_key_id": "nope"}).status_code == 400
    ok = client.post("/api/keys/aws", json={"access_key_id": "AKIAEXAMPLE1234", "secret_access_key": "s" * 40,
                                             "region": "us-west-2"})
    assert ok.status_code == 200
    assert saved["AWS_REGION"] == ["us-west-2"]
    assert "s" * 40 not in ok.text


def test_an_outage_is_skipped_for_a_while_but_still_reported(store, monkeypatch):
    monkeypatch.setattr(model_roles, "_OUTAGE_COOLDOWN", {})
    calls = []

    def fake_generate(provider, model, prompt, size="1024x1024", timeout=180):
        calls.append(provider)
        if provider == "nvidia":
            raise ModelCallError("NVIDIA (flux) answered 504: ")
        return GeneratedImage(b"\xff\xd8\xff", "image/jpeg", provider, model, 5)

    monkeypatch.setattr(model_hub, "generate_image", fake_generate)
    store.generate("one")
    store.generate("two")
    assert calls.count("nvidia") == 1, "a provider that just 504'd is not retried on the next picture"
    _image, run = store.generate("three")
    assert run.fell_back and "moments ago" in run.note


def test_router_cools_down_a_failing_smart_model(monkeypatch):
    import router as router_module
    from providers.base import ProviderError

    monkeypatch.setattr(router_module, "_SMART_COOLDOWN", {})
    monkeypatch.setattr(router_module.SETTINGS, "gemini_smart_model", "smart-x", raising=False)
    monkeypatch.setattr(router_module.SETTINGS, "gemini_model", "fast-x", raising=False)
    seen = []

    class FakeGemini:
        name = "gemini"
        supports_vision = True

        def is_available(self):
            return True

        def stream_events(self, messages, model=None, thinking=False):
            seen.append(model)
            if model == "smart-x":
                raise ProviderError("overloaded")
            yield {"type": "text", "text": "hi"}

    r = router_module.Router.__new__(router_module.Router)
    monkeypatch.setattr(r, "_candidate_chain", lambda: [FakeGemini()], raising=False)
    assert r.stream([{"role": "user", "content": "x"}], smart=True)[0] == "hi"
    assert r.stream([{"role": "user", "content": "x"}], smart=True)[0] == "hi"
    assert seen == ["smart-x", None, None]


# --- Request J1: a code job never dead-ends while another model works ------------------------------


def test_cooling_model_and_quota_do_not_end_a_code_job(store, monkeypatch):
    """The owner's error: "nvidia: skipped: it failed moments ago; gemini: answered 429" and nothing ran."""
    monkeypatch.setattr(model_roles, "_OUTAGE_COOLDOWN", {("nvidia", "nvidia/nemotron-3-super-120b-a12b"): 9e12})
    calls = []

    def fake_complete(provider, model, prompt, **kw):
        calls.append((provider, model))
        if provider == "gemini":
            raise ModelCallError(f"Gemini ({model}) answered 429: You exceeded your current quota")
        if model == "nvidia/nemotron-3-super-120b-a12b":
            raise ModelCallError("nvidia answered 503: busy")
        return ModelReply(text="patched", provider=provider, model=model, ms=5)

    monkeypatch.setattr(model_hub, "complete", fake_complete)
    run = store.run("code_generation", "improve this")
    assert run.text == "patched"
    assert run.provider == "nvidia" and run.model != "nvidia/nemotron-3-super-120b-a12b", "another NVIDIA model did it"
    assert ("nvidia", "nvidia/nemotron-3-super-120b-a12b") not in calls[:1], "a cooling model is tried later, not first"


def test_every_candidate_failing_still_reports_each_one(store, monkeypatch):
    monkeypatch.setattr(model_roles, "_OUTAGE_COOLDOWN", {})
    monkeypatch.setattr(model_hub, "complete", lambda provider, model, prompt, **kw: (_ for _ in ()).throw(
        ModelCallError(f"{provider} ({model}) answered 429: quota")))
    with pytest.raises(ModelCallError) as error:
        store.run("code_generation", "hi")
    text = str(error.value)
    assert "skipped" not in text and "nvidia" in text and "gemini" in text
    assert text.count("answered 429") <= model_roles._MAX_ATTEMPTS
