"""Core contracts and extension points for future application interfaces."""

from .contracts import Capability, ChatRequest, ChatResponse, Source, CapabilityResult
from .registry import REGISTRY, CapabilityRegistry
from .service import AssistantService
__all__ = ["Capability", "ChatRequest", "ChatResponse", "Source", "CapabilityResult", "REGISTRY", "CapabilityRegistry", "AssistantService"]
