"""Integration tests against the REAL local Ollama (portable, 127.0.0.1) and the two approved models.

Skipped automatically (with the reason) when the server is down or a model is not installed.
They never download anything: asking Ollama for a model that is not installed just returns 404.
"""
import asyncio
import json
import re
import urllib.request

import pytest

from fit_ai.ai import (
    ChatMessage,
    LLMContextExceeded,
    LLMIncompleteResponse,
    LLMModelNotFound,
    LLMSettings,
    LLMTimeout,
    OllamaProvider,
    ToolCall,
    ToolDefinition,
    load_system_prompt,
)

SETTINGS = LLMSettings.from_env()
MODEL_A = "qwen3:4b-instruct-2507-q4_K_M"
MODEL_B = "qwen3:8b-q4_K_M"
DIGEST_A = "0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0"
DIGEST_B = "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41"


def _installed() -> dict[str, str] | None:
    try:
        with urllib.request.urlopen(SETTINGS.ollama_url + "/api/tags", timeout=2) as r:
            return {m["name"]: m["digest"] for m in json.loads(r.read())["models"]}
    except Exception:  # noqa: BLE001 - any failure just means "not available"
        return None


_MODELS = _installed()


def needs(model: str):
    if _MODELS is None:
        return pytest.mark.skip(reason=f"Ollama is not running at {SETTINGS.ollama_url}")
    if model not in _MODELS:
        return pytest.mark.skip(reason=f"model {model} is not installed")
    return pytest.mark.integration_llm


pytestmark = pytest.mark.anyio

SCHEMA = {"type": "object", "properties": {"funcao": {"type": "string"}, "idioma": {"type": "string"}},
          "required": ["funcao", "idioma"], "additionalProperties": False}
USER = [ChatMessage.user("Responda em português do Brasil, em uma frase curta: o que você faz?")]
TOOL = ToolDefinition(name="ler_rotacao_motor", description="Lê a rotação atual do motor em RPM. Somente leitura.")


def provider(model=MODEL_A, **over) -> OllamaProvider:
    return OllamaProvider(LLMSettings.from_env().with_model(model) if not over else
                          LLMSettings(**{**LLMSettings.from_env().__dict__, "model": model, **over}))


@needs(MODEL_A)
async def test_real_simple_question_returns_a_typed_response():
    p = provider()
    try:
        r = await p.generate([load_system_prompt().as_message(), *USER], max_tokens=80)
    finally:
        await p.aclose()
    assert r.model == MODEL_A and r.content.strip() and r.tool_calls == ()
    assert r.usage.prompt_tokens and r.usage.completion_tokens
    assert r.timings.total_s and r.timings.generation_s and r.generation_tokens_per_s > 0
    assert r.finish_reason in ("stop", "length") and r.thinking_chars == 0


@needs(MODEL_A)
async def test_real_structured_output_is_valid_json_with_the_requested_keys():
    p = provider()
    try:
        r = await p.generate([ChatMessage.user("Descreva você mesmo como assistente automotivo no JSON pedido. idioma deve ser 'pt-BR'.")],
                             response_format=SCHEMA, max_tokens=150)
    finally:
        await p.aclose()
    data = r.json_content()
    assert set(data) == {"funcao", "idioma"} and all(isinstance(v, str) for v in data.values())


@needs(MODEL_A)
async def test_real_structured_output_is_never_silently_empty():
    """Observed with the 4B model: with `format` it may spend the whole budget on hidden reasoning even
    with think=False (prompt-dependent). The provider must then fail loudly, never return an empty string."""
    p = provider()
    try:
        try:
            r = await p.generate([ChatMessage.user("Descreva você como assistente automotivo. idioma = 'pt-BR'.")],
                                 response_format=SCHEMA, max_tokens=100)
        except LLMIncompleteResponse as exc:
            assert "token limit" in str(exc)  # a typed, explained failure is the accepted outcome
        else:
            assert set(r.json_content()) == {"funcao", "idioma"}  # or a valid answer
    finally:
        await p.aclose()


