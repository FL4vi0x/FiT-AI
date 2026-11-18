"""FakeLLMProvider behaviour, plus ONE contract suite that both providers must pass."""
import asyncio

import pytest
from ai_helpers import FakeOllama, chat_reply, make_provider, tool_reply

from fit_ai.ai import (
    ChatMessage,
    FakeLLMProvider,
    LLMIncompleteResponse,
    LLMInvalidRequest,
    LLMInvalidResponse,
    LLMProvider,
    LLMResponse,
    LLMTimeout,
    LLMTransportError,
    LLMUnavailable,
    ProviderHealth,
    Reply,
    RequestDefaults,
    ToolDefinition,
    prepare_request,
)

pytestmark = pytest.mark.anyio

USER = [ChatMessage.user("oi")]
TOOL = ToolDefinition(name="ler_rotacao_motor", description="Lê o RPM")


# ── the Fake on its own ──────────────────────────────────────────────────────────────────────

async def test_scripted_sequence_is_consumed_in_order():
    fake = FakeLLMProvider([Reply.text("um"), Reply.text("dois")])
    assert [(await fake.generate(USER)).content for _ in range(2)] == ["um", "dois"]
    assert fake.pending == 0


async def test_exhausted_script_fails_loudly_unless_a_default_is_set():
    with pytest.raises(AssertionError, match="exhausted"):
        await FakeLLMProvider().generate(USER)
    fake = FakeLLMProvider(default=Reply.text("sempre"))
    assert [(await fake.generate(USER)).content for _ in range(3)] == ["sempre"] * 3


async def test_script_can_be_extended_fluently():
    fake = FakeLLMProvider().script(Reply.text("a"), Reply.text("b"))
    assert (await fake.generate(USER)).content == "a"
    assert fake.pending == 1


async def test_calls_are_recorded_with_the_validated_request():
    fake = FakeLLMProvider([Reply.text("x")], defaults=RequestDefaults(timeout_s=33, max_tokens=77, think=False))
    await fake.generate([ChatMessage.system("s"), ChatMessage.user("u")], tools=[TOOL], max_tokens=10)
    call = fake.calls[0]
    assert [m.role for m in call.messages] == ["system", "user"]
    assert call.request.tools == (TOOL,) and call.request.max_tokens == 10
    assert call.request.timeout_s == 33 and call.request.think is False


async def test_text_json_tool_empty_and_echo_replies():
    fake = FakeLLMProvider([Reply.json({"a": 1}), Reply.tool_call("ler_rotacao_motor", {"k": 1}), Reply.empty(), Reply.echo("eco: ")])
    assert (await fake.generate(USER, response_format="json")).json_content() == {"a": 1}
    r = await fake.generate(USER, tools=[TOOL])
    assert r.tool_calls[0].name == "ler_rotacao_motor" and r.tool_calls[0].arguments == {"k": 1}
    assert (await fake.generate(USER)).content == ""
    assert (await fake.generate([ChatMessage.user("ping")])).content == "eco: ping"


@pytest.mark.parametrize("reply, exc", [
    (Reply.timeout(), LLMTimeout), (Reply.unavailable(), LLMUnavailable), (Reply.transport_error(), LLMTransportError),
    (Reply.malformed(), LLMInvalidResponse), (Reply.incomplete(), LLMIncompleteResponse),
])
async def test_scripted_failures(reply, exc):
    with pytest.raises(exc):
        await FakeLLMProvider([reply]).generate(USER)


async def test_scripted_delay_and_the_callers_timeout():
    fake = FakeLLMProvider([Reply.text("lento", delay_s=0.3), Reply.text("rápido", delay_s=0.0)])
    with pytest.raises(LLMTimeout):
        await fake.generate(USER, timeout_s=0.05)
    assert (await fake.generate(USER)).content == "rápido"
    assert len(fake.calls) == 2


async def test_delay_that_fits_the_timeout_succeeds():
    assert (await FakeLLMProvider([Reply.text("ok", delay_s=0.05)]).generate(USER, timeout_s=2)).content == "ok"


