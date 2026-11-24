"""Speech-to-text settings from environment variables.

Kept apart from the Core's, the chat's and the LLM's: a typo here disables speech recognition (the route answers 503) but never
stops the Core. Nothing here can point the engine at a remote model: the model is a LOCAL directory chosen by the installer, never
by a request. There is no download logic anywhere in the Core.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from fit_ai.config import ConfigError
from fit_ai.speech.audio import max_body_bytes

# FiT-AI/src/fit_ai/speech/config.py -> FIT/runtime/stt-models/faster-whisper-small (outside the repository, never committed)
_DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[4] / "runtime" / "stt-models" / "faster-whisper-small"

SUPPORTED_LANGUAGES = frozenset({"pt"})
THREADS_RANGE = (1, 16)
BEAM_RANGE = (1, 10)
TIMEOUT_RANGE_S = (5.0, 120.0)
MAX_AUDIO_RANGE_S = (1.0, 30.0)  # Whisper works on 30 s windows: longer audio would be split and slower
MIN_PEAK_RANGE = (0.0, 0.5)
PROMPT_MAX_CHARS = 200

# A vocabulary hint, not a transcript: Whisper reproduces rarely-seen names ("Honda Fit") far more reliably when they appear in the
# initial prompt. Measured on synthetic speech only (docs/poc-09-01-local-stt.md); set FIT_AI_STT_INITIAL_PROMPT= (empty) to turn it off.
DEFAULT_INITIAL_PROMPT = "Fit AI, Honda Fit, RPM, arrefecimento, velocidade, temperatura do motor."


@dataclass(frozen=True)
class SpeechSettings:
    enabled: bool = True
    model_dir: Path = _DEFAULT_MODEL_DIR
    language: str = "pt"
    # Measured on the 10-core laptop: 8 threads is ~10 % faster than 4 on AC power but ~35 % faster when the machine is power-limited
    # (battery, balanced plan: 3.5 s against 5.3 s for the same sentence). A transcription is a short burst, so the worst case wins.
    threads: int = 8
    beam_size: int = 5
    timeout_s: float = 30.0
    max_audio_s: float = 30.0
    min_peak: float = 0.004  # below this (about -48 dBFS) nothing was really captured: answered without running the engine
    initial_prompt: str = DEFAULT_INITIAL_PROMPT

    @property
    def max_body_bytes(self) -> int:
        return max_body_bytes(self.max_audio_s)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "SpeechSettings":
        e = os.environ if env is None else env
        s = cls(
            enabled=_bool(e, "FIT_AI_STT_ENABLED", cls.enabled),
            model_dir=_model_dir(e.get("FIT_AI_STT_MODEL_DIR")),
            language=e.get("FIT_AI_STT_LANGUAGE", cls.language).strip().lower(),
            threads=_num(e, "FIT_AI_STT_THREADS", cls.threads, int),
            beam_size=_num(e, "FIT_AI_STT_BEAM_SIZE", cls.beam_size, int),
            timeout_s=_num(e, "FIT_AI_STT_TIMEOUT_S", cls.timeout_s, float),
            max_audio_s=_num(e, "FIT_AI_STT_MAX_AUDIO_S", cls.max_audio_s, float),
            min_peak=_num(e, "FIT_AI_STT_MIN_PEAK", cls.min_peak, float),
            initial_prompt=e.get("FIT_AI_STT_INITIAL_PROMPT", cls.initial_prompt).strip(),
        )
        s.validate()
        return s

    def validate(self) -> None:
        if self.language not in SUPPORTED_LANGUAGES:
            raise ConfigError(f"FIT_AI_STT_LANGUAGE must be one of {sorted(SUPPORTED_LANGUAGES)}")
        for name, value, (lo, hi) in (("FIT_AI_STT_THREADS", self.threads, THREADS_RANGE), ("FIT_AI_STT_BEAM_SIZE", self.beam_size, BEAM_RANGE),
                                      ("FIT_AI_STT_TIMEOUT_S", self.timeout_s, TIMEOUT_RANGE_S), ("FIT_AI_STT_MAX_AUDIO_S", self.max_audio_s, MAX_AUDIO_RANGE_S),
                                      ("FIT_AI_STT_MIN_PEAK", self.min_peak, MIN_PEAK_RANGE)):
            if not lo <= value <= hi:
                raise ConfigError(f"{name} must be between {lo} and {hi}")
        if len(self.initial_prompt) > PROMPT_MAX_CHARS or any(ord(c) < 32 for c in self.initial_prompt):
            raise ConfigError(f"FIT_AI_STT_INITIAL_PROMPT must be plain text of at most {PROMPT_MAX_CHARS} characters")
        _check_local_directory(str(self.model_dir))


def _check_local_directory(raw: str) -> None:
    """A model location is a path on THIS machine. A colon is only legitimate as a drive letter (`C:\\`): any other colon is a URL
    scheme (`https:`), a hub reference (`hf:name`) or a name:tag, and a leading double slash is a network share. (On Windows
    `Path("https://host/x")` is silently rewritten to `https:\\host\\x`, which is why the colon rule, not "://", is what holds.)"""
    rest = raw[2:] if re.match(r"^[A-Za-z]:[\\/]", raw) else raw
    if ":" in rest or raw.startswith(("\\\\", "//")):
        raise ConfigError("FIT_AI_STT_MODEL_DIR must be a local directory (no URLs, no network shares, no model hub names)")


def _model_dir(raw: str | None) -> Path:
    if not raw:
        return SpeechSettings.model_dir
    _check_local_directory(raw)  # on the text as written, before Path() can turn a URL into something path-like
    return Path(raw)


def _num(env: dict[str, str], key: str, default, cast):
    raw = env.get(key)
    if raw is None:
        return default
    try:
        value = cast(raw)
    except ValueError:
        raise ConfigError(f"{key} must be {'an integer' if cast is int else 'a number'}, got {raw!r}") from None
    if cast is float and value != value:
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
