import dataclasses

import pytest
from pydantic import ValidationError

from fit_ai.ai import ChatMessage, LLMResponse, LLMSettings, Timings, ToolCall, ToolDefinition, Usage
from fit_ai.ai.config import validate_loopback_url, validate_model_name
from fit_ai.config import ConfigError, Settings


# ── configuration ────────────────────────────────────────────────────────────────────────────

def test_defaults_are_the_approved_ones():
    s = LLMSettings.from_env({})
    assert (s.model, s.ollama_url, s.timeout_s, s.context, s.max_tokens, s.temperature, s.seed, s.think) == (
        "qwen3:4b-instruct-2507-q4_K_M", "http://127.0.0.1:11434", 120.0, 4096, 256, 0.2, 42, False)


def test_env_overrides_every_field():
    s = LLMSettings.from_env({
        "FIT_AI_MODEL": "qwen3:8b-q4_K_M", "FIT_AI_OLLAMA_URL": "http://localhost:11434",
        "FIT_AI_LLM_TIMEOUT_S": "30", "FIT_AI_LLM_CONTEXT": "8192", "FIT_AI_LLM_MAX_TOKENS": "128",
        "FIT_AI_LLM_TEMPERATURE": "0", "FIT_AI_LLM_SEED": "7", "FIT_AI_LLM_THINK": "TRUE"})
    assert (s.model, s.timeout_s, s.context, s.max_tokens, s.temperature, s.seed, s.think) == (
        "qwen3:8b-q4_K_M", 30.0, 8192, 128, 0.0, 7, True)


def test_switching_models_is_a_configuration_change():
    s = LLMSettings().with_model("qwen3:8b-q4_K_M")
    assert s.model == "qwen3:8b-q4_K_M" and s.context == 4096
    with pytest.raises(ConfigError):
        LLMSettings().with_model("qwen3:latest")


@pytest.mark.parametrize("model", ["", "qwen3", "qwen3:", ":tag", "qwen3:latest", "qwen3:LATEST", "a b:c", "x:y z", "../../x:1"])
def test_models_need_an_explicit_safe_tag(model):
    with pytest.raises(ConfigError):
        validate_model_name(model)


@pytest.mark.parametrize("model", ["qwen3:8b-q4_K_M", "qwen3:4b-instruct-2507-q4_K_M", "library/qwen3:8b"])
def test_good_model_names(model):
    assert validate_model_name(model) == model


@pytest.mark.parametrize("url, expected", [
    ("http://127.0.0.1:11434", "http://127.0.0.1:11434"),
    ("http://127.0.0.1:11434/", "http://127.0.0.1:11434"),
    ("http://localhost:11434", "http://localhost:11434"),
    ("http://LOCALHOST:11434", "http://localhost:11434"),
    ("http://[::1]:11434", "http://[::1]:11434"),
])
def test_loopback_urls_are_accepted(url, expected):
    assert validate_loopback_url(url) == expected


@pytest.mark.parametrize("url", [
    "http://0.0.0.0:11434", "http://192.168.1.10:11434", "http://example.com:11434", "http://127.0.0.2:11434",
    "https://127.0.0.1:11434", "ftp://127.0.0.1:11434", "127.0.0.1:11434", "http://127.0.0.1",
    "http://127.0.0.1:11434@evil.example", "http://user:pw@127.0.0.1:11434", "http://127.0.0.1@evil.example:11434",
    "http://127.0.0.1.evil.example:11434", "http://127.0.0.1:11434/api", "http://127.0.0.1:11434/?x=1",
    "http://127.0.0.1:11434#x", "http://127.0.0.1:99999", "http://127.0.0.1:abc", "", "http://",
])
def test_non_loopback_or_odd_urls_are_rejected(url):
    with pytest.raises(ConfigError):
        validate_loopback_url(url)


