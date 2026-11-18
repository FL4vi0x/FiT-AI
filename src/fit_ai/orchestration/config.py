"""Settings of the assistant layer (memory, audit, grounding). Separate from the Core's and the LLM's settings:
a bad value here can never stop the Core from starting, and nothing here is needed for the Core's endpoints."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from fit_ai.config import ConfigError

# FiT-AI/src/fit_ai/orchestration/config.py -> FIT/runtime/data (outside the Git repository on purpose)
_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[4] / "runtime" / "data"
AUDIT_POLICIES = ("fail_closed", "degrade_read_only")


@dataclass(frozen=True)
class AssistantSettings:
    data_dir: Path = _DEFAULT_DATA_DIR
    memory_db_name: str = "memory.db"
    audit_db_name: str = "audit.db"
    turn_retention_days: float = 30.0
    audit_retention_days: float = 90.0
    audit_policy: str = "fail_closed"
    telemetry_max_age_s: float = 10.0
    llm_timeout_s: float = 60.0
    llm_max_tokens: int = 200

    @property
    def memory_db(self) -> Path:
        return self.data_dir / self.memory_db_name

    @property
    def audit_db(self) -> Path:
        return self.data_dir / self.audit_db_name

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "AssistantSettings":
        e = os.environ if env is None else env
        s = cls(
            data_dir=Path(e.get("FIT_AI_DATA_DIR", str(cls.data_dir))),
            memory_db_name=e.get("FIT_AI_MEMORY_DB", cls.memory_db_name),
            audit_db_name=e.get("FIT_AI_AUDIT_DB", cls.audit_db_name),
            turn_retention_days=_num(e, "FIT_AI_TURN_RETENTION_DAYS", cls.turn_retention_days),
            audit_retention_days=_num(e, "FIT_AI_AUDIT_RETENTION_DAYS", cls.audit_retention_days),
            audit_policy=e.get("FIT_AI_AUDIT_POLICY", cls.audit_policy),
            telemetry_max_age_s=_num(e, "FIT_AI_TELEMETRY_MAX_AGE_S", cls.telemetry_max_age_s),
            llm_timeout_s=_num(e, "FIT_AI_ASSISTANT_LLM_TIMEOUT_S", cls.llm_timeout_s),
        )
        s.validate()
        return s

    def validate(self) -> None:
        for label, name in (("FIT_AI_MEMORY_DB", self.memory_db_name), ("FIT_AI_AUDIT_DB", self.audit_db_name)):
            # a bare file name inside data_dir: model output and user text can never reach these values anyway
            if (not name or Path(name).name != name or name in (".", "..") or not name.endswith(".db")
                    or any(c in name for c in '<>:"|?*\x00')):
                raise ConfigError(f"{label} must be a plain '*.db' file name (no directories), got {name!r}")
        if self.memory_db_name == self.audit_db_name:
            raise ConfigError("memory and audit must use different database files")
        if ".." in self.data_dir.parts:
            raise ConfigError("FIT_AI_DATA_DIR must not contain '..'")
        if self.audit_policy not in AUDIT_POLICIES:
            raise ConfigError(f"FIT_AI_AUDIT_POLICY must be one of {AUDIT_POLICIES}")
        if not 0.5 <= self.telemetry_max_age_s <= 120:
            raise ConfigError("FIT_AI_TELEMETRY_MAX_AGE_S must be within 0.5..120")
        if not 1 <= self.turn_retention_days <= 3650 or not 1 <= self.audit_retention_days <= 3650:
            raise ConfigError("retention must be within 1..3650 days")
        if not 1 <= self.llm_timeout_s <= 600:
            raise ConfigError("assistant LLM timeout must be within 1..600 s")


def _num(env: dict[str, str], key: str, default: float) -> float:
    raw = env.get(key)
    if raw is None:
        return default
    try:
        v = float(raw)
    except ValueError:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from None
    if v != v:
        raise ConfigError(f"{key} must be finite")
    return v
