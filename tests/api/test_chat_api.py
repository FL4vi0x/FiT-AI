"""POST /api/v1/chat over HTTP: contract, validation, browser/host policy, limits, failures, persistence, leaks."""
import asyncio

import httpx
import pytest
from conftest import GOOD_RPM, MODEL, llm_json
from fastapi.testclient import TestClient

from fit_ai.adapters.fake_telemetry import FakeTelemetryProvider
from fit_ai.ai import Reply
from fit_ai.config import Settings
from fit_ai.conversation import ChatSettings
from fit_ai.domain.telemetry import VehicleLinkDown
from fit_ai.main import create_app

CHAT = "/api/v1/chat"
JSON = {"Content-Type": "application/json"}
GENERAL = "Explique o que é troca de óleo."
GENERAL_REPLY = "Troca de óleo é a renovação do lubrificante do motor, que protege as peças."


def post(c, payload=None, **kw):
    return c.post(CHAT, json=payload if payload is not None else {"message": "Qual é a rotação atual?"}, **kw)


def no_cors(r):
    return not [h for h in r.headers if h.lower().startswith("access-control-")]


def no_leak(text: str):
    for bad in ("Traceback", "File \"", "C:\\", "Users\\", ".db", "sqlite", "SELECT ", "REGRAS DE RESPOSTA",
                "LEITURAS DESTE TURNO", "hunter2"):
        assert bad not in text, bad


# ───────────────────── the happy path and the contract ─────────────────────
def test_valid_chat_request(chat_rig):
    r = chat_rig([llm_json(GOOD_RPM)])
    resp = post(r.client(), {"message": "Fit, qual é a rotação do meu motor?", "conversation_id": None})
    assert resp.status_code == 200 and no_cors(resp)
    body = resp.json()
    assert body["answer"] == GOOD_RPM and body["model"] == MODEL and body["used_tools"] == ["get_vehicle_telemetry"]
    assert body["simulated"] is True and body["data_source"] == "fake-octave" and body["availability"] == "ok"
    assert body["fallback_used"] is False and body["answer_origin"] == "llm" and body["model_status"] == "ok"
    assert body["history_saved"] is True and body["memory_saved"] is False and body["replayed"] is False
    assert resp.headers["x-request-id"] == body["request_id"] and len(body["request_id"]) == 32
    assert body["latency_ms"] >= 0 and len(body["conversation_id"]) == 32


def test_request_ids_are_server_generated_and_unique(chat_rig):
    r = chat_rig([llm_json(GOOD_RPM), llm_json(GOOD_RPM)])
    c = r.client()
    a = post(c, headers={"X-Request-ID": "client-chosen"}).json()["request_id"]
    b = post(c).json()["request_id"]
    assert a != b and a != "client-chosen"


@pytest.mark.parametrize("rpm,speed,temp", [(1234, 56.7, 101.3), (0, 0.0, -5.0), (6100, 130.0, 88.0), (907, 12.5, 77.0)])
def test_values_come_from_the_current_reading_never_from_the_code(chat_rig, rpm, speed, temp):
    fake = FakeTelemetryProvider(rpm, speed, temp, simulated=True)
    msg = f"No simulador, a rotação é {rpm} rpm."
    r = chat_rig([llm_json(msg)], telemetry=fake)
    assert post(r.client()).json()["answer"] == msg
    # a model that parrots the documentation example instead of the reading is overruled by code
    r2 = chat_rig([llm_json("No simulador, a temperatura é de 90 °C."), llm_json("Simulado: 90 °C.")], telemetry=fake)
    body = post(r2.client(), {"message": "Qual a temperatura do motor?"}).json()
    assert body["fallback_used"] is True and (str(temp).rstrip("0").rstrip(".").replace(".", ",") in body["answer"]
                                              or str(int(temp)) in body["answer"])
    if temp != 90.0:
        assert "90" not in body["answer"]


