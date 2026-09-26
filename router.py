"""Intelligent request router that selects providers based on device capability, network state, and hardware safety."""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from config import SETTINGS
from connectivity import is_online
from device_profile import get_device_profile, select_tier
from hardware_safety import SAFETY_MONITOR
from metrics import GLOBAL_METRICS
from providers.anthropic_provider import AnthropicProvider
from providers.base import Provider, ProviderError
from providers.custom import CustomProvider, build_custom_providers
from providers.deepseek_provider import DeepSeekProvider
from providers.gemini_provider import GeminiProvider
from providers.groq_provider import GroqProvider
from providers.kimi_provider import KimiProvider
from providers.nvidia_provider import NvidiaProvider
from providers.ollama_provider import OllamaProvider
from providers.openai_provider import OpenAIProvider
from providers.perplexity_provider import PerplexityProvider
from providers.qwen_provider import QwenProvider

# Providers that hit paid APIs; excluded from selection by default so the
# assistant never auto-routes to a paid model without an explicit opt-in.
_PAID_PROVIDERS = {"claude", "openai", "kimi", "deepseek", "perplexity", "qwen"}
#: Optional "smart" models that recently failed, and until when they are skipped.
#: Module-level so every chat's router learns from one failure.
_SMART_COOLDOWN: Dict[str, float] = {}
_SMART_COOLDOWN_SECONDS = 10 * 60
#: Providers that just failed, and until when fallback tries them after healthy ones.
_RECENT_FAILURE: Dict[str, float] = {}
_RECENT_FAILURE_SECONDS = 5 * 60

# Free-first online order (gemini, groq, and nvidia all have free tiers).
_FREE_FIRST_ORDER = ("gemini", "groq", "nvidia", "claude", "openai", "kimi", "deepseek", "perplexity", "qwen")
# Names owned by the shipped providers; a user-added spec may not take one.
_BUILTIN_ROUTER_NAMES = frozenset(("ollama", "identity0", *_FREE_FIRST_ORDER))
#: Big Kahuna (Request S): leads the chain when enabled; never an "online" provider itself.
_IDENTITY0 = "identity0"


