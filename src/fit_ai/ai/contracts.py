"""The LLMProvider contract plus the request/response rules BOTH providers apply.

`prepare_request` and `check_response` are shared so that the real adapter and the fake can never
drift apart on what is valid.
"""
from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from fit_ai.ai.errors import LLMInvalidRequest, LLMInvalidResponse
from fit_ai.ai.models import ChatMessage, LLMResponse, ProviderHealth, ToolDefinition

ResponseFormat = Literal["json"] | dict[str, Any]

MAX_MESSAGES = 200
MAX_TOOLS = 32
MAX_TOKENS_CEILING = 8192
MAX_TIMEOUT_CEILING_S = 3600.0


@dataclass(frozen=True)
class RequestDefaults:
    """What a provider uses when the caller leaves a parameter out."""

    timeout_s: float = 120.0
    max_tokens: int = 256
    think: bool = False


@dataclass(frozen=True)
class GenerateRequest:
    """A fully validated request (what providers actually act on)."""

    messages: tuple[ChatMessage, ...]
    tools: tuple[ToolDefinition, ...]
    response_format: ResponseFormat | None
    timeout_s: float
    max_tokens: int
    think: bool


@runtime_checkable
class LLMProvider(Protocol):
    """A source of language-model answers. It never executes tools: it only reports the calls the
    model asked for. Provider failures raise subclasses of `LLMError`."""

    @property
    def model(self) -> str: ...

    async def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolDefinition] = (),
        response_format: ResponseFormat | None = None,
        timeout_s: float | None = None,
        max_tokens: int | None = None,
        think: bool | None = None,
    ) -> LLMResponse: ...

    async def health(self) -> ProviderHealth:
        """Never raises for provider failures: they are reported in the result."""
        ...

    async def aclose(self) -> None: ...


def prepare_request(
    messages: Sequence[ChatMessage],
    tools: Sequence[ToolDefinition] = (),
    response_format: ResponseFormat | None = None,
    timeout_s: float | None = None,
    max_tokens: int | None = None,
    think: bool | None = None,
    *,
    defaults: RequestDefaults = RequestDefaults(),
) -> GenerateRequest:
    """Validate a call against the contract. Raises LLMInvalidRequest."""
    msgs = tuple(messages)
    if not msgs:
        raise LLMInvalidRequest("at least one message is required")
    if len(msgs) > MAX_MESSAGES:
        raise LLMInvalidRequest(f"too many messages (max {MAX_MESSAGES})")
    if not all(isinstance(m, ChatMessage) for m in msgs):
        raise LLMInvalidRequest("messages must be ChatMessage instances")
    if any(m.role == "system" for m in msgs[1:]):
        raise LLMInvalidRequest("a system message is only allowed first")
    if msgs[-1].role not in ("user", "tool"):
        raise LLMInvalidRequest("the last message must come from the user or be a tool result")

    tl = tuple(tools)
    if len(tl) > MAX_TOOLS:
        raise LLMInvalidRequest(f"too many tools (max {MAX_TOOLS})")
    if not all(isinstance(t, ToolDefinition) for t in tl):
        raise LLMInvalidRequest("tools must be ToolDefinition instances")
    if len({t.name for t in tl}) != len(tl):
        raise LLMInvalidRequest("tool names must be unique")

    if response_format is not None:
        if response_format != "json" and not (isinstance(response_format, dict) and response_format.get("type") == "object"):
            raise LLMInvalidRequest("response_format must be 'json' or a JSON Schema of type 'object'")
        if tl:
            raise LLMInvalidRequest("tools and response_format cannot be combined in one call")

    t_s = defaults.timeout_s if timeout_s is None else timeout_s
    if isinstance(t_s, bool) or not isinstance(t_s, (int, float)) or not math.isfinite(t_s) or not 0 < t_s <= MAX_TIMEOUT_CEILING_S:
        raise LLMInvalidRequest(f"timeout_s must be within (0, {MAX_TIMEOUT_CEILING_S}]")
    m_t = defaults.max_tokens if max_tokens is None else max_tokens
    if isinstance(m_t, bool) or not isinstance(m_t, int) or not 1 <= m_t <= MAX_TOKENS_CEILING:
        raise LLMInvalidRequest(f"max_tokens must be an integer within 1..{MAX_TOKENS_CEILING}")
    th = defaults.think if think is None else think
    if not isinstance(th, bool):
        raise LLMInvalidRequest("think must be a boolean")

    return GenerateRequest(msgs, tl, response_format, float(t_s), m_t, th)


def check_response(request: GenerateRequest, response: LLMResponse) -> LLMResponse:
    """Rules every answer must obey, whoever produced it. Raises LLMInvalidResponse."""
    declared = {t.name for t in request.tools}
    for call in response.tool_calls:
        if call.name not in declared:
            # Never hand an undeclared tool name onward: the model hallucinated it.
            raise LLMInvalidResponse("the model requested a tool that was not declared")
    if request.response_format is not None:
        try:
            parsed = json.loads(response.content)
        except (TypeError, ValueError):
            raise LLMInvalidResponse("structured output was requested but the answer is not valid JSON") from None
        if request.response_format != "json" and not isinstance(parsed, dict):
            raise LLMInvalidResponse("structured output must be a JSON object")
    return response
