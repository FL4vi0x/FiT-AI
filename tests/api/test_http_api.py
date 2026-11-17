from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from fit_ai.domain.telemetry import (
    ProtocolIncompatible,
    ProviderError,
    ProviderStatus,
    ProviderTimeout,
    ProviderUnavailable,
    VehicleLinkDown,
    VehicleTelemetry,
)
from fit_ai.main import create_app

TZ = timezone(timedelta(hours=-3))
STAMP = datetime(2026, 11, 16, 19, 0, tzinfo=TZ)


class FakeProvider:
    """Injected in place of OCTAVE."""

    def __init__(self, reading=None, error=None, status=None):
        self.reading = reading or VehicleTelemetry(1500, 42.5, 88.0, "fake", True, STAMP)
        self.error = error
        self._status = status or ProviderStatus("connected", "fake", True, 3, "0.9.6", "ok")
        self.read_calls = 0

    async def read(self):
        self.read_calls += 1
        if self.error:
            raise self.error
        return self.reading

    async def status(self):
        return self._status


def client_for(provider) -> TestClient:
    return TestClient(create_app(provider=provider), base_url="http://127.0.0.1:8000")


def test_health_does_not_touch_the_provider():
    p = FakeProvider(error=ProviderUnavailable("down"))
    r = client_for(p).get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "fit-ai-core", "version": "0.1.0"}
    assert p.read_calls == 0


def test_telemetry_returns_injected_provider_data():
    r = client_for(FakeProvider()).get("/api/v1/vehicle/telemetry")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "rpm": 1500, "speed_kmh": 42.5, "coolant_temp_c": 88.0, "missing": [],
        "source": "fake", "simulated": True, "timestamp": "2026-11-16T19:00:00-03:00",
    }


def test_telemetry_partial_data_has_nulls_and_missing_list():
    reading = VehicleTelemetry(800, None, None, "fake", True, STAMP)
    body = client_for(FakeProvider(reading)).get("/api/v1/vehicle/telemetry").json()
    assert body["speed_kmh"] is None and body["coolant_temp_c"] is None
    assert body["missing"] == ["speed_kmh", "coolant_temp_c"]


def test_telemetry_with_no_data_at_all_is_503():
    reading = VehicleTelemetry(None, None, None, "fake", True, STAMP)
    r = client_for(FakeProvider(reading)).get("/api/v1/vehicle/telemetry")
    assert r.status_code == 503 and r.json()["error"]["code"] == "no_data"


@pytest.mark.parametrize(
    "error, status, code",
    [
        (ProviderUnavailable("OCTAVE is not reachable"), 503, "octave_unavailable"),
        (VehicleLinkDown("no vehicle link"), 503, "vehicle_link_down"),
        (ProviderTimeout("slow"), 504, "octave_timeout"),
        (ProtocolIncompatible("protocol 9"), 502, "octave_protocol_incompatible"),
        (ProviderError("bad"), 502, "octave_error"),
    ],
)
def test_telemetry_error_mapping(error, status, code):
    r = client_for(FakeProvider(error=error)).get("/api/v1/vehicle/telemetry")
    assert r.status_code == status
    assert r.json() == {"error": {"code": code, "message": str(error)}}


def test_status_connected():
    body = client_for(FakeProvider()).get("/api/v1/vehicle/status").json()
    assert body == {
        "available": True, "state": "connected", "source": "fake", "simulated": True,
        "protocol_version": 3, "octave_version": "0.9.6", "detail": "ok",
    }


def test_status_when_octave_is_down_is_200_and_says_so():
    status = ProviderStatus("octave_unavailable", "octave", detail="OCTAVE is not reachable")
    r = client_for(FakeProvider(status=status)).get("/api/v1/vehicle/status")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False and body["state"] == "octave_unavailable"
    assert body["protocol_version"] is None and body["simulated"] is None


def test_openapi_documents_the_endpoints():
    spec = client_for(FakeProvider()).get("/openapi.json").json()
    assert {"/health", "/api/v1/vehicle/telemetry", "/api/v1/vehicle/status"} <= set(spec["paths"])
    assert "503" in spec["paths"]["/api/v1/vehicle/telemetry"]["get"]["responses"]


def test_only_get_is_exposed():
    c = client_for(FakeProvider())
    for path in ("/health", "/api/v1/vehicle/telemetry", "/api/v1/vehicle/status"):
        for method in ("post", "put", "patch", "delete"):
            assert getattr(c, method)(path).status_code == 405