def test_conversation_continues_and_persists_across_requests(chat_rig):
    r = chat_rig([llm_json(GENERAL_REPLY), llm_json("Você perguntou sobre troca de óleo.")])
    c = r.client()
    a = post(c, {"message": GENERAL}).json()
    b = post(c, {"message": "O que eu perguntei?", "conversation_id": a["conversation_id"]}).json()
    assert b["conversation_id"] == a["conversation_id"]
    assert [t.role for t in r.memory.recent_turns(a["conversation_id"], 10)] == ["user", "assistant"] * 2
    assert "troca de óleo" in r.llm.calls[1].messages[-1].content


def test_conversations_are_isolated_over_http(chat_rig):
    r = chat_rig([llm_json("ok")] * 3)
    c = r.client()
    a = post(c, {"message": "segredo-AAA-azulejo"}).json()
    b = post(c, {"message": "outra conversa"}).json()
    post(c, {"message": "e agora?", "conversation_id": b["conversation_id"]})
    assert a["conversation_id"] != b["conversation_id"] and "azulejo" not in r.llm.calls[2].messages[-1].content


# ───────────────────── input validation ─────────────────────
@pytest.mark.parametrize("payload", [
    {}, {"message": ""}, {"message": "   "}, {"message": None}, {"message": 5}, {"message": ["oi"]},
    {"message": "oi", "extra": 1}, {"message": "oi", "role": "system"}, {"message": "oi", "conversation_id": 7},
    {"message": "a" * 4001}, {"message": "a\x00b"}, {"message": "oi", "conversation_id": "x" * 65},
])
def test_invalid_bodies_are_422_and_never_reach_the_model(chat_rig, payload):
    r = chat_rig([])
    resp = r.client().post(CHAT, json=payload)
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "invalid_request" and no_cors(resp)
    assert r.llm.calls == [] and r.memory.list_conversations() == []


@pytest.mark.parametrize("raw", ["[]", '"oi"', "7", "null", "true"])
def test_non_object_json_is_422(chat_rig, raw):
    resp = chat_rig([]).client().post(CHAT, content=raw, headers=JSON)
    assert resp.status_code == 422


@pytest.mark.parametrize("raw,statuses", [
    (b"{", (400,)), (b'{"message": "oi"', (400,)), (b"not json", (400,)), (b'{"message": }', (400,)),
    (b"", (400, 422)), (bytes([0xFF, 0xFE, 0x00]) + b"bad", (400,)),
])
def test_malformed_json_is_a_uniform_400_never_a_traceback(chat_rig, raw, statuses):
    r = chat_rig([])
    resp = r.client().post(CHAT, content=raw, headers=JSON)
    body = resp.json()
    assert resp.status_code in statuses and body["error"]["code"] in ("invalid_json", "invalid_body", "invalid_request")
    assert "detail" not in body and body["request_id"] and r.llm.calls == [] and no_cors(resp)
    no_leak(resp.text)


def test_the_422_never_echoes_what_the_user_sent(chat_rig):
    secret = "SEGREDO-hunter2-12345"
    resp = chat_rig([]).client().post(CHAT, json={"message": secret, "bogus": secret})
    assert resp.status_code == 422 and secret not in resp.text
    resp2 = chat_rig([]).client().post(CHAT, content=('{"message": "' + secret + '"').encode(), headers=JSON)
    assert secret not in resp2.text


def test_message_over_the_configured_limit_is_422_invalid_message(chat_rig):
    r = chat_rig([], chat=ChatSettings(max_message_chars=40))
    resp = post(r.client(), {"message": "x" * 41})
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "invalid_message" and r.llm.calls == []


@pytest.mark.parametrize("cid", ["abc", "'; DROP TABLE turns;--", "../../x", "g" * 32, "0" * 31])
def test_invalid_conversation_id_is_422(chat_rig, cid):
    resp = post(chat_rig([]).client(), {"message": "oi", "conversation_id": cid})
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "invalid_conversation_id"


