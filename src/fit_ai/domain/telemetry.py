"""Telemetry domain: the data model, the provider contract and its errors.

Nothing here knows about OCTAVE, HTTP or FastAPI.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

MPH_TO_KMH = 1.609344


def mph_to_kmh(mph: float) -> float:
    return mph * MPH_TO_KMH


@dataclass(frozen=True)
class VehicleTelemetry:
    """One reading. A field is None when the source could not provide it:
    values are never invented or carried over from an earlier reading."""

    rpm: int | None
    speed_kmh: float | None
    coolant_temp_c: float | None
    source: str
    simulated: bool | None  # None: the provider could not tell
    timestamp: datetime  # timezone-aware

    @property
    def missing(self) -> list[str]:
        names = {"rpm": self.rpm, "speed_kmh": self.speed_kmh, "coolant_temp_c": self.coolant_temp_c}
        return [name for name, value in names.items() if value is None]


@dataclass(frozen=True)
class ProviderStatus:
    """state: connected | vehicle_link_down | octave_unavailable | octave_timeout |
    octave_protocol_incompatible | octave_error"""

    state: str
    source: str
    simulated: bool | None = None
    protocol_version: int | None = None
    octave_version: str | None = None
    detail: str | None = None

    @property
    def available(self) -> bool:
        """The provider answered (even if the vehicle link behind it is down)."""
        return self.state in ("connected", "vehicle_link_down")


class TelemetryError(Exception):
    """Base error. `code` is stable and machine readable."""

    code = "telemetry_error"


class ProviderUnavailable(TelemetryError):
    code = "octave_unavailable"


class VehicleLinkDown(ProviderUnavailable):
    """The provider is up but its connection to the vehicle (real or simulated) is not,
    so its last values would be stale."""

    code = "vehicle_link_down"


class ProviderTimeout(TelemetryError):
    code = "octave_timeout"


class ProtocolIncompatible(TelemetryError):
    code = "octave_protocol_incompatible"


class ProviderError(TelemetryError):
    code = "octave_error"


class NoDataAvailable(TelemetryError):
    code = "no_data"


class TelemetryProvider(Protocol):
    """A source of telemetry. Read-only by contract."""

    async def read(self) -> VehicleTelemetry:
        """Raise a TelemetryError subclass on failure."""
        ...

    async def status(self) -> ProviderStatus:
        """Never raises for provider failures: they are reported in the status."""
        ...
