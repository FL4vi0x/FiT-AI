import asyncio
import logging

import httpx
import pytest
from ai_helpers import SETTINGS, FakeOllama, chat_reply, error_response, make_provider, tool_reply

from fit_ai.ai import (
    ChatMessage,
    LLMConfigurationError,
    LLMContextExceeded,
    LLMIncompleteResponse,
    LLMInvalidRequest,
    LLMInvalidResponse,
    LLMModelNotFound,
    LLMModelUnavailable,
    LLMSettings,
    LLMTimeout,
    LLMTransportError,
    LLMUnavailable,
    OllamaProvider,
    ToolCall,
    ToolDefinition,
)

pytestmark = pytest.mark.anyio

USER = [ChatMessage.user("Qual é a sua função?")]
TOOL = ToolDefinition(name="ler_rotacao_motor", description="Lê o RPM atual (somente leitura).")


async def generate(provider, messages=USER, **kw):
    try:
        return await provider.generate(messages, **kw)
    finally:
        await provider.aclose()


# ── request serialization ────────────────────────────────────────────────────────────────────

async def test_request_body_uses_explicit_settings_and_think_false_by_default():
    p, server = make_provider()
    await generate(p)
    body = server.last_body
    assert server.requests[0].url.path == "/api/chat" and server.requests[0].method == "POST"
    assert body["model"] == "qwen3:4b-instruct-2507-q4_K_M"
    assert body["stream"] is False and body["think"] is False
    assert body["options"] == {"num_ctx": 4096, "temperature": 0.2, "seed": 42, "num_predict": 256}
    assert body["messages"] == [{"role": "user", "content": "Qual é a sua função?"}]
    assert "tools" not in body and "format" not in body


async def test_per_call_overrides_and_think_true():
    p, server = make_provider()
    await generate(p, max_tokens=64, think=True, timeout_s=30)
    assert server.last_body["think"] is True and server.last_body["options"]["num_predict"] == 64


async def test_model_switch_by_configuration_changes_only_the_model():
    p, server = make_provider(settings=LLMSettings().with_model("qwen3:8b-q4_K_M"))
    assert p.model == "qwen3:8b-q4_K_M"
    await generate(p)
    assert server.last_body["model"] == "qwen3:8b-q4_K_M"


async def test_tools_and_tool_history_are_serialized_without_leaking_provider_types():
    p, server = make_provider()
    msgs = [
        ChatMessage.system("sys"),
        ChatMessage.user("rpm?"),
        ChatMessage.assistant(tool_calls=(ToolCall(id="1", name="ler_rotacao_motor", arguments={}),)),
        ChatMessage.tool_result("ler_rotacao_motor", '{"rpm": 800, "simulated": true}', tool_call_id="1"),
    ]
    await generate(p, msgs, tools=[TOOL])
    b = server.last_body
    assert b["tools"] == [{"type": "function", "function": {
        "name": "ler_rotacao_motor", "description": "Lê o RPM atual (somente leitura).",
        "parameters": {"type": "object", "properties": {}}}}]
    assert b["messages"][2] == {"role": "assistant", "content": "",
                                "tool_calls": [{"function": {"name": "ler_rotacao_motor", "arguments": {}}}]}
    assert b["messages"][3] == {"role": "tool", "content": '{"rpm": 800, "simulated": true}', "tool_name": "ler_rotacao_motor"}


async def test_structured_output_sends_the_schema_as_format():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
    p, server = make_provider(FakeOllama(chat_reply('{"a": "x"}')))
    r = await generate(p, response_format=schema)
    assert server.last_body["format"] == schema and r.json_content() == {"a": "x"}


# ── response normalization ───────────────────────────────────────────────────────────────────

async def test_normalizes_text_usage_and_timings():
    p, _ = make_provider(FakeOllama(chat_reply("Oi!")))
    r = await generate(p)
    assert (r.content, r.model, r.finish_reason, r.tool_calls) == ("Oi!", SETTINGS.model, "stop", ())
    assert (r.usage.prompt_tokens, r.usage.completion_tokens, r.usage.cached_prompt_tokens) == (40, 20, 0)
    assert (r.timings.total_s, r.timings.load_s, r.timings.prompt_eval_s, r.timings.generation_s) == (2.0, 0.1, 0.4, 1.0)
    assert r.generation_tokens_per_s == 20.0 and r.prompt_tokens_per_s == 100.0
    assert r.metadata["backend"] == "ollama" and r.metadata["num_ctx"] == 4096


