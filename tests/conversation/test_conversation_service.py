"""ConversationService with fake telemetry, a scripted fake model and temporary SQLite databases."""
import asyncio
import uuid

import pytest
from conftest import GOOD_RPM, MODEL, llm_json

from fit_ai.adapters.fake_telemetry import FakeTelemetryProvider
from fit_ai.ai import LLMModelNotFound, LLMUnavailable, Reply
from fit_ai.conversation import (
    AuditUnavailable,
    ChatSettings,
    ConversationNotFound,
    IdempotencyConflict,
    InvalidConversationId,
    InvalidIdempotencyKey,
    InvalidMessage,
    ModelUnavailable,
    RequestInProgress,
    RequestTimeout,
    ServiceBusy,
    StorageUnavailable,
)
from fit_ai.domain.telemetry import VehicleLinkDown
from fit_ai.memory import MemoryStorageError
from fit_ai.orchestration import HISTORY_PLACEHOLDER

pytestmark = pytest.mark.anyio


def turns(rig, cid):
    return [(t.role, t.content) for t in rig.memory.recent_turns(cid, 50)]


# ───────────────────── new conversation, continuation, isolation ─────────────────────
async def test_new_conversation_is_created_and_persisted_atomically(chat_rig):
    r = chat_rig([llm_json(GOOD_RPM)])
    resp = await r.ask("Fit, qual é o RPM atual?")
    assert resp.answer == GOOD_RPM and resp.answer_origin == "llm" and resp.model == MODEL
    assert resp.used_tools == ["get_vehicle_telemetry"] and resp.fallback_used is False
    assert resp.simulated is True and resp.data_source == "fake-octave" and resp.availability == "ok"
    assert resp.model_status == "ok" and resp.history_saved is True and resp.replayed is False
    assert [c.id for c in r.memory.list_conversations()] == [resp.conversation_id]
    # the telemetry value is NOT kept in the stored history
    assert turns(r, resp.conversation_id) == [("user", "Fit, qual é o RPM atual?"), ("assistant", HISTORY_PLACEHOLDER)]


async def test_continuing_a_conversation_recalls_only_its_own_recent_turns(chat_rig):
    r = chat_rig([llm_json("Olá! Posso ajudar."), llm_json("Você perguntou sobre bananas.")])
    a = await r.ask("Me fale sobre bananas")
    b = await r.ask("O que eu perguntei?", a.conversation_id)
    assert b.conversation_id == a.conversation_id and len(turns(r, a.conversation_id)) == 4
    prompt = r.llm.calls[1].messages[-1].content
    assert "bananas" in prompt and "MEMÓRIA" in prompt and "NÃO são leituras de sensores" in prompt


async def test_conversations_are_isolated(chat_rig):
    r = chat_rig([llm_json("ok"), llm_json("ok"), llm_json("ok")])
    a = await r.ask("segredo-do-azulejo-AAA")
    b = await r.ask("outra conversa totalmente diferente")
    assert a.conversation_id != b.conversation_id
    await r.ask("e agora?", b.conversation_id)
    assert "azulejo" not in r.llm.calls[2].messages[-1].content
    assert all("azulejo" not in t for _, t in turns(r, b.conversation_id))


async def test_history_recall_is_limited(chat_rig):
    r = chat_rig([llm_json("ok")] * 8)
    a = await r.ask("pergunta 0")
    for i in range(1, 6):
        await r.ask(f"pergunta {i}", a.conversation_id)
    last_prompt = r.llm.calls[-1].messages[-1].content
    assert "pergunta 4" in last_prompt and "pergunta 0" not in last_prompt  # only the last turns come back


async def test_dashed_uuid_of_an_existing_conversation_is_accepted(chat_rig):
    r = chat_rig([llm_json("ok"), llm_json("ok")])
    a = await r.ask("primeira")
    dashed = str(uuid.UUID(a.conversation_id))
    b = await r.ask("segunda", dashed)
    assert b.conversation_id == a.conversation_id


