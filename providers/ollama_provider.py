"""Local Ollama provider used as Nyx Ichos's offline-first default."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple

import requests

from config import SETTINGS
from providers.base import Provider, ProviderError


#: Context sizes tried for a local model, largest first.
_CTX_STEPS = (262144, 229376, 196608, 163840, 131072, 98304, 65536, 49152, 32768)
#: Share of the GPU left for the voice models, the browser and the desktop.
_GPU_HEADROOM = 0.15
#: Ollama's own working memory beside the weights and the KV cache.
_RUNTIME_BYTES = 1.0e9
_SIZED: Dict[str, int] = {}
_UNREAD: Dict[str, float] = {}


def _vram_bytes() -> float:
    """From the cached device profile (GiB) — never a slow hardware probe."""
    try:
        from pathlib import Path

        vram = float(json.loads((Path(__file__).resolve().parent.parent / "device_profile.json")
                                .read_text(encoding="utf-8")).get("vram_gb") or 0)
    except Exception:  # noqa: BLE001
        vram = 0.0
    return vram * 2 ** 30


def _default_ctx() -> int:
    """When the model can't be read (Ollama not up yet): 64k tokens on a 12 GB+ card, 48k on 8 GB+, else 32k."""
    vram = _vram_bytes() / 2 ** 30
    return 65536 if vram >= 12 else 49152 if vram >= 8 else 32768


