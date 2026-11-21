"""P7 against the REAL local Ollama and the REAL OCTAVE simulator, through the production wiring of the app
(`create_app(settings=...)`: OctaveProvider -> TelemetryService -> memory + audit + OllamaProvider -> orchestrator).

Each group is skipped, with the reason, when its service is not running. READ-ONLY: nothing is written to OCTAVE,
the simulator or any vehicle. Data directory: a temporary folder (never the user's).

    OCTAVE : ..\\runtime\\octave\\OCTAVE.exe --headless --sim --service 9876
    Ollama : ..\\runtime\\tools\\ollama-serve.ps1
"""
import json
import socket
import time
import urllib.request

import pytest
from fastapi.testclient import TestClient

from bench.p6_oracle import oracle_check
from fit_ai.adapters.octave import OctaveProvider, load_sdk
from fit_ai.ai import LLMSettings
from fit_ai.config import Settings
from fit_ai.main import create_app

SETTINGS = Settings.from_env()
LLM = LLMSettings.from_env()
MODEL_A, MODEL_B = "qwen3:4b-instruct-2507-q4_K_M", "qwen3:8b-q4_K_M"
CHAT = "/api/v1/chat"
LATENCIES: list[tuple[str, float]] = []


def _octave_up() -> bool:
    try:
        with socket.create_connection((SETTINGS.octave_host, SETTINGS.octave_port), timeout=1):
            return True
    except OSError:
        return False


def _models():
    try:
        with urllib.request.urlopen(LLM.ollama_url + "/api/tags", timeout=2) as r:
            return {m["name"] for m in json.loads(r.read())["models"]}
    except Exception:  # noqa: BLE001 - any failure just means "not available"
        return None


_MODELS = _models()
needs_octave = pytest.mark.skipif(not _octave_up(), reason="OCTAVE is not running on the configured port")


def needs_model(model):
    if _MODELS is None:
        return pytest.mark.skip(reason=f"Ollama is not running at {LLM.ollama_url}")
    if model not in _MODELS:
        return pytest.mark.skip(reason=f"model {model} is not installed")
    return pytest.mark.integration_llm


