"""What Identity 0 may learn from — provenance for every training example (the owner's "Safe mix").

Two reasons this is deny-by-default rather than a blocklist:

* **Terms.** OpenAI, Anthropic, Google (Gemini), Moonshot (Kimi) and Perplexity forbid using their
  outputs to build a competing model; ``NYX_MODEL_ROUTINE.md`` made that an accepted constraint, and
  the owner re-chose it on 2026-09-18. Meta's Llama license makes any model trained on Llama outputs
  carry "Llama" at the start of its name, and Gemma's terms travel with its outputs, so both are out.
* **Sharing.** Identity 0 is "the start for everyone's code": its weights may go to beta testers, so
  a source whose license is unknown must not slip in just because nobody listed it.

Web and Google results are for looking things up (the super brain), never for training: page
licenses are unknown. Runtime use of every model is unaffected — this only gates the dataset.
"""

from __future__ import annotations

import re
from typing import Dict, Tuple

# Model-family markers, checked against "provider:model" in lower case. Order matters: the first
# match wins, so the denials that hide inside allowed hosts (Llama on NVIDIA, Gemma on Ollama) come first.
_DENY_MODELS = (
    ("llama", "Llama license: anything trained on its outputs must be named \"Llama…\""),
    # DeepSeek-R1 distills built on Llama weights carry the Llama license (Ollama's 8b and 70b tags).
    ("deepseek-r1:8b", "a DeepSeek-R1 distill of Llama: Llama license"),
    ("deepseek-r1:70b", "a DeepSeek-R1 distill of Llama: Llama license"),
    ("gemma", "Gemma terms follow its outputs"),
    ("codellama", "Llama license"),
    ("phi", "unclear output terms for this family"),
)
_ALLOW_MODELS = (
    ("qwen", "Qwen family, Apache-2.0"),
    ("qwq", "Qwen family, Apache-2.0"),
    ("deepseek", "DeepSeek, MIT-licensed weights and outputs"),
    ("mistral", "Mistral Apache-2.0 models"),
    ("mixtral", "Mistral Apache-2.0 models"),
    ("gpt-oss", "gpt-oss, Apache-2.0"),
    ("nemotron", "NVIDIA Open Model License allows derivative models"),
)
_DENY_PROVIDERS = {
    "openai": "OpenAI's terms forbid training a competing model on its outputs",
    "claude": "Anthropic's terms forbid training a competing model on its outputs",
    "anthropic": "Anthropic's terms forbid training a competing model on its outputs",
    "gemini": "Google's Gemini API terms forbid developing competing models with it",
    "kimi": "Moonshot's terms forbid it",
    "moonshot": "Moonshot's terms forbid it",
    "perplexity": "Perplexity's terms forbid it",
    "pollinations": "image service, unknown terms",
}
#: Providers whose own weights we run or host openly: allowed when the model family is allowed.
#: (Not the Qwen/DashScope API: its hosted models, such as qwen-max, are proprietary with their own terms.)
_OPEN_HOSTS = {"ollama", "nvidia", "groq", "deepseek", "local", "custom"}

SOURCES: Dict[str, Dict[str, object]] = {
    "wikipedia": {"license": "CC BY-SA 4.0", "train": True,
                  "attribution": "Text from Wikipedia (https://en.wikipedia.org), CC BY-SA 4.0."},
    "gutenberg": {"license": "Public domain in the USA", "train": True,
                  "attribution": "Books from Project Gutenberg (https://www.gutenberg.org); PG headers removed."},
    "wikidata": {"license": "CC0 1.0", "train": True, "attribution": "Facts from Wikidata, CC0."},
    "arxiv": {"license": "CC0 1.0 (metadata and abstracts)", "train": True,
              "attribution": "Abstracts via the arXiv API; thank you to arXiv for use of its open access interoperability."},
    "chats": {"license": "the owner's own conversations", "train": True,
              "attribution": "The owner's chats, PII-scrubbed, used only while train_on_chats is on."},
    "templates": {"license": "written for Nyx", "train": True, "attribution": "Nyx's own templates."},
    "docs": {"license": "the project's own documentation", "train": True, "attribution": "Nyx's own docs."},
    "web": {"license": "unknown", "train": False, "attribution": "Lookup only."},
    "google": {"license": "unknown", "train": False, "attribution": "Lookup only."},
    "github": {"license": "per repository", "train": False,
               "attribution": "Lookup only unless the repository license is permissive (checked per repo)."},
}


def may_train_on(provider: str, model: str = "") -> Tuple[bool, str]:
    """Whether an answer from ``provider``/``model`` may become training data, and why (in words)."""
    name = (provider or "").strip().lower()
    family = (model or "").strip().lower()
    if name in ("self", "identity0"):
        return True, "Identity 0's own model"
    if name in _DENY_PROVIDERS:
        return False, _DENY_PROVIDERS[name]
    probe = f"{name}:{family}"
    for marker, why in _DENY_MODELS:
        if re.search(rf"(^|[/:\-_ .]){re.escape(marker)}", probe):
            return False, why
    for marker, why in _ALLOW_MODELS:
        if marker in probe:
            if name in _OPEN_HOSTS or name.startswith("custom"):
                return True, why
            return False, f"{why}, but served by {name}, whose terms are unknown"
    return False, "unknown model or license, so it stays out (deny by default)"


def source_license(source: str) -> Dict[str, object]:
    key = (source or "").strip().lower()
    info = SOURCES.get(key, {"license": "unknown", "train": False, "attribution": "unknown source"})
    return {"source": key, **info}


_PII = [
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"(?<!\w)(?:\+?\d{1,3}[\s.\-]?)?(?:\(\d{3}\)|\d{3})[\s.\-]\d{3}[\s.\-]\d{4}(?!\w)"), "[phone]"),
    (re.compile(r"\b(?:\d[ \-]?){13,19}\b"), "[number]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[id]"),
    (re.compile(r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s){1,3}(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way)\b\.?"),
     "[address]"),
]


def scrub_pii(text: str) -> str:
    """Remove what would identify a person or unlock an account (best effort, before anything is stored)."""
    if not text:
        return ""
    cleaned = text
    try:
        from build_release import _RAW_TOKEN_RES, _SECRET_RE

        for pattern in _RAW_TOKEN_RES:
            cleaned = pattern.sub("[secret]", cleaned)
        cleaned = _SECRET_RE.sub(lambda m: m.group(0).replace(m.group(1), "[secret]"), cleaned)
    except Exception:  # pragma: no cover - the scrub below still runs
        pass
    for pattern, placeholder in _PII:
        cleaned = pattern.sub(placeholder, cleaned)
    return cleaned
