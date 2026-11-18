"""Compact, cache-friendly prompts.

The system message is STATIC (identity + response rules): the same bytes every turn and for every question,
so the local runtime can reuse its processed prefix (P5: a cached prefix turns ~10 s into ~1 s on CPU).
Everything that changes per turn (readings, memory, question) goes in the single user message after it.
"""
from __future__ import annotations

from fit_ai.ai import ChatMessage, load_system_prompt
from fit_ai.grounding.evidence import CANONICAL_UNIT, SENSOR_FIELDS, EvidenceBundle
from fit_ai.grounding.fallback import format_number

RULES_PT = """REGRAS DE RESPOSTA (obrigatórias):
- Responda SOMENTE com um objeto JSON: {"answer": "...", "claims": [{"field": "rpm|speed_kmh|coolant_temp_c", "value": número, "unit": "rpm|km/h|°C"}], "unknown": []}.
- Valores de sensores: use SOMENTE os de "LEITURAS DESTE TURNO", com os mesmos números e unidades. Nunca estime nem use números da pergunta ou da memória como se fossem leituras.
- Se "simuladas=sim", COMECE a resposta com "No simulador," (ou "Dados simulados:") e use a palavra "simulado"/"simulador". Se um valor faltar ou as leituras estiverem indisponíveis, diga que não está disponível.
- Em "claims" coloque SOMENTE campos que aparecem com valor em LEITURAS DESTE TURNO. Para um campo ausente ou indisponível, não crie claim: escreva-o em "unknown" e diga no texto que não está disponível.
- Não opine sobre os valores (normal, alta, baixa, perigosa): apenas informe-os.
- Você só lê dados. Nunca diga que controla, acelera, liga ou desliga algo no veículo.
- Use dígitos para números, sem listas, em até 3 frases curtas em português do Brasil."""

MAX_QUESTION_CHARS = 2000


def system_message() -> ChatMessage:
    return ChatMessage.system(load_system_prompt().text + "\n\n" + RULES_PT)


def render_evidence_block(bundle: EvidenceBundle) -> str:
    lines: list[str] = []
    if bundle.telemetry:
        if bundle.has_usable_reading:
            ev = max((e for e in bundle.telemetry if e.usable(bundle.max_age_s)), key=lambda e: e.read_at)
            sim = {True: "sim", False: "não", None: "desconhecido"}[ev.simulated]
            vals = "; ".join(f"{f}={format_number(ev.values[f], f)} {CANONICAL_UNIT[f]}"
                              for f in SENSOR_FIELDS if f in ev.values)
            miss = ", ".join(ev.missing) or "nenhum"
            lines.append(f"LEITURAS DESTE TURNO: simuladas={sim}; idade={ev.age_s or 0:.0f} s; {vals}; ausentes={miss}")
        elif bundle.stale is not None:
            lines.append(f"LEITURAS DESTE TURNO: a última leitura está desatualizada ({bundle.stale.age_s or 0:.0f} s). "
                         "Não há valores atuais; diga que não está disponível.")
        else:
            code = bundle.failure.error_code if bundle.failure and bundle.failure.error_code else "falha"
            lines.append(f"LEITURAS DESTE TURNO: indisponíveis (motivo: {code}). Não há valores; "
                         "diga que não está disponível.")
    for ev in bundle.status:
        if ev.state == "ok":
            sim = {True: "sim", False: "não", None: "desconhecido"}[ev.simulated]
            lines.append(f"CONEXÃO: estado={ev.link_state}; simulada={sim}")
        else:
            lines.append("CONEXÃO: indisponível")
    return "\n".join(lines)


def user_message(question: str, bundle: EvidenceBundle, memory_block: str) -> ChatMessage:
    parts = [p for p in (render_evidence_block(bundle), memory_block) if p]
    parts.append("PERGUNTA: " + question.strip()[:MAX_QUESTION_CHARS])
    return ChatMessage.user("\n".join(parts))


def correction_message(codes: tuple[str, ...]) -> ChatMessage:
    return ChatMessage.user(
        "Sua resposta foi rejeitada pelo verificador (" + ", ".join(codes) + "). Responda de novo apenas com o JSON, "
        "usando somente as LEITURAS DESTE TURNO e sem opinar sobre os valores.")
