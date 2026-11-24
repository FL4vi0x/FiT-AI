"""A deterministic engine for tests and development: no model, no CPU load, no dependency."""
from __future__ import annotations

import threading
import time

from fit_ai.speech.audio import PcmAudio
from fit_ai.speech.errors import STTFailed
from fit_ai.speech.provider import ProviderAvailability


class FakeSTTProvider:
    name = "fake"
    model_label = "fake"

    def __init__(self, text: str = "fit, qual é a temperatura do motor?", *, delay_s: float = 0.0, fail: bool = False,
                 state: str = "available", block: threading.Event | None = None):
        self.text, self.delay_s, self.fail, self.state, self.block = text, delay_s, fail, state, block
        self.calls: list[tuple[float, str]] = []  # (duration_s, language): never the audio
        self.cancelled_seen = False
        self.started = threading.Event()
        self.finished = threading.Event()

    def availability(self) -> ProviderAvailability:
        return ProviderAvailability(self.state)  # type: ignore[arg-type]

    def transcribe(self, audio: PcmAudio, language: str, cancel: threading.Event) -> str:
        self.calls.append((audio.duration_s, language))
        self.started.set()
        try:
            if self.block is not None:
                self.block.wait(10)
            deadline = time.monotonic() + self.delay_s
            while time.monotonic() < deadline:
                if cancel.is_set():
                    self.cancelled_seen = True
                    return ""
                time.sleep(0.005)
            if self.fail:
                raise STTFailed()
            return self.text
        finally:
            self.finished.set()
