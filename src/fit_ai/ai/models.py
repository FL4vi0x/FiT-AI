"""Provider-independent data model of the AI Engine. No Ollama types leak out of here."""
from __future__ import annotations

import json
import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Role = Literal["system", "user", "assistant", "tool"]

MAX_MESSAGE_CHARS = 32_000
_TOOL_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]{0,63}$")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ToolCall(_Frozen):
    """A tool the model ASKED to call. The engine never executes it."""

    id: str | None = None
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not _TOOL_NAME.match(v):
            raise ValueError("invalid tool name")
        return v


class ToolDefinition(_Frozen):
    name: str
    description: str = Field(min_length=1, max_length=1024)
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not _TOOL_NAME.match(v):
            raise ValueError("invalid tool name")
        return v

    @field_validator("parameters")
    @classmethod
    def _params(cls, v: dict[str, Any]) -> dict[str, Any]:
        if v.get("type") != "object":
            raise ValueError("tool parameters must be a JSON Schema of type 'object'")
        return v


class ChatMessage(_Frozen):
    role: Role
    content: str = Field(default="", max_length=MAX_MESSAGE_CHARS)
    tool_name: str | None = None  # role == "tool": which tool produced this result
    tool_call_id: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()  # role == "assistant": calls it requested (history replay)

    @model_validator(mode="after")
    def _shape(self) -> "ChatMessage":
        if self.role == "tool":
            if not self.tool_name:
                raise ValueError("a tool message needs tool_name")
        elif self.tool_name or self.tool_call_id:
            raise ValueError("tool_name/tool_call_id are only valid on tool messages")
        if self.tool_calls and self.role != "assistant":
            raise ValueError("tool_calls are only valid on assistant messages")
        if self.role in ("system", "user") and not self.content.strip():
            raise ValueError(f"{self.role} message needs content")
        if self.role == "assistant" and not self.content.strip() and not self.tool_calls:
            raise ValueError("assistant message needs content or tool_calls")
        return self

    @classmethod
    def system(cls, content: str) -> "ChatMessage":
        return cls(role="system", content=content)

    @classmethod
    def user(cls, content: str) -> "ChatMessage":
        return cls(role="user", content=content)

    @classmethod
    def assistant(cls, content: str = "", tool_calls: tuple[ToolCall, ...] = ()) -> "ChatMessage":
        return cls(role="assistant", content=content, tool_calls=tool_calls)

    @classmethod
    def tool_result(cls, tool_name: str, content: str, tool_call_id: str | None = None) -> "ChatMessage":
        return cls(role="tool", content=content, tool_name=tool_name, tool_call_id=tool_call_id)


class Usage(_Frozen):
    prompt_tokens: int | None = None
    cached_prompt_tokens: int | None = None
    completion_tokens: int | None = None


class Timings(_Frozen):
    """Seconds. Any field is None when the provider did not report it. `total_s` is the provider's
    own total, not a time-to-first-token."""

    total_s: float | None = None
    load_s: float | None = None
    prompt_eval_s: float | None = None
    generation_s: float | None = None


class LLMResponse(_Frozen):
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    model: str
    finish_reason: str | None = None  # e.g. "stop", "length"
    usage: Usage = Field(default_factory=Usage)
    timings: Timings = Field(default_factory=Timings)
    thinking_chars: int = 0  # size only; reasoning text is never kept
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @property
    def generation_tokens_per_s(self) -> float | None:
        return _rate(self.usage.completion_tokens, self.timings.generation_s)

    @property
    def prompt_tokens_per_s(self) -> float | None:
        return _rate(self.usage.prompt_tokens, self.timings.prompt_eval_s)

    def json_content(self) -> Any:
        """The content parsed as JSON. Raises ValueError if it is not."""
        return json.loads(self.content)


def _rate(tokens: int | None, seconds: float | None) -> float | None:
    if not tokens or not seconds or seconds <= 0 or not math.isfinite(seconds):
        return None
    return tokens / seconds


class ProviderHealth(_Frozen):
    """Never raised for provider failures: reported here."""

    available: bool
    backend: str
    model: str
    model_installed: bool | None = None
    model_digest: str | None = None
    server_version: str | None = None
    detail: str | None = None
