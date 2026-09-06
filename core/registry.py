"Capability registry for optional image, voice, translation, and reading extensions."""

from __future__ import annotations
from .contracts import Capability, CapabilityProvider, CapabilityResult, ChatRequest
class CapabilityRegistry:
    def __init__(self) -> None:
        self._providers: dict[Capability, list[CapabilityProvider]] = {}
    def register(self, provider: CapabilityProvider) -> None:
        self._providers.setdefault(provider.capability, []).append(provider)
    def providers_for(self, capability: Capability) -> list[CapabilityProvider]:
        return list(self._providers.get(capability, []))
    def available(self, capability: Capability) -> list[CapabilityProvider]:
        return [provider for provider in self.providers_for(capability) if provider.is_available()]
    def execute(self, capability: Capability, request: ChatRequest) -> CapabilityResult:
        providers = self.available(capability)
        if not providers:
            return CapabilityResult(capability=capability, status="unavailable", error=f"No provider registered for {capability.value}.")
        try:
            return providers[0].execute(request)
        except Exception as error:
            return CapabilityResult(capability=capability, status="error", error=str(error))
    def capabilities(self) -> dict[str, int]:
        return {capability.value: len(providers) for capability, providers in self._providers.items()}
REGISTRY = CapabilityRegistry()
