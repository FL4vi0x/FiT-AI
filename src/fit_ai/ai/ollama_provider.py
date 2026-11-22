"""OllamaProvider: the LLMProvider adapter for a LOCAL Ollama server.

Safety properties (each covered by a test):
- the URL must be plain-http loopback (validated again here, not only in the settings);
- no proxies, no redirects, no environment-driven TLS/proxy configuration (`trust_env=False`);
- prompts and answers are never logged (only model, counts and durations);
- tool calls are only REPORTED, never executed, and undeclared tool names are rejected;
- one request at a time (the server runs with OLLAMA_NUM_PARALLEL=1): extra callers wait, and the
  caller's timeout covers waiting plus running.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from fit_ai.ai.config import LLMSettings, validate_loopback_url, validate_model_name
from fit_ai.ai.contracts import (
    GenerateRequest,
    RequestDefaults,
    ResponseFormat,
    check_response,
    prepare_request,
)
from fit_ai.ai.errors import (
    LLMConfigurationError,
    LLMContextExceeded,
    LLMIncompleteResponse,
    LLMInvalidRequest,
    LLMInvalidResponse,
    LLMModelNotFound,
    LLMModelUnavailable,
    LLMTimeout,
    LLMTransportError,
    LLMUnavailable,
)
from fit_ai.ai.models import (
    ChatMessage,
    LLMResponse,
    ProviderHealth,
    Timings,
    ToolCall,
    ToolDefinition,
    Usage,
)
from fit_ai.config import ConfigError

log = logging.getLogger("fit_ai.ai.ollama")

_NS = 1e9
_CONTEXT_MSG = re.compile(r"request \((\d+) tokens\) exceeds the available context size \((\d+) tokens\)")


# ── wire format of Ollama's /api/chat (private: never leaves this module) ─────────────────────────

class _Fn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    arguments: dict[str, Any] | str = {}


class _Call(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str | None = None
    function: _Fn


class _Msg(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: str | None = None
    content: str | None = ""
    thinking: str | None = None
    tool_calls: list[_Call] | None = None


class _ChatReply(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model: str | None = None
    message: _Msg
    done: bool | None = None
    done_reason: str | None = None
    total_duration: int | None = None
    load_duration: int | None = None
    prompt_eval_count: int | None = None
    prompt_eval_cached_count: int | None = None
    prompt_eval_duration: int | None = None
    eval_count: int | None = None
    eval_duration: int | None = None


def _secs(ns: int | None) -> float | None:
    return None if ns is None else round(ns / _NS, 4)


class OllamaProvider:
    backend = "ollama"

    def __init__(self, settings: LLMSettings | None = None, *, client: httpx.AsyncClient | None = None):
        settings = settings or LLMSettings()
        try:
            settings.validate()
            self._base = validate_loopback_url(settings.ollama_url)
            self._model = validate_model_name(settings.model)
        except ConfigError as exc:
            raise LLMConfigurationError(str(exc)) from None
        self._s = settings
        self._defaults = RequestDefaults(settings.timeout_s, settings.max_tokens, settings.think)
        self._owns_client = client is None
        self._client = client or self._new_client()
        self._client_loop: asyncio.AbstractEventLoop | None = None  # the loop that owns `_client`'s connections
        self._gate = asyncio.Semaphore(1)
        self._closed = False

    def _new_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(self._s.timeout_s, connect=5.0),
            follow_redirects=False,
            trust_env=False,
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=1),
            headers={"User-Agent": "fit-ai"},
        )

    def _client_for_running_loop(self) -> httpx.AsyncClient:
        """A pooled connection belongs to the event loop that opened it. Reusing it from another loop stalls until the
        timeout or fails with "Event loop is closed" (found in the P7 benchmark harness, which served each request
        from a new loop). The app itself runs on one loop and never changes client; an injected client is the
        caller's business. When the loop changes, the old connections are dropped (they cannot be closed from here)
        and a fresh client is used."""
        if not self._owns_client:
            return self._client
        loop = asyncio.get_running_loop()
        if self._client_loop is None:
            self._client_loop = loop
        elif loop is not self._client_loop:
            self._client = self._new_client()
            self._client_loop = loop
        return self._client

    # ── contract ──────────────────────────────────────────────────────────────────────────────

    @property
    def model(self) -> str:
        return self._model

    async def __aenter__(self) -> "OllamaProvider":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            try:
                await self._client.aclose()
            except RuntimeError:
                pass  # its connections belong to a loop that is already closed (see _client_for_running_loop)

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
        req = prepare_request(messages, tools, response_format, timeout_s, max_tokens, think, defaults=self._defaults)
        if self._closed:
            raise LLMUnavailable("the provider is closed")
        try:
            async with asyncio.timeout(req.timeout_s):  # covers queueing + running
                async with self._gate:
                    data = await self._post("/api/chat", self._chat_body(req), req.timeout_s)
        except TimeoutError:
            log.warning("llm timeout model=%s after %.1fs", self._model, req.timeout_s)
            raise LLMTimeout(f"no answer within {req.timeout_s:g} s") from None
        response = check_response(req, self._normalize(data))
        log.info(
            "llm ok model=%s prompt_tokens=%s completion_tokens=%s total_s=%s finish=%s tool_calls=%d",
            response.model, response.usage.prompt_tokens, response.usage.completion_tokens,
            response.timings.total_s, response.finish_reason, len(response.tool_calls),
        )
        return response

    async def health(self) -> ProviderHealth:
        base = dict(backend=self.backend, model=self._model)
        try:
            async with asyncio.timeout(8):
                version = await self._get("/api/version", 5.0)
                tags = await self._get("/api/tags", 5.0)
        except TimeoutError:
            return ProviderHealth(available=False, detail="llm_timeout", **base)
        except (LLMUnavailable, LLMTransportError, LLMInvalidResponse) as exc:
            return ProviderHealth(available=False, detail=exc.code, **base)
        models = tags.get("models") if isinstance(tags, dict) else None
        if not isinstance(models, list):
            return ProviderHealth(available=False, detail="llm_invalid_response", **base)
        found = next((m for m in models if isinstance(m, dict) and m.get("name") == self._model), None)
        digest = found.get("digest") if found else None
        return ProviderHealth(
            available=True,
            model_installed=found is not None,
            model_digest=digest if isinstance(digest, str) else None,
            server_version=version.get("version") if isinstance(version, dict) else None,
            detail=None if found else "llm_model_not_found",
            **base,
        )

    # ── request building ──────────────────────────────────────────────────────────────────────

    def _chat_body(self, req: GenerateRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [self._wire_message(m) for m in req.messages],
            "stream": False,  # streaming is a later phase; the contract does not expose it yet
            "think": req.think,
            "options": {
                "num_ctx": self._s.context,
                "temperature": self._s.temperature,
                "seed": self._s.seed,
                "num_predict": req.max_tokens,
            },
        }
        if req.tools:
            body["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in req.tools
            ]
        if req.response_format is not None:
            body["format"] = req.response_format  # "json" or a JSON Schema
        return body

    @staticmethod
    def _wire_message(m: ChatMessage) -> dict[str, Any]:
        out: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.role == "tool":
            out["tool_name"] = m.tool_name
        if m.tool_calls:
            out["tool_calls"] = [{"function": {"name": c.name, "arguments": c.arguments}} for c in m.tool_calls]
        return out

    # ── transport ─────────────────────────────────────────────────────────────────────────────

    async def _get(self, path: str, timeout_s: float) -> Any:
        return await self._request("GET", path, None, timeout_s)

    async def _post(self, path: str, body: dict[str, Any], timeout_s: float) -> Any:
        return await self._request("POST", path, body, timeout_s)

    async def _request(self, method: str, path: str, body: dict[str, Any] | None, timeout_s: float) -> Any:
        try:
            resp = await self._client_for_running_loop().request(
                method,
                self._base + path,
                json=body,
                timeout=httpx.Timeout(timeout_s, connect=min(5.0, timeout_s)),
            )
        except httpx.ConnectError:
            raise LLMUnavailable("cannot connect to the local Ollama server") from None
        except httpx.TimeoutException:
            raise LLMTimeout("the Ollama server did not answer in time") from None
        except httpx.TransportError as exc:
            raise LLMTransportError(f"transport failure ({type(exc).__name__})") from None
        if resp.status_code != 200:
            raise self._http_error(resp)
        try:
            return resp.json()
        except ValueError:
            raise LLMInvalidResponse("the server answer is not valid JSON") from None

    def _http_error(self, resp: httpx.Response) -> Exception:
        status = resp.status_code
        try:
            err = resp.json().get("error", "")
            err = err if isinstance(err, str) else ""
        except (ValueError, AttributeError):
            err = ""
        low = err.lower()
        if status == 404 and "not found" in low and "model" in low:
            return LLMModelNotFound(f"model {self._model!r} is not installed")
        if status == 400 and "exceeds the available context" in low:
            m = _CONTEXT_MSG.search(err)
            detail = f" ({m.group(1)} tokens > {m.group(2)})" if m else ""
            return LLMContextExceeded(f"the prompt does not fit the context window{detail}")
        if status == 400:
            return LLMInvalidRequest("the Ollama server rejected the request (HTTP 400)")
        if status == 403:
            return LLMTransportError("the Ollama server refused the request (HTTP 403: Host/Origin check)")
        if status in (502, 503):
            return LLMUnavailable(f"the Ollama server is not ready (HTTP {status})")
        if status == 500 and ("memory" in low or "failed to load" in low or "unable to load" in low):
            return LLMModelUnavailable(f"model {self._model!r} cannot be run now (HTTP 500: memory or load failure)")
        return LLMTransportError(f"unexpected HTTP status {status}")

    # ── response normalization ────────────────────────────────────────────────────────────────

    def _normalize(self, data: Any) -> LLMResponse:
        try:
            r = _ChatReply.model_validate(data)
        except ValidationError:
            raise LLMInvalidResponse("the server answer does not have the expected shape") from None
        if r.done is not True:
            raise LLMIncompleteResponse("the server answer is not marked as done")
        calls = []
        for c in r.message.tool_calls or []:
            args = c.function.arguments
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    raise LLMInvalidResponse("a tool call has arguments that are not valid JSON") from None
                if not isinstance(args, dict):
                    raise LLMInvalidResponse("tool call arguments must be a JSON object")
            try:
                calls.append(ToolCall(id=c.id, name=c.function.name, arguments=args))
            except ValidationError:
                raise LLMInvalidResponse("a tool call has an invalid name") from None
        content = r.message.content or ""
        if not content.strip() and not calls and r.done_reason == "length":
            hidden = len(r.message.thinking or "")
            note = f" (the model spent the budget on {hidden} characters of hidden reasoning)" if hidden else ""
            raise LLMIncompleteResponse(f"the answer hit the token limit before producing any output{note}")
        return LLMResponse(
            content=content,
            tool_calls=tuple(calls),
            model=r.model or self._model,
            finish_reason=r.done_reason,
            usage=Usage(
                prompt_tokens=r.prompt_eval_count,
                cached_prompt_tokens=r.prompt_eval_cached_count,
                completion_tokens=r.eval_count,
            ),
            timings=Timings(
                total_s=_secs(r.total_duration),
                load_s=_secs(r.load_duration),
                prompt_eval_s=_secs(r.prompt_eval_duration),
                generation_s=_secs(r.eval_duration),
            ),
            thinking_chars=len(r.message.thinking or ""),
            metadata={"backend": self.backend, "num_ctx": self._s.context},
        )
