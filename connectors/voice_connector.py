"""Voice connector: talk back, listen, voice selection, and voice ID scans.

Wraps the local voice engine (Windows SAPI TTS/STT + ffmpeg capture + spectral
voiceprint) behind the standard connector interface so the CLI, tools, and the
App/Web API all share one path.
"""

from __future__ import annotations

from typing import Any, Dict

from connectors.base import BaseConnector, ConnectorManifest


class VoiceConnector(BaseConnector):
    """Speak, listen, choose voices, and run voice-ID scans."""

    def __init__(self) -> None:
        self._manifest = ConnectorManifest(
            name="voice",
            description=(
                "Talk back (TTS), listen (STT), list/select voices, and run "
                "voice-ID scans. Local-only, no cloud keys."
            ),
            permissions=["read", "audio"],
            is_offline=True,
            requires_auth=False,
            is_write=False,
            risk_level="low",
        )

    @property
    def manifest(self) -> ConnectorManifest:
        return self._manifest

    def is_available(self) -> bool:
        """Voice is available unless explicitly disabled via env."""
        return True

    def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        import voice

        if action == "speak":
            return {"success": True, "message": voice.speak(params.get("text", ""), voice=params.get("voice"))}
        if action == "stop_speaking":
            return {"success": True, "message": voice.stop_speaking()}
        if action == "listen":
            text = voice.listen(timeout=int(params.get("timeout", 10)))
            return {"success": True, "text": text}
        if action == "list_voices":
            return {"success": True, "voices": voice.list_voices()}
        if action == "set_voice":
            return {"success": True, "message": voice.set_voice(params.get("name", ""))}
        if action == "get_voice":
            return {"success": True, "voice": voice.get_voice()}
        if action == "voice_scan":
            mode = params.get("mode", "status")
            if mode == "enroll":
                return voice.enroll_voice(label=params.get("label", "user"), duration=float(params.get("duration", 3.0)))
            if mode == "verify":
                return voice.verify_voice(duration=float(params.get("duration", 3.0)))
            return {"success": True, **voice.voice_status()}
        if action == "status":
            return {"success": True, **voice.voice_status()}
        return {"success": False, "error": f"Unknown action '{action}' for voice connector."}
