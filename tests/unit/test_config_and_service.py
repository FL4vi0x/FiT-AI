from datetime import datetime, timezone

import pytest

from fit_ai.config import ConfigError, Settings
from fit_ai.domain.telemetry import NoDataAvailable, ProviderStatus, VehicleTelemetry
from fit_ai.services.telemetry import TelemetryService

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)


class StubProvider:
    def __init__(self, rpm=None, speed=None, coolant=None):
        self.t = VehicleTelemetry(rpm, speed, coolant, "stub", True, NOW)

    async def read(self):
        return self.t

    async def status(self):
        return ProviderStatus(state="connected", source="stub")


async def test_service_returns_partial_data():
    t = await TelemetryService(StubProvider(rpm=800)).get_telemetry()
    assert t.rpm == 800 and t.missing == ["speed_kmh", "coolant_temp_c"]


async def test_service_rejects_a_reading_with_nothing_in_it():
    with pytest.raises(NoDataAvailable):
        await TelemetryService(StubProvider()).get_telemetry()


async def test_service_status_passthrough():
    assert (await TelemetryService(StubProvider()).get_status()).state == "connected"


def test_defaults_are_loopback():
    s = Settings.from_env({})
    assert (s.api_host, s.octave_host, s.octave_port) == ("127.0.0.1", "127.0.0.1", 9876)


@pytest.mark.parametrize("env", [{"FIT_AI_HOST": "0.0.0.0"}, {"FIT_AI_HOST": "192.168.1.5"}, {"OCTAVE_HOST": "10.0.0.2"}])
def test_non_loopback_hosts_are_refused(env):
    with pytest.raises(ConfigError):
        Settings.from_env(env)


@pytest.mark.parametrize(
    "env",
    [{"FIT_AI_PORT": "abc"}, {"OCTAVE_PORT": "70000"}, {"OCTAVE_TIMEOUT_S": "0"}, {"OCTAVE_TIMEOUT_S": "x"}],
)
def test_bad_numbers_are_refused(env):
    with pytest.raises(ConfigError):
        Settings.from_env(env)


def test_run_exits_cleanly_on_bad_config(monkeypatch):
    from fit_ai.main import run

    monkeypatch.setenv("FIT_AI_HOST", "0.0.0.0")
    with pytest.raises(SystemExit) as exc:
        run()
    assert "loopback" in str(exc.value)


def test_missing_sdk_is_a_clear_provider_error(monkeypatch, tmp_path):
    from fit_ai.adapters import octave
    from fit_ai.domain.telemetry import ProviderError

    monkeypatch.setattr(octave, "_sdk_module", None)  # bypass the load cache; restored after the test
    with pytest.raises(ProviderError, match="SDK not found"):
        octave.load_sdk(tmp_path)