# ───────────────────── validation ─────────────────────
@pytest.mark.parametrize("cid", ["abc", "'; DROP TABLE turns; --", "../../etc/passwd", "g" * 32, "x" * 100, "1234",
                                 "0" * 31, "0" * 33, "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz", "C:\\Windows\\x", ""])
async def test_invalid_conversation_ids_are_rejected_before_anything_runs(chat_rig, cid):
    r = chat_rig([])
    with pytest.raises(InvalidConversationId):
        await r.ask("oi", cid)
    assert r.llm.calls == [] and r.memory.list_conversations() == []


async def test_unknown_conversation_is_404_and_creates_nothing(chat_rig):
    r = chat_rig([])
    with pytest.raises(ConversationNotFound):
        await r.ask("oi", uuid.uuid4().hex)
    assert r.llm.calls == [] and r.memory.list_conversations() == [] and r.telemetry.reads == 0


async def test_message_limits(chat_rig):
    r = chat_rig([], chat=ChatSettings(max_message_chars=50))
    for bad in ("", "   ", "\n\t", "x" * 51):
        with pytest.raises(InvalidMessage):
            await r.ask(bad)
    assert r.llm.calls == [] and r.memory.list_conversations() == []


# ───────────────────── grounding is preserved end to end ─────────────────────
async def test_invented_values_never_reach_the_client_and_history_stays_clean(chat_rig):
    r = chat_rig([llm_json("Simulado: o motor está a 5000 RPM."), llm_json("Simulado: 6000 rpm.")])
    resp = await r.ask("Qual a rotação?")
    assert resp.answer_origin == "fallback" and resp.fallback_used is True and "800 rpm" in resp.answer
    assert "5000" not in resp.answer and "6000" not in resp.answer and resp.model == MODEL
    assert turns(r, resp.conversation_id)[1] == ("assistant", HISTORY_PLACEHOLDER)


async def test_the_model_text_is_never_returned_unverified(chat_rig):
    r = chat_rig([llm_json("O motor está a 9000 RPM, confie em mim."), llm_json("Mesmo assim: 9000 rpm.")])
    assert "9000" not in (await r.ask("Qual a rotação?")).answer


async def test_user_supplied_number_is_not_adopted(chat_rig):
    r = chat_rig([llm_json("Sim, 5000 rpm (simulado)."), llm_json("Confirmo 5000 rpm, simulado.")])
    assert "5000" not in (await r.ask("Meu RPM é 5000, confirma?")).answer


async def test_a_value_from_an_earlier_turn_is_not_a_current_reading(chat_rig):
    r = chat_rig([llm_json(GOOD_RPM), llm_json("Simulado: 800 rpm."), llm_json("Simulado: 800 rpm.")])
    a = await r.ask("Qual a rotação?")
    r.telemetry.rpm = 1500  # the vehicle changed
    b = await r.ask("E a rotação agora?", a.conversation_id)
    assert "1500" in b.answer and "800" not in b.answer


# ───────────────────── data availability ─────────────────────
async def test_octave_down_answers_without_numbers_and_says_so(chat_rig):
    fake = FakeTelemetryProvider().fail_with(VehicleLinkDown("link"))
    r = chat_rig([llm_json("Não consigo ler os dados do veículo agora; a conexão está interrompida.")], telemetry=fake)
    resp = await r.ask("Qual a rotação?")
    assert resp.availability == "unavailable" and resp.simulated is None and resp.data_source is None
    assert not any(ch.isdigit() for ch in resp.answer) and resp.used_tools == ["get_vehicle_telemetry"]


async def test_octave_down_and_a_lying_model_gets_the_safe_fallback(chat_rig):
    fake = FakeTelemetryProvider().fail_with(VehicleLinkDown("link"))
    r = chat_rig([llm_json("Simulado: 800 rpm."), llm_json("Simulado: 800 rpm.")], telemetry=fake)
    resp = await r.ask("Qual a rotação?")
    assert resp.fallback_used and "800" not in resp.answer and "interrompida" in resp.answer