def test_unknown_conversation_is_404(chat_rig):
    r = chat_rig([])
    resp = post(r.client(), {"message": "oi", "conversation_id": "a" * 32})
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "conversation_not_found"
    assert r.memory.list_conversations() == []


# ───────────────────── Content-Type and body size ─────────────────────
@pytest.mark.parametrize("ctype", ["text/plain", "text/plain;charset=UTF-8", "application/x-www-form-urlencoded",
                                   "multipart/form-data; boundary=x", "application/xml", "application/jsonx",
                                   "application/json; charset=latin-1", "application/json; boundary=x", "*/*", ""])
def test_wrong_content_type_is_415(chat_rig, ctype):
    r = chat_rig([])
    resp = r.client().post(CHAT, content=b'{"message": "oi"}', headers={"Content-Type": ctype} if ctype else {})
    assert resp.status_code == 415 and resp.json()["error"]["code"] == "unsupported_media_type" and r.llm.calls == []


@pytest.mark.parametrize("ctype", ["application/json", "application/json; charset=utf-8", "APPLICATION/JSON;CHARSET=UTF-8"])
def test_json_content_types_are_accepted(chat_rig, ctype):
    r = chat_rig([llm_json(GOOD_RPM)])
    assert r.client().post(CHAT, content=b'{"message": "Qual a rotacao?"}', headers={"Content-Type": ctype}).status_code == 200


def test_a_body_over_the_limit_is_413_by_content_length(chat_rig):
    r = chat_rig([])
    resp = r.client().post(CHAT, content=b'{"message": "' + b"a" * 20000 + b'"}', headers=JSON)
    assert resp.status_code == 413 and resp.json()["error"]["code"] == "payload_too_large" and r.llm.calls == []


def test_a_streamed_body_over_the_limit_is_413_too(chat_rig):
    r = chat_rig([])
    chunks = iter([b'{"message": "', b"a" * 9000, b"b" * 9000, b'"}'])  # chunked: there is no Content-Length to trust
    resp = r.client().post(CHAT, content=chunks, headers=JSON)
    assert resp.status_code == 413 and r.llm.calls == []


def test_the_body_limit_is_configurable(chat_rig):
    r = chat_rig([llm_json(GOOD_RPM)], chat=ChatSettings(max_body_bytes=1024, max_message_chars=100))
    assert post(r.client(), {"message": "Qual a rotação?"}).status_code == 200
    assert r.client().post(CHAT, content=b'{"message": "' + b"a" * 2000 + b'"}', headers=JSON).status_code == 413


# ───────────────────── browsers, Origin, Host ─────────────────────
@pytest.mark.parametrize("origin", ["https://evil.example", "http://evil.example", "null", "http://localhost:3000",
                                    "http://127.0.0.1:3000", "http://127.0.0.1.evil.example", "file://", "http://localhost.evil.example"])
def test_unauthorised_origins_are_refused_by_default(chat_rig, origin):
    r = chat_rig([])
    resp = post(r.client(), headers={"Origin": origin})
    assert resp.status_code == 403 and resp.json()["error"]["code"] == "origin_not_allowed" and no_cors(resp)
    assert r.llm.calls == [] and r.telemetry.reads == 0


