"""Real speech engine, real model, real transcription. Skipped automatically unless the engine and the model are installed AND a speech
WAV is provided:   FIT_AI_STT_TEST_WAV=<16 kHz mono 16-bit wav> pytest -m integration_stt

The WAV is not part of the repository (no recordings are committed). Use synthetic speech (e.g. the Windows pt-BR voice) or your own
recording; either way this checks the pipeline, it does not measure accuracy on a population of speakers."""
import asyncio
import os
import pathlib

import pytest

from fit_ai.speech.config import SpeechSettings
from fit_ai.speech.faster_whisper_provider import FasterWhisperProvider
from fit_ai.speech.service import SpeechService

pytestmark = pytest.mark.integration_stt


@pytest.fixture(scope="module")
def live():
    settings = SpeechSettings.from_env()
    provider = FasterWhisperProvider(settings)
    state = provider.availability().state
    if state != "available":
        pytest.skip(f"speech engine not ready ({state}): see docs/poc-09-01-local-stt.md")
    wav = os.environ.get("FIT_AI_STT_TEST_WAV")
    if not wav or not pathlib.Path(wav).is_file():
        pytest.skip("set FIT_AI_STT_TEST_WAV to a speech WAV to run the live transcription test")
    return SpeechService(provider, settings), pathlib.Path(wav).read_bytes()


def test_a_real_utterance_is_transcribed_in_portuguese(live):
    service, audio = live
    result = asyncio.run(service.transcribe(audio, "live"))
    assert not result.silent and result.language == "pt"
    assert len(result.text) > 3
    assert result.processing_ms > 0


def test_silence_is_not_run_through_the_engine(live):
    import struct

    service, _ = live
    silent = b"RIFF" + struct.pack("<I", 36 + 32000) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16) + b"data" + struct.pack("<I", 32000) + bytes(32000)
    result = asyncio.run(service.transcribe(silent, "live"))
    assert result.silent and result.text == "" and result.processing_ms == 0
