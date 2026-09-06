"Tests for future-proof application contracts."""

from core import Capability, ChatRequest, CapabilityRegistry
from core.contracts import CapabilityProvider, CapabilityResult
class StubVoice(CapabilityProvider):
    capability = Capability.VOICE
    def is_available(self) -> bool:
        return True
    def execute(self, request: ChatRequest) -> CapabilityResult:
        return CapabilityResult(Capability.VOICE, status="complete", content=request.message)

def test_registry_supports_optional_capabilities():
    registry = CapabilityRegistry()
    registry.register(StubVoice())
    result = registry.execute(Capability.VOICE, ChatRequest("hello"))
    assert result.status == "complete"
    assert result.content == "hello"

def test_unimplemented_capability_is_explicit():
    registry = CapabilityRegistry()
    result = registry.execute(Capability.IMAGE, ChatRequest("describe"))
    assert result.status == "unavailable"