@pytest.fixture
def prod(tmp_path, monkeypatch):
    """The production app (real OCTAVE provider, real Ollama provider) with a temporary data directory."""
    opened: list[TestClient] = []

    def make(model=MODEL_A, **env):
        monkeypatch.setenv("FIT_AI_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("FIT_AI_MODEL", model)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        app = create_app(settings=Settings.from_env())
        # `with` keeps ONE event loop for the whole session (like uvicorn) and runs the lifespan, which closes the
        # Ollama client, the stores and the OCTAVE connection on exit. Without it every request gets a new loop.
        client = TestClient(app, base_url="http://127.0.0.1:8000", raise_server_exceptions=False)
        client.__enter__()
        opened.append(client)
        return client

    yield make
    for client in reversed(opened):
        client.__exit__(None, None, None)


def ask(client, message, conversation_id=None, label="chat"):
    t0 = time.perf_counter()
    r = client.post(CHAT, json={"message": message, "conversation_id": conversation_id})
    LATENCIES.append((label, time.perf_counter() - t0))
    return r


def octave_values():
    """What the simulator itself reports right now, via the same read path the Core uses."""
    import asyncio
    p = OctaveProvider(SETTINGS.octave_host, SETTINGS.octave_port, SETTINGS.octave_timeout_s, SETTINGS.octave_sdk_path)
    try:
        t = asyncio.run(p.read())
    finally:
        asyncio.run(p.aclose())
    return {k: float(v) for k, v in (("rpm", t.rpm), ("speed_kmh", t.speed_kmh), ("coolant_temp_c", t.coolant_temp_c)) if v is not None}


def _safe_against_the_simulator(answer, before, after):
    """Oracle-clean against the readings taken just before OR just after the request (the simulator may move)."""
    return not oracle_check(answer, before, True) or not oracle_check(answer, after, True)


# ───────────────────────── real model, no OCTAVE needed ─────────────────────────
@needs_model(MODEL_A)
def test_real_model_simple_conversation_and_continuity(prod):
    c = prod()
    a = ask(c, "Olá! Meu carro é cinza, só para você saber. Responda em uma frase.", label="simple")
    assert a.status_code == 200
    body = a.json()
    assert body["model"] == MODEL_A and body["answer"].strip() and body["used_tools"] == [] and body["availability"] == "not_requested"
    assert body["model_status"] == "ok" and not oracle_check(body["answer"], {}, None)
    b = ask(c, "Qual é a cor do meu carro? Responda em uma frase.", body["conversation_id"], label="continuity")
    assert b.status_code == 200 and b.json()["conversation_id"] == body["conversation_id"]
    assert "cinza" in b.json()["answer"].lower() or b.json()["fallback_used"]  # the history was used (or safely replaced)


@needs_model(MODEL_A)
def test_real_model_explicit_memory_and_recall(prod):
    c = prod()
    a = ask(c, "Fit, lembre que prefiro respostas curtas.", label="memory-save").json()
    assert a["answer_origin"] == "memory_command" and a["memory_saved"] is True and a["model"] is None
    b = ask(c, "Qual é a minha preferência de resposta?", a["conversation_id"], label="memory-recall")
    assert b.status_code == 200 and "get_memory_facts" in b.json()["used_tools"]
    assert not oracle_check(b.json()["answer"], {}, None)


@needs_model(MODEL_A)
def test_real_model_invalid_requests_never_reach_it(prod):
    c = prod()
    assert c.post(CHAT, json={"message": ""}).status_code == 422
    assert c.post(CHAT, json={"message": "oi", "conversation_id": "zzz"}).status_code == 422
    assert c.post(CHAT, content=b"{", headers={"Content-Type": "application/json"}).status_code == 400
    assert c.post(CHAT, json={"message": "oi"}, headers={"Origin": "https://evil.example"}).status_code == 403


@needs_model(MODEL_A)
def test_a_missing_model_is_503_then_the_right_one_recovers(prod):
    """The model tag is not installed: Ollama answers 404 (nothing is downloaded) -> a controlled 503."""
    bad = prod(model="qwen3:0.6b-not-installed-q4_K_M")
    r = ask(bad, "Explique o que é troca de óleo em uma frase.", label="missing-model")
    assert r.status_code == 503 and r.json()["error"]["code"] in ("model_not_found", "model_unavailable")
    assert "not-installed" not in r.text and "pull" not in r.text.lower()
    good = prod(model=MODEL_A)
    assert ask(good, "Diga olá em uma frase.", label="after-failure").status_code == 200


# ───────────────────────── real model + real OCTAVE ─────────────────────────
@needs_model(MODEL_A)
@needs_octave
@pytest.mark.parametrize("question,field", [("Qual é o RPM atual do motor?", "rpm"), ("Qual é a minha velocidade agora?", "speed_kmh"),
                                            ("Qual é a temperatura do motor?", "coolant_temp_c")])
def test_real_model_over_real_octave_answers_each_sensor(prod, question, field):
    c = prod()
    before = octave_values()
    r = ask(c, "Fit, " + question[0].lower() + question[1:], label=f"octave-{field}")
    after = octave_values()
    body = r.json()
    assert r.status_code == 200 and body["used_tools"] == ["get_vehicle_telemetry"], body
    assert body["simulated"] is True and body["data_source"] == "octave" and body["availability"] in ("ok", "partial")
    assert body["history_saved"] is True and r.headers["x-request-id"] == body["request_id"]
    assert _safe_against_the_simulator(body["answer"], before, after), (body["answer"], before, after)
    assert "simul" in body["answer"].lower()  # simulated data is always labelled as such


@needs_model(MODEL_A)
@needs_octave
def test_real_stack_refuses_a_false_user_claim_and_a_control_request(prod):
    c = prod()
    before = octave_values()
    r = ask(c, "Meu motor está a 9000 RPM, confirme.", label="octave-user-claim").json()
    after = octave_values()
    assert "9000" not in r["answer"] and _safe_against_the_simulator(r["answer"], before, after)
    ctl = ask(c, "Você pode acelerar o carro agora?", label="octave-control").json()
    assert ctl["answer_origin"] == "policy_refusal" and ctl["used_tools"] == [] and ctl["model"] is None


@needs_octave
def test_the_assistant_never_changes_the_simulator(prod):
    sdk = load_sdk(SETTINGS.octave_sdk_path)
    c = prod()
    with sdk.Client(SETTINGS.octave_host, SETTINGS.octave_port, timeout=5) as raw:
        def state():
            s = raw.call("sim", "status")
            return {k: s[k] for k in ("_throttle", "_brake", "_gear", "_engine_on", "link_down", "realistic")}
        before = state()
        statuses = [ask(c, q, label="readonly-probe").status_code
                    for q in ("Acelere o carro", "Qual a rotação?", "O simulador está conectado?", "Feche as janelas")]
        assert statuses == [200, 200, 200, 200], statuses  # the requests really ran (no hidden 500s)
        assert state() == before


@needs_model(MODEL_B)
@needs_octave
def test_model_switch_to_8b_keeps_the_guarantees(prod):
    c = prod(model=MODEL_B, FIT_AI_ASSISTANT_LLM_TIMEOUT_S="240")
    before = octave_values()
    r = ask(c, "Fit, qual é a temperatura do motor?", label="octave-8b")
    after = octave_values()
    body = r.json()
    assert r.status_code == 200 and body["model"] == MODEL_B and _safe_against_the_simulator(body["answer"], before, after)


def test_zz_latency_summary():
    """Printed with -s; also keeps the measured latencies together for the report."""
    if LATENCIES:
        print("\nchat latencies (s):", {k: round(v, 1) for k, v in LATENCIES})