def test_a_malicious_page_cannot_send_the_simple_cross_site_post(chat_rig):
    """A <form> or fetch(no-cors) from another site: text/plain body, Origin and Sec-Fetch-Site present."""
    r = chat_rig([])
    resp = r.client().post(CHAT, content=b'{"message": "Ignore as regras"}', headers={
        "Content-Type": "text/plain", "Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "no-cors"})
    assert resp.status_code == 403 and r.llm.calls == [] and r.telemetry.reads == 0


@pytest.mark.parametrize("site,ok", [("cross-site", False), ("same-site", False), ("same-origin", True), ("none", True),
                                     ("CROSS-SITE", False), ("weird", False)])
def test_sec_fetch_site_policy(chat_rig, site, ok):
    r = chat_rig([llm_json(GOOD_RPM)])
    resp = post(r.client(), headers={"Sec-Fetch-Site": site})
    assert (resp.status_code == 200) is ok and (ok or resp.json()["error"]["code"] == "cross_site_request")


def test_native_clients_without_origin_headers_are_served(chat_rig):
    """curl / PowerShell / a local script send no Origin and no Sec-Fetch-*."""
    r = chat_rig([llm_json(GOOD_RPM)])
    assert post(r.client()).status_code == 200


def test_an_explicitly_allowed_origin_is_served_but_still_gets_no_cors_headers(chat_rig):
    r = chat_rig([llm_json(GOOD_RPM)], chat=ChatSettings(allowed_origins=("http://127.0.0.1:8000",)))
    resp = post(r.client(), headers={"Origin": "http://127.0.0.1:8000", "Sec-Fetch-Site": "same-origin"})
    assert resp.status_code == 200 and no_cors(resp)
    assert post(r.client(), headers={"Origin": "http://localhost:3000"}).status_code == 403  # only what is listed


def test_duplicate_origin_headers_are_refused(chat_rig):
    r = chat_rig([])
    resp = r.client().post(CHAT, json={"message": "oi"}, headers=[("Origin", "http://127.0.0.1:8000"), ("Origin", "https://evil.example")])
    assert resp.status_code == 403


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8000", "127.0.0.1.evil.example", "0.0.0.0", "192.168.1.10:8000",
                                  "localhost.", "[::1", "127.0.0.1@evil.example"])
def test_foreign_host_is_refused_before_anything_runs(chat_rig, host):
    r = chat_rig([])
    resp = r.client().post(CHAT, json={"message": "oi"}, headers={"Host": host})
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "invalid_host"
    assert r.llm.calls == [] and r.telemetry.reads == 0 and r.memory.list_conversations() == []


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.1:8000", "localhost:8000", "[::1]:8000"])
def test_local_hosts_are_served(chat_rig, host):
    r = chat_rig([llm_json(GOOD_RPM)])
    assert post(r.client(), headers={"Host": host}).status_code == 200


def test_forwarded_headers_are_never_trusted(chat_rig):
    r = chat_rig([llm_json(GOOD_RPM)])
    ok = post(r.client(), headers={"X-Forwarded-Host": "evil.example", "X-Forwarded-For": "8.8.8.8",
                                   "X-Forwarded-Proto": "https", "Forwarded": "host=evil.example"})
    assert ok.status_code == 200  # they change nothing
    r2 = chat_rig([])
    bad = r2.client().post(CHAT, json={"message": "oi"}, headers={"Host": "evil.example", "X-Forwarded-Host": "127.0.0.1"})
    assert bad.status_code == 400  # and cannot launder a bad Host


def test_no_cors_anywhere_and_preflight_is_not_answered(chat_rig):
    c = chat_rig([llm_json(GOOD_RPM)]).client()
    for resp in (post(c), post(c, {"message": ""}), c.get("/health"),
                 c.options(CHAT, headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST",
                                          "Access-Control-Request-Headers": "content-type"})):
        assert no_cors(resp)
    assert c.options(CHAT, headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}).status_code == 405


@pytest.mark.parametrize("method", ["get", "put", "patch", "delete"])
def test_only_post_is_allowed_on_chat(chat_rig, method):
    assert getattr(chat_rig([]).client(), method)(CHAT).status_code == 405


