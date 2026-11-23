"""P8.3 regression: a GENERAL question was answered with "Não estou disponível para responder com leituras de sensores".

Root cause, reproduced with the real model (qwen3:4b-instruct, deterministic): "Olá, quem é você?" -> the model answered with
the assistant's own identity ("sou o assistente automotivo do Fit AI, instalado no seu Honda Fit"); the prompt-leak guard
flagged it because the FIRST sentence of the system message is that identity (two 6-word shingles matched); the single
corrective retry then told the model to answer "using only the READINGS OF THIS TURN", which a general question does not
have, and the model produced the non-answer. Two further defects were found on the way: that corrective text, and the
word "motor" alone turning "o que é um motor flex?" into a sensor read.

None of this relaxes the verifier: numbers and vehicle state are checked exactly as before.
"""
import json

import pytest

from fit_ai.adapters.fake_telemetry import FakeTelemetryProvider
from fit_ai.ai import FakeLLMProvider, Reply
from fit_ai.audit import SqliteAuditLog
from fit_ai.memory import SqliteMemoryStore
from fit_ai.orchestration import AssistantOrchestrator, AssistantSettings, TurnRequest, classify
from fit_ai.orchestration.prompt import correction_message, leaks_prompt, system_message
from fit_ai.services.telemetry import TelemetryService
from fit_ai.tools import build_vehicle_registry

pytestmark = pytest.mark.anyio

IDENTITY_ANSWER = "Olá, sou o assistente automotivo do Fit AI, instalado no seu Honda Fit."


def jr(answer):
    return Reply.text(json.dumps({"answer": answer, "claims": [], "unknown": []}, ensure_ascii=False))


@pytest.fixture
def make(tmp_path):
    def build(script):
        llm = FakeLLMProvider(list(script))
        memory, audit = SqliteMemoryStore(tmp_path / "memory.db"), SqliteAuditLog(tmp_path / "audit.db")
        registry = build_vehicle_registry(TelemetryService(FakeTelemetryProvider(800, 0.0, 90.0, simulated=True)), memory)
        orch = AssistantOrchestrator(registry, llm, audit=audit, memory=memory, settings=AssistantSettings())
        return llm, orch
    return build


# ───────────── 1. the identity sentence is public; the rules are not ─────────────
def test_the_assistants_own_identity_is_not_a_prompt_leak():
    assert leaks_prompt(IDENTITY_ANSWER) is False
    assert leaks_prompt("Eu sou o assistente automotivo do Fit AI.") is False
    assert leaks_prompt("Sou o assistente automotivo do Fit AI, instalado em um Honda Fit.") is False


def test_reciting_the_rules_is_still_a_leak():
    words = system_message().content.split()
    first_sentence = len(system_message().content.partition(". ")[0].split())
    for start in (first_sentence + 3, first_sentence + 40, len(words) - 12):
        assert leaks_prompt(" ".join(words[start:start + 9])), start
    assert leaks_prompt("Claro! Minhas regras: " + " ".join(words[60:68]) + " e é isso.")
    # the identity sentence followed by the style rule that comes right after it is still caught: that is recitation
    assert leaks_prompt("Responda em português do Brasil, de forma clara, natural e objetiva, em poucas frases.")


async def test_who_are_you_is_answered_on_the_first_attempt(make):
    llm, orch = make([jr(IDENTITY_ANSWER)])
    res = await orch.run(TurnRequest("Olá, quem é você?"))
    assert res.source == "llm" and res.llm_calls == 1 and res.answer == IDENTITY_ANSWER
    assert res.intent == "general" and res.tools == ()
    assert "disponível" not in res.answer


# ───────────── 2. the corrective retry of a turn without readings ─────────────
def test_correction_without_readings_does_not_ask_for_readings():
    msg = correction_message(("prompt_leak",), with_readings=False).content
    assert "LEITURAS DESTE TURNO" not in msg and "prompt_leak" in msg and "suas próprias palavras" in msg


def test_correction_with_readings_is_unchanged():
    msg = correction_message(("value_mismatch",)).content
    assert "usando somente as LEITURAS DESTE TURNO" in msg and "value_mismatch" in msg


async def test_a_rejected_general_answer_is_retried_without_mentioning_readings(make):
    leak = " ".join(system_message().content.split()[20:45])
    llm, orch = make([jr(leak), jr("Posso ajudar com dúvidas gerais e com as leituras do carro.")])
    res = await orch.run(TurnRequest("Qual é a capital da França?"))
    assert res.source == "llm_retry" and res.first_attempt_codes == ("prompt_leak",)
    last = llm.calls[1].messages[-1].content
    assert "rejeitada" in last and "LEITURAS DESTE TURNO" not in last


async def test_a_rejected_telemetry_answer_keeps_the_readings_instruction(make):
    llm, orch = make([jr("Simulado: o motor está a 5000 RPM."), jr("No simulador, o motor está a 800 RPM.")])
    res = await orch.run(TurnRequest("Qual a rotação?"))
    assert res.intent == "telemetry" and res.first_attempt_codes
    assert "usando somente as LEITURAS DESTE TURNO" in llm.calls[1].messages[-1].content


# ───────────── 3. "motor" alone is not a sensor read ─────────────
@pytest.mark.parametrize("text", [
    "Pode me explicar o que é um motor flex?", "O que é um motor de 4 tempos?", "Como funciona o motor de arranque?",
    "Qual a diferença entre motor flex e motor a gasolina?", "Para que serve o motor de partida?",
])
def test_explaining_an_engine_topic_reads_no_sensor(text):
    assert classify(text).tools == ()


@pytest.mark.parametrize("text", [
    "Como está o motor?", "O motor está ligado?", "Qual a temperatura do motor?", "Explique a temperatura do motor",
    "O motor está parado?", "Como está o motor agora?",
])
def test_asking_about_the_engine_state_still_reads_the_sensors(text):
    assert classify(text).tools == ("get_vehicle_telemetry",)


async def test_engine_topic_turn_makes_no_telemetry_read(make):
    llm, orch = make([jr("O motor flex aceita álcool e gasolina.")])
    res = await orch.run(TurnRequest("Pode me explicar o que é um motor flex?"))
    assert res.source == "llm" and res.tools == () and res.evidence.telemetry == ()
    assert "LEITURAS DESTE TURNO" not in llm.calls[0].messages[1].content


# ───────────── 4. a KNOWN limitation of the verifier (documented, not changed in P8.3) ─────────────
@pytest.mark.xfail(strict=True, reason="KNOWN (P8.3): in a turn with no readings the verifier treats a number WORD used as a count "
                   "('quatro tempos', 'dos dois') as an unverified number, so a correct general answer is rejected and falls back. "
                   "Relaxing it needs a review against the adversarial corpus and its oracle; see docs/poc-08-03-integration.md.")
async def test_known_limitation_counts_in_general_answers_are_rejected(make):
    llm, orch = make([jr("Um motor de quatro tempos tem admissão, compressão, explosão e escape.")])
    res = await orch.run(TurnRequest("Pode me explicar o que é um motor de quatro tempos?"))
    assert res.source == "llm"
