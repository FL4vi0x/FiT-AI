"""POST /api/v1/voice/transcribe and GET /api/v1/voice/status: contract, limits, Host/Origin protection, privacy, independence."""
import logging
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "speech"))  # wavs helper (tests/speech has no import path from here)
from wavs import make_wav  # noqa: E402

from fit_ai.main import create_app  # noqa: E402
from fit_ai.speech.config import SpeechSettings  # noqa: E402
from fit_ai.speech.fake_provider import FakeSTTProvider  # noqa: E402
from fit_ai.speech.service import SpeechService  # noqa: E402
from test_http_api import FakeProvider  # noqa: E402

URL = "/api/v1/voice/transcribe"
WAV = {"Content-Type": "audio/wav"}
SPOKEN = make_wav(1.5)
TEXT = "fit, qual é a velocidade do carro?"


def app_with(stt=None, settings=None, **kw):
    settings = settings or SpeechSettings()
    svc = SpeechService(stt or FakeSTTProvider(TEXT), settings)
    return create_app(provider=FakeProvider(), speech_service=svc, speech_settings=settings, **kw), svc


@pytest.fixture
def client():
    app, _ = app_with()
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        yield c


def test_transcribes_a_wav_and_returns_text_with_minimal_metadata(client):
    r = client.post(URL, content=SPOKEN, headers=WAV)
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == TEXT and body["silent"] is False and body["duration_s"] == 1.5 and body["language"] == "pt"
    assert set(body) == {"text", "silent", "duration_s", "processing_ms", "language", "model"}
    assert r.headers["cache-control"] == "no-store" and r.headers["x-request-id"]


def test_silence_is_answered_without_running_the_engine():
    stt = FakeSTTProvider(TEXT)
    app, _ = app_with(stt)
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        r = c.post(URL, content=make_wav(pcm=bytes(48000)), headers=WAV)
    assert r.status_code == 200 and r.json()["silent"] is True and r.json()["text"] == "" and stt.calls == []


@pytest.mark.parametrize("ctype", ["application/json", "text/plain", "application/octet-stream", "multipart/form-data; boundary=x",
                                   "audio/mpeg", "audio/wav; codecs=1", "video/webm", "application/x-www-form-urlencoded"])
def test_only_audio_wav_is_accepted(client, ctype):
    r = client.post(URL, content=SPOKEN, headers={"Content-Type": ctype})
    assert r.status_code == 415 and r.json()["error"]["code"] == "unsupported_media_type"


def test_missing_content_type_is_refused(client):
    assert client.post(URL, content=SPOKEN, headers={"Content-Type": ""}).status_code == 415


def test_x_wav_alias_is_accepted(client):
    assert client.post(URL, content=SPOKEN, headers={"Content-Type": "audio/x-wav"}).status_code == 200


def test_declared_size_over_the_limit_is_refused_before_reading():
    app, svc = app_with(settings=SpeechSettings(max_audio_s=2.0))
    limit = SpeechSettings(max_audio_s=2.0).max_body_bytes
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        r = c.post(URL, content=b"RIFF" + bytes(limit), headers=WAV)
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"


