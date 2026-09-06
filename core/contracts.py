"""Stable contracts and future-proof attachment models for Nyx Ichos."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Dict, List, Optional


class Capability(StrEnum):
    """Extensible capability flags for multimodal extensions."""

    TEXT = "text"
    WEB = "web"
    IMAGE = "image"
    VOICE = "voice"
    TRANSLATION = "translation"
    READING = "reading"
    CONNECTOR = "connector"
    EXECUTION = "execution"
    CODE_ANALYSIS = "code_analysis"


class AttachmentType(StrEnum):
    """Types of modular attachments supported by the assistant."""

    IMAGE = "image"
    DOCUMENT = "document"
    CODE_SNIPPET = "code_snippet"
    CONNECTOR_RESOURCE = "connector_resource"  # Google Docs, Gmail, etc.
    TRANSLATION_SNIPPET = "translation_snippet"
    GENERIC = "generic"


@dataclass(slots=True)
class Attachment:
    """Base attachment model for rich multimodal inputs."""

    name: str
    attachment_type: AttachmentType = AttachmentType.GENERIC
    content_bytes: Optional[bytes] = None
    text_content: Optional[str] = None
    mime_type: str = "text/plain"
    uri: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChatRequest:
    """Standardized request envelope for conversations across CLI, API, and extensions."""

    message: str
    mode: str = "auto"
    approach: str = "auto"
    web_access: bool = True
    conversation_id: Optional[str] = None
    attachments: List[Attachment] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Source:
    """Attribution metadata for retrieved knowledge or web sources."""

    url: str
    title: str = ""
    published_at: Optional[str] = None
    accessed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    domain: str = ""
    corroborated: bool = True


@dataclass(slots=True)
class ChatResponse:
    """Standardized response envelope returned by the assistant core."""

    answer: str
    provider: str = ""
    mode: str = "auto"
    status: str = "complete"
    sources: List[Source] = field(default_factory=list)
    capabilities_used: List[Capability] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CapabilityResult:
    """Result returned by a pluggable capability provider."""

    capability: Capability
    status: str = "not_implemented"
    content: Any = None
    error: Optional[str] = None


class CapabilityProvider:
    """Extension interface for future multimodal plugins (voice, OCR, connectors, etc.)."""

    capability: Capability

    def is_available(self) -> bool:
        """Check whether the capability runtime/dependencies are present."""
        return False

    def execute(self, request: ChatRequest) -> CapabilityResult:
        """Execute the capability against the given request envelope."""
        raise NotImplementedError
