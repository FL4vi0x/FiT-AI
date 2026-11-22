"""Audit of the tool-less relaxation of the judgment rules (`_PRESENT_STATE`) — P7 stabilisation.

Policy under test: a CURRENT statement about the vehicle's state needs valid evidence from the CURRENT turn. A
turn that read no vehicle data may still explain how cars work (definitions, advice, hypotheticals), but it must never
assert, speculate about, or confirm the state of THIS car — in any phrasing, tense or register.

Before this audit the relaxation exempted every clause that lacked a handful of "present-tense" words, so
"A temperatura do motor continua alta." or "O motor pode estar superaquecendo." passed on a turn with no reading,
while the same sentences were rejected as soon as a tool had run. The default is now fail-closed: a clause is exempt
only when it carries an explicit generic/explanatory marker AND no present-state marker.
"""
from __future__ import annotations

import pytest
from grounding_helpers import ans, bundle, live, status_outcome, telemetry_outcome

from fit_ai.grounding import EvidenceBundle, EvidenceError, build_evidence, verify

# the ten statements of the audit brief
BRIEF = [
    "Seu carro está parado.", "Você está a 80 km/h.", "O motor está funcionando normalmente.",
    "A temperatura está segura.", "Seu motor está superaquecendo.", "O carro estava a 90 km/h ontem.",
    "Você me disse que estava a 120 km/h, então essa é sua velocidade atual.", "A leitura anterior continua válida.",
    "Seu veículo está ligado.", "O motor parece estar em boas condições.",
]
# the same concepts with no "está/seu/agora": tense, aspect, register, speculation, informal Brazilian Portuguese
VARIANTS = [
    "A temperatura do motor continua alta.", "O motor continua superaquecendo.", "A temperatura é alta.",
    "O motor é saudável.", "O motor funciona normalmente.", "A rotação do motor segue estável.",
    "A velocidade permanece constante.", "O carro anda bem.", "O motor parece saudável.",
    "A temperatura do líquido de arrefecimento fica alta.", "Tá tudo certo com o motor.", "O motor ficou quente.",
    "A rotação continua alta.", "O motor segue quente.", "Os pneus continuam calibrados.",
    "A pressão dos pneus permanece boa.", "O óleo é de boa qualidade.", "A bateria parece fraca.",
    "O motor esteve superaquecendo ontem.", "A leitura de ontem ainda vale.", "Os dados anteriores continuam atuais.",
    "Seu carro está desligado.", "O motor está ligado.", "Tudo normal com o seu carro.",
    "O motor pode estar superaquecendo.", "A temperatura deve estar alta.", "O carro tá bem, pode ficar tranquilo.",
    "O ponteiro da temperatura está no vermelho.", "Parece que o motor está esquentando.",
]
# numbers and states with units spelled out, quoted text, and a user claim turned into a measurement
NUMBERS_AND_QUOTES = [
    "Você está a oitenta quilômetros por hora.", "O motor está a três mil rotações por minuto.",
    "A temperatura está em oitenta graus.", "O motor está a oitocentas rotações.",
    "Você disse: 'o motor está superaquecendo'. Então ele está superaquecendo.",
    "O RPM que você mencionou é o atual: 5000.",
]

NO_CURRENT_EVIDENCE = {
    "no_tool": lambda: EvidenceBundle("turn-1"),
    "tool_down": lambda: bundle(telemetry_outcome(ok=False)),
    "stale_reading": lambda: live(age_s=60.0),
    "status_only": lambda: bundle(status_outcome(simulated=True)),
}


@pytest.mark.parametrize("kind", NO_CURRENT_EVIDENCE)
@pytest.mark.parametrize("text", BRIEF + VARIANTS + NUMBERS_AND_QUOTES)
def test_no_current_statement_about_the_car_survives_without_current_evidence(kind, text):
    v = verify(ans(text), NO_CURRENT_EVIDENCE[kind]())
    assert not v.passed, f"[{kind}] accepted: {text!r}"


def test_evidence_from_an_earlier_turn_cannot_even_enter_the_bundle():
    # "a tool ran in the previous turn" is not evidence for this one: refused structurally, before any verification
    with pytest.raises(EvidenceError):
        EvidenceBundle.of("turn-2", [build_evidence(telemetry_outcome(), "turn-1")], 10.0)


def test_partial_fields_do_not_license_the_missing_ones():
    b = live(speed=None, temp=None)  # only rpm was read
    for t in ("Simulado: seu carro está parado.", "Simulado: a temperatura continua alta.",
              "Simulado: o motor pode estar superaquecendo.", "Simulado: você está a 80 km/h."):
        assert not verify(ans(t), b).passed, t