# ───────────────────── resources: concurrency and timeouts ─────────────────────
@pytest.mark.anyio
async def test_overflow_gets_429_with_retry_after_and_everything_recovers(chat_rig):
    slow = lambda: Reply.text(llm_json("ok").response.content, delay_s=0.4)  # noqa: E731
    r = chat_rig([slow(), slow()], chat=ChatSettings(max_concurrent=1, max_waiting=1, queue_timeout_s=5))
    transport = httpx.ASGITransport(app=r.app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as c:
        t1 = asyncio.create_task(c.post(CHAT, json={"message": GENERAL}))
        await asyncio.sleep(0.08)
        t2 = asyncio.create_task(c.post(CHAT, json={"message": "Explique o que é um catalisador."}))
        await asyncio.sleep(0.08)
        t3 = await c.post(CHAT, json={"message": "Explique o que é uma vela de ignição."})
        assert t3.status_code == 429 and t3.json()["error"]["code"] == "service_busy" and int(t3.headers["retry-after"]) >= 1
        assert (await t1).status_code == 200 and (await t2).status_code == 200
        r.llm._queue.append(llm_json("ok"))
        assert (await c.post(CHAT, json={"message": "Olá, tudo bem?"})).status_code == 200  # nothing stayed locked


def test_generation_timeout_is_504_and_saves_nothing(chat_rig):
    r = chat_rig([Reply.hang()], chat=ChatSettings(request_timeout_s=0.2))
    resp = post(r.client(), {"message": GENERAL})
    assert resp.status_code == 504 and resp.json()["error"]["code"] == "request_timeout" and no_cors(resp)
    assert r.memory.list_conversations() == []


@pytest.mark.anyio
async def test_a_client_that_disconnects_leaves_the_service_clean(chat_rig):
    r = chat_rig([Reply.hang(), llm_json("ok")])
    transport = httpx.ASGITransport(app=r.app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as c:
        task = asyncio.create_task(c.post(CHAT, json={"message": GENERAL}))
        await asyncio.sleep(0.15)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.05)
        assert not r.service._sem.locked() and r.service._waiting == 0 and r.memory.list_conversations() == []
        assert (await c.post(CHAT, json={"message": "Olá, tudo bem?"})).status_code == 200


# ───────────────────── Ollama / OCTAVE / storage / audit failures ─────────────────────
@pytest.mark.parametrize("reply,status,code", [
    (Reply.unavailable(), 503, "model_unavailable"), (Reply.timeout(), 504, "model_timeout"),
])
def test_model_failures_on_a_general_question(chat_rig, reply, status, code):
    r = chat_rig([reply])
    resp = post(r.client(), {"message": GENERAL})
    assert resp.status_code == status and resp.json()["error"]["code"] == code and r.memory.list_conversations() == []
    no_leak(resp.text)


def test_missing_model_is_503_model_not_found(chat_rig):
    from fit_ai.ai import LLMModelNotFound
    resp = post(chat_rig([Reply.fail(LLMModelNotFound("model 'x' not found, try pulling it first"))]).client(), {"message": GENERAL})
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "model_not_found" and "pulling" not in resp.text


def test_model_down_with_vehicle_data_still_answers_honestly(chat_rig):
    body = post(chat_rig([Reply.unavailable()]).client()).json()
    assert body["fallback_used"] is True and body["model_status"] == "unavailable" and "800 rpm" in body["answer"]
    assert body["answer_origin"] == "fallback"  # it never pretends the model answered


def test_model_recovers_after_a_failure(chat_rig):
    c = chat_rig([Reply.unavailable(), llm_json("Posso ajudar com leituras do veículo.")]).client()
    assert post(c, {"message": "Olá, tudo bem?"}).status_code == 503
    assert post(c, {"message": "Olá, tudo bem?"}).status_code == 200


def test_octave_down_is_a_safe_answer_not_a_server_error(chat_rig):
    fake = FakeTelemetryProvider().fail_with(VehicleLinkDown("link"))
    r = chat_rig([llm_json("Não consigo ler os dados do veículo agora; a conexão está interrompida.")], telemetry=fake)
    resp = post(r.client())
    body = resp.json()
    assert resp.status_code == 200 and body["availability"] == "unavailable" and body["simulated"] is None
    assert not any(ch.isdigit() for ch in body["answer"])


def test_octave_down_and_a_model_that_invents_gets_the_unavailable_fallback(chat_rig):
    fake = FakeTelemetryProvider().fail_with(VehicleLinkDown("link"))
    body = post(chat_rig([llm_json("Simulado: 800 rpm."), llm_json("Simulado: 800 rpm.")], telemetry=fake).client()).json()
    assert body["fallback_used"] and "800" not in body["answer"] and body["availability"] == "unavailable"


def test_audit_down_is_503_and_nothing_runs(chat_rig):
    r = chat_rig([llm_json(GOOD_RPM)], audit_ok_writes=0)
    resp = post(r.client())
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "audit_unavailable"
    assert r.telemetry.reads == 0 and r.memory.list_conversations() == []


def test_storage_failure_is_503_and_a_retry_is_safe(chat_rig, monkeypatch):
    r = chat_rig([llm_json(GOOD_RPM)] * 2)
    real = r.memory.record_exchange
    from fit_ai.memory import MemoryStorageError
    monkeypatch.setattr(r.memory, "record_exchange", lambda *a, **k: (_ for _ in ()).throw(MemoryStorageError("disk C:\\x.db")))
    c = r.client()
    resp = post(c)
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "storage_unavailable"
    no_leak(resp.text)
    monkeypatch.setattr(r.memory, "record_exchange", real)
    assert post(c).status_code == 200 and len(r.memory.list_conversations()) == 1


def test_unexpected_internal_errors_are_500_without_details(chat_rig, monkeypatch):
    r = chat_rig([])

    async def boom(*a, **k):
        raise RuntimeError("password=hunter2 C:\\Users\\x\\secret.db SELECT * FROM turns")
    monkeypatch.setattr(r.service, "chat", boom)
    resp = post(r.client())
    assert resp.status_code == 500 and resp.json()["error"]["code"] == "internal_error" and resp.json()["request_id"]
    no_leak(resp.text)


# ───────────────────── idempotency and duplicates ─────────────────────
def test_retry_with_idempotency_key_does_not_duplicate_or_call_the_model_again(chat_rig):
    r = chat_rig([llm_json(GOOD_RPM)])
    c = r.client()
    h = {"Idempotency-Key": "retry-key-0001"}
    a = post(c, headers=h).json()
    b = post(c, headers=h).json()
    assert b["replayed"] is True and a["replayed"] is False and a["conversation_id"] == b["conversation_id"]
    assert a["request_id"] != b["request_id"] and a["answer"] == b["answer"]
    assert len(r.llm.calls) == 1 and len(r.memory.recent_turns(a["conversation_id"], 10)) == 2


def test_idempotency_key_misuse(chat_rig):
    r = chat_rig([llm_json(GOOD_RPM)])
    c = r.client()
    post(c, headers={"Idempotency-Key": "retry-key-0001"})
    other = post(c, {"message": "Qual a velocidade?"}, headers={"Idempotency-Key": "retry-key-0001"})
    assert other.status_code == 422 and other.json()["error"]["code"] == "idempotency_key_reuse"
    bad = post(c, headers={"Idempotency-Key": "short"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_idempotency_key"


# ───────────────────── explicit memory over HTTP ─────────────────────
def test_memory_command_saves_and_is_used_later(chat_rig):
    r = chat_rig([llm_json("Você me pediu para lembrar que prefere respostas curtas.")])
    c = r.client()
    a = post(c, {"message": "Fit, lembre que prefiro respostas curtas."}).json()
    assert a["answer_origin"] == "memory_command" and a["memory_saved"] is True and a["model"] is None
    assert [f.content for f in r.memory.list_facts()] == ["prefiro respostas curtas."]
    b = post(c, {"message": "Qual é a minha preferência?", "conversation_id": a["conversation_id"]}).json()
    assert "get_memory_facts" in b["used_tools"] and b["memory_saved"] is False


def test_a_question_does_not_create_memory_and_telemetry_is_not_memory(chat_rig):
    r = chat_rig([llm_json("Posso ajudar com isso.")])
    c = r.client()
    assert post(c, {"message": "Você lembra que eu prefiro respostas curtas?"}).json()["memory_saved"] is False
    refused = post(c, {"message": "Fit, lembre que meu motor está a 3000 RPM agora"}).json()
    assert refused["memory_saved"] is False and "Nada foi guardado" in refused["answer"]
    assert r.memory.list_facts() == []


# ───────────────────── the rest of the Core is untouched ─────────────────────
def test_existing_endpoints_still_work_and_are_not_guarded_like_chat(chat_rig):
    c = chat_rig([]).client()
    assert c.get("/health").status_code == 200
    assert c.get("/api/v1/vehicle/telemetry").status_code == 200
    assert c.get("/api/v1/vehicle/status").status_code == 200
    assert c.post("/api/v1/vehicle/telemetry").status_code == 405  # unchanged: still a plain 405


def test_without_a_chat_service_only_chat_is_unavailable():
    c = TestClient(create_app(provider=FakeTelemetryProvider()), base_url="http://127.0.0.1:8000")
    resp = post(c)
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "chat_unavailable"
    assert c.get("/health").status_code == 200 and c.get("/api/v1/vehicle/telemetry").status_code == 200


def test_injected_provider_alone_creates_no_database(tmp_path, monkeypatch):
    monkeypatch.setenv("FIT_AI_DATA_DIR", str(tmp_path / "must-stay-empty"))
    create_app(provider=FakeTelemetryProvider())
    assert not (tmp_path / "must-stay-empty").exists()  # hermetic: tests never touch the user's data directory


# ───────────────────── production wiring (no services running) ─────────────────────
def test_production_wiring_builds_the_chat_and_survives_missing_services(tmp_path, monkeypatch):
    monkeypatch.setenv("FIT_AI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FIT_AI_OLLAMA_URL", "http://127.0.0.1:9")  # nothing listens here
    monkeypatch.setenv("OCTAVE_PORT", "9")
    c = TestClient(create_app(settings=Settings.from_env()), base_url="http://127.0.0.1:8000", raise_server_exceptions=False)
    assert (tmp_path / "data" / "memory.db").exists() and (tmp_path / "data" / "audit.db").exists()
    assert c.get("/health").status_code == 200
    down = post(c, {"message": GENERAL})
    assert down.status_code == 503 and down.json()["error"]["code"] == "model_unavailable"
    ask = post(c)  # vehicle question with OCTAVE and Ollama both off: a safe answer, never an invented number
    body = ask.json()
    assert ask.status_code == 200 and body["fallback_used"] is True and body["availability"] == "unavailable"
    assert not any(ch.isdigit() for ch in body["answer"]) and body["model_status"] == "unavailable"


def test_unwritable_data_directory_disables_chat_but_not_the_core(tmp_path, monkeypatch):
    blocker = tmp_path / "a-file"
    blocker.write_text("x")
    monkeypatch.setenv("FIT_AI_DATA_DIR", str(blocker / "data"))
    monkeypatch.setenv("OCTAVE_PORT", "9")
    c = TestClient(create_app(settings=Settings.from_env()), base_url="http://127.0.0.1:8000", raise_server_exceptions=False)
    assert c.get("/health").status_code == 200
    assert post(c).json()["error"]["code"] == "chat_unavailable"


def test_invalid_chat_settings_disable_chat_and_keep_the_strict_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("FIT_AI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FIT_AI_CHAT_MAX_CONCURRENT", "banana")
    monkeypatch.setenv("OCTAVE_PORT", "9")
    c = TestClient(create_app(settings=Settings.from_env()), base_url="http://127.0.0.1:8000", raise_server_exceptions=False)
    assert c.get("/health").status_code == 200
    assert post(c).json()["error"]["code"] == "chat_unavailable"
    assert post(c, headers={"Origin": "https://evil.example"}).status_code == 403  # the guard stayed on
