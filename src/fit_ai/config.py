"""Settings from environment variables.

Everything is local-only during development: both the Core's own API and the
OCTAVE service must be loopback addresses, otherwise loading fails.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

# The SDK of the OCTAVE release we run (v0.9.6), extracted outside this repository with
#   git -C externals/octave archive --format=tar v0.9.6 sdk/python/octave_client sdk/python/LICENSE
# into FIT/runtime/octave-sdk-0.9.6 (see README). Override with OCTAVE_SDK_PATH.
# FiT-AI/src/fit_ai/config.py -> FIT/runtime/octave-sdk-0.9.6/sdk/python
_DEFAULT_SDK_PATH = Path(__file__).resolve().parents[3] / "runtime" / "octave-sdk-0.9.6" / "sdk" / "python"


class ConfigError(ValueError):
    """An environment variable holds a value the Core refuses to run with."""


@dataclass(frozen=True)
class Settings:
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    octave_host: str = "127.0.0.1"
    octave_port: int = 9876
    octave_timeout_s: float = 2.0
    octave_sdk_path: Path = _DEFAULT_SDK_PATH

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        e = os.environ if env is None else env
        settings = cls(
            api_host=e.get("FIT_AI_HOST", cls.api_host),
            api_port=_int(e, "FIT_AI_PORT", cls.api_port),
            octave_host=e.get("OCTAVE_HOST", cls.octave_host),
            octave_port=_int(e, "OCTAVE_PORT", cls.octave_port),
            octave_timeout_s=_float(e, "OCTAVE_TIMEOUT_S", cls.octave_timeout_s),
            octave_sdk_path=Path(e.get("OCTAVE_SDK_PATH", str(_DEFAULT_SDK_PATH))),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.api_host not in LOOPBACK_HOSTS:
            raise ConfigError(f"FIT_AI_HOST must be a loopback address, got {self.api_host!r}")
        if self.octave_host not in LOOPBACK_HOSTS:
            raise ConfigError(f"OCTAVE_HOST must be a loopback address, got {self.octave_host!r}")
        for name, port in (("FIT_AI_PORT", self.api_port), ("OCTAVE_PORT", self.octave_port)):
            if not 1 <= port <= 65535:
                raise ConfigError(f"{name} out of range: {port}")
        if not 0.1 <= self.octave_timeout_s <= 30:
            raise ConfigError(f"OCTAVE_TIMEOUT_S must be between 0.1 and 30, got {self.octave_timeout_s}")


def _int(env: dict[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from None


def _float(env: dict[str, str], key: str, default: float) -> float:
    raw = env.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from None
