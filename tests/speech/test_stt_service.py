import asyncio
import logging
import threading
import time

import pytest

from fit_ai.speech.config import SpeechSettings
from fit_ai.speech.errors import (AudioEmpty, InvalidAudio, STTBusy, STTDisabled, STTFailed, STTModelMissing, STTTimeout,
                                  STTUnavailable)
from fit_ai.speech.fake_provider import FakeSTTProvider
from fit_ai.speech.service import INSTALL_HINT, SpeechService

from .wavs import make_wav

SPOKEN = make_wav(1.5)  # a loud tone: above the silence gate
SECRET_TEXT = "texto-privado-do-usuario"

pytestmark = pytest.mark.anyio


def service(provider=None, **settings):
    p = provider or FakeSTTProvider(SECRET_TEXT)
    return SpeechService(p, SpeechSettings(**settings)), p


async def test_transcribes_and_reports_numbers_only():
    svc, provider = service()
    out = await svc.transcribe(SPOKEN, "rid1")
    assert out.text == SECRET_TEXT and not out.silent and out.duration_s == 1.5 and out.language == "pt"
    assert provider.calls == [(1.5, "pt")]
    await svc.close()


async def test_text_is_normalised_and_bounded():
    svc, _ = service(FakeSTTProvider("  uma   frase \n com\tespaços  "))
    assert (await svc.transcribe(SPOKEN)).text == "uma frase com espaços"
    svc, _ = service(FakeSTTProvider("a " * 5000))
    assert len((await svc.transcribe(SPOKEN)).text) <= 2000


async def test_silence_never_reaches_the_engine():
    svc, provider = service()
    out = await svc.transcribe(make_wav(pcm=bytes(48000)), "rid")
    assert out.silent and out.text == "" and out.processing_ms == 0
    assert provider.calls == []


async def test_a_quiet_but_real_signal_is_transcribed():
    svc, provider = service()
    await svc.transcribe(make_wav(1.0, amplitude=0.02))
    assert len(provider.calls) == 1


async def test_invalid_audio_never_reaches_the_engine():
    svc, provider = service()
    for bad, error in ((b"", AudioEmpty), (b"hello", InvalidAudio), (make_wav(1.0, rate=44100), InvalidAudio)):
        with pytest.raises(error):
            await svc.transcribe(bad)
    assert provider.calls == []


async def test_disabled_installation():
    svc, provider = service(enabled=False)
    with pytest.raises(STTDisabled):
        await svc.transcribe(SPOKEN)
    assert svc.status().state == "disabled" and provider.calls == []


@pytest.mark.parametrize("state, error", [("model_missing", STTModelMissing), ("engine_missing", STTUnavailable)])
async def test_missing_model_or_engine(state, error):
    svc, provider = service(FakeSTTProvider(state=state))
    with pytest.raises(error):
        await svc.transcribe(SPOKEN)
    st = svc.status()
    assert st.state == state and st.hint == INSTALL_HINT and provider.calls == []


async def test_status_when_available_has_no_hint_and_loads_nothing():
    svc, provider = service()
    st = svc.status()
    assert (st.state, st.hint, st.language, st.sample_rate) == ("available", None, "pt", 16000) and provider.calls == []


async def test_engine_failure_is_a_typed_error_without_detail():
    svc, _ = service(FakeSTTProvider(fail=True))
    with pytest.raises(STTFailed):
        await svc.transcribe(SPOKEN)


async def test_unexpected_exception_from_the_engine_is_sanitised():
    class Boom(FakeSTTProvider):
        def transcribe(self, audio, language, cancel):
            raise RuntimeError(r"C:\Users\someone\secret\model.bin exploded")

    svc, _ = service(Boom())
    with pytest.raises(STTFailed) as e:
        await svc.transcribe(SPOKEN)
    assert "secret" not in str(e.value)


async def test_only_one_transcription_at_a_time():
    gate = threading.Event()
    svc, provider = service(FakeSTTProvider("ok", block=gate))
    first = asyncio.create_task(svc.transcribe(SPOKEN))
    while not provider.started.is_set():
        await asyncio.sleep(0.005)
    with pytest.raises(STTBusy):
        await svc.transcribe(SPOKEN)
    gate.set()
    assert (await first).text == "ok"
    assert (await svc.transcribe(SPOKEN)).text == "ok"  # the slot is free again
    await svc.close()


async def test_timeout_cancels_and_keeps_the_slot_until_the_engine_really_stops():
    svc, provider = service(FakeSTTProvider("late", delay_s=0.4), timeout_s=5.0)
    svc._settings = SpeechSettings(timeout_s=5.0)  # validated range is >= 5 s; shrink it for the test only
    object.__setattr__(svc._settings, "timeout_s", 0.1)
    with pytest.raises(STTTimeout):
        await svc.transcribe(SPOKEN)
    # the abandoned call is still running: a new request must be refused, not piled onto the same CPU
    with pytest.raises(STTBusy):
        await svc.transcribe(SPOKEN)
    assert await asyncio.to_thread(provider.finished.wait, 3)
    await asyncio.sleep(0.05)
    assert provider.cancelled_seen  # the engine was told to stop between decoding steps
    object.__setattr__(svc._settings, "timeout_s", 5.0)
    provider.delay_s = 0
    assert (await svc.transcribe(SPOKEN)).text == "late"
    await svc.close()


async def test_client_disconnect_cancels_the_engine_and_frees_the_slot():
    svc, provider = service(FakeSTTProvider("x", delay_s=2.0))
    task = asyncio.create_task(svc.transcribe(SPOKEN))
    while not provider.started.is_set():
        await asyncio.sleep(0.005)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await asyncio.to_thread(provider.finished.wait, 3) and provider.cancelled_seen
    await asyncio.sleep(0.05)
    provider.delay_s = 0
    assert (await svc.transcribe(SPOKEN)).text == "x"
    await svc.close()


async def test_the_event_loop_is_not_blocked_while_the_engine_works():
    svc, provider = service(FakeSTTProvider("ok", delay_s=0.3))
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    t = asyncio.create_task(ticker())
    await svc.transcribe(SPOKEN)
    t.cancel()
    assert ticks >= 15  # ~30 expected: the loop kept running while the worker thread worked
    await svc.close()


async def test_logs_carry_numbers_never_the_transcript(caplog):
    caplog.set_level(logging.DEBUG)
    svc, _ = service()
    await svc.transcribe(SPOKEN, "rid-42")
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "rid-42" in logged and "24" in logged  # request id, 24 characters
    assert SECRET_TEXT not in logged and "texto" not in logged


async def test_audio_is_never_written_anywhere(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TMP", str(tmp_path))
    monkeypatch.setenv("TEMP", str(tmp_path))
    svc, _ = service()
    await svc.transcribe(SPOKEN)
    await svc.close()
    assert list(tmp_path.rglob("*")) == []  # no temp file, no cache, no database


async def test_no_database_or_model_client_is_imported_by_the_speech_package():
    import fit_ai.speech.service as mod
    source = open(mod.__file__, encoding="utf-8").read()
    assert "sqlite" not in source and "ollama" not in source.lower() and "open(" not in source
