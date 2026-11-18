"""Tool contracts. Only READ tools exist in P6: everything else is rejected by code, not by prompt."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict


class Permission(StrEnum):
    READ = "READ"
    ACTION_LOW = "ACTION_LOW"
    ACTION_CONFIRM = "ACTION_CONFIRM"
    FORBIDDEN = "FORBIDDEN"


# P6 policy: the registry accepts and executes ONLY these.
EXECUTABLE_PERMISSIONS = frozenset({Permission.READ})


class ToolInput(BaseModel):
    """Base of every tool argument model: unknown fields are an error, never ignored."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolOutput(BaseModel):
    model_config = ConfigDict(frozen=True)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[ToolInput]
    output_model: type[ToolOutput]
    permission: Permission
    side_effects: tuple[str, ...] = ()  # must be empty for READ tools
    timeout_s: float = 3.0
    dependencies: tuple[str, ...] = ()


class Tool(Protocol):
    spec: ToolSpec

    async def run(self, args: Any) -> ToolOutput: ...


class ToolOutcome(BaseModel):
    """The audited result of one execution attempt (also for refused ones). Never raises to the caller."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    requested_name: str
    decision: Literal["allowed", "denied"]
    permission: str | None = None
    ok: bool
    data: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime
    duration_s: float = 0.0
    simulated: bool | None = None


class ToolRegistrationError(Exception):
    """A tool that must not exist in this phase (wrong permission, side effects, bad name...)."""