@needs(MODEL_A)
async def test_real_tool_call_is_reported_not_executed():
    p = provider()
    try:
        r = await p.generate([ChatMessage.user("Qual é a rotação do motor agora?")], tools=[TOOL], max_tokens=100)
    finally:
        await p.aclose()
    assert [c.name for c in r.tool_calls] == ["ler_rotacao_motor"] and r.tool_calls[0].arguments == {}


@needs(MODEL_A)
async def test_real_tool_result_round_trip_is_accepted_by_the_server():
    """The history shape (assistant tool_calls + role=tool with tool_name) is accepted and used."""
    p = provider()
    msgs = [
        load_system_prompt().as_message(),
        ChatMessage.user("Qual é a rotação do motor agora?"),
        ChatMessage.assistant(tool_calls=(ToolCall(name="ler_rotacao_motor", arguments={}),)),
        ChatMessage.tool_result("ler_rotacao_motor", '{"rpm": 1234, "simulated": true}'),
    ]
    try:
        r = await p.generate(msgs, tools=[TOOL], max_tokens=100)
    finally:
        await p.aclose()
    # The model wrote "1.234" (pt-BR thousands separator): the value is right, the format differs.
    # P6's verifier must therefore compare numbers after locale-aware normalisation, never by substring.
    assert "1234" in re.sub(r"[.\s]", "", r.content)


@needs(MODEL_A)
async def test_real_health_reports_version_and_the_verified_digest():
    p = provider()
    try:
        h = await p.health()
    finally:
        await p.aclose()
    assert h.available and h.model_installed and h.model_digest == DIGEST_A and h.server_version == "0.40.16"


@needs(MODEL_B)
async def test_real_model_switch_to_8b_by_configuration_and_think_false():
    pa, pb = provider(MODEL_A), provider(MODEL_B)
    try:
        ra = await pa.generate(USER, max_tokens=24)
        rb = await pb.generate(USER, max_tokens=24)  # think=False comes from the default settings
        hb = await pb.health()
    finally:
        await pa.aclose()
        await pb.aclose()
    assert (ra.model, rb.model) == (MODEL_A, MODEL_B)
    assert rb.thinking_chars == 0 and rb.content.strip()
    assert hb.model_digest == DIGEST_B


@needs(MODEL_A)
async def test_real_timeout_is_typed_and_the_provider_recovers():
    p = provider()
    try:
        with pytest.raises(LLMTimeout):
            await p.generate([ChatMessage.user("Conte de 1 a 100 por extenso.")], timeout_s=1.0, max_tokens=200)
        r = await p.generate([ChatMessage.user("Diga apenas: ok")], max_tokens=8)
    finally:
        await p.aclose()
    assert r.content.strip()


@needs(MODEL_A)
async def test_real_cancellation_leaves_the_provider_usable():
    p = provider()
    try:
        task = asyncio.create_task(p.generate([ChatMessage.user("Conte de 1 a 100 por extenso.")], max_tokens=200))
        await asyncio.sleep(1.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        r = await p.generate([ChatMessage.user("Diga apenas: ok")], max_tokens=8)
    finally:
        await p.aclose()
    assert r.content.strip()


@needs(MODEL_A)
async def test_real_context_overflow_is_an_error_not_a_silent_truncation():
    p = provider(MODEL_A, context=512, max_tokens=32)
    long_text = "O carro tem rodas e um motor de combustão interna. " * 120
    try:
        with pytest.raises(LLMContextExceeded):
            await p.generate([ChatMessage.user(long_text + " Diga ok.")])
    finally:
        await p.aclose()


@needs(MODEL_A)
async def test_real_missing_model_is_not_found_and_is_never_downloaded():
    before = _installed()
    p = provider("qwen3:0.6b-q4_K_M")
    try:
        with pytest.raises(LLMModelNotFound):
            await p.generate(USER, max_tokens=8)
    finally:
        await p.aclose()
    assert _installed() == before  # nothing was pulled
