"""Deterministic answers built ONLY from verified evidence. The LLM is never the last authority on sensor values.

Every text produced here is plain Brazilian Portuguese with digits, always states whether data is simulated,
and is guaranteed (by property tests) to pass the verifier with the same evidence.
"""
from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from fit_ai.grounding.evidence import CANONICAL_UNIT, FIELD_LABEL, SENSOR_FIELDS, EvidenceBundle

_ERROR_TEXT = {
    "vehicle_link_down": "a conexão com o veículo (ou com o simulador) está interrompida",
    "octave_unavailable": "a fonte de dados do veículo não está disponível",
    "octave_timeout": "a fonte de dados do veículo não respondeu a tempo",
    "octave_protocol_incompatible": "a versão do protocolo da fonte de dados é incompatível",
    "octave_error": "a fonte de dados do veículo retornou um erro",
    "no_data": "a fonte não informou nenhum valor",
    "tool_timeout": "a leitura demorou demais",
    "unknown_tool": "a leitura não está disponível",
}


def format_number(value: float, field: str) -> str:
    if field == "rpm":
        return str(int(round(value)))
    # half-up on the decimal representation: the SAME rule the verifier applies to displayed precision
    shown = Decimal(repr(float(value))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if shown == 0:
        return "0"  # never "-0"
    s = f"{shown:f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")  # Brazilian decimal comma


def _origin_prefix(simulated: bool | None) -> str:
    if simulated is True:
        return "Dados simulados (não são do carro real): "
    if simulated is False:
        return "Leitura do veículo: "
    return "Leitura (a fonte não informou se é simulada ou real): "


def render_unavailable_info() -> str:
    return "Essa informação não está disponível para mim agora, e não vou estimar um valor."


def render_fallback(bundle: EvidenceBundle, requested: Sequence[str] = ()) -> str:
    """A safe answer from the evidence alone. `requested`: sensor fields the user asked about (empty = all)."""
    fields = [f for f in SENSOR_FIELDS if not requested or f in requested]
    if not bundle.telemetry:
        return render_unavailable_info()

    if not bundle.has_usable_reading:
        if bundle.stale is not None:
            age = bundle.stale.age_s or 0
            return (f"A última leitura tem {age:.0f} s e está desatualizada, por isso não vou apresentá-la "
                    "como valor atual. Tente novamente em instantes.")
        code = bundle.failure.error_code if bundle.failure else None
        reason = _ERROR_TEXT.get(code or "", "ocorreu uma falha ao ler os dados")
        return f"Não consegui ler os dados do veículo agora: {reason}. Não vou estimar valores."

    parts, missing = [], []
    for f in fields:
        v = bundle.value(f)
        if v is None:
            missing.append(FIELD_LABEL[f])
        else:
            parts.append(f"{FIELD_LABEL[f]} {format_number(v, f)} {CANONICAL_UNIT[f]}")
    text = _origin_prefix(bundle.simulated)
    text += "; ".join(parts) + "." if parts else "nenhum dos valores pedidos foi informado pela fonte."
    if missing and parts:
        text += f" Indisponível: {', '.join(missing)}."
    elif missing:
        text += f" Indisponível: {', '.join(missing)}."
    return text
