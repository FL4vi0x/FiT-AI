"""READ tools over the Core's existing services. They call the in-process services directly (never the Core's
own HTTP API) and invent nothing: a field the source could not provide stays None and is listed in `missing`."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from fit_ai.memory.contracts import MemoryStore
from fit_ai.services.telemetry import TelemetryService
from fit_ai.tools.contracts import Permission, ToolInput, ToolOutput, ToolSpec
from fit_ai.tools.registry import ToolRegistry


class NoArguments(ToolInput):
    pass


class TelemetryOutput(ToolOutput):
    state: Literal["ok", "partial"]  # partial: at least one field is missing (and listed in `missing`)
    rpm: int | None
    speed_kmh: float | None
    coolant_temp_c: float | None
    missing: list[str]
    source: str
    simulated: bool | None  # None: the provider could not tell
    timestamp: datetime


class StatusOutput(ToolOutput):
    available: bool
    state: str
    source: str
    simulated: bool | None
    protocol_version: int | None
    octave_version: str | None
    detail: str | None


class MemoryFactsInput(ToolInput):
    query: str = Field(default="", max_length=200)
    limit: int = Field(default=5, ge=1, le=10)


class FactItem(ToolOutput):
    id: str
    content: str
    created_at: datetime
    age_days: float


class MemoryFactsOutput(ToolOutput):
    # Stored information, NOT a measurement: the grounding layer never accepts it as sensor evidence.
    authority: Literal["user_statement"] = "user_statement"
    is_measurement: Literal[False] = False
    facts: list[FactItem]


class GetVehicleTelemetry:
    spec = ToolSpec(
        name="get_vehicle_telemetry",
        description="Lê RPM, velocidade (km/h) e temperatura do líquido de arrefecimento (°C). Somente leitura.",
        input_model=NoArguments, output_model=TelemetryOutput, permission=Permission.READ,
        timeout_s=5.0, dependencies=("TelemetryService",))

    def __init__(self, service: TelemetryService):
        self._service = service

    async def run(self, args: NoArguments) -> TelemetryOutput:
        r = await self._service.get_telemetry()  # TelemetryError subclasses propagate to the registry
        return TelemetryOutput(state="ok" if not r.missing else "partial", rpm=r.rpm, speed_kmh=r.speed_kmh,
                               coolant_temp_c=r.coolant_temp_c, missing=r.missing, source=r.source,
                               simulated=r.simulated, timestamp=r.timestamp)


class GetVehicleStatus:
    spec = ToolSpec(
        name="get_vehicle_status",
        description="Estado da conexão com a fonte de dados do veículo (disponibilidade, simulação, versões).",
        input_model=NoArguments, output_model=StatusOutput, permission=Permission.READ,
        timeout_s=5.0, dependencies=("TelemetryService",))

    def __init__(self, service: TelemetryService):
        self._service = service

    async def run(self, args: NoArguments) -> StatusOutput:
        s = await self._service.get_status()
        return StatusOutput(available=s.available, state=s.state, source=s.source, simulated=s.simulated,
                            protocol_version=s.protocol_version, octave_version=s.octave_version,
                            detail=(s.detail or None) and s.detail[:200])


class GetMemoryFacts:
    spec = ToolSpec(
        name="get_memory_facts",
        description="Recupera fatos que o usuário pediu para lembrar. Informação guardada, não é medição.",
        input_model=MemoryFactsInput, output_model=MemoryFactsOutput, permission=Permission.READ,
        timeout_s=3.0, dependencies=("MemoryStore",))

    def __init__(self, store: MemoryStore, clock=lambda: datetime.now(UTC)):
        self._store, self._clock = store, clock

    async def run(self, args: MemoryFactsInput) -> MemoryFactsOutput:
        if args.query.strip():
            hits = await asyncio.to_thread(self._store.search, args.query, kinds=("fact",), limit=args.limit)
            rows = [(h.id, h.content, h.created_at) for h in hits]
        else:
            facts = await asyncio.to_thread(self._store.list_facts, args.limit)
            rows = [(f.id, f.content, f.created_at) for f in facts]
        now = self._clock()
        return MemoryFactsOutput(facts=[
            FactItem(id=i, content=c, created_at=t, age_days=round(max(0.0, (now - t).total_seconds()) / 86400, 3))
            for i, c, t in rows])


def build_vehicle_registry(service: TelemetryService, memory: MemoryStore | None = None) -> ToolRegistry:
    """The P6 tool set. `get_memory_facts` is only registered when a memory store is supplied."""
    reg = ToolRegistry()
    reg.register(GetVehicleTelemetry(service))
    reg.register(GetVehicleStatus(service))
    if memory is not None:
        reg.register(GetMemoryFacts(memory))
    return reg
