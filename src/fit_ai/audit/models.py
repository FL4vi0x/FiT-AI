"""Audit events. Metadata about OPERATIONS, never conversation content.

`summary` is redacted and truncated by the model itself, so no code path can store an unredacted value.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_SUMMARY = 240

_REDACTIONS = [
    (re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), "[redacted-credential]"),
    (re.compile(r"(?i)\b(?:api[_-]?key|token|secret|senha|password|passwd|authorization)\b\s*[:=]\s*\S+"),
     "[redacted-secret]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "[redacted-key]"),
    (re.compile(r"\b(?:ghp|gho|github_pat|xox[bap])_?[A-Za-z0-9_-]{12,}\b"), "[redacted-key]"),
    (re.compile(r"\b[A-Za-z0-9+/_-]{32,}={0,2}"), "[redacted-blob]"),  # long keys / hashes / base64
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[redacted-email]"),
    (re.compile(r"\b(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4}\b"), "[redacted-phone]"),
    (re.compile(r"(?i)([A-Z]:\\Users\\)[^\\\s]+"), r"\1<user>"),  # Windows home folder name
    (re.compile(r"(?i)(/home/|/Users/)[^/\s]+"), r"\1<user>"),
]


def redact(text: str, limit: int = MAX_SUMMARY) -> str:
    """Remove credentials, e-mails, phone numbers and user-folder names, collapse whitespace, truncate."""
    for rx, rep in _REDACTIONS:
        text = rx.sub(rep, text)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class AuditEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str
    request_id: str
    turn_id: str | None = None
    timestamp: datetime
    kind: Literal["tool_authorization", "tool_result", "turn", "policy"]
    tool: str | None = Field(default=None, max_length=64)
    permission: str | None = None
    decision: Literal["allowed", "denied", "ok", "error", "refused"]
    summary: str = ""
    duration_ms: int | None = None
    error_code: str | None = Field(default=None, max_length=64)
    simulated: bool | None = None

    @field_validator("summary", mode="before")
    @classmethod
    def _redact_summary(cls, v: object) -> str:
        return redact(str(v or ""))

    @field_validator("tool", "error_code", mode="before")
    @classmethod
    def _clean_short(cls, v: object) -> object:
        if v is None:
            return v
        return redact(str(v), 64)