def test_a_current_reading_does_not_make_an_opinion_or_a_contradiction_acceptable():
    b = live(rpm=800, speed=0.0, temp=90.0)  # simulated, valid, current
    for t in ("Simulado: você está a 80 km/h.", "Simulado: a temperatura está segura.",
              "Simulado: o motor continua superaquecendo.", "Simulado: o motor parece estar em boas condições.",
              "Simulado: ontem sua velocidade era 0 km/h.",
              "Simulado: você me disse que estava a 120 km/h, então essa é sua velocidade atual."):
        assert not verify(ans(t), b).passed, t


@pytest.mark.parametrize("text", [
    "Simulado: seu carro está parado.", "No simulador, a velocidade é 0 km/h.",
    "No simulador, o motor está a 800 RPM.", "Dados simulados: a temperatura do líquido de arrefecimento é 90 °C.",
])
def test_statements_the_current_reading_supports_still_pass(text):
    assert verify(ans(text), live(rpm=800, speed=0.0, temp=90.0)).passed


@pytest.mark.parametrize("text", [
    "Temperatura alta no motor pode danificar o cabeçote.",
    "Se o motor estiver superaquecendo, pare o carro em local seguro.",
    "O líquido de arrefecimento evita o superaquecimento do motor.",
    "A troca de óleo mantém o motor bem lubrificado.",
    "Hipoteticamente, um motor superaquecendo precisa ser desligado.",
    'O manual diz: "temperatura alta no motor pode danificar o cabeçote".',
    "Normalmente, o óleo deve ser trocado a cada seis meses.",
    "Pneus calibrados corretamente garantem um desgaste uniforme e mais segurança.",
])
def test_legitimate_explanations_still_pass_on_a_turn_with_no_vehicle_data(text):
    assert verify(ans(text), EvidenceBundle("turn-1")).passed, text


def test_a_generic_marker_cannot_launder_a_claim_about_this_car():
    # the exemption needs a generic marker AND the absence of any present-state marker
    for t in ("O motor pode estar superaquecendo.", "A temperatura deve estar alta.",
              "Se quiser saber, o motor está superaquecendo.", "O motor continua quente, caso queira saber."):
        assert not verify(ans(t), EvidenceBundle("turn-1")).passed, t


# ───────── a denial must not launder what comes after it (found by this audit) ─────────
# `_DENIAL` used to excuse the WHOLE clause, and a comma does not end a clause: "Não consigo ler os dados, acelerei o
# motor." passed the verifier on every kind of evidence, even with a valid reading. The denial now covers only its own
# comma/new-subject segment.
LAUNDERING = [
    "Não consigo ler os dados, o motor está superaquecendo.",
    "Não vou estimar valores e o motor continua superaquecendo.",
    "Não tenho acesso aos sensores, mas o motor está superaquecendo.",
    "Não consigo dizer o valor; o motor está superaquecendo.",
    "Não consegui ler os dados, porém o motor está bem.",
    "Sem acesso aos sensores, o motor está superaquecendo.",
    "Não posso confirmar números, o carro está ligado e o motor está saudável.",
    "Não consigo ler, e a temperatura do motor está alta.",
    "Não consigo ler os dados, acelerei o motor.",                       # control claim
    "Não tenho acesso, usei o GPS e a internet para confirmar.",          # capability that does not exist
    "Não consigo ler os dados, o carro está parado.",                     # state claim
    "Não sei dizer a velocidade, ontem o carro estava parado.",           # past state
]


@pytest.mark.parametrize("kind", ["no_tool", "tool_down", "live_reading"])
@pytest.mark.parametrize("text", LAUNDERING)
def test_a_denial_does_not_excuse_the_claim_that_follows_it(kind, text):
    b = {"no_tool": lambda: EvidenceBundle("turn-1"), "tool_down": lambda: bundle(telemetry_outcome(ok=False)),
         "live_reading": lambda: live(speed=50.0)}[kind]()  # the car is moving: "parado" is also wrong
    assert not verify(ans(text), b).passed, f"[{kind}] accepted: {text!r}"


@pytest.mark.parametrize("text", [
    "Não consigo saber se o motor está superaquecendo.",
    "Não consigo dizer se a temperatura está alta ou baixa.",
    "Não tenho acesso aos sensores do carro, por isso não sei dizer se o motor está bem.",
    "Simulado: 90 °C. Não tenho como dizer se isso é normal para o seu carro.",
    "Não consegui ler os dados do veículo agora: ocorreu uma falha ao ler os dados. Não vou estimar valores.",
    "A última leitura tem 45 s e está desatualizada, por isso não vou apresentá-la como valor atual.",
])
def test_honest_denials_keep_passing(text):
    b = live() if text.startswith("Simulado") else EvidenceBundle("turn-1")
    assert not any(c in verify(ans(text), b).codes
                   for c in ("unverifiable_judgment", "claims_vehicle_control", "temporal_misattribution")), text


def test_denying_access_to_the_state_is_still_the_honest_answer():
    for t in ("Não consigo saber se o motor está superaquecendo.", "Não tenho a leitura de ontem.",
              "A leitura anterior não está disponível."):
        assert verify(ans(t), EvidenceBundle("turn-1")).passed, t
