"""OPTIONAL start-up warm-up of the local language model (P8.3). Off unless FIT_AI_LLM_WARMUP is set.

Why it exists (measured on the development machine, qwen3:4b-instruct, CPU only): the first question after the model was unloaded
took 20.7 s and 25.4 s; the same question after a warm-up took 3.1 s and 3.1 s. Loading the model is only ~2.6 s of that: the rest is
the server processing the long system prompt for the first time. So the warm-up sends the REAL system prompt with a trivial
question and `max_tokens=1`, which lets the server reuse that prefix (655 of 668 prompt tokens were then served from cache).

What it costs, so nobody is surprised: the model's memory (about 3.0 GB resident), and one burst of CPU work of roughly 20 s at
start-up, in the background. What it does NOT do: it does not block the Core's start (it is a background task), it does not store
anything (no conversation, memory or audit record: it bypasses the orchestrator), it does not read telemetry, and it never raises.
It is skipped when free RAM is below `warmup_min_free_ram_mb`, when the machine is busy, or when either cannot be measured.

The benefit lasts only while the server keeps the model loaded. The server's default (measured here, Ollama 0.40.16) is 10
minutes after the last request; set FIT_AI_LLM_KEEP_ALIVE (for example 30m, confirmed to be honoured) to ask for longer. That keeps the memory in use for that long, which is why it is a separate
opt-in.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from fit_ai.ai import ChatMessage, LLMError, LLMProvider
from fit_ai.ai.hostload import cpu_busy_fraction, free_ram_mb
from fit_ai.orchestration.prompt import system_message

log = logging.getLogger("fit_ai.warmup")

BUSY_CPU_FRACTION = 0.8
WARMUP_QUESTION = "PERGUNTA: oi"  # constant: nothing from any conversation is ever sent

Outcome = Literal["done", "skipped_low_ram", "skipped_ram_unknown", "skipped_busy_cpu", "skipped_cpu_unknown", "failed"]


@dataclass(frozen=True)
class WarmupResult:
    outcome: Outcome
    seconds: float = 0.0
    free_ram_mb: int | None = None


async def warm_up(llm: LLMProvider, *, min_free_ram_mb: int, timeout_s: float = 120.0,
                  free_ram: Callable[[], int | None] = free_ram_mb,
                  cpu_busy: Callable[[], float | None] = cpu_busy_fraction) -> WarmupResult:
    """Never raises (except cancellation at shutdown). Returns what happened."""
    ram = free_ram()
    if ram is None:
        log.info("warm-up skipped: free RAM cannot be measured")
        return WarmupResult("skipped_ram_unknown")
    if ram < min_free_ram_mb:
        log.info("warm-up skipped: %d MB free is below the %d MB configured", ram, min_free_ram_mb)
        return WarmupResult("skipped_low_ram", free_ram_mb=ram)
    busy = await asyncio.to_thread(cpu_busy)  # samples the CPU for half a second: keep it off the event loop
    if busy is None:
        log.info("warm-up skipped: CPU load cannot be measured")
        return WarmupResult("skipped_cpu_unknown", free_ram_mb=ram)
    if busy > BUSY_CPU_FRACTION:
        log.info("warm-up skipped: the machine is busy (CPU %.0f%%)", busy * 100)
        return WarmupResult("skipped_busy_cpu", free_ram_mb=ram)
    t0 = time.perf_counter()
    try:
        await llm.generate([system_message(), ChatMessage.user(WARMUP_QUESTION)], think=False, max_tokens=1, timeout_s=timeout_s)
    except LLMError as exc:
        log.warning("warm-up failed (%s); the first question will be slow instead", type(exc).__name__)
        return WarmupResult("failed", time.perf_counter() - t0, ram)
    except Exception:
        log.exception("warm-up failed unexpectedly")
        return WarmupResult("failed", time.perf_counter() - t0, ram)
    seconds = time.perf_counter() - t0
    log.info("warm-up done in %.1f s", seconds)
    return WarmupResult("done", seconds, ram)


def start_background_warmup(runtime) -> "asyncio.Task | None":
    """Schedule the warm-up and return at once (the Core's start is never delayed). None when it is not enabled."""
    if runtime is None or not getattr(runtime, "warmup", None):
        return None
    return asyncio.create_task(runtime.warmup(), name="fit-ai-llm-warmup")
