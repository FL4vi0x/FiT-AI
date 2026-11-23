"""P8.3: the OPTIONAL start-up warm-up and the OPTIONAL keep-alive. Both are off unless explicitly enabled."""
import asyncio

import httpx
import pytest

from fit_ai.adapters.fake_telemetry import FakeTelemetryProvider
from fit_ai.ai import FakeLLMProvider, LLMSettings, LLMUnavailable, OllamaProvider, Reply
from fit_ai.config import ConfigError
from fit_ai.conversation.config import ChatSettings
from fit_ai.conversation.factory import build_chat_runtime
from fit_ai.conversation.warmup import BUSY_CPU_FRACTION, WARMUP_QUESTION, start_background_warmup, warm_up
from fit_ai.orchestration import AssistantSettings
from fit_ai.orchestration.prompt import system_message
from fit_ai.services.telemetry import TelemetryService

pytestmark = pytest.mark.anyio


def fake(*script):
    return FakeLLMProvider(list(script))


# ───────────── the guards: nothing is sent unless RAM and CPU allow it ─────────────
async def test_it_is_skipped_without_calling_the_model_when_free_ram_is_low():
    llm = fake()  # an empty script: ANY call fails the test
    r = await warm_up(llm, min_free_ram_mb=6000, free_ram=lambda: 5999, cpu_busy=lambda: 0.1)
    assert r.outcome == "skipped_low_ram" and r.free_ram_mb == 5999 and llm.calls == []


async def test_unknown_ram_means_do_not_warm_up():
    llm = fake()
    assert (await warm_up(llm, min_free_ram_mb=6000, free_ram=lambda: None, cpu_busy=lambda: 0.1)).outcome == "skipped_ram_unknown"
    assert llm.calls == []


async def test_a_busy_machine_is_left_alone():
    llm = fake()
    r = await warm_up(llm, min_free_ram_mb=6000, free_ram=lambda: 20000, cpu_busy=lambda: BUSY_CPU_FRACTION + 0.01)
    assert r.outcome == "skipped_busy_cpu" and llm.calls == []


async def test_unknown_cpu_load_means_do_not_warm_up():
    llm = fake()
    r = await warm_up(llm, min_free_ram_mb=6000, free_ram=lambda: 20000, cpu_busy=lambda: None)
    assert r.outcome == "skipped_cpu_unknown" and llm.calls == []


# ───────────── what it sends ─────────────
async def test_it_sends_the_real_system_prompt_and_a_constant_question_and_nothing_else():
    llm = fake(Reply.text("."))
    r = await warm_up(llm, min_free_ram_mb=6000, free_ram=lambda: 20000, cpu_busy=lambda: 0.1)
    assert r.outcome == "done" and r.seconds >= 0 and len(llm.calls) == 1
    req = llm.calls[0].request
    assert req.messages[0] == system_message()  # the same bytes as every real turn: that is what lets the server reuse the prefix
    assert [m.content for m in req.messages[1:]] == [WARMUP_QUESTION]
    assert req.max_tokens == 1 and req.tools == () and req.response_format is None and req.think is False


async def test_a_model_failure_never_raises():
    for error in (LLMUnavailable("down"),):
        llm = fake(Reply.fail(error))
        r = await warm_up(llm, min_free_ram_mb=6000, free_ram=lambda: 20000, cpu_busy=lambda: 0.1)
        assert r.outcome == "failed"


async def test_an_unexpected_error_never_raises_either():
    class Boom:
        model = "x"

        async def generate(self, *a, **k):
            raise RuntimeError("secret")
    r = await warm_up(Boom(), min_free_ram_mb=6000, free_ram=lambda: 20000, cpu_busy=lambda: 0.1)  # type: ignore[arg-type]
    assert r.outcome == "failed"


# ───────────── it never delays the Core's start, and it is opt-in ─────────────
async def test_background_start_returns_at_once_while_the_warm_up_is_still_running():
    release = asyncio.Event()

    class Runtime:
        async def warmup(self):
            await release.wait()
            return "done"
    task = start_background_warmup(Runtime())
    assert task is not None and not task.done()  # the caller got control back before it finished
    release.set()
    assert await task == "done"


async def test_nothing_is_scheduled_when_it_is_not_enabled():
    class Off:
        warmup = None
    assert start_background_warmup(Off()) is None
    assert start_background_warmup(None) is None


def runtime_for(tmp_path, llm_settings):
    return build_chat_runtime(TelemetryService(FakeTelemetryProvider()), ChatSettings(),
                              assistant_settings=AssistantSettings(data_dir=tmp_path), llm_settings=llm_settings)


async def test_the_production_wiring_is_off_by_default(tmp_path):
    runtime = runtime_for(tmp_path, LLMSettings())
    try:
        assert LLMSettings().warmup is False and LLMSettings().keep_alive is None
        assert runtime is not None and runtime.warmup is None
    finally:
        await runtime.close()


async def test_the_production_wiring_offers_it_only_when_enabled(tmp_path):
    runtime = runtime_for(tmp_path, LLMSettings(warmup=True))
    try:
        assert runtime is not None and runtime.warmup is not None  # offered, but nothing ran: the model was not contacted
    finally:
        await runtime.close()


# ───────────── configuration ─────────────
def test_environment_switches():
    s = LLMSettings.from_env({"FIT_AI_LLM_WARMUP": "1", "FIT_AI_LLM_KEEP_ALIVE": "30m", "FIT_AI_LLM_WARMUP_MIN_FREE_RAM_MB": "8000"})
    assert s.warmup is True and s.keep_alive == "30m" and s.warmup_min_free_ram_mb == 8000
    assert LLMSettings.from_env({}).warmup is False


@pytest.mark.parametrize("value", ["30s", "10m", "2h", "24h", "1440m"])
def test_valid_keep_alive(value):
    LLMSettings(keep_alive=value).validate()


@pytest.mark.parametrize("value", ["-1", "0", "0s", "29s", "5", "10", "2d", "25h", "9999h", "forever", "1.5h", "m", "10 m", "10M"])
def test_invalid_keep_alive_is_refused(value):
    with pytest.raises(ConfigError):
        LLMSettings(keep_alive=value).validate()


@pytest.mark.parametrize("mb", [0, 1023, 131073, -5])
def test_the_ram_threshold_is_bounded(mb):
    with pytest.raises(ConfigError):
        LLMSettings(warmup_min_free_ram_mb=mb).validate()


def test_a_bad_warmup_flag_is_refused():
    with pytest.raises(ConfigError):
        LLMSettings.from_env({"FIT_AI_LLM_WARMUP": "maybe"})


# ───────────── keep-alive reaches the server only when asked for ─────────────
def chat_body(settings):
    bodies = []

    def handler(request: httpx.Request):
        import json
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"model": settings.model, "message": {"role": "assistant", "content": "ok"}, "done": True,
                                         "done_reason": "stop"})
    provider = OllamaProvider(settings, client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:11434"))
    return provider, bodies


async def test_keep_alive_is_sent_only_when_configured():
    from fit_ai.ai import ChatMessage
    for configured, expected in ((None, None), ("30m", "30m")):
        provider, bodies = chat_body(LLMSettings(keep_alive=configured))
        await provider.generate([ChatMessage.user("oi")])
        assert bodies[0].get("keep_alive") == expected
        if configured is None:
            assert "keep_alive" not in bodies[0]