async def test_missing_optional_metrics_become_none_not_errors():
    reply = {"model": SETTINGS.model, "message": {"role": "assistant", "content": "x"}, "done": True}
    p, _ = make_provider(FakeOllama(reply))
    r = await generate(p)
    assert r.usage.prompt_tokens is None and r.timings.total_s is None and r.finish_reason is None
    assert r.generation_tokens_per_s is None


async def test_empty_but_complete_answer_is_returned_as_is():
    p, _ = make_provider(FakeOllama(chat_reply("")))
    r = await generate(p)
    assert r.content == "" and r.tool_calls == ()


async def test_tool_call_is_extracted_and_never_executed():
    p, server = make_provider(FakeOllama(tool_reply("ler_rotacao_motor", {"x": 1}, call_id="abc")))
    r = await generate(p, tools=[TOOL])
    assert r.tool_calls == (ToolCall(id="abc", name="ler_rotacao_motor", arguments={"x": 1}),)
    assert len(server.requests) == 1  # exactly one request: nothing was executed or followed up


async def test_tool_call_arguments_given_as_json_text_are_parsed():
    p, _ = make_provider(FakeOllama(tool_reply(arguments='{"a": 2}')))
    r = await generate(p, tools=[TOOL])
    assert r.tool_calls[0].arguments == {"a": 2}


@pytest.mark.parametrize("args", ["not json", "[1, 2]"])
async def test_bad_tool_call_arguments_are_invalid_responses(args):
    p, _ = make_provider(FakeOllama(tool_reply(arguments=args)))
    with pytest.raises(LLMInvalidResponse):
        await generate(p, tools=[TOOL])


async def test_tool_call_without_id_is_accepted():
    p, _ = make_provider(FakeOllama(tool_reply(call_id=None)))
    assert (await generate(p, tools=[TOOL])).tool_calls[0].id is None


async def test_undeclared_tool_is_rejected():
    p, _ = make_provider(FakeOllama(tool_reply("apagar_tudo")))
    with pytest.raises(LLMInvalidResponse):
        await generate(p, tools=[TOOL])


async def test_tool_call_when_no_tools_were_declared_is_rejected():
    p, _ = make_provider(FakeOllama(tool_reply()))
    with pytest.raises(LLMInvalidResponse):
        await generate(p)


async def test_json_was_required_but_answer_is_not_json():
    p, _ = make_provider(FakeOllama(chat_reply("não sou json")))
    with pytest.raises(LLMInvalidResponse):
        await generate(p, response_format={"type": "object", "properties": {}})


async def test_thinking_is_measured_but_never_kept():
    msg = {"role": "assistant", "content": "51", "thinking": "raciocínio-secreto-xyz"}
    p, _ = make_provider(FakeOllama(chat_reply("51", message=msg)))
    r = await generate(p)
    assert r.thinking_chars == len("raciocínio-secreto-xyz")
    assert "secreto" not in repr(r) and "secreto" not in r.model_dump_json()


async def test_length_finish_with_content_is_returned_for_the_caller_to_judge():
    p, _ = make_provider(FakeOllama(chat_reply("meio da fra", done_reason="length")))
    r = await generate(p)
    assert r.finish_reason == "length" and r.content == "meio da fra"


async def test_length_finish_with_nothing_produced_is_incomplete():
    p, _ = make_provider(FakeOllama(chat_reply("", done_reason="length")))
    with pytest.raises(LLMIncompleteResponse):
        await generate(p)


@pytest.mark.parametrize("reply", [
    chat_reply(done=False), {"model": "m", "message": {"role": "assistant", "content": "x"}},  # no done
])
async def test_not_done_is_incomplete(reply):
    p, _ = make_provider(FakeOllama(reply))
    with pytest.raises(LLMIncompleteResponse):
        await generate(p)


@pytest.mark.parametrize("reply", [{}, {"done": True}, {"message": "oops", "done": True}, [], "text", {"message": {"tool_calls": [{"function": {}}]}, "done": True}])
async def test_malformed_shapes_are_invalid_responses(reply):
    p, _ = make_provider(FakeOllama(reply))
    with pytest.raises(LLMInvalidResponse):
        await generate(p)


async def test_non_json_body_is_an_invalid_response():
    p, _ = make_provider(FakeOllama(httpx.Response(200, text="<html>nope</html>")))
    with pytest.raises(LLMInvalidResponse):
        await generate(p)