@pytest.mark.parametrize("env", [
    {"FIT_AI_LLM_TIMEOUT_S": "0"}, {"FIT_AI_LLM_TIMEOUT_S": "9999"}, {"FIT_AI_LLM_TIMEOUT_S": "x"}, {"FIT_AI_LLM_TIMEOUT_S": "nan"},
    {"FIT_AI_LLM_CONTEXT": "100"}, {"FIT_AI_LLM_CONTEXT": "999999"}, {"FIT_AI_LLM_CONTEXT": "4k"},
    {"FIT_AI_LLM_MAX_TOKENS": "0"}, {"FIT_AI_LLM_MAX_TOKENS": "99999"},
    {"FIT_AI_LLM_MAX_TOKENS": "600", "FIT_AI_LLM_CONTEXT": "512"},  # answer must be smaller than the window
    {"FIT_AI_LLM_TEMPERATURE": "3"}, {"FIT_AI_LLM_TEMPERATURE": "-0.1"}, {"FIT_AI_LLM_SEED": "-1"}, {"FIT_AI_LLM_SEED": "99999999999"},
    {"FIT_AI_LLM_THINK": "maybe"}, {"FIT_AI_OLLAMA_URL": "http://10.0.0.5:11434"}, {"FIT_AI_MODEL": "qwen3"},
])
def test_invalid_settings_are_refused(env):
    with pytest.raises(ConfigError):
        LLMSettings.from_env(env)


def test_bad_llm_env_never_breaks_the_core_settings():
    """The Core must start even if an LLM variable is wrong or Ollama is off."""
    bad = {"FIT_AI_LLM_CONTEXT": "oops", "FIT_AI_OLLAMA_URL": "http://evil.example:1"}
    assert Settings.from_env(bad).api_host == "127.0.0.1"
    with pytest.raises(ConfigError):
        LLMSettings.from_env(bad)


# ── messages and tools ───────────────────────────────────────────────────────────────────────

def test_message_helpers_and_immutability():
    m = ChatMessage.user("oi")
    assert (m.role, m.content) == ("user", "oi")
    with pytest.raises(ValidationError):
        m.content = "outro"  # frozen


@pytest.mark.parametrize("kwargs", [
    dict(role="user", content=""), dict(role="user", content="   "), dict(role="system", content=""),
    dict(role="assistant", content=""), dict(role="tool", content="x"),  # tool without tool_name
    dict(role="user", content="x", tool_name="t"), dict(role="user", content="x", tool_call_id="1"),
    dict(role="user", content="x", tool_calls=(ToolCall(name="t"),)), dict(role="other", content="x"),
    dict(role="user", content="x" * 32_001), dict(role="user", content="x", extra_field=1),
])
def test_invalid_messages_are_rejected(kwargs):
    with pytest.raises(ValidationError):
        ChatMessage(**kwargs)


def test_assistant_message_may_carry_only_tool_calls_and_tool_results_name_their_tool():
    a = ChatMessage.assistant(tool_calls=(ToolCall(id="1", name="ler_rotacao_motor", arguments={}),))
    assert a.tool_calls[0].name == "ler_rotacao_motor"
    t = ChatMessage.tool_result("ler_rotacao_motor", '{"rpm": 800}', tool_call_id="1")
    assert (t.role, t.tool_name) == ("tool", "ler_rotacao_motor")


@pytest.mark.parametrize("name", ["", "1abc", "a b", "a;rm", "x" * 65, "ação"])
def test_tool_names_are_restricted(name):
    with pytest.raises(ValidationError):
        ToolDefinition(name=name, description="d")
    with pytest.raises(ValidationError):
        ToolCall(name=name)


def test_tool_definition_rules():
    ok = ToolDefinition(name="ler_rotacao_motor", description="Lê o RPM")
    assert ok.parameters == {"type": "object", "properties": {}}
    with pytest.raises(ValidationError):
        ToolDefinition(name="t", description="d", parameters={"type": "string"})
    with pytest.raises(ValidationError):
        ToolDefinition(name="t", description="")


# ── response ─────────────────────────────────────────────────────────────────────────────────

def test_response_rates_and_missing_values():
    r = LLMResponse(content="x", model="m", usage=Usage(prompt_tokens=40, completion_tokens=20),
                    timings=Timings(total_s=3, prompt_eval_s=2, generation_s=4))
    assert r.generation_tokens_per_s == 5.0 and r.prompt_tokens_per_s == 20.0
    empty = LLMResponse(content="", model="m")
    assert empty.generation_tokens_per_s is None and empty.prompt_tokens_per_s is None
    zero = LLMResponse(content="", model="m", usage=Usage(completion_tokens=5), timings=Timings(generation_s=0))
    assert zero.generation_tokens_per_s is None  # never divide by zero


def test_json_content():
    assert LLMResponse(content='{"a": 1}', model="m").json_content() == {"a": 1}
    with pytest.raises(ValueError):
        LLMResponse(content="not json", model="m").json_content()


def test_settings_are_a_frozen_dataclass():
    with pytest.raises(dataclasses.FrozenInstanceError):
        LLMSettings().model = "x:y"
