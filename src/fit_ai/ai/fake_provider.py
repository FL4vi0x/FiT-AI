"""FakeLLMProvider: a deterministic, scriptable LLMProvider for tests (no server, no model).

It applies exactly the same request validation (`prepare_request`) and response rules
(`check_response`) as the real adapter, honours the caller's timeout and cancellation, and records
every call so tests can assert on what the service sent. It is the base for future memory,
grounding and tool tests.

    fake = FakeLLMProvider([Reply.text("Olá"), Reply.tool_call("ler_rotacao_motor"), Reply.timeout()])
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from fit_ai.ai.contracts import (
    GenerateRequest,
    RequestDefaults,
    ResponseFormat,
    check_response,
    prepare_request,
)
from fit_ai.ai.errors import (
    LLMError,
    LLMIncompleteResponse,
    LLMInvalidResponse,
    LLMTimeout,
    LLMTransportError,
    LLMUnavailable,
)
from fit_ai.ai.models import ChatMessage, LLMResponse, ProviderHealth, Timings, ToolCall, ToolDefinition, Usage


@dataclass(frozen=True)
class Reply:
    """One scripted step: an answer (built from the request when `build` is given) or an error."""

    response: LLMResponse | None = None
    error: BaseException | None = None
    delay_s: float = 0.0
    build: Callable[[GenerateRequest], LLMResponse] | None = None

    # ── answers ──
    @classmethod
    def text(cls, content: str, *, finish_reason: str = "stop", delay_s: float = 0.0,
             prompt_tokens: int = 10, completion_tokens: int | None = None) -> "Reply":
        return cls(response=_resp(content, (), finish_reason, prompt_tokens, completion_tokens), delay_s=delay_s)

    @classmethod
    def json(cls, obj: Any, *, delay_s: float = 0.0) -> "Reply":
        return cls(response=_resp(json.dumps(obj, ensure_ascii=False), (), "stop", 10, None), delay_s=delay_s)

    @classmethod
    def tool_call(cls, name: str, arguments: dict[str, Any] | None = None, *, call_id: str | None = "call-1",
                  delay_s: float = 0.0) -> "Reply":
        return cls(response=_resp("", (ToolCall(id=call_id, name=name, arguments=arguments or {}),), "stop", 10, None),
                   delay_s=delay_s)

    @classmethod
    def empty(cls) -> "Reply":
        """A well-formed answer with no content and no tool call."""
        return cls(response=_resp("", (), "stop", 10, 0))

    @classmethod
    def echo(cls, prefix: str = "") -> "Reply":
        """Answers with the last user/tool message (handy to prove what reached the provider)."""
        return cls(build=lambda r: _resp(prefix + r.messages[-1].content, (), "stop", 10, None))

    # ── failures ──
    @classmethod
    def timeout(cls) -> "Reply":
        return cls(error=LLMTimeout("scripted timeout"))

    @classmethod
    def unavailable(cls) -> "Reply":
        return cls(error=LLMUnavailable("scripted: the server is not reachable"))

    @classmethod
    def transport_error(cls) -> "Reply":
        return cls(error=LLMTransportError("scripted transport failure"))

    @classmethod
    def malformed(cls) -> "Reply":
        return cls(error=LLMInvalidResponse("scripted malformed answer"))

    @classmethod
    def incomplete(cls) -> "Reply":
        return cls(error=LLMIncompleteResponse("scripted incomplete answer"))

    @classmethod
    def fail(cls, error: LLMError) -> "Reply":
        return cls(error=error)

    @classmethod
    def hang(cls) -> "Reply":
        """Never answers: only the caller's timeout or cancellation ends it."""
        return cls(delay_s=float("inf"))


@dataclass
class FakeCall:
    request: GenerateRequest

    @property
    def messages(self) -> tuple[ChatMessage, ...]:
        return self.request.messages


@dataclass
class FakeLLMProvider:
    replies: Iterable[Reply] = ()
    model: str = "fake-model:test"
    default: Reply | None = None  # used when the script is exhausted; None = fail loudly
    defaults: RequestDefaults = field(default_factory=RequestDefaults)
    calls: list[FakeCall] = field(default_factory=list)
    closed: bool = False

    def __post_init__(self) -> None:
        self._queue: list[Reply] = list(self.replies)

    def script(self, *replies: Reply) -> "FakeLLMProvider":
        self._queue.extend(replies)
        return self

    @property
    def pending(self) -> int:
        return len(self._queue)

    async def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolDefinition] = (),
        response_format: ResponseFormat | None = None,
        timeout_s: float | None = None,
        max_tokens: int | None = None,
        think: bool | None = None,
    ) -> LLMResponse:
        req = prepare_request(messages, tools, response_format, timeout_s, max_tokens, think, defaults=self.defaults)
        if self.closed:
            raise LLMUnavailable("the provider is closed")
        self.calls.append(FakeCall(req))
        step = self._queue.pop(0) if self._queue else self.default
        if step is None:
            raise AssertionError("FakeLLMProvider: the script is exhausted (a call was not expected)")
        try:
            async with asyncio.timeout(req.timeout_s):
                if step.delay_s:
                    await asyncio.sleep(step.delay_s)
        except TimeoutError:
            raise LLMTimeout(f"no answer within {req.timeout_s:g} s") from None
        if step.error is not None:
            raise step.error
        response = step.build(req) if step.build else step.response
        assert response is not None
        return check_response(req, response.model_copy(update={"model": self.model}))

    async def health(self) -> ProviderHealth:
        return ProviderHealth(available=not self.closed, backend="fake", model=self.model,
                              model_installed=True, model_digest="fake", server_version="fake")

    async def aclose(self) -> None:
        self.closed = True


def _resp(content: str, calls: tuple[ToolCall, ...], finish: str, prompt_tokens: int,
          completion_tokens: int | None) -> LLMResponse:
    n = len(content.split()) if completion_tokens is None else completion_tokens
    return LLMResponse(
        content=content, tool_calls=calls, model="fake-model:test", finish_reason=finish,
        usage=Usage(prompt_tokens=prompt_tokens, completion_tokens=n),
        timings=Timings(total_s=0.01, load_s=0.0, prompt_eval_s=0.005, generation_s=0.005),
    )