def test_streamed_body_over_the_limit_is_cut_off_even_without_content_length():
    app, _ = app_with(settings=SpeechSettings(max_audio_s=2.0))
    limit = SpeechSettings(max_audio_s=2.0).max_body_bytes

    def chunks():  # chunked upload: no Content-Length to check up front
        for _ in range(limit // 4096 + 3):
            yield bytes(4096)

    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        r = c.post(URL, content=chunks(), headers=WAV)
    assert r.status_code == 413


def test_audio_longer_than_allowed_is_refused_by_duration():
    app, _ = app_with(settings=SpeechSettings(max_audio_s=2.0))
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        r = c.post(URL, content=make_wav(2.04), headers=WAV)  # small enough for the byte limit, too long in seconds
    assert r.status_code == 413 and r.json()["error"]["code"] == "audio_too_long"


@pytest.mark.parametrize("data, code", [
    (b"", "audio_empty"), (make_wav(1.0)[:400], "invalid_audio"), (b"RIFF....WAVEjunk" * 4, "invalid_audio"),
    (make_wav(1.0, rate=44100), "invalid_audio"), (make_wav(1.0, channels=2), "invalid_audio"), (make_wav(0.05), "audio_too_short"),
    (b"\x89PNG\r\n" + bytes(200), "invalid_audio"),
])
def test_malformed_audio_gets_a_stable_code(client, data, code):
    r = client.post(URL, content=data, headers=WAV)
    assert r.status_code == 422 and r.json()["error"]["code"] == code
    assert r.json()["request_id"]


@pytest.mark.parametrize("state, status, code", [("model_missing", 503, "stt_model_missing"), ("engine_missing", 503, "stt_unavailable")])
def test_model_or_engine_missing(state, status, code):
    app, _ = app_with(FakeSTTProvider(state=state))
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        r = c.post(URL, content=SPOKEN, headers=WAV)
    assert r.status_code == status and r.json()["error"]["code"] == code
    assert "runtime" not in r.text and "Users" not in r.text  # no filesystem path in the answer


def test_engine_failure_is_a_clean_502():
    app, _ = app_with(FakeSTTProvider(fail=True))
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        r = c.post(URL, content=SPOKEN, headers=WAV)
    assert r.status_code == 502 and r.json()["error"]["code"] == "stt_failed"


def test_disabled_speech_answers_503():
    app, _ = app_with(settings=SpeechSettings(enabled=False))
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        assert c.post(URL, content=SPOKEN, headers=WAV).json()["error"]["code"] == "stt_disabled"
        assert c.get("/api/v1/voice/status").json()["state"] == "disabled"


def test_without_a_speech_service_the_route_answers_503_and_the_core_keeps_working():
    app = create_app(provider=FakeProvider())  # hermetic: no engine is built when only a provider is injected
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        r = c.post(URL, content=SPOKEN, headers=WAV)
        assert r.status_code == 503 and r.json()["error"]["code"] == "stt_unavailable"
        assert c.get("/api/v1/voice/status").json() == {"state": "unavailable", "language": None, "max_audio_s": None, "sample_rate": None, "hint": None}
        assert c.get("/api/v1/vehicle/telemetry").status_code == 200 and c.get("/health").status_code == 200


def test_busy_answers_429_with_retry_after():
    import threading

    gate = threading.Event()
    stt = FakeSTTProvider(TEXT, block=gate)
    app, _ = app_with(stt)
    import concurrent.futures as cf

    with TestClient(app, base_url="http://127.0.0.1:8000") as c, cf.ThreadPoolExecutor(1) as pool:
        first = pool.submit(lambda: c.post(URL, content=SPOKEN, headers=WAV))
        assert stt.started.wait(5)
        second = c.post(URL, content=SPOKEN, headers=WAV)
        gate.set()
        assert first.result(10).status_code == 200
    assert second.status_code == 429 and second.headers["retry-after"] == "2" and second.json()["error"]["code"] == "stt_busy"


# ---------------------------------------------------------------- Host / Origin / browser protections
@pytest.mark.parametrize("host", ["evil.example", "evil.example:8000", "127.0.0.1.evil.example", "localhost.evil.example"])
def test_rebinding_hosts_are_refused(client, host):
    for call in (lambda: client.post(URL, content=SPOKEN, headers={**WAV, "Host": host}),
                 lambda: client.get("/api/v1/voice/status", headers={"Host": host})):
        r = call()
        assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_host"


@pytest.mark.parametrize("origin", ["https://evil.example", "http://localhost:5173", "null", "http://127.0.0.1:5173"])
def test_foreign_origins_are_refused_unless_allow_listed(client, origin):
    r = client.post(URL, content=SPOKEN, headers={**WAV, "Origin": origin})
    assert r.status_code == 403 and r.json()["error"]["code"] == "origin_not_allowed"


def test_an_allow_listed_origin_passes():
    app, _ = app_with(chat_settings=__import__("fit_ai.conversation.config", fromlist=["ChatSettings"]).ChatSettings(allowed_origins=("http://localhost:5173",)))
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        assert c.post(URL, content=SPOKEN, headers={**WAV, "Origin": "http://localhost:5173"}).status_code == 200


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_cross_site_fetches_are_refused(client, site):
    r = client.post(URL, content=SPOKEN, headers={**WAV, "Sec-Fetch-Site": site})
    assert r.status_code == 403 and r.json()["error"]["code"] == "cross_site_request"


def test_same_origin_fetch_passes(client):
    assert client.post(URL, content=SPOKEN, headers={**WAV, "Sec-Fetch-Site": "same-origin"}).status_code == 200


def test_no_cors_headers_and_preflight_is_not_answered(client):
    r = client.post(URL, content=SPOKEN, headers=WAV)
    assert not any(h.startswith("access-control-") for h in r.headers)
    pre = client.options(URL, headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert pre.status_code in (403, 405) and not any(h.startswith("access-control-") for h in pre.headers)


def test_wrong_methods_are_refused(client):
    assert client.get(URL).status_code == 405
    assert client.put(URL, content=SPOKEN, headers=WAV).status_code in (403, 405)


def test_the_chat_route_keeps_its_own_json_rule_and_limit(client):
    # the audio policy must not have loosened the chat: still JSON only, still 16 KB
    assert client.post("/api/v1/chat", content=SPOKEN, headers=WAV).status_code == 415
    assert client.post("/api/v1/chat", content=b"{" + b" " * 20000 + b"}", headers={"Content-Type": "application/json"}).status_code == 413


# ---------------------------------------------------------------- privacy and independence
def test_the_transcript_never_reaches_the_logs(caplog):
    caplog.set_level(logging.DEBUG)
    app, _ = app_with()
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        c.post(URL, content=SPOKEN, headers=WAV)
    assert "velocidade" not in "\n".join(r.getMessage() for r in caplog.records)


def test_a_transcription_leaves_nothing_on_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TMP", str(tmp_path))
    monkeypatch.setenv("TEMP", str(tmp_path))
    app, _ = app_with()
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        assert c.post(URL, content=SPOKEN, headers=WAV).status_code == 200
    assert list(tmp_path.rglob("*")) == []


def test_speech_does_not_touch_the_chat_or_the_language_model():
    app, _ = app_with()
    assert app.state.conversation_service is None  # no chat runtime, no Ollama client exists in this app
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        assert c.post(URL, content=SPOKEN, headers=WAV).status_code == 200
        assert c.get("/api/v1/llm/status").json()["state"] == "not_configured"  # Ollama off does not matter to speech
        assert c.post("/api/v1/chat", json={"message": "oi"}).status_code == 503


def test_status_reports_availability_without_running_anything():
    stt = FakeSTTProvider(state="model_missing")
    app, _ = app_with(stt)
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        r = c.get("/api/v1/voice/status")
    body = r.json()
    assert body["state"] == "model_missing" and "poc-09-01-local-stt" in body["hint"] and stt.calls == []
    assert (body["language"], body["sample_rate"], body["max_audio_s"]) == ("pt", 16000, 30.0)
    assert r.headers["cache-control"] == "no-store"
