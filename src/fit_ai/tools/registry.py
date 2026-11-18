"""Typed tool registry: registration policy + safe execution. Nothing here knows OCTAVE, Ollama or HTTP."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from collections.abc import Callable, Collection, Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from fit_ai.ai.models import ToolDefinition
from fit_ai.domain.telemetry import TelemetryError
from fit_ai.memory.contracts import MemoryError_
from fit_ai.tools.contracts import (
    EXECUTABLE_PERMISSIONS,
    Tool,
    ToolOutcome,
    ToolRegistrationError,
)

log = logging.getLogger("fit_ai.tools")
_NAME = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_MAX_ARGS_JSON = 4000


class ToolRegistry:
    def __init__(self, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._tools: dict[str, Tool] = {}
        self._clock = clock

    # ── registration ──
    def register(self, tool: Tool) -> None:
        spec = tool.spec
        if not _NAME.match(spec.name):
            raise ToolRegistrationError(f"invalid tool name {spec.name!r}")
        if spec.name in self._tools:
            raise ToolRegistrationError(f"tool {spec.name!r} is already registered")
        if spec.permission not in EXECUTABLE_PERMISSIONS:
            raise ToolRegistrationError(
                f"tool {spec.name!r} requires {spec.permission}: only READ tools may be registered in P6")
        if spec.side_effects:
            raise ToolRegistrationError(f"READ tool {spec.name!r} declares side effects: {spec.side_effects}")
        if not 0 < spec.timeout_s <= 30:
            raise ToolRegistrationError("timeout_s must be within (0, 30]")
        self._tools[spec.name] = tool

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def spec(self, name: str):
        return self._tools[name].spec

    def definitions(self, names: Collection[str] | None = None) -> list[ToolDefinition]:
        """What the LLM is told about (only the requested subset: fewer tools = a shorter, cacheable prompt)."""
        out = []
        for n in sorted(self._tools if names is None else (x for x in names if x in self._tools)):
            s = self._tools[n].spec
            schema = s.input_model.model_json_schema()
            schema.pop("title", None)
            out.append(ToolDefinition(name=s.name, description=s.description, parameters=schema))
        return out

    # ── execution ──
    async def execute(self, name: Any, arguments: Mapping[str, Any] | str | None = None, *,
                      allowed: Collection[str] | None = None, run_id: str | None = None) -> ToolOutcome:
        """Never raises for tool/model problems: returns a ToolOutcome (`ok=False`, `decision`, `error_code`)."""
        run_id = run_id or uuid.uuid4().hex
        started = self._clock()
        shown = name if isinstance(name, str) and len(name) <= 64 and name.isprintable() else "<invalid>"

        def refused(code: str, msg: str, permission: str | None = None) -> ToolOutcome:
            return ToolOutcome(run_id=run_id, requested_name=shown, decision="denied", permission=permission,
                               ok=False, error_code=code, error_message=msg, started_at=started)

        if not isinstance(name, str) or name not in self._tools:
            return refused("unknown_tool", "no such tool")  # also: any name the model invents
        tool = self._tools[name]
        perm = tool.spec.permission
        if allowed is not None and name not in allowed:
            return refused("tool_not_offered", "tool not available for this request", perm.value)
        if perm not in EXECUTABLE_PERMISSIONS or tool.spec.side_effects:  # defence in depth (registration checks too)
            return refused("permission_denied", "tool permission is not executable", perm.value)

        try:
            args = self._parse_args(arguments)
            parsed = tool.spec.input_model.model_validate(args)
        except ValidationError as exc:
            fields = sorted({".".join(map(str, e["loc"])) or "<root>" for e in exc.errors()})
            return refused("invalid_arguments", f"invalid arguments: {', '.join(fields)}", perm.value)
        except ValueError as exc:
            return refused("invalid_arguments", str(exc), perm.value)

        t0 = time.perf_counter()

        def outcome(ok: bool, **kw: Any) -> ToolOutcome:
            return ToolOutcome(run_id=run_id, requested_name=name, decision="allowed", permission=perm.value, ok=ok,
                               started_at=started, duration_s=round(time.perf_counter() - t0, 4), **kw)

        try:
            async with asyncio.timeout(tool.spec.timeout_s):
                result = await tool.run(parsed)
            data = result.model_dump(mode="json")
            return outcome(True, data=data, simulated=data.get("simulated"))
        except TimeoutError:
            return outcome(False, error_code="tool_timeout", error_message=f"no result within {tool.spec.timeout_s:g} s")
        except TelemetryError as exc:  # stable machine-readable code from the telemetry domain
            return outcome(False, error_code=exc.code, error_message=str(exc)[:200])
        except MemoryError_ as exc:
            return outcome(False, error_code="memory_error", error_message=type(exc).__name__)
        except Exception:  # noqa: BLE001 - tool boundary: logged with traceback, reported without internals
            log.exception("tool %s failed unexpectedly", name)
            return outcome(False, error_code="tool_error", error_message="the tool failed")

    @staticmethod
    def _parse_args(arguments: Mapping[str, Any] | str | None) -> dict[str, Any]:
        if arguments is None or arguments == "":
            return {}
        if isinstance(arguments, str):
            if len(arguments) > _MAX_ARGS_JSON:
                raise ValueError("arguments too large")
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                raise ValueError("arguments are not valid JSON") from None
        if not isinstance(arguments, Mapping):
            raise ValueError("arguments must be a JSON object")
        return dict(arguments)
