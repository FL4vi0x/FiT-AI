"""Read-only availability of the local language-model server, for the interface.

What it does: asks the provider's `health()` (GET /api/version and GET /api/tags on the configured loopback server). It never
loads a model, never generates, never starts anything, and takes no input from the client: the URL and the model name come
from the Core's own configuration. The answer carries no server version, digest, URL or path.

States (the interface shows exactly these):
- available            the server answers and the configured model is installed
- model_not_installed  the server answers but the configured model is not installed
- unavailable          nothing is listening (the server is switched off)
- unverified           the check could not be completed (timeout, odd answer, internal error): NOT a statement about the server
- not_configured       the Core runs without a language model (chat disabled)

A short cache keeps a polling interface from hammering the server.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from fit_ai.ai.models import ProviderHealth

log = logging.getLogger("fit_ai.llm_status")

LLMState = Literal["available", "model_not_installed", "unavailable", "unverified", "not_configured"]

CHECK_TIMEOUT_S = 2.5
CACHE_TTL_S = 5.0


@dataclass(frozen=True)
class LLMStatus:
    state: LLMState
    model: str | None
    checked_at: datetime


def classify(health: ProviderHealth) -> LLMState:
    """Map the provider's report to a state. Only a definite refusal to connect is "unavailable": a timeout or an odd answer
    does not prove the server is off, so it stays "unverified"."""
    if health.available:
        return "available" if health.model_installed else "model_not_installed"
    if health.detail == "llm_unavailable":
        return "unavailable"
    return "unverified"


class LLMStatusService:
    def __init__(
        self,
        health: Callable[[], Awaitable[ProviderHealth]] | None,
        *,
        model: str | None = None,
        timeout_s: float = CHECK_TIMEOUT_S,
        ttl_s: float = CACHE_TTL_S,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._health, self._model = health, model
        self._timeout_s, self._ttl_s, self._clock, self._now = timeout_s, ttl_s, clock, now
        self._lock = asyncio.Lock()
        self._cached: tuple[float, LLMStatus] | None = None

    async def get_status(self) -> LLMStatus:
        if self._health is None:
            return LLMStatus("not_configured", None, self._now())
        async with self._lock:  # concurrent callers share one check
            if self._cached is not None and self._clock() - self._cached[0] < self._ttl_s:
                return self._cached[1]
            status = await self._check()
            self._cached = (self._clock(), status)
            return status

    async def _check(self) -> LLMStatus:
        assert self._health is not None
        try:
            async with asyncio.timeout(self._timeout_s):
                report = await self._health()
            state = classify(report)
        except TimeoutError:
            state = "unverified"
        except Exception as exc:  # the interface must always get an answer
            log.warning("llm status check failed: %s", type(exc).__name__)
            state = "unverified"
        return LLMStatus(state, self._model, self._now())
