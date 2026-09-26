"""The Safe mix: what Identity 0 may train on, decided deny-by-default."""

import pytest

from identity0.policy import may_train_on, scrub_pii, source_license


@pytest.mark.parametrize("provider,model", [
    ("ollama", "qwen3.5:9b"), ("nvidia", "nvidia/nemotron-3-super-120b-a12b"), ("deepseek", "deepseek-chat"),
    ("ollama", "gpt-oss:20b"), ("ollama", "mistral:7b"), ("self", "nano-v1"),
])
def test_open_license_models_are_allowed(provider, model):
    assert may_train_on(provider, model)[0]


@pytest.mark.parametrize("provider,model", [
    ("openai", "gpt-5"), ("claude", "x"), ("gemini", "gemini-flash-lite-latest"), ("kimi", "k2"),
    ("perplexity", "sonar"), ("nvidia", "meta/llama-3.3-70b-instruct"),
    ("nvidia", "nvidia/llama-3.1-nemotron-70b-instruct"), ("ollama", "gemma3:4b"), ("ollama", "mystery:1b"),
    ("somewhere", "qwen3"),
])
def test_everything_else_is_denied_with_a_reason(provider, model):
    allowed, why = may_train_on(provider, model)
    assert not allowed and why


def test_ollama_is_not_mistaken_for_llama():
    assert may_train_on("ollama", "qwen3.5:9b")[0]


def test_sources_carry_licenses_and_web_is_lookup_only():
    assert source_license("wikipedia")["train"] and "CC BY-SA" in source_license("wikipedia")["license"]
    assert source_license("gutenberg")["train"]
    assert not source_license("web")["train"] and not source_license("google")["train"]
    assert not source_license("unheard-of")["train"]


def test_scrub_removes_people_and_secrets():
    text = ("mail me at jane.doe@example.com or call (555) 123-4567, key nvapi-" + "a" * 30 +
            ", card 4111 1111 1111 1111, I live at 12 Oak Street.")
    cleaned = scrub_pii(text)
    for leaked in ("jane.doe", "123-4567", "nvapi-", "4111", "Oak Street"):
        assert leaked not in cleaned
    assert "[email]" in cleaned and "[secret]" in cleaned
