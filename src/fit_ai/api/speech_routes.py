"""HTTP layer of local speech recognition: a read-only status and one transcription route. All logic lives in SpeechService.

The request body is the audio itself (Content-Type audio/wav, 16 kHz mono 16-bit PCM). There is no filename, no path, no URL, no model
or language parameter: what the engine loads and which language it listens for are the installer's decisions, never the request's."""
from __future__ import annotations

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from fit_ai.speech.errors import SpeechError, STTBusy, STTUnavailable

log = logging.getLogger("fit_ai.api.speech")

STATUS_BY_CODE = {
    "invalid_audio": 422,
    "audio_empty": 422,
    "audio_too_short": 422,
    "audio_too_long": 413,
    "stt_busy": 429,
    "stt_timeout": 504,
    "stt_failed": 502,
    "stt_disabled": 503,
    "stt_unavailable": 503,
    "stt_model_missing": 503,
}
NO_STORE = {"Cache-Control": "no-store"}  # a transcript is private: nothing may cache it


class VoiceStatusResponse(BaseModel):
    state: Literal["available", "disabled", "model_missing", "engine_missing", "unavailable"]
    language: str | None
    max_audio_s: float | None
    sample_rate: int | None
    hint: str | None


class TranscribeResponse(BaseModel):
    text: str
    silent: bool
    duration_s: float
    processing_ms: int
    language: str
    model: str


router = APIRouter(tags=["voice"])


def _request_id(request: Request) -> str:
    return request.scope.get("state", {}).get("request_id") or uuid.uuid4().hex


@router.get("/api/v1/voice/status", response_model=VoiceStatusResponse)
async def voice_status(request: Request, response: Response) -> VoiceStatusResponse:
    """Whether speech recognition can run. Read-only: it never opens the microphone and never loads a model."""
    response.headers.update(NO_STORE)
    service = getattr(request.app.state, "speech_service", None)
    if service is None:
        return VoiceStatusResponse(state="unavailable", language=None, max_audio_s=None, sample_rate=None, hint=None)
    s = service.status()
    return VoiceStatusResponse(state=s.state, language=s.language, max_audio_s=s.max_audio_s, sample_rate=s.sample_rate, hint=s.hint)


@router.post("/api/v1/voice/transcribe", response_model=TranscribeResponse)
async def transcribe(request: Request, response: Response) -> TranscribeResponse:
    """Transcribe one utterance. The audio is processed in memory and discarded; the response carries the text and a few numbers."""
    response.headers.update(NO_STORE)
    service = getattr(request.app.state, "speech_service", None)
    if service is None:
        raise STTUnavailable()
    body = await request.body()  # the size is already capped by BrowserGuard (header and stream); the service validates it again
    result = await service.transcribe(body, _request_id(request))
    return TranscribeResponse(text=result.text, silent=result.silent, duration_s=result.duration_s,
                              processing_ms=result.processing_ms, language=result.language, model=result.model)


async def speech_error_handler(request: Request, exc: SpeechError) -> JSONResponse:
    headers = dict(NO_STORE)
    if isinstance(exc, STTBusy):
        headers["Retry-After"] = str(exc.retry_after_s)
    return JSONResponse(status_code=STATUS_BY_CODE.get(exc.code, 500), headers=headers,
                        content={"error": {"code": exc.code, "message": exc.safe_message}, "request_id": _request_id(request)})


def install_speech(app: FastAPI) -> None:
    app.add_exception_handler(SpeechError, speech_error_handler)
    app.include_router(router)