def kv_bytes_per_token(info: Dict[str, Any]) -> float:
    """KV-cache bytes one token costs (f16), from Ollama's ``model_info``.

    Hybrid models such as Qwen 3.5 keep a cache on only one layer in four (``head_count_kv`` is listed per layer,
    0 for the linear-attention layers), so they hold four times the context a dense model of the same size does.
    """
    arch = str(info.get("general.architecture") or "")
    layers = int(info.get(f"{arch}.block_count") or 0)
    heads = int(info.get(f"{arch}.attention.head_count") or 0) if not isinstance(
        info.get(f"{arch}.attention.head_count"), list) else max(info[f"{arch}.attention.head_count"])
    kv = info.get(f"{arch}.attention.head_count_kv")
    if isinstance(kv, list):
        kv_heads = sum(int(n or 0) for n in kv)
    else:
        interval = max(1, int(info.get(f"{arch}.full_attention_interval") or 1))
        kv_heads = int(kv or heads) * (layers // interval)
    head_dim = int(info.get(f"{arch}.embedding_length") or 0) / heads if heads else 128
    key = float(info.get(f"{arch}.attention.key_length") or head_dim)
    value = float(info.get(f"{arch}.attention.value_length") or head_dim)
    return kv_heads * (key + value) * 2


def fit_ctx(model_bytes: float, per_token: float, trained: int, vram_bytes: float) -> int:
    """The largest step whose weights + KV cache stay on the GPU with headroom, never past what the model was trained on."""
    room = vram_bytes * (1 - _GPU_HEADROOM) - model_bytes - _RUNTIME_BYTES
    for step in _CTX_STEPS:
        if (not trained or step <= trained) and per_token > 0 and step * per_token <= room:
            return step
    return _CTX_STEPS[-1]


def num_ctx(model: Optional[str] = None) -> int:
    """Context window asked of a local model: as large as fits on this GPU (owner, 2026-10-11: "context fills up fast …
    increase it, at least like Claude's 1M"). On the RTX 5080 (16 GB) Qwen 3.5 9B gets 192k, measured 100 % on the GPU at
    full speed; 256k spilled onto the CPU and ran a third slower.

    ``OLLAMA_NUM_CTX`` overrides it. Sized once per model, so every call asks the same — a different ``num_ctx`` makes
    Ollama reload the model. When Ollama can't be read the GPU tier is used and the next call tries again.
    """
    try:
        if os.getenv("OLLAMA_NUM_CTX", "").strip():
            return max(2048, min(262144, int(os.environ["OLLAMA_NUM_CTX"])))
    except ValueError:
        pass
    name = (model or SETTINGS.ollama_model or "").strip()
    if name in _SIZED:
        return _SIZED[name]
    if _UNREAD.get(name, 0.0) > time.monotonic():
        return _default_ctx()
    host = (SETTINGS.ollama_host or "http://127.0.0.1:11434").replace("//localhost:", "//127.0.0.1:")
    try:
        info = requests.post(f"{host}/api/show", json={"model": name}, timeout=2).json().get("model_info") or {}
        sizes = {m.get("name"): float(m.get("size") or 0) for m in requests.get(f"{host}/api/tags", timeout=2).json().get("models", [])}
        arch = str(info.get("general.architecture") or "")
        size = sizes.get(name) or sizes.get(f"{name}:latest") or 0.0
        if not arch or not size:
            _UNREAD[name] = time.monotonic() + 60
            return _default_ctx()
        _SIZED[name] = fit_ctx(size, kv_bytes_per_token(info), int(info.get(f"{arch}.context_length") or 0), _vram_bytes())
    except Exception:  # noqa: BLE001 - never fails a call; the tier below is what the last version always used
        # Ollama down: ask again in a minute, not on every meter refresh (a refused loopback costs ~2 s on Windows).
        _UNREAD[name] = time.monotonic() + 60
        return _default_ctx()
    return _SIZED[name]


def __getattr__(name: str) -> Any:
    # Older callers import the constant; it is now sized from the model on first use.
    if name == "NUM_CTX":
        return num_ctx()
    raise AttributeError(name)


class OllamaProvider(Provider):
    """Talk to a locally running Ollama server through its HTTP API."""

    name = "ollama"
    _TIMEOUT_SECONDS = 30
    # A loopback health check. A running Ollama answers in milliseconds; when it
    # is absent the probe costs whatever budget it is given, on every request
    # from anyone without Ollama installed.
    #
    # The trap here is that the timeout applies *per resolved address*, and
    # "localhost" resolves to both ::1 and 127.0.0.1 — so the real cost is double
    # the number written here. That is why the original 5s behaved like ~4s, and
    # why lowering it to 1s still measured 2s. `_probe_url` now pins the IPv4
    # loopback so exactly one address is tried and this budget means what it says.
    _PROBE_TIMEOUT_SECONDS = 0.5
    # Availability barely changes within a turn, and the router asks more than
    # once. Cache briefly so a cold local service costs one probe, not several.
    _AVAILABILITY_TTL_SECONDS = 30.0

    def __init__(self) -> None:
        self._availability_cache: Optional[Tuple[float, bool]] = None

    def reset_availability_cache(self) -> None:
        """Forget the cached probe result, forcing the next check to hit the network."""
        self._availability_cache = None

    @staticmethod
    def _probe_url(path: str) -> str:
        """Build a probe URL that resolves to exactly one address.

        `localhost` resolves to ::1 *and* 127.0.0.1, and requests tries each in
        turn — so any timeout is silently doubled when the service is absent.
        Pinning the IPv4 loopback keeps the budget honest. Ollama binds
        127.0.0.1 by default, so this is also where it actually listens.
        """
        host = SETTINGS.ollama_host or "http://127.0.0.1:11434"
        return f"{host.replace('//localhost:', '//127.0.0.1:')}{path}"

    def is_available(self) -> bool:
        """Check the local service without allowing network errors to escape."""
        cached = self._availability_cache
        if cached is not None and (time.monotonic() - cached[0]) < self._AVAILABILITY_TTL_SECONDS:
            return cached[1]

        try:
            response = requests.get(
                self._probe_url('/api/tags'),
                timeout=self._PROBE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            available = True
        except requests.RequestException:
            available = False

        self._availability_cache = (time.monotonic(), available)
        return available

    def is_model_installed(self, model_name: str | None = None) -> bool:
        """Verify the configured model is present on the local Ollama instance.

        Reuses `list_models`, so it inherits the same short-circuit rather than
        paying its own timeout against a server that is already known to be down.
        """
        target_model = model_name or SETTINGS.ollama_model
        return any(target_model in name for name in self.list_models())

    def list_models(self) -> list[str]:
        """Return the names of models currently installed on the local Ollama server.

        Short-circuits when the server is known to be down. Without this the call
        paid a full timeout against a dead loopback port on every request — the
        same defect fixed in `is_available()`, which made `/api/models` take four
        seconds for anyone without Ollama installed.
        """
        if not self.is_available():
            return []
        try:
            response = requests.get(
                self._probe_url('/api/tags'),
                timeout=self._PROBE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return [m.get("name", "") for m in response.json().get("models", [])]
        except requests.RequestException:
            return []

    def chat(self, messages: List[Dict[str, str]]) -> str:
        """Send a non-streaming chat request to the configured local model."""
        try:
            response = requests.post(
                f"{SETTINGS.ollama_host}/api/chat",
                json={
                    "model": SETTINGS.ollama_model,
                    "messages": messages,
                    "stream": False,
                    "options": {"num_ctx": num_ctx()},
                },
                timeout=self._TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            content = response.json()["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("Ollama returned a non-text response.")
            return content
        except (requests.RequestException, KeyError, TypeError, ValueError) as error:
            raise ProviderError(f"Ollama request failed: {error}") from error

    def chat_stream(self, messages: List[Dict[str, str]]) -> Iterator[str]:
        """Stream chunks of the chat response from Ollama in real-time."""
        try:
            with requests.post(
                f"{SETTINGS.ollama_host}/api/chat",
                json={
                    "model": SETTINGS.ollama_model,
                    "messages": messages,
                    "stream": True,
                    "options": {"num_ctx": num_ctx()},
                },
                timeout=self._TIMEOUT_SECONDS,
                stream=True,
            ) as response:
                response.raise_for_status()
                # /api/chat streams JSON lines as content-type text/html (no
                # charset), which requests decodes as ISO-8859-1 — UTF-8
                # multi-byte characters arrive as mojibake. Pin the encoding.
                response.encoding = "utf-8"
                for line in response.iter_lines(decode_unicode=True):
                    if line:
                        chunk = json.loads(line)
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            yield content
        except Exception as error:
            raise ProviderError(f"Ollama stream failed: {error}") from error

    _vision: Optional[Tuple[float, str, bool]] = None

    @property
    def supports_vision(self) -> bool:  # type: ignore[override]
        """True when the configured local model can see pictures (qwen3.5, llava, gemma3…), cached 10 min."""
        model = SETTINGS.ollama_model or ""
        cached = self._vision
        if cached and cached[1] == model and time.time() - cached[0] < 600:
            return cached[2]
        can_see = False
        if model and self.is_available():
            try:
                response = requests.post(self._probe_url("/api/show"), json={"model": model}, timeout=1.5)
                can_see = "vision" in (response.json().get("capabilities") or [])
            except Exception:
                can_see = False
        self._vision = (time.time(), model, can_see)
        return can_see

    def stream_events(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: Optional[str] = None,
        thinking: bool = False,
    ) -> Iterator[Dict[str, str]]:
        """Stream one answer from ``model`` (default: the configured one), with its reasoning as thoughts.

        The base class ignores ``model``, which made every local call use ``OLLAMA_MODEL`` even when
        Identity 0 or an agent named another installed model. Pictures are passed in Ollama's own
        format; the router only sends them here when the provider says it can see.
        """
        chosen = (model or SETTINGS.ollama_model or "").strip()
        body: List[Dict[str, Any]] = []
        for message in messages:
            item: Dict[str, Any] = {"role": message.get("role", "user"), "content": str(message.get("content", "") or "")}
            images = [img.get("data") for img in (message.get("images") or []) if isinstance(img, dict) and img.get("data")]
            if images:
                item["images"] = images
            body.append(item)
        try:
            with requests.post(
                f"{SETTINGS.ollama_host}/api/chat",
                json={"model": chosen, "messages": body, "stream": True, "think": bool(thinking),
                      "options": {"num_ctx": num_ctx(chosen)}},
                # A cold model takes up to a minute to load before its first token.
                timeout=(5, 180),
                stream=True,
            ) as response:
                if response.status_code >= 400:
                    raise ProviderError(f"Ollama answered {response.status_code}: {response.text[:200]}")
                response.encoding = "utf-8"
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise ProviderError(f"Ollama: {str(chunk['error'])[:200]}")
                    message = chunk.get("message") or {}
                    if message.get("thinking"):
                        yield {"type": "thought", "text": message["thinking"]}
                    if message.get("content"):
                        yield {"type": "text", "text": message["content"]}
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError(f"Ollama stream failed: {error}") from error
