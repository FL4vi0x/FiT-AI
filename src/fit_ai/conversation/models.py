"""Strict request/response models of the chat contract (no HTTP types here)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_MESSAGE_HARD_CAP = 4000  # the configurable limit (ChatSettings.max_message_chars) is always <= this


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=MAX_MESSAGE_HARD_CAP)
    conversation_id: str | None = Field(default=None, max_length=64)

    @field_validator("message")
    @classmethod
    def _clean(cls, v: str) -> str:
        try:
            v.encode("utf-8")  # a lone surrogate ("\ud800") is valid JSON text but not valid UTF-8
        except UnicodeEncodeError:
            raise ValueError("message must be valid UTF-8 text") from None
        if any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in v):
            raise ValueError("message must not contain control characters")
        if not v.strip():
            raise ValueError("message must not be blank")
        return v


AnswerOrigin = Literal["llm", "llm_retry", "fallback", "deterministic", "policy_refusal", "memory_command"]
Availability = Literal["not_requested", "ok", "partial", "stale", "unavailable"]
ModelStatus = Literal["ok", "unavailable", "timeout", "not_found", "error", "not_used"]


class ChatResponse(BaseModel):
    """Everything here is safe to show: no prompts, memory contents, paths or reasoning."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    request_id: str
    answer: str
    model: str | None  # the model that was asked; null when no model call was made
    answer_origin: AnswerOrigin
    used_tools: list[str]
    fallback_used: bool  # the answer was built by code from verified evidence, not by the model
    data_source: str | None  # where the readings came from (e.g. "octave"); null when no reading was used
    simulated: bool | None  # null: no reading used, or the source did not say
    availability: Availability  # state of the vehicle data for THIS turn
    model_status: ModelStatus
    memory_saved: bool = False  # true only when a memory was really persisted by this request
    history_saved: bool = True
    replayed: bool = False  # true when this is the stored answer of an earlier request with the same Idempotency-Key
    latency_ms: int
