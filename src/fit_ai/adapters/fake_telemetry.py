"""A controllable in-memory TelemetryProvider: for tests, benchmarks and the adversarial corpus.

It never touches OCTAVE, the network or the vehicle. Values, simulation flag, failures and latency are set
by the caller, and every call is counted so tests can assert that a tool really read (or did not read).
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

from fit_ai.domain.telemetry import ProviderStatus, TelemetryError, VehicleTelemetry


class FakeTelemetryProvider:
    def __init__(
        self,
        rpm: int | None = 800,
        speed_kmh: float | None = 0.0,
        coolant_temp_c: float | None = 90.0,
        *,
        simulated: bool | None = True,
        source: str = "fake",
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        delay_s: float = 0.0,
    ):
        self.rpm, self.speed_kmh, self.coolant_temp_c = rpm, speed_kmh, coolant_temp_c
        self.simulated, self.source, self.clock, self.delay_s = simulated, source, clock, delay_s
        self.error: TelemetryError | None = None  # raised by read() when set
        self.status_state = "connected"
        self.reads = 0
        self.status_calls = 0
        self.reading_timestamp: datetime | None = None  # None: stamp each read with `clock()`

    def fail_with(self, error: TelemetryError | None) -> "FakeTelemetryProvider":
        self.error = error
        return self

    async def read(self) -> VehicleTelemetry:
        self.reads += 1
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.error is not None:
            raise self.error
        return VehicleTelemetry(
            rpm=self.rpm, speed_kmh=self.speed_kmh, coolant_temp_c=self.coolant_temp_c, source=self.source,
            simulated=self.simulated, timestamp=self.reading_timestamp or self.clock())

    async def status(self) -> ProviderStatus:
        self.status_calls += 1
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        return ProviderStatus(state=self.status_state, source=self.source, simulated=self.simulated,
                              protocol_version=3, octave_version="fake")
