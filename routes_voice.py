"""HTTP routes for neural voices and per-role voices (contract §4.5).

The older ``/api/voice/status|voices|speak|listen|set|scan`` routes in
``server.py`` (SAPI on the PC, microphone, voice ID) are unchanged; these add
the browser-played neural voices.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from server_auth import RequireChat

router = APIRouter()


@router.get("/api/voice/engines")
def voice_engines(_user=RequireChat) -> Dict[str, Any]:
    import tts

    return {"engines": tts.engines()}


@router.get("/api/voice/neural-voices")
def voice_neural(locale: str = "en", refresh: bool = False, _user=RequireChat) -> Dict[str, Any]:
    import tts

    voices = tts.neural_voices(locale, refresh=refresh)
    return {"voices": voices, "count": len(voices), "windows_voices": tts.sapi_voices()}


class TTSRequest(BaseModel):
    text: str
    voice: str = ""
    role: str = ""
    rate: str = "+0%"
    pitch: str = "+0Hz"
    engine: str = ""
    #: The voice conversation this belongs to; equalize keeps the assistant's name to one introduction per session.
    session: str = "default"


@router.post("/api/voice/tts")
def voice_tts(body: TTSRequest, _user=RequireChat) -> FileResponse:
    """Synthesize and return the audio (mp3 for neural voices, wav for Windows voices)."""
    import tts
    import equalize_voice

    # A spoken reply says the assistant's own name at most once per session (equalize). A voice sample, which has
    # no role, is read exactly as written so the owner hears the voice, not an edited line.
    spoken = equalize_voice.clean(body.text, body.session or "default") if body.role == "reply" else body.text
    try:
        result = tts.synthesize(spoken, voice_id=body.voice, rate=body.rate, pitch=body.pitch,
                                engine=body.engine, role=body.role)
    except tts.TTSError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    headers = {"X-Voice": result["voice"], "X-Voice-Engine": result["engine"], "X-Audio-Key": result["key"],
               "Cache-Control": "private, max-age=86400"}
    if result["fallback"]:
        headers["X-Voice-Fallback"] = result["fallback"][:200].encode("ascii", "replace").decode()
    return FileResponse(result["path"], media_type=result["mime"], headers=headers)


@router.get("/api/voice/audio/{key}")
def voice_audio(key: str, _user=RequireChat) -> FileResponse:
    """Audio a ``voice.say`` event points at."""
    import tts

    hit = tts.cached_audio(key)
    if not hit:
        raise HTTPException(status_code=404, detail="That audio is no longer cached.")
    return FileResponse(str(hit[0]), media_type=hit[1], headers={"Cache-Control": "private, max-age=86400"})


@router.get("/api/voice/roles")
def voice_roles(_user=RequireChat) -> Dict[str, Any]:
    import tts

    return {"roles": tts.role_voices(), "defaults": tts.DEFAULT_ROLE_VOICES}


class RoleVoice(BaseModel):
    voice: str = ""


@router.put("/api/voice/roles/{role}")
def put_voice_role(role: str, body: RoleVoice, _user=RequireChat) -> Dict[str, Any]:
    import tts

    try:
        return {"roles": tts.set_role_voice(role, body.voice.strip())}
    except tts.TTSError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


class ThinkRequest(BaseModel):
    """What has been heard so far, sent every few hundred milliseconds."""

    session_id: str = ""
    text: str = ""
    final: bool = False
    chat_id: str = ""
    utterance_id: str = ""
    #: The UI's tab list, [{"id", "label"}], so spoken tab names map to real tabs.
    tabs: list[dict] = []


@router.post("/api/voice/think")
def voice_think(body: ThinkRequest, _user=RequireChat) -> Dict[str, Any]:
    """Listen along: how finished it sounds, what it means, what to get ready."""
    import voice_pipeline

    return voice_pipeline.think(body.session_id or "default", body.text, final=body.final,
                                chat_id=body.chat_id, utterance_id=body.utterance_id, tabs=body.tabs[:60])


@router.get("/api/voice/pipeline")
def voice_pipeline_state(_user=RequireChat) -> Dict[str, Any]:
    """The five voice jobs and the switches that shape them."""
    import voice_pipeline

    return {"settings": voice_pipeline.settings(), "roles": voice_pipeline.roles()}


class PipelineSettings(BaseModel):
    listening: str | None = None
    think_ahead: bool | None = None
    listen_while_speaking: bool | None = None
    smaller_panel: bool | None = None
    speak_as_written: bool | None = None
    wait_done: int | None = None
    wait_unsure: int | None = None
    wait_open: int | None = None


@router.put("/api/voice/pipeline")
def set_voice_pipeline(body: PipelineSettings, _user=RequireChat) -> Dict[str, Any]:
    import voice_pipeline

    return {"settings": voice_pipeline.update_settings(**body.model_dump(exclude_none=True))}


class SayRequest(BaseModel):
    text: str
    role: str = "reply"
    voice: str = ""


@router.post("/api/voice/say")
def voice_say(body: SayRequest, _user=RequireChat) -> Dict[str, Any]:
    """Speak through every open Nyx window (or the PC speakers if none is open)."""
    import tts

    try:
        result = tts.say(body.text, role=body.role, voice_id=body.voice)
    except tts.TTSError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {k: result[k] for k in ("key", "voice", "engine", "cached", "played_by", "fallback")}
