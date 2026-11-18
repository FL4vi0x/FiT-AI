"""Memory entities. Plain typed data: no SQLite, FastAPI or LLM types here."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_FACT_CHARS = 1000
MAX_TURN_CHARS = 8000
MAX_PREF_KEY_CHARS = 60
MAX_PREF_VALUE_CHARS = 300

TurnRole = Literal["user", "assistant"]
# The ONLY origin accepted for facts and preferences: the user explicitly asked for it. Telemetry, tool
# results and model output can never become permanent facts about the vehicle.
Origin = Literal["user_explicit"]
MemoryKind = Literal["fact", "preference", "turn"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Conversation(_Frozen):
    id: str
    title: str | None = None
    created_at: datetime
    updated_at: datetime


class ConversationTurn(_Frozen):
    id: str
    conversation_id: str
    role: TurnRole
    content: str = Field(max_length=MAX_TURN_CHARS)
    created_at: datetime
    expires_at: datetime | None = None


class MemoryFact(_Frozen):
    """Something the user asked the assistant to remember. A user STATEMENT, never a sensor measurement."""

    id: str
    content: str = Field(min_length=1, max_length=MAX_FACT_CHARS)
    origin: Origin = "user_explicit"
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None

    @field_validator("content")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content must not be blank")
        return v


class UserPreference(_Frozen):
    id: str
    key: str = Field(min_length=1, max_length=MAX_PREF_KEY_CHARS)
    value: str = Field(min_length=1, max_length=MAX_PREF_VALUE_CHARS)
    origin: Origin = "user_explicit"
    created_at: datetime
    updated_at: datetime


class MemoryHit(_Frozen):
    """A search result. `score` is bm25 when FTS5 is used (lower is better) or 0.0 for the LIKE fallback."""

    kind: MemoryKind
    id: str
    content: str
    conversation_id: str | None = None
    created_at: datetime
    score: float = 0.0
