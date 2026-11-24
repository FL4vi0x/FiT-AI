"""The contract between the speech service and an STT engine. The service never imports an engine: it is given one."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Literal, Protocol

from fit_ai.speech.audio import PcmAudio

ProviderState = Literal["available", "model_missing", "engine_missing"]


@dataclass(frozen=True)
class ProviderAvailability:
    state: ProviderState
    detail: str = ""  # safe, no paths


class STTProvider(Protocol):
    """A synchronous, CPU-bound engine. The service runs `transcribe` on a worker thread, one call at a time, with a timeout.

    `availability()` must be cheap and must NOT load a model. `transcribe()` receives validated 16 kHz mono PCM and a `cancel`
    event: the engine should stop between decoding steps once it is set (the call that is already running cannot be interrupted
    inside the encoder, which is why the service also keeps the slot busy until the call really returns). It returns the text
    only; it must not log, store or forward the audio or the text."""

    name: str
    model_label: str

    def availability(self) -> ProviderAvailability: ...

    def transcribe(self, audio: PcmAudio, language: str, cancel: threading.Event) -> str: ...
