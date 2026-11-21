"""Settings of the chat layer (HTTP limits, admission control, idempotency, browser origins).

Kept apart from the Core's, the LLM's and the assistant's settings: a bad value here disables chat (and the
strict default guard stays on) but never stops the Core from serving telemetry.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from fit_ai.config import LOOPBACK_HOSTS, ConfigError


@dataclass(frozen=True)
class ChatSettings:
    max_message_chars: int = 1000
    max_body_bytes: int = 16 * 1024
    request_timeout_s: float = 180.0  # generation + verification (queue wait is separate)
    max_concurrent: int = 1  # simultaneous generations (CPU inference is expensive)
    max_waiting: int = 1  # requests allowed to wait for a free slot; more are refused at once
    queue_timeout_s: float = 60.0  # how long a waiting request may wait
    idempotency_ttl_s: float = 600.0
    idempotency_max_entries: int = 256
    allowed_origins: tuple[str, ...] = ()  # browser origins allowed to call the API; empty = none

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "ChatSettings":
        e = os.environ if env is None else env
        s = cls(
            max_message_chars=_num(e, "FIT_AI_CHAT_MAX_MESSAGE_CHARS", cls.max_message_chars, int),
            max_body_bytes=_num(e, "FIT_AI_CHAT_MAX_BODY_BYTES", cls.max_body_bytes, int),
            request_timeout_s=_num(e, "FIT_AI_CHAT_REQUEST_TIMEOUT_S", cls.request_timeout_s, float),
            max_concurrent=_num(e, "FIT_AI_CHAT_MAX_CONCURRENT", cls.max_concurrent, int),
            max_waiting=_num(e, "FIT_AI_CHAT_MAX_WAITING", cls.max_waiting, int),
            queue_timeout_s=_num(e, "FIT_AI_CHAT_QUEUE_TIMEOUT_S", cls.queue_timeout_s, float),
            idempotency_ttl_s=_num(e, "FIT_AI_CHAT_IDEMPOTENCY_TTL_S", cls.idempotency_ttl_s, float),
            allowed_origins=tuple(o.strip() for o in e.get("FIT_AI_CHAT_ALLOWED_ORIGINS", "").split(",") if o.strip()),
        )
        s.validate()
        return s

    def validate(self) -> None:
        if not 1 <= self.max_message_chars <= 4000:
            raise ConfigError("FIT_AI_CHAT_MAX_MESSAGE_CHARS must be within 1..4000")
        if not 1024 <= self.max_body_bytes <= 1024 * 1024:
            raise ConfigError("FIT_AI_CHAT_MAX_BODY_BYTES must be within 1024..1048576")
        if self.max_body_bytes < self.max_message_chars:
            raise ConfigError("FIT_AI_CHAT_MAX_BODY_BYTES must not be smaller than the message limit")
        if not 5 <= self.request_timeout_s <= 900:
            raise ConfigError("FIT_AI_CHAT_REQUEST_TIMEOUT_S must be within 5..900")
        if not 1 <= self.max_concurrent <= 4:
            raise ConfigError("FIT_AI_CHAT_MAX_CONCURRENT must be within 1..4")
        if not 0 <= self.max_waiting <= 10:
            raise ConfigError("FIT_AI_CHAT_MAX_WAITING must be within 0..10")
        if not 0.1 <= self.queue_timeout_s <= 300:
            raise ConfigError("FIT_AI_CHAT_QUEUE_TIMEOUT_S must be within 0.1..300")
        if not 1 <= self.idempotency_ttl_s <= 86400:
            raise ConfigError("FIT_AI_CHAT_IDEMPOTENCY_TTL_S must be within 1..86400")
        for origin in self.allowed_origins:
            validate_origin(origin)


def validate_origin(origin: str) -> str:
    """Only plain http(s) origins on a loopback name, no path/query/credentials. Never "null" or "*"."""
    try:
        parts = urlsplit(origin)
        host = parts.hostname
        parts.port  # noqa: B018 - raises ValueError on a bad port
    except ValueError:
        raise ConfigError(f"invalid allowed origin {origin!r}") from None
    if (origin in ("null", "*") or parts.scheme not in ("http", "https") or host is None
            or host.lower() not in LOOPBACK_HOSTS or parts.username or parts.password
            or parts.path not in ("", "/") or parts.query or parts.fragment):
        raise ConfigError(f"allowed origins must be http(s)://127.0.0.1|localhost[:port] only, got {origin!r}")
    return origin


def _num(env: dict[str, str], key: str, default, cast):
    raw = env.get(key)
    if raw is None:
        return default
    try:
        v = cast(raw)
    except ValueError:
        raise ConfigError(f"{key} must be {'an integer' if cast is int else 'a number'}, got {raw!r}") from None
    if cast is float and v != v:
        raise ConfigError(f"{key} must be finite")
    return v