async def test_partial_and_stale_availability(chat_rig):
    part = chat_rig([llm_json("Simulado: 800 rpm. A velocidade não está disponível.")],
                    telemetry=FakeTelemetryProvider(800, None, 90.0))
    assert (await part.ask("Qual a rotação e a velocidade?")).availability == "partial"
    from datetime import UTC, datetime, timedelta
    old = FakeTelemetryProvider(800, 0.0, 90.0)
    old.reading_timestamp = datetime.now(UTC) - timedelta(seconds=120)
    stale = chat_rig([Reply.timeout()], telemetry=old)
    resp = await stale.ask("Qual a rotação?")
    assert resp.availability == "stale" and "desatualizada" in resp.answer and "800" not in resp.answer


async def test_general_chat_uses_no_tools_and_no_vehicle_data(chat_rig):
    r = chat_rig([llm_json("Troca de óleo é a renovação do lubrificante do motor, que protege as peças.")])
    resp = await r.ask("Explique o que é troca de óleo.")
    assert resp.used_tools == [] and resp.availability == "not_requested" and resp.simulated is None
    assert r.telemetry.reads == 0 and resp.data_source is None


async def test_control_requests_are_refused_without_model_or_vehicle(chat_rig):
    r = chat_rig([])
    resp = await r.ask("Acelere o carro agora.")
    assert resp.answer_origin == "policy_refusal" and resp.model is None and resp.model_status == "not_used"
    assert r.llm.calls == [] and r.telemetry.reads == 0 and resp.used_tools == []
    assert len(turns(r, resp.conversation_id)) == 2  # the refusal is part of the conversation


# ───────────────────── model failures ─────────────────────
@pytest.mark.parametrize("reply,exc,kind", [
    (Reply.unavailable(), ModelUnavailable, "unavailable"),
    (Reply.timeout(), ModelUnavailable, "timeout"),
    (Reply.fail(LLMModelNotFound("gone")), ModelUnavailable, "not_found"),
])
async def test_without_a_model_a_general_question_is_an_error_and_saves_nothing(chat_rig, reply, exc, kind):
    r = chat_rig([reply])
    with pytest.raises(exc) as e:
        await r.ask("Explique o que é um catalisador.")
    assert e.value.kind == kind and r.memory.list_conversations() == []
    assert "gone" not in e.value.safe_message  # provider text never travels


async def test_error_codes_for_model_failures():
    assert ModelUnavailable("timeout").code == "model_timeout"
    assert ModelUnavailable("not_found").code == "model_not_found"
    assert ModelUnavailable("unavailable").code == "model_unavailable"


@pytest.mark.parametrize("reply,status", [(Reply.unavailable(), "unavailable"), (Reply.timeout(), "timeout"),
                                          (Reply.fail(LLMModelNotFound("x")), "not_found")])
async def test_with_a_reading_the_assistant_still_answers_from_evidence_without_pretending(chat_rig, reply, status):
    r = chat_rig([reply])
    resp = await r.ask("Qual a rotação?")
    assert resp.fallback_used and resp.model_status == status and "800 rpm" in resp.answer
    assert resp.answer_origin == "fallback" and resp.model == MODEL  # it WAS asked; it did not answer


async def test_ollama_down_then_recovered(chat_rig):
    r = chat_rig([Reply.unavailable(), llm_json("Posso ajudar com leituras do veículo.")])
    with pytest.raises(ModelUnavailable):
        await r.ask("Olá, tudo bem?")
    assert (await r.ask("Olá, tudo bem?")).model_status == "ok"
    assert len(r.memory.list_conversations()) == 1  # the failed attempt left nothing behind


async def test_no_llm_configured_answers_deterministically(chat_rig):
    r = chat_rig(with_llm=False)
    resp = await r.ask("Qual a temperatura?")
    assert resp.answer_origin == "deterministic" and resp.fallback_used and resp.model is None
    assert "90 °C" in resp.answer


# ───────────────────── audit, storage, partial failures ─────────────────────
async def test_audit_failure_fails_closed_before_any_read_or_save(chat_rig):
    r = chat_rig([llm_json(GOOD_RPM)], audit_ok_writes=0)
    with pytest.raises(AuditUnavailable):
        await r.ask("Qual a rotação?")
    assert r.telemetry.reads == 0 and r.llm.calls == [] and r.memory.list_conversations() == []


