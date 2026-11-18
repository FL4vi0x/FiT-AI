"""Deterministic request routing: which READ tools does this question need? No LLM involved.

Fewer tools per turn = shorter prompts (the P5 benchmark showed prompt processing dominates latency) and a
smaller attack surface. Control requests are recognised here and refused WITHOUT calling the model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from fit_ai.grounding.evidence import STATUS_TOOL, TELEMETRY_TOOL
from fit_ai.grounding.numbers import normalise

MEMORY_TOOL = "get_memory_facts"

_ACTION = re.compile(
    r"\b(?:acelere|acelerar|freie|frear|pise|buzine|desligue|desligar|ligue|ligar|abra|abrir|feche|fechar|trave|"
    r"travar|destrave|destravar|aumente|aumentar|diminua|diminuir|reduza|reduzir|ajuste|ajustar|mude|mudar|ative|"
    r"ativar|desative|desativar|apague|acenda|regule|dirija|dirigir|estacione|ande|engate|coloque|ponha|defina|"
    r"configure|aperte|pressione|gire|vire|controle|controlar|desbloqueie|bloqueie|pare|parar)\b")
_STRONG = frozenset({"acelere", "acelerar", "freie", "frear", "pise", "buzine", "dirija", "dirigir", "estacione",
                     "engate", "ande", "desligue o motor", "controle", "controlar"})
_TARGET = re.compile(
    r"\b(?:carro|veiculo|motor|vidros?|janelas?|portas?|far(?:ol|ois)|ar condicionado|ar|climatizador|volante|"
    r"freios?|acelerador|marcha|ignicao|buzina|limpador|travas?|banco|retrovisor|velocidade|rotacao|temperatura)\b")
_QUESTION_LEAD = re.compile(r"^\s*(?:como|qual|quais|quando|por que|porque|o que|quanto)\b")
_INJECTION = re.compile(
    r"\b(?:ignore|ignora|desconsidere|esqueca|descarte)\b.{0,25}\b(?:instrucoes|regras|ordens|orientacoes|prompt)\b|"
    r"\b(?:ignore|ignora|desconsidere|esqueca|descarte)\s+(?:tudo|isso|aquilo|todas|todos)\b|"
    r"\bfinja que\b|\b(?:voce|tu) agora e\b|\bmodo (?:desenvolvedor|admin|deus|livre)\b|\bsystem prompt\b|"
    r"\bprompt do sistema\b|\bjailbreak\b|\bsem restricoes\b|\baja como\b|\bdan mode\b")

_TELEMETRY = re.compile(
    r"\b(?:rotac\w*|rpm|giros?|velocidade|kmh|km h|temperatura|arrefec\w*|esquent\w*|aquec\w*|superaquec\w*|"
    r"quente|motor|parado|parada|andando|movimento|devagar|rapido|leitura\w*|telemetria|sensores?|graus|celsius|"
    r"mph|milhas|fahrenheit|ms|metros por segundo|"
    r"marcha lenta|como esta o carro|dados do (?:carro|veiculo))\b")
_RPM = re.compile(r"\b(?:rotac\w*|rpm|giros?|marcha lenta)\b")
_SPEED = re.compile(r"\b(?:velocidade|kmh|km h|mph|milhas|ms|metros por segundo|parado|parada|andando|movimento|devagar|rapido)\b")
_TEMP = re.compile(r"\b(?:temperatura|arrefec\w*|esquent\w*|aquec\w*|superaquec\w*|quente|graus|celsius|fahrenheit)\b")
_STATUS = re.compile(r"\b(?:conect\w*|conexao|status|estado d[aeo]|simulador|simulad[oa]|simulacao|octave|obd|link|"
                     r"protocolo|disponivel|funcionando|online|offline|ligad[oa] ao)\b")
_MEMORY = re.compile(r"\b(?:lembr\w*|memoria|memorias|preferenc\w*|te falei|te disse|eu falei|eu disse|falei antes|"
                     r"disse antes|ontem|anteontem|semana passada|antes|anterior|anteriormente|historico|anotad\w*|"
                     r"guardad\w*|salvou|registrou)\b")


@dataclass(frozen=True)
class Intent:
    control: bool
    injection: bool
    telemetry: bool
    status: bool
    memory: bool
    fields: tuple[str, ...]  # sensor fields the question is about (empty = all / unspecified)

    @property
    def tools(self) -> tuple[str, ...]:
        out: list[str] = []
        if self.telemetry:
            out.append(TELEMETRY_TOOL)
        if self.status:
            out.append(STATUS_TOOL)
        if self.memory:
            out.append(MEMORY_TOOL)
        return tuple(out)

    @property
    def kind(self) -> str:
        if self.control:
            return "control"
        return "+".join(n for n, on in (("telemetry", self.telemetry), ("status", self.status),
                                        ("memory", self.memory)) if on) or "general"


def classify(text: str) -> Intent:
    t = normalise(text)
    verbs = _ACTION.findall(t)
    control = False
    if verbs:
        strong = any(v in _STRONG for v in verbs)
        control = strong or (bool(_TARGET.search(t)) and not _QUESTION_LEAD.match(t))
    fields = tuple(f for f, rx in (("rpm", _RPM), ("speed_kmh", _SPEED), ("coolant_temp_c", _TEMP)) if rx.search(t))
    return Intent(control=control, injection=bool(_INJECTION.search(t)), telemetry=bool(_TELEMETRY.search(t)),
                  status=bool(_STATUS.search(t)), memory=bool(_MEMORY.search(t)), fields=fields)
