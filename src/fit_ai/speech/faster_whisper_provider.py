"""faster-whisper (CTranslate2, int8, CPU) behind the STTProvider contract. Chosen in the P9.1 evaluation (docs/poc-09-01-local-stt.md).

Offline by construction: the model is loaded from a local directory with `local_files_only=True`, so the library can never reach a model
hub, and this module has no download code. The engine is an OPTIONAL dependency (`pip install .[stt]`): it is imported only when a
transcription is really requested, so the Core starts and serves telemetry without it.

The audio is handed to the engine as an in-memory float32 array decoded here from the validated PCM: no temporary file, and no reliance
on PyAV (faster-whisper 1.2.1 cannot open files with av 19)."""
from __future__ import annotations

import importlib.util
import logging
import threading
from pathlib import Path

from fit_ai.speech.audio import PcmAudio
from fit_ai.speech.config import SpeechSettings
from fit_ai.speech.errors import STTFailed, STTModelMissing, STTUnavailable
from fit_ai.speech.provider import ProviderAvailability

log = logging.getLogger("fit_ai.speech")

REQUIRED_FILES = ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")


class FasterWhisperProvider:
    name = "faster-whisper"

    def __init__(self, settings: SpeechSettings):
        self._settings = settings
        self._model = None
        self._load_lock = threading.Lock()
        self.model_label = settings.model_dir.name

    def availability(self) -> ProviderAvailability:
        if importlib.util.find_spec("faster_whisper") is None or importlib.util.find_spec("numpy") is None:
            return ProviderAvailability("engine_missing", "faster-whisper is not installed")
        directory: Path = self._settings.model_dir
        missing = [f for f in REQUIRED_FILES if not (directory / f).is_file()]
        if missing:
            return ProviderAvailability("model_missing", "missing model files: " + ", ".join(missing))
        return ProviderAvailability("available")

    def _load(self):
        with self._load_lock:
            if self._model is None:
                from faster_whisper import WhisperModel  # noqa: PLC0415 - optional dependency, imported on first use

                self._model = WhisperModel(str(self._settings.model_dir), device="cpu", compute_type="int8",
                                           cpu_threads=self._settings.threads, local_files_only=True)
                log.info("speech model loaded (%s, int8, %d threads)", self.model_label, self._settings.threads)
        return self._model

    def transcribe(self, audio: PcmAudio, language: str, cancel: threading.Event) -> str:
        state = self.availability()
        if state.state == "engine_missing":
            raise STTUnavailable()
        if state.state == "model_missing":
            raise STTModelMissing()
        try:
            import numpy as np  # noqa: PLC0415

            samples = np.frombuffer(audio.pcm, dtype="<i2").astype(np.float32) / 32768.0
            segments, _info = self._load().transcribe(
                samples, language=language, beam_size=self._settings.beam_size,
                initial_prompt=self._settings.initial_prompt or None)
            parts: list[str] = []
            for segment in segments:  # lazy: decoding happens here, so a cancel is honoured between segments
                if cancel.is_set():
                    return ""
                parts.append(segment.text)
            return " ".join(p.strip() for p in parts).strip()
        except (STTUnavailable, STTModelMissing):
            raise
        except Exception as exc:  # noqa: BLE001 - the engine's own failures; the cause is logged WITHOUT any text or audio
            log.error("speech engine failed: %s", type(exc).__name__)
            raise STTFailed() from None