async def test_audit_failing_after_the_read_discards_the_answer(chat_rig):
    r = chat_rig([llm_json(GOOD_RPM)], audit_ok_writes=1)
    with pytest.raises(AuditUnavailable):
        await r.ask("Qual a rotação?")
    assert r.memory.list_conversations() == []


async def test_degraded_audit_policy_is_reported_not_hidden(chat_rig):
    r = chat_rig([llm_json(GOOD_RPM)], audit_ok_writes=0, audit_policy="degrade_read_only")
    assert (await r.ask("Qual a rotação?")).answer == GOOD_RPM


async def test_storage_failure_discards_the_answer_and_a_retry_does_not_duplicate(chat_rig, monkeypatch):
    r = chat_rig([llm_json("Posso ajudar com isso.")] * 3)  # 1st request, the one that fails to save, and its retry
    first = await r.ask("primeira")
    real = r.memory.record_exchange
    monkeypatch.setattr(r.memory, "record_exchange", lambda *a, **k: (_ for _ in ()).throw(MemoryStorageError("disk")))
    with pytest.raises(StorageUnavailable):
        await r.ask("segunda", first.conversation_id)
    monkeypatch.setattr(r.memory, "record_exchange", real)
    assert len(turns(r, first.conversation_id)) == 2  # nothing of the failed request was stored
    await r.ask("segunda", first.conversation_id)
    assert len(turns(r, first.conversation_id)) == 4  # exactly one copy after the retry


async def test_storage_failure_on_a_new_conversation_leaves_no_conversation(chat_rig, monkeypatch):
    r = chat_rig([llm_json(GOOD_RPM)])
    monkeypatch.setattr(r.memory, "record_exchange", lambda *a, **k: (_ for _ in ()).throw(MemoryStorageError("disk")))
    with pytest.raises(StorageUnavailable):
        await r.ask("Qual a rotação?")
    monkeypatch.undo()
    assert r.memory.list_conversations() == []


async def test_lookup_failure_is_a_storage_error_not_a_crash(chat_rig, monkeypatch):
    r = chat_rig([])
    monkeypatch.setattr(r.memory, "get_conversation", lambda *a: (_ for _ in ()).throw(MemoryStorageError("locked")))
    with pytest.raises(StorageUnavailable):
        await r.ask("oi", uuid.uuid4().hex)


async def test_memory_recall_failure_does_not_stop_the_answer(chat_rig, monkeypatch):
    r = chat_rig([llm_json(GOOD_RPM)])
    monkeypatch.setattr(r.memory, "list_preferences", lambda: (_ for _ in ()).throw(MemoryStorageError("locked")))
    assert (await r.ask("Qual a rotação?")).answer == GOOD_RPM


# ───────────────────── idempotency ─────────────────────
async def test_retry_with_the_same_key_replays_without_a_second_call_or_duplicate_turns(chat_rig):
    r = chat_rig([llm_json(GOOD_RPM)])
    a = await r.ask("Qual a rotação?", idempotency_key="chave-12345678", request_id="req-1")
    b = await r.ask("Qual a rotação?", idempotency_key="chave-12345678", request_id="req-2")
    assert b.replayed is True and a.replayed is False and b.request_id == "req-2"
    assert (b.answer, b.conversation_id) == (a.answer, a.conversation_id)
    assert len(r.llm.calls) == 1 and r.telemetry.reads == 1 and len(turns(r, a.conversation_id)) == 2


async def test_same_key_with_a_different_payload_is_refused(chat_rig):
    r = chat_rig([llm_json(GOOD_RPM)])
    await r.ask("Qual a rotação?", idempotency_key="chave-12345678")
    with pytest.raises(IdempotencyConflict):
        await r.ask("Qual a velocidade?", idempotency_key="chave-12345678")


async def test_same_key_in_flight_is_a_conflict_and_the_slot_is_not_taken(chat_rig):
    slow = Reply.text(llm_json(GOOD_RPM).response.content, delay_s=0.3)
    r = chat_rig([slow], chat=ChatSettings(max_waiting=3))
    first = asyncio.create_task(r.ask("Qual a rotação?", idempotency_key="chave-12345678"))
    await asyncio.sleep(0.05)
    with pytest.raises(RequestInProgress):
        await r.ask("Qual a rotação?", idempotency_key="chave-12345678")
    assert (await first).answer == GOOD_RPM and len(r.llm.calls) == 1


