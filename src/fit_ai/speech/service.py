"""The speech-to-text service: validation, one-at-a-time concurrency, timeout and cancellation around an STTProvider.

Privacy by design: the audio exists only as bytes in this request; it is never written to disk or to SQLite, never sent to the language
model, never logged. Logs carry numbers only (duration, milliseconds, character count), never the transcript."""
from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Literal

from fit_ai.speech.audio import SAMPLE_RATE, PcmAudio, parse_wav
from fit_ai.speech.config import SpeechSettings
from fit_ai.speech.errors import STTBusy, STTDisabled, STTFailed, STTModelMissing, STTTimeout, STTUnavailable
from fit_ai.speech.provider import STTProvider

log = logging.getLogger("fit_ai.speech")

VoiceState = Literal["available", "disabled", "model_missing", "engine_missing"]
MAX_TEXT_CHARS = 2000
INSTALL_HINT = "Instale o motor e o modelo conforme docs/poc-09-01-local-stt.md (modelo em runtime/stt-models ou em FIT_AI_STT_MODEL_DIR)."


@dataclass(frozen=True)
class VoiceStatus:
    state: VoiceState
    language: str
    max_audio_s: float
    sample_rate: int
    hint: str | None


@dataclass(frozen=True)
class Transcript:
    text: str
    silent: bool  # nothing loud enough was captured: the engine was NOT run
    duration_s: float
    processing_ms: int
    language: str
    model: str


class SpeechService:
    def __init__(self, provider: STTProvider, settings: SpeechSettings):
        self._provider, self._settings = provider, settings
        self._slot = asyncio.Semaphore(1)  # one transcription at a time: it is CPU-bound and the same CPU runs the language model
        self._executor: ThreadPoolExecutor | None = None

    # ------------------------------------------------------------------ status (never loads a model)
    def status(self) -> VoiceStatus:
        s = self._settings
        if not s.enabled:
            return VoiceStatus("disabled", s.language, s.max_audio_s, SAMPLE_RATE, None)
        availability = self._provider.availability()
        hint = None if availability.state == "available" else INSTALL_HINT
        return VoiceStatus(availability.state, s.language, s.max_audio_s, SAMPLE_RATE, hint)

    # ------------------------------------------------------------------ transcription
    async def transcribe(self, body: bytes, request_id: str = "-") -> Transcript:
        s = self._settings
        if not s.enabled:
            raise STTDisabled()
        audio = parse_wav(body, max_bytes=s.max_body_bytes, max_duration_s=s.max_audio_s)
        if audio.peak < s.min_peak:
            log.info("voice request %s: %.1fs of silence, engine not run", request_id, audio.duration_s)
            return Transcript("", True, audio.duration_s, 0, s.language, self._provider.model_label)
        availability = self._provider.availability()
        if availability.state == "engine_missing":
            raise STTUnavailable()
        if availability.state == "model_missing":
            raise STTModelMissing()
        if self._slot.locked():
            raise STTBusy()
        await self._slot.acquire()
        started = time.perf_counter()
        text = await self._run(audio)
        ms = round((time.perf_counter() - started) * 1000)
        text = re.sub(r"\s+", " ", text).strip()[:MAX_TEXT_CHARS]
        log.info("voice request %s: %.1fs audio, %d ms, %d characters", request_id, audio.duration_s, ms, len(text))  # never the text
        return Transcript(text, False, audio.duration_s, ms, s.language, self._provider.model_label)

    async def _run(self, audio: PcmAudio) -> str:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")
        loop = asyncio.get_running_loop()
        cancel = threading.Event()
        future = loop.run_in_executor(self._executor, self._provider.transcribe, audio, self._settings.language, cancel)
        # The slot is released only when the worker thread REALLY returns: an abandoned (timed-out or disconnected) call keeps running
        # inside the engine for a while, and a second one must not pile onto the same CPU meanwhile.
        future.add_done_callback(lambda f: (self._slot.release(), f.cancelled() or f.exception()))
        try:
            return await asyncio.wait_for(asyncio.shield(future), self._settings.timeout_s)
        except TimeoutError:
            cancel.set()
            raise STTTimeout() from None
        except asyncio.CancelledError:  # the client went away
            cancel.set()
            raise
        except (STTFailed, STTModelMissing, STTUnavailable):
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("speech provider raised %s", type(exc).__name__)
            raise STTFailed() from None

    async def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
