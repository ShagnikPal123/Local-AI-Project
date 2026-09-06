"""Intelligent request router that selects providers based on device capability, network state, and hardware safety."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

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
from providers.ollama_provider import OllamaProvider
from providers.openai_provider import OpenAIProvider
from providers.perplexity_provider import PerplexityProvider

# Providers that hit paid APIs; excluded from selection by default so the
# assistant never auto-routes to a paid model without an explicit opt-in.
_PAID_PROVIDERS = {"claude", "openai", "kimi", "deepseek", "perplexity"}
# Free-first online order (gemini and groq both have free tiers).
_FREE_FIRST_ORDER = ("gemini", "groq", "claude", "openai", "kimi", "deepseek", "perplexity")
# Names owned by the shipped providers; a user-added spec may not take one.
_BUILTIN_ROUTER_NAMES = frozenset(("ollama", *_FREE_FIRST_ORDER))


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
        self.providers: Dict[str, Provider] = {
            "ollama": self.ollama,
            "claude": self.claude,
            "openai": self.openai,
            "gemini": self.gemini,
            "kimi": self.kimi,
            "deepseek": self.deepseek,
            "groq": self.groq,
            "perplexity": self.perplexity,
        }
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
        """Provider names that cost money, built-in and user-added alike.

        A user-added provider declares this itself: a spec flagged is_free is
        treated like Gemini or Groq, and anything else like Claude or OpenAI.
        Free-only mode has to hold for providers nobody had heard of when it
        was written, or it is not a spending guarantee at all.
        """
        return set(_PAID_PROVIDERS) | {
            name for name, provider in self.custom.items() if not provider.is_free
        }

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
        custom_free = sorted(n for n, p in self.custom.items() if p.is_free)
        custom_paid = sorted(n for n, p in self.custom.items() if not p.is_free)
        order = [preferred]
        order += [name for name in _FREE_FIRST_ORDER if name != preferred]
        order += [name for name in (*custom_free, *custom_paid) if name != preferred]
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

    def direct_chat(self, messages: List[Dict[str, str]], provider_name: str) -> Tuple[str, str]:
        """Talk to one named agent without changing local-first routing policy."""
        if provider_name not in self.providers:
            raise ProviderError(f"Unknown provider: {provider_name}")
        if SETTINGS.free_only and provider_name in self._paid_names():
            raise ProviderError(
                f"{provider_name} is a paid provider and free-only mode is on "
                "(set FREE_ONLY=false in .env.local to enable paid models)."
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
            "perplexity", *sorted(self.custom),
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
                response = provider.chat(messages)
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
            "ollama_available": self.ollama.is_available(),
            "perplexity_available": self.perplexity.is_available(),
            "claude_available": self.claude.is_available(),
            "openai_available": self.openai.is_available(),
            "gemini_available": self.gemini.is_available(),
            "kimi_available": self.kimi.is_available(),
            "deepseek_available": self.deepseek.is_available(),
            "groq_available": self.groq.is_available(),
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