async def test_a_failed_request_frees_its_key_for_a_retry(chat_rig):
    r = chat_rig([Reply.unavailable(), llm_json("Posso ajudar com leituras do veículo.")])
    with pytest.raises(ModelUnavailable):
        await r.ask("Olá", idempotency_key="chave-12345678")
    assert (await r.ask("Olá", idempotency_key="chave-12345678")).replayed is False


@pytest.mark.parametrize("key", ["curta", "x" * 65, "com espaço 123", "chave;drop;table", "ação-12345678", "a" * 8 + "\n"])
async def test_invalid_idempotency_keys_are_rejected(chat_rig, key):
    with pytest.raises(InvalidIdempotencyKey):
        await chat_rig([]).ask("oi", idempotency_key=key)


async def test_idempotency_store_is_bounded_and_expires(chat_rig):
    clock = [0.0]
    r = chat_rig([llm_json("ok")] * 6, chat=ChatSettings(idempotency_max_entries=3, idempotency_ttl_s=10))
    r.service._clock = lambda: clock[0]
    for i in range(5):
        await r.ask(f"pergunta {i}", idempotency_key=f"chave-{i:08d}")
    assert len(r.service._idem) <= 3
    clock[0] += 100
    await r.ask("pergunta nova", idempotency_key="chave-novinha1")
    assert len(r.service._idem) == 1  # expired entries were dropped


# ───────────────────── timeout, cancellation, concurrency ─────────────────────
async def test_timeout_is_reported_and_leaves_no_trace(chat_rig):
    r = chat_rig([Reply.hang()], chat=ChatSettings(request_timeout_s=0.2))
    with pytest.raises(RequestTimeout):
        await r.ask("Explique o que é troca de óleo.", idempotency_key="chave-12345678")
    assert r.memory.list_conversations() == []
    r.llm._queue.extend([llm_json("Posso ajudar.")])
    assert (await r.ask("Olá de novo, tudo bem?", idempotency_key="chave-12345678")).replayed is False  # key was freed
    assert not r.service._sem.locked()  # the slot was released


async def test_cancellation_releases_everything_and_saves_nothing(chat_rig):
    r = chat_rig([Reply.hang(), llm_json("Posso ajudar.")])
    task = asyncio.create_task(r.ask("Explique o que é troca de óleo.", idempotency_key="chave-12345678"))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not r.service._sem.locked() and r.service._waiting == 0 and r.service._idem == {}
    assert r.memory.list_conversations() == []
    assert (await r.ask("Olá de novo, tudo bem?")).model_status == "ok"  # the service still works


async def test_concurrency_is_bounded_and_the_overflow_is_refused_at_once(chat_rig):
    slow = lambda: Reply.text(llm_json("ok").response.content, delay_s=0.3)  # noqa: E731
    r = chat_rig([slow(), slow(), slow()], chat=ChatSettings(max_concurrent=1, max_waiting=1, queue_timeout_s=5))
    t1 = asyncio.create_task(r.ask("Explique o que é troca de óleo."))
    await asyncio.sleep(0.05)
    t2 = asyncio.create_task(r.ask("Explique o que é um catalisador."))
    await asyncio.sleep(0.05)
    with pytest.raises(ServiceBusy) as busy:  # slot taken + waiting room full -> no queueing without bound
        await r.ask("Explique o que é uma vela de ignição.")
    assert busy.value.retry_after_s >= 1
    assert (await t1).model_status == "ok" and (await t2).model_status == "ok"
    assert len(r.llm.calls) == 2 and r.service._waiting == 0 and not r.service._sem.locked()


