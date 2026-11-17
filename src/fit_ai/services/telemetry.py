"""Telemetry use cases. Depends only on the provider contract."""
from __future__ import annotations

from fit_ai.domain.telemetry import (
    NoDataAvailable,
    ProviderStatus,
    TelemetryProvider,
    VehicleTelemetry,
)


class TelemetryService:
    def __init__(self, provider: TelemetryProvider):
        self._provider = provider

    async def get_telemetry(self) -> VehicleTelemetry:
        """Raises a TelemetryError. Partial data is returned (with None fields);
        a reading with nothing at all is an error, not a success."""
        reading = await self._provider.read()
        if len(reading.missing) == 3:
            raise NoDataAvailable("the source is up but reported none of RPM, speed or coolant temperature")
        return reading

    async def get_status(self) -> ProviderStatus:
        return await self._provider.status()