def _without_images(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Replace attached images with a note, for providers that cannot see them."""
    from providers.base import image_note

    cleaned: List[Dict[str, Any]] = []
    for message in messages:
        images = message.get("images") if isinstance(message, dict) else None
        if not images:
            cleaned.append(message)
            continue
        copy = {k: v for k, v in message.items() if k != "images"}
        copy["content"] = f"{copy.get('content', '')}\n\n{image_note(images)}".strip()
        cleaned.append(copy)
    return cleaned


def _key_name(provider: str) -> str:
    try:
        import key_pool

        return key_pool.key_name_for(provider)
    except Exception:  # pragma: no cover
        return ""


def _key_plan(provider: str) -> List[str]:
    """The provider's keys in the order to try them (several keys per provider, Request H8)."""
    name = _key_name(provider)
    if not name:
        return []
    try:
        import key_pool

        return key_pool.plan(name)
    except Exception:  # pragma: no cover - a broken health file must not stop a reply
        return []


def _use_key(key_name: str, key: str) -> None:
    try:
        import key_pool

        key_pool.use(key_name, key)
    except Exception:  # pragma: no cover
        pass


def _report_key(key_name: str, key: Optional[str], ok: bool, error: str = "") -> str:
    """Record what a key's API said. Without a planned key, the live one is the key used."""
    try:
        import key_pool

        used = key or key_pool.current_key(key_name)
        return key_pool.report(key_name, used, ok=ok, error=error)
    except Exception:  # pragma: no cover
        return ""


def _log_event(message: str, source: str, ok: bool = True) -> None:
    """Record a routing event. Logging must never break a chat request."""
    try:
        from event_log import ok as log_ok, warn as log_warn

        (log_ok if ok else log_warn)(message, source)
    except Exception:
        pass


class Router:
    """Route chat requests to the best available provider with intelligent fallback and metrics tracking."""

    def __init__(self, web_access: bool = True):
        """Initialize providers and cache device profile."""
        self.ollama = OllamaProvider()
        self.perplexity = PerplexityProvider()
        self.claude = AnthropicProvider()
        self.openai = OpenAIProvider()
        self.gemini = GeminiProvider()
        self.kimi = KimiProvider()
        self.deepseek = DeepSeekProvider()
        self.groq = GroqProvider()
        self.nvidia = NvidiaProvider()
        self.qwen = QwenProvider()
        self.providers: Dict[str, Provider] = {
            "ollama": self.ollama,
            "claude": self.claude,
            "openai": self.openai,
            "gemini": self.gemini,
            "kimi": self.kimi,
            "deepseek": self.deepseek,
            "groq": self.groq,
            "nvidia": self.nvidia,
            "perplexity": self.perplexity,
            "qwen": self.qwen,
        }
        # Identity 0 (Request S) is the main brain: it plans which of the providers above answers,
        # and it sits in front of the chain so a failure inside it falls through to the old order.
        try:
            from identity0.provider import Identity0Provider

            self.providers[_IDENTITY0] = Identity0Provider(self)
        except Exception as error:  # pragma: no cover - the router must build without it
            _log_event(f"identity0 unavailable: {str(error)[:90]}", "router", ok=False)
        # Providers the user added at runtime. They are ordinary members of
        # self.providers from here on, so the fallback chain, direct_chat, and
        # multi_chat need no special case for them.
        self.custom: Dict[str, CustomProvider] = {}
        self.refresh_custom_providers()
        self.device_profile = get_device_profile()
        self.device_tier = select_tier(self.device_profile)
        self.web_access_enabled = web_access
        from web_access import set_enabled

        set_enabled(web_access)

    def refresh_custom_providers(self) -> List[str]:
        """Re-read user-added provider specs into this router.

        Called at construction and again after a spec is written, so a provider
        the user just added answers the very next message. Routers are cached
        per chat (server._services), and without this a new provider would only
        appear after a restart — the same "I configured it and nothing
        happened" failure that reload_keys exists to prevent.

        A broken store must never stop a router from being built, so the load
        is best-effort and simply yields no custom providers on failure.
        """
        try:
            rebuilt = build_custom_providers()
        except Exception as error:  # pragma: no cover - defensive
            _log_event(f"custom providers unavailable: {str(error)[:90]}", "router", ok=False)
            rebuilt = {}

        for name in list(self.custom):
            if self.providers.get(name) is self.custom[name]:
                self.providers.pop(name, None)
        self.custom = {n: p for n, p in rebuilt.items() if n not in _BUILTIN_ROUTER_NAMES}
        self.providers.update(self.custom)
        return sorted(self.custom)

    def _paid_names(self) -> set[str]:
        """Providers that may bill the owner and that the owner has not picked themselves.

        A user-added provider declares this itself: a spec flagged is_free is
        treated like Gemini or Groq, and anything else like Claude or OpenAI.
        Free-only mode keeps these out of *automatic* routing. Picking one in the
        dropdown or by asking is consent (Request H11: "it says it's paid but I do
        have an API key for free"), and whether a key really needs payment is
        decided by what its API answers (``key_pool.payment_problem``).
        """
        try:
            from model_choice import allowed_paid

            allowed = set(allowed_paid())
        except Exception:  # pragma: no cover
            allowed = set()
        return (set(_PAID_PROVIDERS) | {
            name for name, provider in self.custom.items() if not provider.is_free
        }) - allowed

    def set_web_access(self, enabled: bool) -> None:
        """Enable or disable online provider access for future requests."""
        self.web_access_enabled = enabled
        from web_access import set_enabled

        set_enabled(enabled)

    def web_access_status(self) -> Dict[str, bool]:
        """Report permission and current network reachability separately."""
        online = is_online()
        return {
            "enabled": self.web_access_enabled,
            "online": online,
            "available": self.web_access_enabled and online,
        }

    def _online_available(self) -> bool:
        """Return whether online providers may be used for this request."""
        return self.web_access_enabled and is_online()

    def _online_order(self) -> List[str]:
        """Free-first provider order, dropping paid providers in free-only mode.

        User-added providers slot in behind the shipped ones of the same cost:
        a free custom provider is a perfectly good fallback, but it should not
        displace a provider the user has been relying on just because it was
        added later. A custom provider named as `preferred` still leads.
        """
        preferred = SETTINGS.preferred_online_provider
        if preferred == _IDENTITY0:
            preferred = "gemini"
        custom_free = sorted(n for n, p in self.custom.items() if p.is_free)
        custom_paid = sorted(n for n, p in self.custom.items() if not p.is_free)
        order = [preferred]
        order += [name for name in _FREE_FIRST_ORDER if name != preferred]
        order += [name for name in (*custom_free, *custom_paid) if name != preferred]
        now = time.time()
        order = order[:1] + sorted(order[1:], key=lambda n: 1 if _RECENT_FAILURE.get(n, 0.0) > now else 0)
        if SETTINGS.free_only:
            paid = self._paid_names()
            order = [name for name in order if name not in paid]
        return order

    def _is_local_suitable(self) -> bool:
        """Determine if local Ollama is a reasonable choice for this device."""
        if self.device_tier.name == "tiny":
            return False
        return True

    def _get_primary_provider(self) -> Provider:
        """Select the primary provider based on device capability, safety status, and connectivity."""
        online_available = self._online_available()

        # Check if local hardware is safe for inference
        safe, _ = SAFETY_MONITOR.is_safe_to_run(job_type="inference")

        # Prefer local if device is capable, safe, and Ollama is online
        if safe and self._is_local_suitable() and self.ollama.is_available():
            return self.ollama

        # Local not suitable, throttled, or unavailable; use online if permitted & connected
        if online_available:
            for name in self._online_order():
                provider = self.providers.get(name)
                if provider is not None and provider.is_available():
                    return provider

        # Fallback: try local even if not ideal
        if self.ollama.is_available():
            return self.ollama

        raise ProviderError(
            "No providers available: Ollama is offline and no internet connection detected."
        )

    def _get_fallback_provider(self, primary: Provider) -> Optional[Provider]:
        """Return an alternative provider if the primary fails."""
        if primary.name != "ollama" and self.ollama.is_available():
            return self.ollama
        if self._online_available():
            for name in self._online_order():
                candidate = self.providers.get(name)
                if candidate is not None and candidate is not primary and candidate.is_available():
                    return candidate
        return None

    def unavailable_reason(self, name: str, explicit: bool = False) -> Optional[str]:
        """Why the named provider cannot answer right now, in words — or None when it can.

        ``explicit`` is the owner picking it themselves (dropdown, "switch to X", an
        agent's model): that is consent, so free-only mode does not refuse it. Only
        an API that said the key needs payment does.
        """
        name = (name or "").strip().lower()
        provider = self.providers.get(name)
        if provider is None:
            return f"{name or 'that'} is not a provider Nyx knows (add it in Keys & Models)"
        if name == _IDENTITY0:
            return None if provider.is_available() else "Big Kahuna is switched off or has no model to work with"
        try:
            import key_pool

            payment = key_pool.payment_problem(name)
        except Exception:  # pragma: no cover
            payment = None
        if payment:
            return f"the {name} API said this key needs payment ({payment[:160]})"
        if SETTINGS.free_only and not explicit and name in self._paid_names():
            return f"{name} may bill your account, so Nyx only uses it when you pick it yourself"
        if name != "ollama" and not self._online_available():
            return "online models are switched off or the network is down"
        if not provider.is_available():
            return "Ollama is not running" if name == "ollama" else f"no API key is set for {name}"
        return None

    def direct_chat(self, messages: List[Dict[str, str]], provider_name: str) -> Tuple[str, str]:
        """Talk to one named agent without changing local-first routing policy."""
        if provider_name not in self.providers:
            raise ProviderError(f"Unknown provider: {provider_name}")
        if SETTINGS.free_only and provider_name in self._paid_names():
            raise ProviderError(
                f"{provider_name} may bill your account and you have not picked it yet "
                "(pick it in the chat's model menu to allow it)."
            )
        provider = self.providers[provider_name]
        if provider_name != "ollama" and not self._online_available():
            raise ProviderError("Online providers are disabled or the network is unavailable.")
        if not provider.is_available():
            raise ProviderError(f"Provider is unavailable: {provider_name}")

        start_time = time.time()
        try:
            response = provider.chat(messages)
            latency = time.time() - start_time
            GLOBAL_METRICS.record(provider=provider_name, latency_seconds=latency, success=True)
            return response, provider.name
        except Exception as error:
            latency = time.time() - start_time
            GLOBAL_METRICS.record(
                provider=provider_name,
                latency_seconds=latency,
                success=False,
                error_message=str(error),
            )
            raise

    def multi_chat(
        self,
        messages: List[Dict[str, str]],
        provider_names: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """Query several agents independently in parallel; one failure does not cancel others."""
        from concurrent.futures import ThreadPoolExecutor

        # Paid entries report [unavailable ...] via direct_chat's free-only gate.
        names = provider_names or [
            "ollama", "claude", "openai", "gemini", "kimi", "deepseek", "groq",
            "perplexity", "qwen", *sorted(self.custom),
        ]
        results = {}

        def _query_one(name: str) -> Tuple[str, str]:
            try:
                text, _ = self.direct_chat(messages, name)
                return name, text
            except ProviderError as error:
                return name, f"[unavailable: {error}]"

        with ThreadPoolExecutor(max_workers=len(names)) as executor:
            for name, text in executor.map(_query_one, names):
                results[name] = text

        return results

    def _candidate_chain(self) -> List[Provider]:
        """Build the ordered list of providers to try for one request.

        Primary first, then local Ollama, then the free-first online order. The
        chain is deduplicated and filtered to providers that report themselves
        available, so a single broken provider can never end the request while a
        working one is still sitting behind it.
        """
        chain: List[Provider] = []
        seen: set[int] = set()

        def _add(provider: Optional[Provider]) -> None:
            if provider is None or id(provider) in seen:
                return
            seen.add(id(provider))
            chain.append(provider)

        # A failure to pick a *primary* is not a failure to build a chain: the
        # loops below can still find a usable provider. Letting this propagate
        # made the far more actionable "no chat provider is available" message
        # in chat() unreachable dead code, and surfaced "no internet connection
        # detected" for what was really a missing-API-key problem.
        kahuna = self.providers.get(_IDENTITY0)
        if kahuna is not None:
            try:
                if kahuna.is_available():
                    _add(kahuna)
            except Exception:  # pragma: no cover - never let the new brain block the old chain
                pass

        try:
            _add(self._get_primary_provider())
        except ProviderError as error:
            _log_event(f"no primary provider: {str(error)[:90]}", "router", ok=False)

        if self.ollama.is_available():
            _add(self.ollama)

        if self._online_available():
            for name in self._online_order():
                candidate = self.providers.get(name)
                if candidate is not None and candidate.is_available():
                    _add(candidate)

        return chain

    def chat(self, messages: List[Dict[str, str]]) -> Tuple[str, str]:
        """Route a chat request through every available provider in turn.

        Previously this tried the primary and exactly one fallback, so a single
        misconfigured provider (a retired model name, an expired key) collapsed the
        whole request into the offline canned reply even when other working
        providers were configured. Now the full chain is walked before giving up.

        Returns:
            A tuple of (response_text, provider_name)
        """
        chain = self._candidate_chain()
        if not chain:
            raise ProviderError(
                "No chat provider is available. Configure a key in .env.local, or "
                "start Ollama for local inference."
            )

        failures: List[str] = []
        for provider in chain:
            start_time = time.time()
            try:
                payload = messages if getattr(provider, "supports_vision", False) else _without_images(messages)
                response = provider.chat(payload)
                latency = time.time() - start_time
                GLOBAL_METRICS.record(
                    provider=provider.name,
                    latency_seconds=latency,
                    success=True,
                )
                _log_event(f"{provider.name} answered in {latency:.2f}s", "router", ok=True)
                return response, provider.name
            except ProviderError as error:
                GLOBAL_METRICS.record(
                    provider=provider.name,
                    latency_seconds=time.time() - start_time,
                    success=False,
                    error_message=str(error),
                )
                failures.append(f"{provider.name}: {error}")
                _log_event(f"{provider.name} failed: {str(error)[:90]}", "router", ok=False)

        raise ProviderError(
            "Every available provider failed. " + " | ".join(failures)
        )

    def stream(
        self,
        messages: List[Dict[str, Any]],
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
        *,
        smart: bool = False,
        thinking: bool = True,
        cancelled: Optional[Callable[[], bool]] = None,
        prefer: Optional[str] = None,
        exclude: Optional[List[str]] = None,
        prefer_model: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Route one request like :meth:`chat`, streaming as the reply forms.

        ``on_event`` receives ``{"type": "provider", "name", "model"}`` when an
        attempt starts, ``{"type": "text" | "thought", "text"}`` as it arrives, and
        ``{"type": "reset"}`` when an attempt that had already produced text
        fails and the next provider starts over.

        Two routing rules on top of the normal chain:

        * **A turn with images prefers providers that can see them.** A text-only
          model handed a screenshot would answer confidently about nothing.
        * **``smart`` turns try the stronger Gemini model first** and fall back to
          the fast one on the same key before moving to another provider, so a
          busy smart model costs a retry, not the turn.
        * **``prefer`` goes first** — the provider the owner picked in the chat's
          dropdown. When it cannot answer, ``{"type": "provider.unavailable",
          "name", "reason"}`` says why before the chain moves on, so the UI can
          tell the owner instead of quietly answering with someone else.
        * **``exclude``** drops providers for this call (a retry after an empty reply).
        * **``prefer_model``** is the model to ask the preferred provider for (an agent's
          own model from its Properties); other providers use their defaults.
        """
        emit = on_event or (lambda _event: None)
        chain = self._candidate_chain()
        if exclude:
            # Never fall back to Identity 0 when it is the caller: that would be a loop.
            chain = [p for p in chain if p.name not in set(exclude)] or [
                p for p in chain if p.name != _IDENTITY0 or _IDENTITY0 not in exclude]
        wanted = (prefer or "").strip().lower()
        if wanted:
            reason = self.unavailable_reason(wanted, explicit=True)
            if reason:
                emit({"type": "provider.unavailable", "name": wanted, "reason": reason})
            else:
                picked = self.providers[wanted]
                chain = [picked] + [p for p in chain if p is not picked]
        if not chain:
            raise ProviderError(
                "No chat provider is available. Configure a key in .env.local, or "
                "start Ollama for local inference."
            )

        wants_vision = any(m.get("images") for m in messages if isinstance(m, dict))
        if wants_vision:
            # Stable sort: the preferred provider stays first among those that can see.
            chain.sort(key=lambda p: 0 if getattr(p, "supports_vision", False) else 1)

        attempts: List[Tuple[Provider, Optional[str]]] = []
        pinned_model = (prefer_model or "").strip() or None
        for provider in chain:
            if pinned_model and wanted and provider.name == wanted:
                attempts.append((provider, pinned_model))
                continue
            smart_model = getattr(SETTINGS, "gemini_smart_model", "") if provider.name == "gemini" else ""
            if (
                smart and smart_model and smart_model != getattr(SETTINGS, "gemini_model", "")
                and _SMART_COOLDOWN.get(smart_model, 0.0) <= time.time()
            ):
                attempts.append((provider, smart_model))
            attempts.append((provider, None))

        failures: List[str] = []
        for provider, model in attempts:
            if cancelled is not None and cancelled():
                raise ProviderError("Stopped.")
            prepared = messages if getattr(provider, "supports_vision", False) else _without_images(messages)
            emit({"type": "provider", "name": provider.name, "model": model or ""})
            produced = False
            parts: List[str] = []
            start_time = time.time()
            try:
                keys = _key_plan(provider.name)
                for index, key in enumerate(keys or [None]):
                    key_name = _key_name(provider.name)
                    if key:
                        _use_key(key_name, key)
                    try:
                        for event in provider.stream_events(prepared, model=model, thinking=thinking):
                            if cancelled is not None and cancelled():
                                raise ProviderError("Stopped.")
                            kind = event.get("type")
                            if kind == "reset":
                                # A planner provider (Identity 0) switched members mid-answer.
                                parts.clear()
                                emit({"type": "reset"})
                                continue
                            if kind == "member":
                                emit({"type": "provider", "name": provider.name, "model": event.get("model", "")})
                                continue
                            text = event.get("text", "")
                            if not text:
                                continue
                            produced = True
                            if kind == "text":
                                parts.append(text)
                            emit({"type": kind, "text": text})
                    except ProviderError as key_error:
                        if str(key_error) == "Stopped.":
                            raise
                        failed_kind = _report_key(key_name, key, ok=False, error=str(key_error))
                        if failed_kind in ("auth", "payment", "quota") and index + 1 < len(keys) and not produced:
                            emit({"type": "key.failover", "name": provider.name, "kind": failed_kind})
                            _log_event(f"{provider.name} key failed ({failed_kind}); trying its next key", "router", ok=False)
                            continue
                        raise
                    _report_key(key_name, key, ok=True)
                    break
                latency = time.time() - start_time
                GLOBAL_METRICS.record(provider=provider.name, latency_seconds=latency, success=True)
                _RECENT_FAILURE.pop(provider.name, None)
                label = f"{provider.name}{'/' + model if model else ''}"
                _log_event(f"{label} streamed in {latency:.2f}s", "router", ok=True)
                return "".join(parts), provider.name
            except ProviderError as error:
                if str(error) == "Stopped.":
                    raise
                GLOBAL_METRICS.record(
                    provider=provider.name,
                    latency_seconds=time.time() - start_time,
                    success=False,
                    error_message=str(error),
                )
                label = f"{provider.name}{' (' + model + ')' if model else ''}"
                failures.append(f"{label}: {error}")
                if not model:
                    _RECENT_FAILURE[provider.name] = time.time() + _RECENT_FAILURE_SECONDS
                if model:
                    # The optional smart model failed (overloaded, timed out):
                    # stop offering it to every turn for a while, so the next
                    # turns go straight to the model that answers.
                    _SMART_COOLDOWN[model] = time.time() + _SMART_COOLDOWN_SECONDS
                _log_event(f"{label} failed: {str(error)[:90]}", "router", ok=False)
                emit({"type": "attempt.failed", "name": provider.name, "model": model or "", "error": str(error)[:240]})
                if produced:
                    emit({"type": "reset"})
                if getattr(error, "chain_exhausted", False):
                    # Big Kahuna's own inner call already went through every provider: don't try them all again.
                    break

        raise ProviderError("Every available provider failed. " + " | ".join(failures))

    def get_status(self) -> Dict[str, Any]:
        """Return the current routing and hardware health status for debugging."""
        safety_status = SAFETY_MONITOR.get_hardware_status()
        # Probe connectivity once. This used to be called twice in the same
        # response — for "online" and again inside "web_access_available" — which
        # paid two network round trips for one fact and made /api/status take
        # roughly two seconds.
        online = is_online()
        return {
            "device_tier": self.device_tier.name,
            "device_profile": {
                "os": self.device_profile.operating_system,
                "cpu": self.device_profile.cpu_name,
                "cpu_cores": self.device_profile.cpu_cores,
                "ram_gb": self.device_profile.ram_gb,
                "gpu": self.device_profile.gpu_name,
                "vram_gb": self.device_profile.vram_gb,
                "max_workers": self.device_profile.max_workers,
                "power_mode": self.device_profile.recommended_power_mode,
            },
            "hardware_health": {
                "gpu_temp_c": safety_status.gpu_temp,
                "vram_used_mb": safety_status.vram_used_mb,
                "vram_total_mb": safety_status.vram_total_mb,
                "disk_free_gb": safety_status.disk_free_gb,
                "throttled": safety_status.throttle_recommended,
            },
            "online": online,
            "web_access_enabled": self.web_access_enabled,
            "web_access_available": self.web_access_enabled and online,
            "free_only": SETTINGS.free_only,
            "identity0_available": bool(self.providers.get(_IDENTITY0) and self.providers[_IDENTITY0].is_available()),
            "ollama_available": self.ollama.is_available(),
            "perplexity_available": self.perplexity.is_available(),
            "claude_available": self.claude.is_available(),
            "openai_available": self.openai.is_available(),
            "gemini_available": self.gemini.is_available(),
            "kimi_available": self.kimi.is_available(),
            "deepseek_available": self.deepseek.is_available(),
            "groq_available": self.groq.is_available(),
            "nvidia_available": self.nvidia.is_available(),
            "qwen_available": self.qwen.is_available(),
            "custom_providers": [
                {
                    "name": name,
                    "label": provider.label,
                    "free": provider.is_free,
                    "available": provider.is_available(),
                }
                for name, provider in sorted(self.custom.items())
            ],
            "preferred_online_provider": SETTINGS.preferred_online_provider,
            "metrics": GLOBAL_METRICS.get_summary(),
        }
