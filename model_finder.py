"""Model finder: hunt down models Nyx could use for free, and where to get a key (Request R13).

The owner (2026-09-17): "Add a model finder. It searches extremely hard to find more models for free and gives the link
or search so the user can find and api key for it. Put this specifically in the key tab on the bottom. Last resort kind
of thing."

It searches in three ways and merges the results:

1. **OpenRouter's public catalogue** (no key needed to read it) — every model whose prompt *and* completion price is
   zero is genuinely free to call with an OpenRouter key.
2. **A checked list of providers with free tiers** — what each one gives, and the page where the key comes from.
   Anything already configured in Keys is marked so, and providers Nyx already knows are not offered twice.
3. **The web** — several searches, then the promising pages are read and judged ("is there a free tier, and what does
   it give?") by the fast model, with an offline reading when no model answers.

Every result carries the link to get the key, so the owner can finish in one click; "Use this" hands the provider,
address and example model to the Add-a-model form in Keys & Models — the key is always typed by the owner.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Sequence

import requests

_LOG = logging.getLogger("nyx.model_finder")

TIMEOUT = 20
OPENROUTER_MODELS = "https://openrouter.ai/api/v1/models"
MAX_WEB_PAGES = 6

#: Providers with a free tier, checked by hand. ``free`` says what you actually get.
CATALOG: List[Dict[str, Any]] = [
    {"provider": "nvidia", "label": "NVIDIA NIM (build.nvidia.com)", "free": "Free API credits for every hosted model, "
     "including Nemotron 3 Ultra, Llama Vision and FLUX images.", "signup": "https://build.nvidia.com/models",
     "chat_url": "https://integrate.api.nvidia.com/v1/chat/completions", "model": "nvidia/nemotron-3-super-120b-a12b"},
    {"provider": "gemini", "label": "Google AI Studio (Gemini)", "free": "Free tier with daily limits on Gemini Flash and "
     "Flash-Lite, including vision and long documents.", "signup": "https://aistudio.google.com/apikey",
     "chat_url": "", "model": "gemini-flash-lite-latest"},
    {"provider": "groq", "label": "Groq", "free": "Free tier, very fast; Llama, Qwen and GPT-OSS models.",
     "signup": "https://console.groq.com/keys", "chat_url": "https://api.groq.com/openai/v1/chat/completions",
     "model": "llama-3.3-70b-versatile"},
    {"provider": "cerebras", "label": "Cerebras", "free": "Free daily token allowance, the fastest tokens per second of "
     "these.", "signup": "https://cloud.cerebras.ai/", "chat_url": "https://api.cerebras.ai/v1/chat/completions",
     "model": "llama3.1-8b"},
    {"provider": "openrouter", "label": "OpenRouter", "free": "Any model id ending in “:free” costs nothing (rate "
     "limited). One key, dozens of models.", "signup": "https://openrouter.ai/keys",
     "chat_url": "https://openrouter.ai/api/v1/chat/completions", "model": "meta-llama/llama-3.3-70b-instruct:free"},
    {"provider": "mistral", "label": "Mistral", "free": "Free experiment tier — opt in when creating the key.",
     "signup": "https://console.mistral.ai/api-keys/", "chat_url": "https://api.mistral.ai/v1/chat/completions",
     "model": "mistral-small-latest"},
    {"provider": "github-models", "label": "GitHub Models", "free": "Free with a GitHub token (models scope); OpenAI, "
     "Llama, Mistral and Phi models with monthly limits.", "signup": "https://github.com/marketplace/models",
     "chat_url": "https://models.github.ai/inference/chat/completions", "model": "openai/gpt-4o-mini"},
    {"provider": "together", "label": "Together AI", "free": "Models with a “-Free” suffix are served at no cost.",
     "signup": "https://api.together.ai/settings/api-keys", "chat_url": "https://api.together.xyz/v1/chat/completions",
     "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free"},
    {"provider": "cloudflare", "label": "Cloudflare Workers AI", "free": "A free daily allowance of neurons on Llama, "
     "Mistral and Qwen models.", "signup": "https://dash.cloudflare.com/profile/api-tokens",
     "chat_url": "https://api.cloudflare.com/client/v4/accounts/<account-id>/ai/v1/chat/completions",
     "model": "@cf/meta/llama-3.1-8b-instruct"},
    {"provider": "huggingface", "label": "Hugging Face Inference", "free": "Free monthly credits across many open "
     "models with a read token.", "signup": "https://huggingface.co/settings/tokens",
     "chat_url": "https://router.huggingface.co/v1/chat/completions", "model": "meta-llama/Llama-3.3-70B-Instruct"},
    {"provider": "qwen", "label": "Qwen — Alibaba Model Studio", "free": "Free token quota per model for new accounts, "
     "then billed.", "signup": "https://modelstudio.console.alibabacloud.com/model/settings/api-key",
     "chat_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions", "model": "qwen-plus"},
    {"provider": "ollama", "label": "Ollama (on this PC)", "free": "Free forever and offline — it runs on your own "
     "graphics card. Set it up in Local models above.", "signup": "https://ollama.com/download", "chat_url": "",
     "model": "qwen3:8b"},
    {"provider": "pollinations", "label": "Pollinations (images)", "free": "Keyless free image generation; pictures "
     "carry a small watermark.", "signup": "https://pollinations.ai/", "chat_url": "", "model": "flux"},
]

SEARCHES = [
    "free LLM API key no credit card {year}",
    "free inference API for open models {year}",
    "LLM provider generous free tier developers {year}",
    "list of free AI APIs github awesome",
]


class FinderError(RuntimeError):
    pass


JOBS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.RLock()


def _job(query: str) -> Dict[str, Any]:
    job = {"id": uuid.uuid4().hex[:8], "query": query, "status": "running", "step": "Starting", "results": [],
           "started_at": time.time(), "ended_at": 0.0, "error": "", "searched": []}
    with _LOCK:
        JOBS[job["id"]] = job
        for old in sorted(JOBS.values(), key=lambda j: j["started_at"])[:-6]:
            JOBS.pop(old["id"], None)
    return job


def _publish(job: Dict[str, Any]) -> None:
    try:
        from agent_events import publish_ui

        publish_ui("model_finder.update", job={"id": job["id"], "status": job["status"], "step": job["step"],
                                               "results": len(job["results"])})
    except Exception:  # noqa: BLE001
        pass


def jobs() -> List[Dict[str, Any]]:
    with _LOCK:
        return sorted(JOBS.values(), key=lambda j: -j["started_at"])


def latest() -> Optional[Dict[str, Any]]:
    found = jobs()
    return found[0] if found else None


def configured() -> Dict[str, bool]:
    """Which providers already have a key here, so the finder does not send the owner shopping for one twice."""
    state: Dict[str, bool] = {}
    try:
        import model_hub

        for name in model_hub.known_providers():
            state[name] = model_hub.is_configured(name)
    except Exception:  # noqa: BLE001
        pass
    try:
        from provider_specs import PROVIDER_SPECS

        for spec in PROVIDER_SPECS.list_specs():
            state.setdefault(spec.name, False)
    except Exception:  # noqa: BLE001
        pass
    return state


def _result(kind: str, name: str, label: str, free: str, signup: str, **extra: Any) -> Dict[str, Any]:
    return {"id": uuid.uuid4().hex[:6], "kind": kind, "provider": name, "label": label, "free": free[:400],
            "signup": signup, "chat_url": extra.get("chat_url", ""), "model": extra.get("model", ""),
            "note": str(extra.get("note", ""))[:300], "source": extra.get("source", ""), "score": float(extra.get("score", 0))}


# ---------------------------------------------------------------------------
# The three searches
# ---------------------------------------------------------------------------


def from_catalog(query: str = "") -> List[Dict[str, Any]]:
    have = configured()
    words = [w for w in re.findall(r"[a-z0-9]+", (query or "").lower()) if len(w) > 2]
    out = []
    for item in CATALOG:
        text = f"{item['label']} {item['free']} {item['model']}".lower()
        if words and not any(w in text for w in words):
            continue
        score = 3.0 if not have.get(item["provider"]) else 1.0
        note = "Already set up here." if have.get(item["provider"]) else ""
        out.append(_result("catalog", item["provider"], item["label"], item["free"], item["signup"],
                           chat_url=item["chat_url"], model=item["model"], note=note, score=score, source="Nyx's checked list"))
    return out


def openrouter_free(limit: int = 25, get: Optional[Callable[..., Any]] = None) -> List[Dict[str, Any]]:
    """Models OpenRouter serves at zero cost right now — read from its public catalogue, no key needed."""
    http = get or requests.get
    try:
        response = http(OPENROUTER_MODELS, timeout=TIMEOUT, headers={"User-Agent": "NyxIchos-ModelFinder/1.0"})
        data = response.json() if response.status_code == 200 else {}
    except Exception as error:  # noqa: BLE001
        raise FinderError(f"OpenRouter's catalogue could not be read ({type(error).__name__}).") from error
    free = []
    for model in data.get("data") or []:
        pricing = model.get("pricing") or {}
        try:
            if float(pricing.get("prompt", 1)) > 0 or float(pricing.get("completion", 1)) > 0:
                continue
        except (TypeError, ValueError):
            continue
        context = model.get("context_length") or 0
        free.append(_result("openrouter", "openrouter", str(model.get("name") or model.get("id")),
                            f"Free on OpenRouter · {context:,} tokens of context" if context else "Free on OpenRouter",
                            "https://openrouter.ai/keys", chat_url="https://openrouter.ai/api/v1/chat/completions",
                            model=str(model.get("id")), score=2.0 + min(1.0, context / 200_000), source="OpenRouter catalogue"))
    free.sort(key=lambda item: -item["score"])
    return free[:limit]


def _judge(job: Dict[str, Any], url: str, title: str, text: str, model_fn: Optional[Callable[..., str]]) -> Optional[Dict[str, Any]]:
    """Does this page really offer a free model API? The model answers; a keyword read stands in for it."""
    snippet = re.sub(r"\s+", " ", text)[:4000]
    if model_fn is not None:
        try:
            reply = model_fn(
                f"Page: {title}\nURL: {url}\n{snippet}\n\n"
                "Does this page offer an API for AI models that someone can use for free (a free tier, free credits, or free "
                "models)? Reply with JSON only: {\"free\": true/false, \"provider\": \"short name\", \"what_you_get\": \"one "
                "sentence\", \"signup\": \"the page to get an API key, or empty\"}",
                system="detailed thinking off\nYou judge whether a page offers a free AI model API. Reply with JSON only.",
                max_tokens=300)
            from absorb_engine import json_from

            data = json_from(reply or "")
            if isinstance(data, dict) and data.get("free"):
                return _result("web", str(data.get("provider") or title)[:40], str(data.get("provider") or title)[:60],
                               str(data.get("what_you_get") or "")[:300], str(data.get("signup") or url), source=url, score=1.5)
            if isinstance(data, dict):
                return None
        except Exception as error:  # noqa: BLE001 - fall through to the offline read
            _LOG.debug("finder judge failed: %s", error)
    lowered = snippet.lower()
    hits = sum(1 for word in ("free tier", "free api", "no credit card", "free credits", "free to use", "free plan") if word in lowered)
    if hits >= 1 and ("api" in lowered and ("model" in lowered or "llm" in lowered)):
        return _result("web", title[:40] or url, title[:60] or url,
                       "This page mentions a free tier for an AI API — open it to check what it gives.", url,
                       source=url, score=0.8)
    return None


def search(query: str = "", *, deep: bool = True, threaded: bool = True, model_fn: Optional[Callable[..., str]] = None,
           searcher: Optional[Callable[[str], List[Dict[str, str]]]] = None,
           fetcher: Optional[Callable[[str], str]] = None) -> Dict[str, Any]:
    """Start a hunt. Results arrive in the job as each source answers, so the tab can show them while it works."""
    job = _job((query or "").strip()[:200])

    def work() -> None:
        try:
            job["step"] = "Reading Nyx's checked list"
            job["results"] = from_catalog(job["query"])
            _publish(job)
            job["step"] = "Reading OpenRouter's free models"
            _publish(job)
            try:
                job["results"] += openrouter_free()
            except FinderError as error:
                job["results"].append(_result("note", "openrouter", "OpenRouter", str(error), "https://openrouter.ai/models"))
            _publish(job)
            if deep:
                import web_access

                search_web = searcher or (lambda q: web_access.search_results(q, freshness="any"))
                fetch = fetcher or (lambda url: web_access.fetch(url))
                year = time.strftime("%Y")
                queries = [q.format(year=year) for q in SEARCHES]
                if job["query"]:
                    queries.insert(0, f"free API key {job['query']} model")
                seen_urls = set()
                pages: List[Dict[str, str]] = []
                for one in queries[:5]:
                    job["step"] = f"Searching: {one}"
                    _publish(job)
                    try:
                        for hit in search_web(one)[:6]:
                            url = str(hit.get("url", ""))
                            if url.startswith("http") and url not in seen_urls:
                                seen_urls.add(url)
                                pages.append({"url": url, "title": str(hit.get("title", ""))})
                    except Exception as error:  # noqa: BLE001 - one engine failing is not the end
                        job["searched"].append(f"{one}: {type(error).__name__}")
                    job["searched"].append(one)
                for page in pages[:MAX_WEB_PAGES]:
                    job["step"] = f"Reading {page['title'][:60] or page['url'][:60]}"
                    _publish(job)
                    try:
                        text = fetch(page["url"])
                    except Exception:  # noqa: BLE001
                        continue
                    found = _judge(job, page["url"], page["title"], text, model_fn or _default_model)
                    if found and not any(r["signup"] == found["signup"] for r in job["results"]):
                        job["results"].append(found)
                        _publish(job)
            job["results"].sort(key=lambda r: -r["score"])
            job["status"], job["step"] = "done", f"{len(job['results'])} places to get a model"
        except Exception as error:  # noqa: BLE001
            job["status"], job["error"] = "error", f"{type(error).__name__}: {str(error)[:200]}"
            job["step"] = "Stopped"
        job["ended_at"] = time.time()
        _publish(job)

    if threaded:
        threading.Thread(target=work, name=f"nyx-finder-{job['id']}", daemon=True).start()
    else:
        work()
    return job


def _default_model(prompt: str, *, system: str = "", max_tokens: int = 300) -> str:
    from model_roles import MODEL_ROLES

    return MODEL_ROLES.run("fast_chat", prompt, system=system, max_tokens=max_tokens).text


def prefill(result: Dict[str, Any]) -> Dict[str, Any]:
    """What the Add-a-model form needs. Never a key — the owner types that themselves."""
    return {"name": result.get("label") or result.get("provider"), "company": result.get("provider", "other"),
            "model": result.get("model", ""), "chat_url": result.get("chat_url", ""), "free": True,
            "signup": result.get("signup", "")}
