"""Standard benchmark scenarios (PoC 03 / P4). Fixed prompts + a functional check each, so runs of
different models are comparable. Contains no personal data and no vehicle values."""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fit_ai.ai import ChatMessage, LLMResponse, ToolDefinition, load_system_prompt

JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"funcao": {"type": "string"}, "idioma": {"type": "string"}},
    "required": ["funcao", "idioma"],
    "additionalProperties": False,
}
TOOL = ToolDefinition(name="ler_rotacao_motor", description="Lê a rotação atual do motor em RPM. Somente leitura.")

_FILLER = (
    "O Honda Fit LX 2005 usa um motor 1.4 de quatro cilindros. A manutenção preventiva inclui troca de óleo, "
    "filtros, velas e verificação de correias. "
)


@dataclass(frozen=True)
class Scenario:
    id: str
    description: str
    messages: tuple[ChatMessage, ...]
    check: Callable[[LLMResponse], str | None]  # None = functional check passed, else the reason it failed
    tools: tuple[ToolDefinition, ...] = ()
    response_format: Any = None
    think: bool | None = None  # None = provider default (false)
    max_tokens: int | None = None


def _text(r: LLMResponse) -> str | None:
    return None if r.content.strip() else "empty content"


def _json(r: LLMResponse) -> str | None:
    try:
        obj = json.loads(r.content)
    except ValueError:
        return "content is not valid JSON"
    if not isinstance(obj, dict) or set(obj) != {"funcao", "idioma"}:
        return "JSON does not match the schema"
    return None


def _tool(r: LLMResponse) -> str | None:
    if any(c.name == TOOL.name for c in r.tool_calls):
        return None
    return "the model did not request the declared tool"


def _no_think(r: LLMResponse) -> str | None:
    if r.thinking_chars:
        return f"think=false but {r.thinking_chars} reasoning chars were returned"
    return _text(r)


def build_scenarios() -> list[Scenario]:
    system = load_system_prompt().as_message()
    u = ChatMessage.user
    return [
        Scenario("S1_short_pt", "Pergunta curta em português", (system, u("Em uma frase: o que você faz?")), _text,
                 max_tokens=80),
        Scenario("S2_contextual", "Pergunta contextual mais longa",
                 (system, u("Tenho um Honda Fit 2005 e quero montar um assistente de bordo que converse comigo e "
                            "mostre diagnósticos. Quais são os três cuidados mais importantes para que ele seja "
                            "seguro durante a condução? Responda em até cinco linhas.")), _text, max_tokens=200),
        Scenario("S3_json_schema", "Saída com JSON Schema",
                 (system, u("Descreva sua função e o idioma em que responde.")), _json,
                 response_format=JSON_SCHEMA, max_tokens=120),
        Scenario("S4_tool_call", "Chamada de ferramenta fictícia (não executada)",
                 (system, u("Qual a rotação do motor agora? Use a ferramenta disponível.")), _tool,
                 tools=(TOOL,), max_tokens=120),
        Scenario("S5_no_tools_vehicle", "Pergunta sobre o veículo sem ferramentas",
                 (system, u("Qual é a temperatura do líquido de arrefecimento agora?")), _text, max_tokens=120),
        Scenario("S6_large_context", "Prompt com contexto maior (~1 mil tokens)",
                 (system, u(_FILLER * 20 + "\n\nCom base no texto acima, cite um item de manutenção preventiva.")),
                 _text, max_tokens=100),
        Scenario("S7_think_false", "Resposta curta com think=false", (system, u("Diga olá em uma frase.")),
                 _no_think, think=False, max_tokens=60),
    ]
