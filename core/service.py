"""Backend-facing facade that keeps UI and API adapters independent from ChatService internals."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict

from .contracts import Capability, ChatRequest, ChatResponse
from .registry import REGISTRY


class AssistantService:
    """Facade for dispatching chat requests and managing pluggable capability extensions."""

    def __init__(self, chat_service: Any):
        self.chat_service = chat_service

    def handle(self, request: ChatRequest) -> ChatResponse:
        """Process a standardized ChatRequest and return a ChatResponse."""
        if hasattr(self.chat_service, "router"):
            self.chat_service.router.set_web_access(request.web_access)

        # Append attachment context if present
        augmented_message = request.message
        if request.attachments:
            attachment_notes = []
            for att in request.attachments:
                if att.text_content:
                    attachment_notes.append(f"[{att.attachment_type.value.upper()}: {att.name}]\n{att.text_content}")
                elif att.uri:
                    attachment_notes.append(f"[{att.attachment_type.value.upper()}: {att.name}] -> {att.uri}")
            if attachment_notes:
                augmented_message = "\n\n".join(attachment_notes) + "\n\n" + augmented_message

        response, provider = self.chat_service.chat(augmented_message)
        return ChatResponse(
            answer=response,
            provider=provider,
            mode=request.mode,
            metadata={"request": asdict(request)},
        )

    def capability_status(self) -> Dict[str, int]:
        """Report registered capability counts."""
        return REGISTRY.capabilities()

    def execute_capability(self, capability: Capability, request: ChatRequest):
        """Execute a specific capability (e.g. OCR, speech, translation)."""
        return REGISTRY.execute(capability, request)