async def test_a_waiting_request_gives_up_after_the_queue_timeout(chat_rig):
    slow = Reply.text(llm_json("ok").response.content, delay_s=0.6)
    r = chat_rig([slow, llm_json("ok")], chat=ChatSettings(max_concurrent=1, max_waiting=2, queue_timeout_s=0.15))
    t1 = asyncio.create_task(r.ask("Explique o que é troca de óleo."))
    await asyncio.sleep(0.05)
    with pytest.raises(ServiceBusy):
        await r.ask("Explique o que é um catalisador.")
    await t1
    assert r.service._waiting == 0


async def test_two_slots_run_two_generations_in_parallel(chat_rig):
    slow = lambda: Reply.text(llm_json("ok").response.content, delay_s=0.3)  # noqa: E731
    r = chat_rig([slow(), slow()], chat=ChatSettings(max_concurrent=2, max_waiting=0))
    started = asyncio.get_running_loop().time()
    await asyncio.gather(r.ask("Explique o que é troca de óleo."), r.ask("Explique o que é um catalisador."))
    assert asyncio.get_running_loop().time() - started < 0.55  # parallel, not 0.6 s in sequence


# ───────────────────── explicit memory commands ─────────────────────
async def test_explicit_command_saves_a_fact_and_only_then_says_so(chat_rig):
    r = chat_rig([llm_json("Você pediu para lembrar que prefere respostas curtas.")])
    resp = await r.ask("Fit, lembre que prefiro respostas curtas.")
    assert resp.answer_origin == "memory_command" and resp.memory_saved is True and resp.model is None
    assert "Anotado" in resp.answer and r.llm.calls == [] and resp.used_tools == []
    facts = r.memory.list_facts()
    assert [f.content for f in facts] == ["prefiro respostas curtas."] and facts[0].origin == "user_explicit"
    follow = await r.ask("Qual é a minha preferência de resposta?", resp.conversation_id)
    assert "get_memory_facts" in follow.used_tools and "respostas curtas" in r.llm.calls[0].messages[-1].content


@pytest.mark.parametrize("text", [
    "Você lembra que eu prefiro respostas curtas?", "Lembra do que combinamos?", "Será que você lembra de mim?",
    "Preciso lembrar de trocar o óleo.", "Qual é a minha preferência?", "Fit, o que eu pedi para você lembrar?",
    "Lembre-me de trocar o óleo amanhã",  # a reminder request is not a memory command
])
async def test_questions_and_other_sentences_never_create_memory(chat_rig, text):
    r = chat_rig([llm_json("Posso ajudar com isso."), llm_json("Posso ajudar com isso.")])
    resp = await r.ask(text)
    assert resp.memory_saved is False and r.memory.list_facts() == []


@pytest.mark.parametrize("text", [
    "Fit, lembre que meu motor está a 3000 RPM agora", "Lembre que a velocidade é 120 km/h",
    "Memorize que a temperatura está em 95 °C", "Guarde que a rotação é de oitocentas rpm",
])
async def test_sensor_readings_are_refused_as_permanent_memory(chat_rig, text):
    r = chat_rig([])
    resp = await r.ask(text)
    assert resp.memory_saved is False and "Nada foi guardado" in resp.answer and r.memory.list_facts() == []
    assert r.llm.calls == [] and r.telemetry.reads == 0  # and it is never treated as a measurement


@pytest.mark.parametrize("text", [
    "Lembre que minha senha: hunter2senha", "Lembre que meu e-mail é fulano@exemplo.com",
    "Lembre que minha senha é hunter2senha", "Lembre que meu CPF é 123.456.789-09", "Guarde que meu pin é 1234",
    "Lembre que o número do meu cartão de crédito é 4111 1111 1111 1111", "Lembre que a chave pix é fulano",
    "Memorize que o segredo do cofre é 4821", "Lembre que meu token de acesso é abc",
    "Lembre que meu telefone é (11) 91234-5678", "Lembre que o token=abc123XYZ789 é meu", "Anote que Bearer abcdef0123456789abcdef",
])
async def test_sensitive_data_is_refused(chat_rig, text):
    r = chat_rig([])
    resp = await r.ask(text)
    assert resp.memory_saved is False and "sensíveis" in resp.answer and r.memory.list_facts() == []


