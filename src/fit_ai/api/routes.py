"""HTTP layer: routes, response models and error mapping."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from fit_ai import __version__
from fit_ai.domain.telemetry import TelemetryError
from fit_ai.services.telemetry import TelemetryService

# error code -> HTTP status
_STATUS_BY_CODE = {
    "octave_unavailable": 503,
    "vehicle_link_down": 503,
    "no_data": 503,
    "octave_timeout": 504,
    "octave_protocol_incompatible": 502,
    "octave_error": 502,
}


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class TelemetryResponse(BaseModel):
    rpm: int | None
    speed_kmh: float | None
    coolant_temp_c: float | None
    missing: list[str]
    source: str
    simulated: bool | None
    timestamp: datetime


class StatusResponse(BaseModel):
    available: bool
    state: str
    source: str
    simulated: bool | None
    protocol_version: int | None
    octave_version: str | None
    detail: str | None


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


router = APIRouter()


def _service(request: Request) -> TelemetryService:
    return request.app.state.telemetry_service


async def telemetry_error_handler(_: Request, exc: TelemetryError) -> JSONResponse:
    status = _STATUS_BY_CODE.get(exc.code, 502)
    return JSONResponse(status_code=status, content={"error": {"code": exc.code, "message": str(exc)}})


_ERRORS = {code: {"model": ErrorResponse} for code in sorted(set(_STATUS_BY_CODE.values()))}


@router.get("/health", response_model=HealthResponse, tags=["core"])
async def health() -> HealthResponse:
    """Liveness of the Fit AI Core itself. Does not contact OCTAVE."""
    return HealthResponse(status="ok", service="fit-ai-core", version=__version__)


@router.get("/api/v1/vehicle/telemetry", response_model=TelemetryResponse, responses=_ERRORS, tags=["vehicle"])
async def get_telemetry(request: Request) -> TelemetryResponse:
    """Latest RPM, speed (km/h) and coolant temperature. A field is null when the source
    cannot provide it; nothing is invented. 5xx with an `error` body when there is no usable reading."""
    reading = await _service(request).get_telemetry()
    return TelemetryResponse(
        rpm=reading.rpm,
        speed_kmh=reading.speed_kmh,
        coolant_temp_c=reading.coolant_temp_c,
        missing=reading.missing,
        source=reading.source,
        simulated=reading.simulated,
        timestamp=reading.timestamp,
    )


@router.get("/api/v1/vehicle/status", response_model=StatusResponse, tags=["vehicle"])
async def get_status(request: Request) -> StatusResponse:
    """State of the link to OCTAVE. Always 200: an unreachable OCTAVE is reported in `state`."""
    status = await _service(request).get_status()
    return StatusResponse(
        available=status.available,
        state=status.state,
        source=status.source,
        simulated=status.simulated,
        protocol_version=status.protocol_version,
        octave_version=status.octave_version,
        detail=status.detail,
    )
