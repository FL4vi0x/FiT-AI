"""The real provider's own behaviour, against a FAKE `faster_whisper` module: no model, no engine, no CPU load. This is what runs in CI,
where the engine is not installed. A real-engine check lives in tests/integration/test_stt_live.py."""
import sys
import threading
import types

import pytest

pytest.importorskip("numpy")  # the provider turns PCM into a float array; numpy is part of the dev extra

from fit_ai.speech.audio import parse_wav  # noqa: E402
from fit_ai.speech.config import SpeechSettings  # noqa: E402
from fit_ai.speech.errors import STTFailed, STTModelMissing, STTUnavailable  # noqa: E402
from fit_ai.speech.faster_whisper_provider import REQUIRED_FILES, FasterWhisperProvider  # noqa: E402

from .wavs import make_wav  # noqa: E402

AUDIO = parse_wav(make_wav(1.0), max_bytes=10**7, max_duration_s=30.0)


class Seg:
    def __init__(self, text):
        self.text = text


class FakeWhisperModel:
    instances: list["FakeWhisperModel"] = []

    def __init__(self, path, **kwargs):
        self.path, self.kwargs, self.calls = path, kwargs, []
        self.segments = [" olá ", "mundo "]
        self.boom: Exception | None = None
        FakeWhisperModel.instances.append(self)

    def transcribe(self, samples, **kwargs):
        self.calls.append((samples, kwargs))
        if self.boom:
            raise self.boom
        return iter(Seg(t) for t in self.segments), object()


@pytest.fixture
def fake_engine(monkeypatch):
    FakeWhisperModel.instances = []
    module = types.ModuleType("faster_whisper")
    module.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    import importlib.util as util

    real = util.find_spec
    monkeypatch.setattr("fit_ai.speech.faster_whisper_provider.importlib.util.find_spec",
                        lambda name, *a, **k: object() if name == "faster_whisper" else real(name, *a, **k))
    return FakeWhisperModel


def model_dir(tmp_path, missing=()):
    for f in REQUIRED_FILES:
        if f not in missing:
            (tmp_path / f).write_bytes(b"x")
    return tmp_path


def provider(tmp_path, **kw):
    return FasterWhisperProvider(SpeechSettings(model_dir=tmp_path, **kw))


def test_engine_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr("fit_ai.speech.faster_whisper_provider.importlib.util.find_spec", lambda *a, **k: None)
    p = provider(model_dir(tmp_path))
    assert p.availability().state == "engine_missing"
    with pytest.raises(STTUnavailable):
        p.transcribe(AUDIO, "pt", threading.Event())


@pytest.mark.parametrize("missing", [("model.bin",), ("config.json",), ("tokenizer.json",), ("vocabulary.txt",), REQUIRED_FILES])
def test_model_files_missing(fake_engine, tmp_path, missing):
    p = provider(model_dir(tmp_path, missing))
    a = p.availability()
    assert a.state == "model_missing"
    assert all(m in a.detail for m in missing)
    assert str(tmp_path) not in a.detail  # no filesystem path leaves the provider
    with pytest.raises(STTModelMissing):
        p.transcribe(AUDIO, "pt", threading.Event())
    assert fake_engine.instances == []  # nothing was loaded


def test_a_missing_directory_is_a_missing_model(fake_engine, tmp_path):
    assert provider(tmp_path / "nope").availability().state == "model_missing"


def test_available_checks_files_without_loading_anything(fake_engine, tmp_path):
    p = provider(model_dir(tmp_path))
    assert p.availability().state == "available"
    assert p.availability().state == "available"
    assert fake_engine.instances == []  # status is read-only: the model is not loaded by asking about it


def test_loads_lazily_once_from_a_local_directory_only(fake_engine, tmp_path):
    p = provider(model_dir(tmp_path), threads=6)
    p.transcribe(AUDIO, "pt", threading.Event())
    p.transcribe(AUDIO, "pt", threading.Event())
    assert len(fake_engine.instances) == 1  # loaded on first use, then kept
    m = fake_engine.instances[0]
    assert m.path == str(tmp_path)
    assert m.kwargs == {"device": "cpu", "compute_type": "int8", "cpu_threads": 6, "local_files_only": True}  # can never reach a model hub


def test_passes_the_audio_language_and_settings_to_the_engine(fake_engine, tmp_path):
    p = provider(model_dir(tmp_path), beam_size=3)
    p.transcribe(AUDIO, "pt", threading.Event())
    samples, kwargs = fake_engine.instances[0].calls[0]
    assert samples.dtype.name == "float32" and len(samples) == AUDIO.frames
    assert -1.0 <= float(samples.min()) and float(samples.max()) <= 1.0
    assert kwargs["language"] == "pt" and kwargs["beam_size"] == 3
    assert "Honda Fit" in kwargs["initial_prompt"]


def test_the_vocabulary_hint_can_be_turned_off(fake_engine, tmp_path):
    provider(model_dir(tmp_path), initial_prompt="").transcribe(AUDIO, "pt", threading.Event())
    assert fake_engine.instances[0].calls[0][1]["initial_prompt"] is None


def test_the_pcm_is_decoded_with_the_right_scale_and_sign(fake_engine, tmp_path):
    import struct

    pcm = struct.pack("<hhhh", 16384, -16384, 32767, -32768) + bytes(2 * 4800)
    audio = parse_wav(make_wav(pcm=pcm), max_bytes=10**7, max_duration_s=30.0)
    provider(model_dir(tmp_path)).transcribe(audio, "pt", threading.Event())
    s = fake_engine.instances[0].calls[0][0]
    assert [round(float(x), 3) for x in s[:4]] == [0.5, -0.5, 1.0, -1.0]


def test_segments_are_joined_and_stripped(fake_engine, tmp_path):
    assert provider(model_dir(tmp_path)).transcribe(AUDIO, "pt", threading.Event()) == "olá mundo"


def test_cancel_stops_between_segments(fake_engine, tmp_path):
    p = provider(model_dir(tmp_path))
    cancel = threading.Event()
    cancel.set()
    assert p.transcribe(AUDIO, "pt", cancel) == ""


def test_engine_failure_becomes_a_typed_error_that_hides_the_cause(fake_engine, tmp_path, caplog):
    p = provider(model_dir(tmp_path))
    p.transcribe(AUDIO, "pt", threading.Event())  # load it
    fake_engine.instances[0].boom = RuntimeError(r"C:\Users\x\model.bin: out of memory while hearing 'texto privado'")
    with pytest.raises(STTFailed) as e:
        p.transcribe(AUDIO, "pt", threading.Event())
    assert "model.bin" not in str(e.value) and "privado" not in str(e.value)
    assert "privado" not in caplog.text and "model.bin" not in caplog.text  # the log carries only the exception TYPE


def test_a_model_that_cannot_be_loaded_is_a_typed_error(monkeypatch, tmp_path, fake_engine):
    def broken(*a, **k):
        raise OSError(r"C:\secret\path\model.bin is corrupt")

    sys.modules["faster_whisper"].WhisperModel = broken
    with pytest.raises(STTFailed) as e:
        provider(model_dir(tmp_path)).transcribe(AUDIO, "pt", threading.Event())
    assert "secret" not in str(e.value)


def test_the_provider_has_no_download_or_network_code():
    import fit_ai.speech.faster_whisper_provider as mod

    src = open(mod.__file__, encoding="utf-8").read().lower()
    assert "local_files_only=true" in src
    for forbidden in ("urllib", "requests", "httpx", "socket", "huggingface", "snapshot_download", "http://", "https://"):
        assert forbidden not in src, forbidden