async def test_hang_is_ended_by_cancellation():
    fake = FakeLLMProvider([Reply.hang()])
    task = asyncio.create_task(fake.generate(USER, timeout_s=60))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_instances_are_isolated_from_each_other():
    a, b = FakeLLMProvider([Reply.text("a")]), FakeLLMProvider([Reply.text("b")])
    await a.generate(USER)
    assert len(a.calls) == 1 and b.calls == [] and b.pending == 1


# ── ONE contract, TWO providers ──────────────────────────────────────────────────────────────

def _fake(*replies):
    return FakeLLMProvider(list(replies))


def _ollama(*payloads):
    queue = list(payloads)
    p, _ = make_provider(FakeOllama(lambda r: queue.pop(0) if len(queue) > 1 else queue[0]))
    return p


PROVIDERS = {
    "fake": (lambda: _fake(Reply.text("Olá!")),
             lambda: _fake(Reply.tool_call("apagar_tudo")),
             lambda: _fake(Reply.text("não é json")),
             lambda: _fake(Reply.text("lento", delay_s=2))),
    "ollama": (lambda: _ollama(chat_reply("Olá!")),
               lambda: _ollama(tool_reply("apagar_tudo")),
               lambda: _ollama(chat_reply("não é json")),
               lambda: _slow_ollama()),
}


@pytest.fixture(params=sorted(PROVIDERS))
def kit(request):
    ok, undeclared_tool, not_json, slow = PROVIDERS[request.param]
    return ok, undeclared_tool, not_json, slow


def _slow_ollama():
    async def responder(request):
        await asyncio.sleep(2)
        return chat_reply("lento")

    p, _ = make_provider(FakeOllama(responder))
    return p


async def test_contract_satisfies_the_protocol_and_returns_a_typed_response(kit):
    p = kit[0]()
    assert isinstance(p, LLMProvider)
    assert isinstance(p.model, str) and p.model
    r = await p.generate(USER)
    assert isinstance(r, LLMResponse) and r.content == "Olá!" and r.tool_calls == ()
    await p.aclose()


async def test_contract_health_never_raises_and_is_typed(kit):
    p = kit[0]()
    h = await p.health()
    assert isinstance(h, ProviderHealth) and h.model == p.model
    await p.aclose()


@pytest.mark.parametrize("kwargs", [
    dict(messages=[]), dict(messages=[ChatMessage.assistant("sou eu")]),
    dict(messages=[ChatMessage.user("a"), ChatMessage.system("tarde demais"), ChatMessage.user("b")]),
    dict(messages=USER, timeout_s=0), dict(messages=USER, timeout_s=-1), dict(messages=USER, timeout_s=float("nan")),
    dict(messages=USER, max_tokens=0), dict(messages=USER, max_tokens=10**6), dict(messages=USER, max_tokens=True),
    dict(messages=USER, think="yes"),
    dict(messages=USER, tools=[TOOL, TOOL]),
    dict(messages=USER, response_format="xml"), dict(messages=USER, response_format={"type": "array"}),
    dict(messages=USER, tools=[TOOL], response_format="json"),
    dict(messages=["texto solto"]), dict(messages=USER, tools=[{"name": "x"}]),
])
async def test_contract_invalid_requests_are_refused_identically(kit, kwargs):
    p = kit[0]()
    with pytest.raises(LLMInvalidRequest):
        await p.generate(**kwargs)
    await p.aclose()


async def test_contract_undeclared_tools_are_rejected(kit):
    p = kit[1]()
    with pytest.raises(LLMInvalidResponse):
        await p.generate(USER, tools=[TOOL])
    await p.aclose()


async def test_contract_required_json_must_be_json(kit):
    p = kit[2]()
    with pytest.raises(LLMInvalidResponse):
        await p.generate(USER, response_format="json")
    await p.aclose()


async def test_contract_timeout_is_a_typed_error(kit):
    p = kit[3]()
    with pytest.raises(LLMTimeout):
        await p.generate(USER, timeout_s=0.1)
    await p.aclose()


async def test_contract_closed_provider_is_unavailable(kit):
    p = kit[0]()
    await p.aclose()
    with pytest.raises(LLMUnavailable):
        await p.generate(USER)


def test_prepare_request_applies_the_defaults():
    req = prepare_request(USER, defaults=RequestDefaults(timeout_s=12, max_tokens=34, think=True))
    assert (req.timeout_s, req.max_tokens, req.think) == (12.0, 34, True)