# ── typed errors ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("response, exc", [
    (error_response(404, "model 'qwen3:x' not found"), LLMModelNotFound),
    (error_response(400, "request (1694 tokens) exceeds the available context size (512 tokens), try increasing it"), LLMContextExceeded),
    (error_response(400, "json: cannot unmarshal string"), LLMInvalidRequest),
    (error_response(403, ""), LLMTransportError),
    (error_response(500, "model requires more system memory (9.0 GiB) than is available (4.0 GiB)"), LLMModelUnavailable),
    (error_response(500, "something exploded"), LLMTransportError),
    (error_response(503, "busy"), LLMUnavailable),
    (httpx.Response(404, text="page not found"), LLMTransportError),
    (httpx.Response(302, headers={"location": "http://evil.example/"}), LLMTransportError),
])
async def test_http_errors_map_to_typed_errors(response, exc):
    p, _ = make_provider(FakeOllama(response))
    with pytest.raises(exc):
        await generate(p)


async def test_context_exceeded_reports_the_counts_but_no_content():
    p, _ = make_provider(FakeOllama(error_response(400, "request (1694 tokens) exceeds the available context size (512 tokens), try increasing it")))
    with pytest.raises(LLMContextExceeded) as e:
        await generate(p, [ChatMessage.user("SEGREDO-PROMPT")])
    assert "1694" in str(e.value) and "512" in str(e.value) and "SEGREDO" not in str(e.value)


@pytest.mark.parametrize("raised, exc", [
    (httpx.ConnectError("refused"), LLMUnavailable),
    (httpx.ConnectTimeout("slow"), LLMTimeout),
    (httpx.ReadTimeout("slow"), LLMTimeout),
    (httpx.PoolTimeout("busy"), LLMTimeout),
    (httpx.RemoteProtocolError("bad"), LLMTransportError),
    (httpx.ReadError("reset"), LLMTransportError),
])
async def test_network_failures_map_to_typed_errors(raised, exc):
    def boom(request):
        raise raised

    p, _ = make_provider(FakeOllama(boom))
    with pytest.raises(exc):
        await generate(p)


async def test_a_real_closed_port_means_unavailable():
    """No mock: nothing listens on this loopback port."""
    p = OllamaProvider(LLMSettings(ollama_url="http://127.0.0.1:9", timeout_s=5.0))
    with pytest.raises(LLMUnavailable):
        await generate(p)


async def test_unknown_exceptions_are_not_silenced():
    class Weird(Exception):
        pass

    def boom(request):
        raise Weird("unexpected")

    p, _ = make_provider(FakeOllama(boom))
    with pytest.raises(Weird):
        await generate(p)


# ── time, cancellation, concurrency, lifecycle ───────────────────────────────────────────────

async def test_overall_deadline_applies_even_if_the_server_hangs():
    async def slow(request):
        await asyncio.sleep(5)

    p, _ = make_provider(FakeOllama(slow))
    t = asyncio.get_running_loop().time()
    with pytest.raises(LLMTimeout):
        await generate(p, timeout_s=0.2)
    assert asyncio.get_running_loop().time() - t < 2


async def test_cancellation_propagates_and_the_provider_stays_usable():
    gate = {"slow": True}

    async def responder(request):
        if gate["slow"]:
            await asyncio.sleep(30)
        return chat_reply("depois")

    p, _ = make_provider(FakeOllama(responder))
    task = asyncio.create_task(p.generate(USER))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    gate["slow"] = False
    assert (await p.generate(USER)).content == "depois"  # the gate was released, the client still works
    await p.aclose()


async def test_requests_are_serialized_one_at_a_time():
    state = {"active": 0, "max": 0}

    async def responder(request):
        state["active"] += 1
        state["max"] = max(state["max"], state["active"])
        await asyncio.sleep(0.05)
        state["active"] -= 1
        return chat_reply("ok")

    p, _ = make_provider(FakeOllama(responder))
    results = await asyncio.gather(*(p.generate(USER) for _ in range(4)))
    assert len(results) == 4 and state["max"] == 1
    await p.aclose()


async def test_queue_wait_counts_against_the_callers_timeout():
    async def slow(request):
        await asyncio.sleep(0.5)
        return chat_reply("ok")

    p, _ = make_provider(FakeOllama(slow))
    first = asyncio.create_task(p.generate(USER))
    await asyncio.sleep(0.05)
    with pytest.raises(LLMTimeout):
        await p.generate(USER, timeout_s=0.1)  # waits behind the first call, then runs out of time
    await first
    await p.aclose()