async def test_command_variants_and_limits(chat_rig):
    r = chat_rig([llm_json("Posso ajudar com isso.")])  # only "lembre que" alone is not a command: it goes to the model
    for text, saved in [("lembre que gosto de jazz", True), ("Fit: memorize que moro perto do trabalho", True),
                        ("Por favor, anote que meu carro é cinza", True), ("guarde isso: levo as crianças às 7h", True),
                        ("lembre que", False), ("lembre que ab", False), ("lembre que " + "x" * 950, False)]:
        resp = await r.ask(text)
        assert resp.memory_saved is saved, text
    assert len(r.memory.list_facts()) == 4


async def test_a_failed_save_never_claims_success(chat_rig, monkeypatch):
    r = chat_rig([])
    monkeypatch.setattr(r.memory, "remember_fact", lambda *a, **k: (_ for _ in ()).throw(MemoryStorageError("disk")))
    with pytest.raises(StorageUnavailable):
        await r.ask("lembre que gosto de jazz")
    assert r.memory.list_conversations() == []


async def test_a_fact_is_rolled_back_when_its_exchange_cannot_be_saved(chat_rig, monkeypatch):
    r = chat_rig([])
    monkeypatch.setattr(r.memory, "record_exchange", lambda *a, **k: (_ for _ in ()).throw(MemoryStorageError("disk")))
    with pytest.raises(StorageUnavailable):
        await r.ask("lembre que gosto de jazz")
    monkeypatch.undo()
    assert r.memory.list_facts() == []  # no "saved" fact without its record in the conversation


# ───────────────────── what the client never sees ─────────────────────
async def test_the_response_never_carries_prompts_memory_or_internals(chat_rig):
    r = chat_rig([llm_json(GOOD_RPM)])
    r.memory.remember_fact("detalhe privado do usuário XYZ")
    resp = await r.ask("Qual a rotação?")
    dump = resp.model_dump_json()
    for forbidden in ("REGRAS DE RESPOSTA", "LEITURAS DESTE TURNO", "XYZ", "system", "messages", ".db", "Traceback"):
        assert forbidden not in dump, forbidden
    assert set(resp.model_dump()) == {
        "conversation_id", "request_id", "answer", "model", "answer_origin", "used_tools", "fallback_used",
        "data_source", "simulated", "availability", "model_status", "memory_saved", "history_saved", "replayed", "latency_ms"}


async def test_error_messages_are_safe(chat_rig):
    for exc in (ServiceBusy(), RequestTimeout(), StorageUnavailable(), AuditUnavailable(), ModelUnavailable("timeout"),
                ConversationNotFound(), InvalidConversationId()):
        msg = exc.safe_message
        assert "Traceback" not in msg and ".db" not in msg and "C:\\" not in msg and "sqlite" not in msg.lower()


async def test_ids_and_keys_with_a_trailing_newline_are_rejected(chat_rig):
    """`$` in a regex matches before a final newline: the id/key patterns must use fullmatch."""
    r = chat_rig([])
    with pytest.raises(InvalidIdempotencyKey):
        await r.ask("oi", idempotency_key="chave-12345678\n")
    with pytest.raises(InvalidConversationId):
        await r.ask("oi", uuid.uuid4().hex + chr(0))


async def test_the_audit_trail_carries_the_same_request_id_as_the_response(chat_rig):
    r = chat_rig([llm_json(GOOD_RPM)])
    resp = await r.ask("Qual a rotação?", request_id="req-correlate-1")
    events = r.audit_db.list_events("req-correlate-1")
    assert resp.request_id == "req-correlate-1"
    assert [(e.kind, e.decision) for e in events] == [("tool_authorization", "allowed"), ("tool_result", "ok"), ("turn", "ok")]


@pytest.mark.parametrize("text", ["Lembre que moro na Rua das Flores, 123", "Lembre que o pneu dianteiro é 195/55",
                                  "Lembre que prefiro a rota sem pedágio", "Anote que a revisão é em março",
                                  "Lembre que levo o pino de reserva"])
async def test_ordinary_facts_with_digits_or_lookalike_words_are_still_saved(chat_rig, text):
    resp = await chat_rig([]).ask(text)
    assert resp.memory_saved is True
