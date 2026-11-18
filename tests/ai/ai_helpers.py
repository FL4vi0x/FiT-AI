"""Shared helpers for the AI Engine tests: a simulated Ollama server built on httpx.MockTransport."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from fit_ai.ai import LLMSettings, OllamaProvider

SETTINGS = LLMSettings()  # defaults: qwen3:4b-instruct-2507-q4_K_M @ 127.0.0.1:11434


def chat_reply(content: str = "Olá!", **over: Any) -> dict[str, Any]:
    """A realistic /api/chat answer (stream=false)."""
    base: dict[str, Any] = {
        "model": SETTINGS.model,
        "created_at": "2026-11-16T22:00:00Z",
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": "stop",
        "total_duration": 2_000_000_000,
        "load_duration": 100_000_000,
        "prompt_eval_count": 40,
        "prompt_eval_cached_count": 0,
        "prompt_eval_duration": 400_000_000,
        "eval_count": 20,
        "eval_duration": 1_000_000_000,
    }
    base.update(over)
    return base


def tool_reply(name: str = "ler_rotacao_motor", arguments: Any = None, call_id: str | None = "abc") -> dict[str, Any]:
    call: dict[str, Any] = {"function": {"index": 0, "name": name, "arguments": {} if arguments is None else arguments}}
    if call_id is not None:
        call["id"] = call_id
    return chat_reply("", message={"role": "assistant", "content": "", "tool_calls": [call]})


class FakeOllama:
    """Records requests and answers with whatever `responder` returns (a dict -> 200 JSON, or an httpx.Response)."""

    def __init__(self, responder: Callable[[httpx.Request], Any] | dict[str, Any] | None = None):
        self.requests: list[httpx.Request] = []
        self.bodies: list[dict[str, Any]] = []
        self.responder = responder if responder is not None else chat_reply()

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.content:
            self.bodies.append(json.loads(request.content))
        out = self.responder(request) if callable(self.responder) else self.responder
        if hasattr(out, "__await__"):
            out = await out
        if isinstance(out, httpx.Response):
            return out
        return httpx.Response(200, json=out)

    @property
    def last_body(self) -> dict[str, Any]:
        return self.bodies[-1]


def make_provider(server: FakeOllama | None = None, settings: LLMSettings | None = None) -> tuple[OllamaProvider, FakeOllama]:
    server = server or FakeOllama()
    client = httpx.AsyncClient(transport=httpx.MockTransport(server))
    return OllamaProvider(settings or SETTINGS, client=client), server


def error_response(status: int, message: str) -> httpx.Response:
    return httpx.Response(status, json={"error": message})
