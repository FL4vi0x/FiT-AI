"""Integration tests against a REAL running OCTAVE (`OCTAVE.exe --sim --service 9876`, GUI or --headless).

Skipped automatically when nothing listens on OCTAVE_HOST:OCTAVE_PORT. They only read.
"""
import socket

import pytest
from fastapi.testclient import TestClient

from fit_ai.adapters.octave import OctaveProvider, load_sdk
from fit_ai.config import Settings
from fit_ai.main import create_app

SETTINGS = Settings.from_env()


def _reachable() -> bool:
    try:
        with socket.create_connection((SETTINGS.octave_host, SETTINGS.octave_port), timeout=1):
            return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _reachable(), reason="OCTAVE is not running on the configured port"),
]


def make_provider():
    return OctaveProvider(
        SETTINGS.octave_host, SETTINGS.octave_port, SETTINGS.octave_timeout_s, SETTINGS.octave_sdk_path
    )


@pytest.fixture
def raw_sdk_client():
    sdk = load_sdk(SETTINGS.octave_sdk_path)
    with sdk.Client(SETTINGS.octave_host, SETTINGS.octave_port, timeout=5) as c:
        yield c


def _sim_state(c):
    s = c.call("sim", "status")
    return {k: s[k] for k in ("_throttle", "_brake", "_gear", "_engine_on", "link_down", "realistic")}


@pytest.mark.anyio
async def test_reads_the_three_parameters_from_the_real_service(raw_sdk_client):
    p = make_provider()
    before = raw_sdk_client.get("paramStore", "SPEED")
    t = await p.read()
    after = raw_sdk_client.get("paramStore", "SPEED")
    await p.aclose()
    assert t.source == "octave" and t.simulated is True
    assert t.timestamp.tzinfo is not None
    assert isinstance(t.rpm, int) and t.rpm > 0
    assert t.coolant_temp_c is not None and 0 < t.coolant_temp_c < 150
    # speed in km/h must match OCTAVE's mph (read before and after) times 1.609344
    lo, hi = sorted((before, after))
    assert (lo - 1) * 1.609344 <= t.speed_kmh <= (hi + 1) * 1.609344


@pytest.mark.anyio
async def test_status_against_the_real_service():
    p = make_provider()
    s = await p.status()
    await p.aclose()
    assert s.state == "connected" and s.available
    assert s.protocol_version == 3 and s.simulated is True and s.octave_version


@pytest.mark.anyio
async def test_core_does_not_change_the_simulator(raw_sdk_client):
    before = _sim_state(raw_sdk_client)
    p = make_provider()
    for _ in range(5):
        await p.read()
        await p.status()
    await p.aclose()
    assert _sim_state(raw_sdk_client) == before


def test_http_api_end_to_end_with_real_octave():
    with TestClient(create_app(settings=SETTINGS), base_url="http://127.0.0.1:8000") as c:
        t = c.get("/api/v1/vehicle/telemetry")
        s = c.get("/api/v1/vehicle/status")
    assert t.status_code == 200 and t.json()["simulated"] is True
    assert s.status_code == 200 and s.json()["state"] == "connected"
