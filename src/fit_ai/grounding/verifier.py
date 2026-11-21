"""Deterministic answer verifier. Independent of the LLM, fail-closed.

An answer is accepted only if every statement about vehicle telemetry in it can be tied, by code, to a
valid reading obtained in the CURRENT turn. It checks the structured `claims` AND the free text (a number in
the text with no claim is still a claim). Whatever it cannot verify, it rejects:

    codes: no_evidence, evidence_unavailable, stale_evidence, field_missing, value_mismatch, unit_mismatch,
           unverified_number, unsupported_sensor, unsupported_sensor_claim, unverifiable_judgment,
           state_claim_mismatch, temporal_misattribution, negated_value_mismatch,
           claims_unavailable_capability, unreadable_number, not_portuguese, simulation_not_disclosed, simulation_misrepresented, claims_vehicle_control,
           turn_mixing, empty_answer

Known limits (see numbers.py too): it is a lexical/positional analysis, not language understanding. A sentence
it cannot parse is not "assumed fine": numbers it cannot attach to evidence are rejected, and judgments about
sensor values (normal/alta/superaquecendo...) are rejected because no approved thresholds exist in P6.
Consequently some correct answers are rejected (false positives); the deterministic fallback covers them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from fit_ai.grounding.evidence import CANONICAL_UNIT, SENSOR_FIELDS, EvidenceBundle
from fit_ai.grounding.numbers import (
    clauses,
    orphan_units,
    extract_mentions,
    matches,
    normalise,
)
from fit_ai.grounding.response import StructuredAnswer


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str = ""


@dataclass(frozen=True)
class Verdict:
    passed: bool
    violations: tuple[Violation, ...] = ()
    verified: dict[str, float] = field(default_factory=dict)  # field -> value the answer stated and evidence confirmed

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(v.code for v in self.violations))


# ───────────────────────── lexicons (normalised: lower-case, no accents) ─────────────────────────
_UNIT_ALIASES = {"rpm": "rpm", "km/h": "km/h", "kmh": "km/h", "°c": "°C", "ºc": "°C", "c": "°C", "celsius": "°C",
                 "°C": "°C"}
_TELEMETRY_TERMS = frozenset({"rotacao", "rotacoes", "rpm", "giro", "giros", "velocidade", "kmh", "temperatura",
                              "arrefecimento", "graus", "celsius", "parado", "parada", "movimento", "motor",
                              "superaquecendo", "superaquecimento", "superaquecido", "superaquecida",
                              "esquentando", "esquentou", "aquecendo"})
_JUDGMENT = frozenset({
    "normal", "normais", "anormal", "anormais", "alta", "alto", "altas", "altos", "baixa", "baixo", "baixas",
    "baixos", "elevada", "elevado", "elevadas", "elevados", "excessiva", "excessivo", "superaquecendo",
    "superaquecimento", "superaquecido", "superaquecida", "esquentando", "esquentou", "aquecendo", "fria", "frio",
    "gelado", "quente", "quentes", "saudavel", "ideal", "adequada", "adequado", "boa", "bom", "ok", "otima",
    "otimo", "perigosa", "perigoso", "preocupante", "estavel", "instavel", "constante", "oscilando", "subindo",
    "caindo", "acelerada", "acelerado", "lenta", "lento", "regular", "tranquila", "tranquilo", "critica", "critico",
    "segura", "seguro", "bem", "mal", "funcionando", "problema", "problemas", "defeito", "falha",
    "tudo"})
_PRESENT_STATE = frozenset({"esta", "estao", "seu", "sua", "seus", "suas", "meu", "minha", "meus", "minhas", "atual", "agora",
                            "momento", "hoje", "marca", "marcando", "indica", "indicando", "apresenta", "mostra", "voce", "tem"})
_UNSUPPORTED_NOUNS = frozenset({"pneu", "pneus", "pressao", "combustivel", "tanque", "oleo", "bateria", "tensao",
                                "freio", "freios", "consumo", "odometro", "hodometro", "quilometragem", "gasolina",
                                "etanol", "airbag", "abs", "nivel", "farol", "farois", "porta", "portas"})
_STATE_WORDS = _JUDGMENT | frozenset({"cheio", "cheia", "vazio", "vazia", "calibrado", "calibrados", "desgastado",
                                      "desgastados", "bem", "certo", "funcionando", "acesa", "aceso", "apagada",
                                      "aberta", "fechada", "trancada", "destrancada", "cheios", "cheias"})
_DENIAL = re.compile(
    r"\bnao (?:tenho|ha|existe|possuo|disponho) (?:como|criterio|referencia|parametro|acesso|dados?|informac\w*|"
    r"sensor\w*|leitura\w*|ferramenta\w*|nenhum\w*)\b|"
    r"\bnao consigo (?:dizer|avaliar|afirmar|medir|informar|confirmar|acessar|ler|ver|verificar|saber)\b|"
    r"\bnao (?:e|seria) possivel (?:dizer|avaliar|afirmar|confirmar|medir|verificar|saber)\b|"
    r"\bnao posso (?:dizer|avaliar|afirmar|confirmar|acessar|medir|verificar)\b|"
    r"\bnao sei (?:dizer|avaliar|se)\b|\bsem acesso\b|\bindisponivel\b|\bindisponiveis\b|\bnao foi possivel\b|"
    r"\bnao (?:esta |estao |ha |foi )?(?:informad\w+|disponiv\w+)\b|\bnao (?:monitoro|monitoramos|medimos|meco)\b")
_MOVING = re.compile(r"\b(?:em movimento|andando|rodando|em marcha|se movendo|em deslocamento)\b")
_STOPPED = re.compile(r"\b(?:parado|parada|estacionado|estacionada|imovel)\b")
_NEG_BEFORE = re.compile(r"\b(?:nao|nem|nunca|jamais)\b")
_CONTROL = [
    re.compile(r"\b(?:vou|irei|vamos|ja|acabei de|estou|posso|consigo|sou capaz de)\s+(?:\w+\s+)?"
               r"(?:acelerar|frear|ligar|desligar|abrir|fechar|travar|destravar|ativar|desativar|aumentar|reduzir|"
               r"ajustar|definir|controlar|desbloquear|bloquear|trocar|mudar|apagar|acender)\b"),
    re.compile(r"\b(?:acelerei|freei|liguei|desliguei|abri|fechei|travei|destravei|ativei|desativei|aumentei|reduzi|"
               r"ajustei|defini|alterei|configurei|bloqueei|desbloqueei|apaguei|acendi)\b"),
    re.compile(r"\bestou\s+(?:acelerando|freando|ligando|desligando|abrindo|fechando|travando|ativando|ajustando)\b"),
    re.compile(r"\b(?:controlo|controlamos|assumi o controle|assumindo o controle)\b"),
]
_PAST = re.compile(r"\b(?:ontem|anteontem|antes|anterior|anteriormente|passad[oa]s?|mais cedo|naquel[ea]|outro dia|"
                   r"(?:ha|faz) \d+ (?:dias?|horas?|minutos?|semanas?|meses)|era|estava|foi|tinha|marcava|indicava|"
                   r"registrava)\b")
_CAPABILITY = re.compile(r"\b(?:usei|utilizei|consultei|acessei|acionei|chamei|executei)\b.{0,30}\b(?:gps|mapa|internet|camera|nuvem|servidor|api|ecu|scanner|computador de bordo)\b")
_EN_WORDS = frozenset({"the", "is", "are", "at", "and", "of", "to", "you", "your", "engine", "speed", "temperature",
                       "currently", "running", "was", "it", "in", "on", "thousand", "hundred", "five", "eight",
                       "simulated", "reading"})
_PT_WORDS = frozenset({"a", "o", "as", "os", "de", "do", "da", "e", "em", "no", "na", "que", "um", "uma", "para", "com",
                       "por", "esta", "estao", "nao", "voce", "motor", "simulado", "leitura", "agora", "ao", "se"})
_SIM_MARK = re.compile(r"\bsimulad[oa]s?\b|\bsimulacao\b|\bsimulador\b|\bsimulando\b")
_REAL_CLAIM = re.compile(
    r"\b(?:dados|leitura|leituras|valor|valores|medicao|medicoes)\s+reais?\b|"
    r"\b(?:ao|com o|no|do|de|pelo|para o|num)\s+(?:meu\s+|seu\s+|o\s+)?(?:carro|veiculo|automovel|honda fit|fit)\s+(?:real|de verdade)\b|"
    r"\b(?:carro|veiculo)\s+(?:real|de verdade)\b|\bcarro fisico\b|\bveiculo fisico\b|\bobd (?:real|fisico)\b|"
    r"\becu (?:real|fisica)\b")


def _norm_unit(u: str) -> str | None:
    return _UNIT_ALIASES.get(u.strip().lower()) or _UNIT_ALIASES.get(u.strip())


class Verifier:
    def __init__(self, bundle: EvidenceBundle):
        self.bundle = bundle

    def verify(self, answer: StructuredAnswer) -> Verdict:
        b = self.bundle
        bad: list[Violation] = []
        verified: dict[str, float] = {}

        def add(code: str, detail: str = "") -> None:
            if not any(v.code == code and v.detail == detail for v in bad):
                bad.append(Violation(code, detail))

        if any(e.turn_id != b.turn_id for e in b.items):
            add("turn_mixing", "evidence belongs to another turn")
        if not answer.answer.strip():
            add("empty_answer")

        mentions = extract_mentions(answer.answer)
        states = self._state_claims(answer.answer)
        tele_in_text = any(m.field is not None for m in mentions) or bool(states)
        strict = bool(b.telemetry or b.status)  # the turn read the vehicle: judgment rules apply without exception
        wants_values = bool(answer.claims) or tele_in_text or any(
            m for m in mentions if not (m.benign or m.year_like))

        # ── evidence availability (only matters when the answer states something) ──
        if wants_values:
            self._availability(add)

        # ── structured claims ──
        for c in answer.claims:
            unit = _norm_unit(c.unit)
            if unit != CANONICAL_UNIT[c.field]:
                add("unit_mismatch", f"{c.field} must be reported in {CANONICAL_UNIT[c.field]}")
                continue
            self._check_value(add, verified, c.field, c.value, _decimals(c.value), None)

        # ── every number in the free text ──
        evidence_values = [(f, b.value(f)) for f in SENSOR_FIELDS if b.value(f) is not None]
        for m in mentions:
            if m.benign or m.year_like:
                continue
            if m.unsupported_unit:
                add("unsupported_sensor", f"number with unit '{m.unsupported_unit}'")
            elif m.field is not None:
                if m.negated and b.has_usable_reading and b.value(m.field) is not None and                         matches(m.value, m.decimals, b.value(m.field), m.field, m.unit):
                    add("negated_value_mismatch", "the answer denies a value that the reading confirms")
                else:
                    self._check_value(add, verified, m.field, m.value, m.decimals, m.unit)
            else:  # unattached number: allowed only if it equals some observed value
                if not any(matches(m.value, m.decimals, v, f, None) for f, v in evidence_values):
                    add("unverified_number", "a number that no valid reading supports")

        # ── qualitative statements ──
        for code, detail in states:
            if code == "stopped":
                v = b.value("speed_kmh")
                if v is None or v != 0:
                    add("state_claim_mismatch", "stated the vehicle is stopped without a zero-speed reading")
                else:
                    verified["speed_kmh"] = 0.0
            elif code == "not_stopped":
                v = b.value("speed_kmh")
                if v is None or v <= 0:
                    add("state_claim_mismatch", "stated the vehicle is moving without a positive speed reading")
            elif code == "moving":
                v = b.value("speed_kmh")
                if v is None or v <= 0:
                    add("state_claim_mismatch", "stated the vehicle is moving without a positive speed reading")
                else:
                    verified["speed_kmh"] = v
            elif code == "not_moving":
                v = b.value("speed_kmh")
                if v is None or v != 0:
                    add("state_claim_mismatch", "stated the vehicle is not moving without a zero-speed reading")
        for _sid, c_toks, c_txt in clauses(answer.answer):
            words = {t.text for t in c_toks}
            if _DENIAL.search(c_txt):
                continue
            # On a turn that read the vehicle these rules are strict. On a tool-less (general-knowledge) turn they only
            # apply to clauses about the car's PRESENT state, so "a troca de óleo mantém a lubrificação adequada do
            # motor" is a definition, not a claim about this car (found by the P7 run with the real model).
            applies = strict or bool(words & _PRESENT_STATE)
            if applies and words & _TELEMETRY_TERMS and words & _JUDGMENT:
                add("unverifiable_judgment", "judgment about sensor values: no approved thresholds exist")
            if applies and words & _UNSUPPORTED_NOUNS and words & _STATE_WORDS:
                add("unsupported_sensor_claim", "statement about a sensor this system does not have")

        # ── temporal attribution: readings describe NOW, never the past ──
        past_ids = {sid for sid, _t, txt in clauses(answer.answer) if _PAST.search(txt)}
        for m in mentions:
            if m.field is not None and m.sentence in past_ids:
                add("temporal_misattribution", "a current reading was presented as a past value")
        for sid, _t, txt in clauses(answer.answer):
            if sid in past_ids and (_STOPPED.search(txt) or _MOVING.search(txt)) and not _DENIAL.search(txt):
                add("temporal_misattribution", "a current state was presented as a past state")

        # ── control claims ──
        norm = normalise(answer.answer)
        for _sid, c_toks, c_txt in clauses(answer.answer):
            for rx in _CONTROL:
                for m in rx.finditer(c_txt):
                    before = c_txt[max(0, m.start() - 16):m.start()]
                    if not _NEG_BEFORE.search(before) and not _DENIAL.search(c_txt):
                        add("claims_vehicle_control", "the answer claims to act on or control the vehicle")

        for _sid, _t, c_txt in clauses(answer.answer):
            if _CAPABILITY.search(c_txt) and not _DENIAL.search(c_txt):
                add("claims_unavailable_capability", "the answer claims to have used a tool/source that does not exist")

        # ── numbers this analyser cannot read, and answers that are not Portuguese ──
        orphans = orphan_units(answer.answer)
        if orphans:
            # a clause that only DENIES access ("não consigo ler em rpm") may name a unit; anything else may not
            carrying = [txt for _sid, _t, txt in clauses(answer.answer) if any(u in txt.split() for u in orphans)]
            if not all(_DENIAL.search(txt) for txt in carrying):
                add("unreadable_number", f"unit '{orphans[0]}' without a number the verifier can read")
        words = normalise(answer.answer).split()
        en, pt = sum(w in _EN_WORDS for w in words), sum(w in _PT_WORDS for w in words)
        if en >= 2 and en > pt:
            add("not_portuguese", "answers must be in Brazilian Portuguese (numbers in other languages cannot be verified)")

        # ── simulation disclosure ──
        shows_value = bool(verified) or tele_in_text or bool(answer.claims)
        if shows_value and b.simulated is True and not _SIM_MARK.search(norm):
            add("simulation_not_disclosed", "readings are simulated but the answer does not say so")
        if b.simulated is True:
            for m in _REAL_CLAIM.finditer(norm):  # negation must be LOCAL ("não são do carro real"), not anywhere
                if not _NEG_BEFORE.search(norm[max(0, m.start() - 24):m.start()]):
                    add("simulation_misrepresented", "simulated readings presented as real")
                    break
        if shows_value and b.simulated is False and _SIM_MARK.search(norm):
            add("simulation_misrepresented", "real readings presented as simulated")

        return Verdict(passed=not bad, violations=tuple(bad), verified=verified if not bad else {})

    # ───────────────────────── helpers ─────────────────────────
    def _availability(self, add) -> None:
        b = self.bundle
        if not b.telemetry:
            add("no_evidence", "no telemetry tool was executed in this turn")
        elif not b.has_usable_reading:
            if b.stale is not None:
                add("stale_evidence", "the only reading is older than the freshness limit")
            else:
                add("evidence_unavailable", b.failure.error_code if b.failure and b.failure.error_code else "no valid reading")

    def _check_value(self, add, verified: dict[str, float], name: str, value: float, decimals: int,
                     unit: str | None) -> None:
        b = self.bundle
        if not b.has_usable_reading:
            return  # reported once by _availability
        observed = b.value(name)
        if observed is None:
            add("field_missing", f"{name} was not provided by the source")
            return
        if matches(value, decimals, observed, name, unit):
            verified[name] = observed
        else:
            add("value_mismatch", f"{name} does not match the reading of this turn")

    def _state_claims(self, text: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for _sid, c_toks, c_txt in clauses(text):
            if _DENIAL.search(c_txt):
                continue
            for kind, rx in (("stopped", _STOPPED), ("moving", _MOVING)):
                for m in rx.finditer(c_txt):
                    negated = bool(_NEG_BEFORE.search(c_txt[max(0, m.start() - 14):m.start()]))
                    if kind == "stopped":
                        out.append(("not_stopped" if negated else "stopped", ""))
                    else:
                        out.append(("not_moving" if negated else "moving", ""))
        return out


def _decimals(value: float) -> int:
    s = repr(float(value))
    return len(s.split(".")[1].rstrip("0")) if "." in s else 0


def verify(answer: StructuredAnswer, bundle: EvidenceBundle) -> Verdict:
    return Verifier(bundle).verify(answer)