async def test_aclose_closes_an_owned_client_and_is_idempotent():
    p = OllamaProvider(SETTINGS)
    client = p._client
    await p.aclose()
    await p.aclose()
    assert client.is_closed
    with pytest.raises(LLMUnavailable):
        await p.generate(USER)


async def test_an_injected_client_is_not_closed_by_the_provider():
    client = httpx.AsyncClient(transport=httpx.MockTransport(FakeOllama()))
    p = OllamaProvider(SETTINGS, client=client)
    await p.aclose()
    assert not client.is_closed
    await client.aclose()


async def test_async_context_manager_closes():
    async with OllamaProvider(SETTINGS) as p:
        client = p._client
    assert client.is_closed


# ── safety ───────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", ["http://10.0.0.5:11434", "http://example.com:11434", "https://127.0.0.1:11434",
                                 "http://127.0.0.1:11434@evil.example", "http://127.0.0.1:11434/x"])
def test_the_provider_itself_refuses_non_loopback_urls(url):
    with pytest.raises(LLMConfigurationError):
        OllamaProvider(LLMSettings(ollama_url=url))


def test_the_provider_refuses_untagged_models_and_bad_settings():
    for s in (LLMSettings(model="qwen3"), LLMSettings(model="qwen3:latest"), LLMSettings(context=10)):
        with pytest.raises(LLMConfigurationError):
            OllamaProvider(s)


def test_the_http_client_ignores_proxies_and_redirects(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:3128")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:3128")
    p = OllamaProvider(SETTINGS)
    assert p._client.trust_env is False and p._client.follow_redirects is False


async def test_prompts_and_answers_are_not_logged(caplog):
    caplog.set_level(logging.DEBUG)
    p, _ = make_provider(FakeOllama(chat_reply("RESPOSTA-SECRETA-777")))
    await generate(p, [ChatMessage.user("PROMPT-SECRETO-555")])
    assert "model=" in caplog.text  # something was logged...
    assert "SECRETO" not in caplog.text and "RESPOSTA" not in caplog.text and "PROMPT" not in caplog.text


# ── health ───────────────────────────────────────────────────────────────────────────────────

async def test_health_reports_version_installed_model_and_digest():
    def responder(request):
        if request.url.path == "/api/version":
            return {"version": "0.40.16"}
        return {"models": [{"name": SETTINGS.model, "digest": "0edcdef3"}, {"name": "outro:1", "digest": "x"}]}

    p, _ = make_provider(FakeOllama(responder))
    h = await p.health()
    await p.aclose()
    assert (h.available, h.backend, h.model_installed, h.model_digest, h.server_version, h.detail) == (
        True, "ollama", True, "0edcdef3", "0.40.16", None)


async def test_health_when_the_model_is_not_installed():
    def responder(request):
        return {"version": "0.40.16"} if request.url.path == "/api/version" else {"models": []}

    p, _ = make_provider(FakeOllama(responder))
    h = await p.health()
    await p.aclose()
    assert h.available and h.model_installed is False and h.detail == "llm_model_not_found"


async def test_health_never_raises_when_the_server_is_down():
    p = OllamaProvider(LLMSettings(ollama_url="http://127.0.0.1:9"))
    h = await p.health()
    await p.aclose()
    assert (h.available, h.detail) == (False, "llm_unavailable")


async def test_health_with_garbage_is_unavailable_not_a_crash():
    p, _ = make_provider(FakeOllama(lambda r: {"version": "1"} if r.url.path == "/api/version" else {"models": "x"}))
    h = await p.health()
    await p.aclose()
    assert h.available is False and h.detail == "llm_invalid_response"


async def test_empty_answer_at_the_limit_mentions_hidden_reasoning_when_there_was_some():
    """Seen with the real 4B model: with `format` it can burn the whole budget on `thinking` even if think=False."""
    msg = {"role": "assistant", "content": "", "thinking": "x" * 1896}
    p, _ = make_provider(FakeOllama(chat_reply("", message=msg, done_reason="length")))
    with pytest.raises(LLMIncompleteResponse, match="1896 characters of hidden reasoning") as e:
        await generate(p, response_format="json")
    assert "xxxx" not in str(e.value)
