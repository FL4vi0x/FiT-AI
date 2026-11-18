"""AI Engine settings from environment variables.

Kept apart from `fit_ai.config.Settings` on purpose: a typo in an LLM variable must never stop the
Core (telemetry API) from starting. These settings are validated only when the AI Engine is built.
Having Ollama switched off is NOT a configuration error.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from urllib.parse import urlsplit

from fit_ai.config import LOOPBACK_HOSTS, ConfigError

DEFAULT_MODEL = "qwen3:4b-instruct-2507-q4_K_M"
DEFAULT_URL = "http://127.0.0.1:11434"

# repository/name:tag, the tag is mandatory and may not be the moving alias "latest"
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/]{0,100}:[A-Za-z0-9][A-Za-z0-9._\-]{0,100}$")

TIMEOUT_RANGE_S = (1.0, 600.0)
CONTEXT_RANGE = (512, 16384)  # 16K keeps KV-cache RAM moderate on a 31 GB laptop; raise deliberately
MAX_TOKENS_LIMIT = 4096


def validate_model_name(model: str) -> str:
    if not isinstance(model, str) or not _MODEL.match(model):
        raise ConfigError(f"model must be an explicit 'name:tag' identifier, got {model!r}")
    if model.rsplit(":", 1)[1].lower() == "latest":
        raise ConfigError("model tag 'latest' is not accepted: pin an explicit tag")
    return model


def validate_loopback_url(url: str) -> str:
    """Return the normalized base URL ('http://host:port') or raise ConfigError. Only plain-HTTP
    loopback addresses with an explicit port and no credentials, path, query or fragment."""
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError as exc:
        raise ConfigError(f"invalid Ollama URL: {exc}") from None
    if parts.scheme != "http":
        raise ConfigError("Ollama URL must use plain http on loopback")
    if "@" in parts.netloc or parts.username or parts.password:
        raise ConfigError("Ollama URL must not contain credentials")
    if host is None or host.lower() not in LOOPBACK_HOSTS:
        raise ConfigError("Ollama URL host must be a loopback address (127.0.0.1, localhost, ::1)")
    if port is None or not 1 <= port <= 65535:
        raise ConfigError("Ollama URL needs an explicit valid port")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ConfigError("Ollama URL must be just scheme://host:port")
    shown = f"[{host}]" if ":" in host else host.lower()
    return f"http://{shown}:{port}"


@dataclass(frozen=True)
class LLMSettings:
    model: str = DEFAULT_MODEL
    ollama_url: str = DEFAULT_URL
    timeout_s: float = 120.0
    context: int = 4096
    max_tokens: int = 256
    temperature: float = 0.2
    seed: int = 42
    think: bool = False

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "LLMSettings":
        e = os.environ if env is None else env
        settings = cls(
            model=e.get("FIT_AI_MODEL", cls.model),
            ollama_url=e.get("FIT_AI_OLLAMA_URL", cls.ollama_url),
            timeout_s=_num(e, "FIT_AI_LLM_TIMEOUT_S", cls.timeout_s, float),
            context=_num(e, "FIT_AI_LLM_CONTEXT", cls.context, int),
            max_tokens=_num(e, "FIT_AI_LLM_MAX_TOKENS", cls.max_tokens, int),
            temperature=_num(e, "FIT_AI_LLM_TEMPERATURE", cls.temperature, float),
            seed=_num(e, "FIT_AI_LLM_SEED", cls.seed, int),
            think=_bool(e, "FIT_AI_LLM_THINK", cls.think),
        )
        settings.validate()
        return settings

    def with_model(self, model: str) -> "LLMSettings":
        """The same settings for another model (switching models is a configuration change)."""
        new = replace(self, model=model)
        new.validate()
        return new

    def validate(self) -> None:
        validate_model_name(self.model)
        validate_loopback_url(self.ollama_url)
        if not TIMEOUT_RANGE_S[0] <= self.timeout_s <= TIMEOUT_RANGE_S[1]:
            raise ConfigError(f"FIT_AI_LLM_TIMEOUT_S must be within {TIMEOUT_RANGE_S}, got {self.timeout_s}")
        if not CONTEXT_RANGE[0] <= self.context <= CONTEXT_RANGE[1]:
            raise ConfigError(f"FIT_AI_LLM_CONTEXT must be within {CONTEXT_RANGE}, got {self.context}")
        if not 1 <= self.max_tokens <= MAX_TOKENS_LIMIT:
            raise ConfigError(f"FIT_AI_LLM_MAX_TOKENS must be within 1..{MAX_TOKENS_LIMIT}, got {self.max_tokens}")
        if self.max_tokens >= self.context:
            raise ConfigError("FIT_AI_LLM_MAX_TOKENS must be smaller than FIT_AI_LLM_CONTEXT")
        if not 0.0 <= self.temperature <= 2.0:
            raise ConfigError(f"FIT_AI_LLM_TEMPERATURE must be within 0..2, got {self.temperature}")
        if not 0 <= self.seed <= 2**31 - 1:
            raise ConfigError("FIT_AI_LLM_SEED must be within 0..2147483647")


def _num(env: dict[str, str], key: str, default, cast):
    raw = env.get(key)
    if raw is None:
        return default
    try:
        value = cast(raw)
    except ValueError:
        raise ConfigError(f"{key} must be {'an integer' if cast is int else 'a number'}, got {raw!r}") from None
    if cast is float and value != value:  # NaN
        raise ConfigError(f"{key} must be a finite number")
    return value


def _bool(env: dict[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    v = raw.strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{key} must be true or false, got {raw!r}")
