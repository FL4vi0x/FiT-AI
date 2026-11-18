"""P5 scenarios: objective, automatically scored QUALITY checks (pass/fail) kept apart from speed metrics.

Every scenario builds its messages from a per-round `nonce` placed at the START of the user message, so the
whole user turn is never served from Ollama's prompt cache (only the shared system prompt prefix is, which is
also what real use looks like). Tools are fictitious and are never executed. No vehicle values are real.
Quality is a conservative heuristic, not human judgement: see docs/poc-03-p5-model-selection.md.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fit_ai.ai import ChatMessage, LLMResponse, ToolCall, ToolDefinition, load_system_prompt

Score = tuple[bool, str]  # (passed, short reason without any model text)

TOOLS = (
    ToolDefinition(name="ler_rotacao_motor", description="Lê a rotação atual do motor em RPM. Somente leitura."),
    ToolDefinition(name="ler_temperatura_arrefecimento",
                   description="Lê a temperatura atual do líquido de arrefecimento em °C. Somente leitura."),
    ToolDefinition(name="ler_velocidade_veiculo", description="Lê a velocidade atual do veículo em km/h. Somente leitura."),
)
TOOL_NAMES = {t.name for t in TOOLS}

INTENTS = ["consultar_dado_veiculo", "diagnostico", "multimidia", "navegacao", "conversa_geral", "controle_veiculo"]
INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"intencao": {"type": "string", "enum": INTENTS}},
    "required": ["intencao"], "additionalProperties": False,
}
INTENT_HELP = (
    "Classifique a intenção da frase do usuário em exatamente uma categoria: "
    "consultar_dado_veiculo (pede um valor de sensor/telemetria), diagnostico (problema, luz, barulho, falha), "
    "multimidia (música, rádio, mídia), navegacao (rota, destino, lugar), "
    "controle_veiculo (pede para atuar no carro: vidros, ar-condicionado, travas, luzes), "
    "conversa_geral (qualquer outro assunto). Responda só com o JSON."
)
DTC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"codigo_dtc": {"type": "string"},
                   "origem_dado": {"type": "string", "enum": ["informado_pelo_usuario", "medido_por_sensor"]},
                   "gravidade": {"type": "string", "enum": ["baixa", "media", "alta"]}},
    "required": ["codigo_dtc", "origem_dado", "gravidade"], "additionalProperties": False,
}

_FILLER = ("O Honda Fit LX 2005 usa um motor 1.4 de quatro cilindros. A manutenção preventiva inclui troca de óleo, "
           "filtros, velas e verificação de correias. ")

# measured value + unit pattern: a number the model could only know from a sensor
_FABRICATED = re.compile(r"\d+(?:[.,]\d+)?\s*(?:°\s?c\b|graus|psi\b|bar\b|kpa\b|litros?\b|l\b|%|km/h|rpm\b)", re.I)
_ADMITS = re.compile(r"não\s+(?:tenho|consigo|possuo|há|posso|estou|foi possível|está disponível|disponho|dispon)|"
                     r"sem\s+acesso|indispon|não\s+(?:me\s+)?(?:é possível|foi fornecid)|impossível", re.I)
_PT = re.compile(r"\b(?:que|de|para|o|a|os|as|um|uma|é|do|da|em|com|por|se|não)\b", re.I)
_EN = re.compile(r"\b(?:the|and|is|of|to|you|your|with|this|that)\b", re.I)


@dataclass(frozen=True)
class P5Scenario:
    id: str
    category: str  # intent | tool | tool_negative | unavailable | structured | pt_chat | latency
    build: Callable[[str], list[ChatMessage]]  # nonce -> messages
    score: Callable[[LLMResponse], Score]
    tools: tuple[ToolDefinition, ...] = ()
    response_format: Any = None
    max_tokens: int = 150
    cold_pair: str | None = None  # latency: id of the scenario whose exact prompt this one repeats (cache probe)


def _sys() -> ChatMessage:
    return load_system_prompt().as_message()


def _user(text: str) -> Callable[[str], list[ChatMessage]]:
    return lambda nonce: [_sys(), ChatMessage.user(f"[{nonce}] {text}")]


def _intent(label: str, text: str) -> P5Scenario:
    def score(r: LLMResponse) -> Score:
        try:
            got = json.loads(r.content).get("intencao")
        except (ValueError, AttributeError):
            return False, "invalid json"
        return (got == label), ("ok" if got == label else f"wrong intent ({got})")
    return P5Scenario(f"INT_{label}", "intent", _user(f"{INTENT_HELP}\n\nFrase: {text}"), score,
                      response_format=INTENT_SCHEMA, max_tokens=40)


def _tool_pos(sid: str, tool: str, text: str) -> P5Scenario:
    def score(r: LLMResponse) -> Score:
        names = [c.name for c in r.tool_calls]
        if not names:
            return False, "no tool call"
        return (names[0] == tool), ("ok" if names[0] == tool else f"wrong tool ({names[0]})")
    return P5Scenario(sid, "tool", _user(text), score, tools=TOOLS, max_tokens=80)


def _tool_neg(sid: str, text: str) -> P5Scenario:
    def score(r: LLMResponse) -> Score:
        if r.tool_calls:
            return False, "called a tool without need"
        return (bool(r.content.strip()), "ok" if r.content.strip() else "empty")
    return P5Scenario(sid, "tool_negative", _user(text), score, tools=TOOLS, max_tokens=100)


def _no_invention(r: LLMResponse) -> Score:
    if r.tool_calls:
        return False, "called a tool that does not exist"
    if _FABRICATED.search(r.content):
        return False, "stated a measured-looking value"
    if not _ADMITS.search(r.content):
        return False, "did not acknowledge the missing data"
    return True, "ok"


def _unavailable_tool_result(nonce: str) -> list[ChatMessage]:
    call = ToolCall(id="c1", name="ler_temperatura_arrefecimento", arguments={})
    return [_sys(), ChatMessage.user(f"[{nonce}] Qual a temperatura do líquido de arrefecimento agora?"),
            ChatMessage.assistant("", (call,)),
            ChatMessage.tool_result("ler_temperatura_arrefecimento",
                                    '{"status": "indisponivel", "motivo": "sensor sem resposta"}', "c1")]


def _dtc(r: LLMResponse) -> Score:
    try:
        o = json.loads(r.content)
    except ValueError:
        return False, "invalid json"
    ok = o.get("codigo_dtc", "").upper() == "P0301" and o.get("origem_dado") == "informado_pelo_usuario"
    return ok, "ok" if ok else "wrong extraction/provenance"


def _pt(r: LLMResponse) -> Score:
    pt, en = len(_PT.findall(r.content)), len(_EN.findall(r.content))
    ok = pt >= 5 and en <= 1 and r.finish_reason == "stop"
    return ok, "ok" if ok else f"not clean pt-BR (pt={pt}, en={en}, finish={r.finish_reason})"


def _long(r: LLMResponse) -> Score:
    return (bool(r.content.strip()), "ok" if r.content.strip() else "empty")


def _long_msgs(nonce: str) -> list[ChatMessage]:
    return [_sys(), ChatMessage.user(f"[{nonce}] " + _FILLER * 20 +
                                     "\n\nCom base no texto acima, cite um item de manutenção preventiva.")]


def build_p5_scenarios() -> list[P5Scenario]:
    return [
        _intent("consultar_dado_veiculo", "Quantas rotações o motor está girando agora?"),
        _intent("diagnostico", "Acendeu uma luz no painel e o carro está falhando, o que pode ser?"),
        _intent("multimidia", "Toca uma música do Legião Urbana."),
        _intent("navegacao", "Me leva até o posto de gasolina mais próximo."),
        _intent("controle_veiculo", "Fecha os vidros e liga o ar-condicionado."),
        _intent("conversa_geral", "Qual é a capital da França?"),
        _tool_pos("TOOL_rpm", "ler_rotacao_motor", "Qual a rotação do motor agora?"),
        _tool_pos("TOOL_temp", "ler_temperatura_arrefecimento", "O motor está esquentando? Veja a temperatura do líquido."),
        _tool_pos("TOOL_speed", "ler_velocidade_veiculo", "A que velocidade estou indo agora?"),
        _tool_neg("TOOLNEG_greeting", "Bom dia! Tudo bem com você?"),
        _tool_neg("TOOLNEG_concept", "Explique em uma frase o que é um catalisador."),
        P5Scenario("UNAV_tyre_notools", "unavailable", _user("Qual é a pressão atual do pneu dianteiro esquerdo?"),
                   _no_invention, max_tokens=120),
        P5Scenario("UNAV_fuel_notools", "unavailable", _user("Quantos litros de combustível ainda tenho no tanque?"),
                   _no_invention, max_tokens=120),
        P5Scenario("UNAV_tool_unavailable", "unavailable", _unavailable_tool_result, _no_invention,
                   tools=TOOLS, max_tokens=120),
        P5Scenario("STRUCT_dtc", "structured",
                   _user("Relato do usuário (informado por ele, não medido): o carro falhou ao ligar hoje, cheiro de "
                         "gasolina, e o mecânico anotou o código P0301 no scanner dele. Extraia os campos."),
                   _dtc, response_format=DTC_SCHEMA, max_tokens=100),
        P5Scenario("PTCHAT_oil", "pt_chat", _user("Explique em duas frases o que é a troca de óleo e por que ela importa."),
                   _pt, max_tokens=150),
        P5Scenario("LATENCY_long_cold", "latency", _long_msgs, _long, max_tokens=40),
        P5Scenario("LATENCY_long_warm", "latency", _long_msgs, _long, max_tokens=40, cold_pair="LATENCY_long_cold"),
    ]
