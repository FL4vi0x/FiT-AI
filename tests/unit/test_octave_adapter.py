import time
from datetime import datetime, timezone

import pytest

from fit_ai.adapters.octave import OctaveProvider, _ReadOnlyClient
from fit_ai.domain.telemetry import (
    ProtocolIncompatible,
    ProviderError,
    ProviderTimeout,
    ProviderUnavailable,
    VehicleLinkDown,
)

from fakes import FakeClient

pytestmark = pytest.mark.anyio

FIXED = datetime(2026, 11, 16, 19, 0, tzinfo=timezone.utc)


def provider_for(client_or_factory, **kw):
    factory = client_or_factory if callable(client_or_factory) else (lambda: client_or_factory)
    kw.setdefault("demand_settle_s", 0)
    return OctaveProvider(client_factory=factory, clock=lambda: FIXED, **kw)


async def test_maps_octave_values_and_converts_mph_to_kmh():
    client = FakeClient({("paramStore", "RPM"): 2210.4, ("paramStore", "SPEED"): 49.1, ("paramStore", "COOLANT_TEMP"): 91.25})
    t = await provider_for(client).read()
    assert t.rpm == 2210
    assert t.speed_kmh == pytest.approx(79.0, abs=0.05)  # 49.1 mph * 1.609344 = 79.02
    assert t.coolant_temp_c == 91.2  # 91.25 is exact in binary: round-half-even gives 91.2
    assert (t.source, t.simulated, t.timestamp) == ("octave", True, FIXED)
    assert t.missing == []


async def test_speed_already_in_kmh_is_not_converted():
    client = FakeClient({("paramStore", "SPEED"): 100}, speed_unit="km/h")
    assert (await provider_for(client).read()).speed_kmh == 100.0


async def test_unavailable_parameter_stays_none_and_is_reported_missing():
    client = FakeClient({("paramStore", "COOLANT_TEMP"): None})
    t = await provider_for(client).read()
    assert t.coolant_temp_c is None
    assert t.missing == ["coolant_temp_c"]
    assert t.rpm == 800


async def test_simulated_is_none_when_octave_cannot_say():
    def boom(obj, prop):
        if obj == "sim":
            raise RuntimeError("no sim object")

    t = await provider_for(FakeClient(on_get=boom)).read()
    assert t.simulated is None


async def test_vehicle_link_down_is_an_error_not_stale_data():
    client = FakeClient({("obdManager", "connected"): False})
    with pytest.raises(VehicleLinkDown):
        await provider_for(client).read()
    assert ("get", "paramStore", "RPM") not in client.ops


async def test_non_numeric_value_is_a_provider_error():
    client = FakeClient({("paramStore", "RPM"): "fast"})
    with pytest.raises(ProviderError):
        await provider_for(client).read()


async def test_connection_failure_maps_to_unavailable():
    """What every SDK raises when nothing listens (newer SDKs wrap it in OctaveConnectError, an OSError)."""

    def refuse():
        raise ConnectionRefusedError("nothing listening")

    with pytest.raises(ProviderUnavailable):
        await provider_for(refuse).read()


async def test_sdk_connect_error_class_maps_to_unavailable(sdk):
    if not hasattr(sdk, "OctaveConnectError"):
        pytest.skip("this SDK predates OctaveConnectError (v0.9.6 release)")

    def refuse():
        raise sdk.OctaveConnectError("cannot connect")

    with pytest.raises(ProviderUnavailable):
        await provider_for(refuse).read()


async def test_connect_timeout_means_unavailable_not_slow():
    """Windows can run out the connect timeout on a closed loopback port; the old SDK lets TimeoutError through."""

    def no_answer():
        raise TimeoutError("timed out")

    with pytest.raises(ProviderUnavailable):
        await provider_for(no_answer).read()


async def test_octave_timeout_maps_to_timeout(sdk):
    def slow(obj, prop):
        raise sdk.OctaveError("get: no reply within 2.0 s")

    with pytest.raises(ProviderTimeout):
        await provider_for(FakeClient(on_get=slow)).read()


async def test_hung_octave_hits_overall_deadline():
    def hang(obj, prop):
        time.sleep(1.5)

    p = provider_for(FakeClient(on_get=hang), timeout_s=0.01)  # deadline = 1.02 s
    with pytest.raises(ProviderTimeout):
        await p.read()


async def test_lost_connection_is_unavailable_then_reconnects(sdk):
    clients = []

    def factory():
        c = FakeClient(on_get=(lambda o, p: (_ for _ in ()).throw(sdk.OctaveError("connection lost: x"))) if not clients else None)
        clients.append(c)
        return c

    p = provider_for(factory)
    with pytest.raises(ProviderUnavailable):
        await p.read()
    assert clients[0].closed
    assert (await p.read()).rpm == 800  # second call opened a fresh connection
    assert len(clients) == 2


async def test_connection_is_reused_between_reads():
    created = []

    def factory():
        created.append(FakeClient())
        return created[-1]

    p = provider_for(factory)
    await p.read()
    await p.read()
    assert len(created) == 1


async def test_incompatible_protocol_is_refused():
    client = FakeClient(protocol=4)
    with pytest.raises(ProtocolIncompatible):
        await provider_for(client).read()
    assert client.closed


async def test_unexpected_speed_unit_is_refused():
    with pytest.raises(ProtocolIncompatible):
        await provider_for(FakeClient(speed_unit="knots")).read()


async def test_only_whitelisted_reads_happen_and_nothing_is_written():
    client = FakeClient()
    p = provider_for(client)
    await p.read()
    await p.status()
    kinds = {op[0] for op in client.ops}
    assert kinds <= {"get", "call"}, f"unexpected operations: {client.ops}"
    assert [op for op in client.ops if op[0] == "call"] == [
        ("call", "parameterCatalog", "info", "SPEED"),
        ("call", "parameterCatalog", "info", "COOLANT_TEMP"),
        ("call", "obdManager", "setParameterDemand", "fit-ai-core", ["RPM", "SPEED", "COOLANT_TEMP"]),
    ]
    assert all(op[1:3] in {("paramStore", "RPM"), ("paramStore", "SPEED"), ("paramStore", "COOLANT_TEMP"),
                           ("obdManager", "connected"), ("obdManager", "connectionStatus"), ("sim", "active")}
               for op in client.ops if op[0] == "get")


def test_read_only_proxy_refuses_anything_else():
    fake = FakeClient()
    ro = _ReadOnlyClient(fake)
    for obj, prop in [("sim", "status"), ("settingsManager", "x"), ("paramStore", "FUEL_LEVEL")]:
        with pytest.raises(PermissionError):
            ro.get(obj, prop)
    with pytest.raises(PermissionError):
        ro.catalog_info("FUEL_LEVEL")
    with pytest.raises(PermissionError):
        ro.set_demand(["RPM", "FUEL_LEVEL"])
    assert fake.ops == []
    assert not hasattr(ro, "set") and not hasattr(ro, "call") and not hasattr(ro, "request")


async def test_status_connected():
    s = await provider_for(FakeClient()).status()
    assert (s.state, s.available, s.simulated, s.protocol_version, s.octave_version) == ("connected", True, True, 3, "0.9.6")
    assert s.detail == "Simulated · Connected"


async def test_status_vehicle_link_down_is_still_available():
    s = await provider_for(FakeClient({("obdManager", "connected"): False})).status()
    assert (s.state, s.available) == ("vehicle_link_down", True)


async def test_status_never_raises_when_octave_is_down():
    def refuse():
        raise ConnectionRefusedError("nothing listening")

    s = await provider_for(refuse).status()
    assert (s.state, s.available) == ("octave_unavailable", False)


async def test_status_reports_protocol_mismatch():
    s = await provider_for(FakeClient(protocol=9)).status()
    assert (s.state, s.available) == ("octave_protocol_incompatible", False)


async def test_core_registers_poll_demand_so_octave_keeps_values_fresh():
    """OCTAVE only polls PIDs somebody asked for; without this, paramStore goes stale."""
    client = FakeClient()
    p = provider_for(client)
    await p.read()
    assert client.demand == {"fit-ai-core": ["RPM", "SPEED", "COOLANT_TEMP"]}
    await p.aclose()
    assert client.demand == {"fit-ai-core": []}  # released on shutdown
    assert client.closed


async def test_demand_is_registered_before_first_value_is_read():
    client = FakeClient()
    await provider_for(client).read()
    first_get = next(i for i, op in enumerate(client.ops) if op[:2] == ("get", "paramStore"))
    demand = next(i for i, op in enumerate(client.ops) if op[:3] == ("call", "obdManager", "setParameterDemand"))
    assert demand < first_get


async def test_demand_is_registered_again_on_reconnect(sdk):
    clients = []

    def factory():
        lost = not clients
        c = FakeClient(on_get=(lambda o, pr: (_ for _ in ()).throw(sdk.OctaveError("connection lost: x"))) if lost else None)
        clients.append(c)
        return c

    p = provider_for(factory)
    with pytest.raises(ProviderUnavailable):
        await p.read()
    await p.read()
    assert all(c.demand == {"fit-ai-core": ["RPM", "SPEED", "COOLANT_TEMP"]} for c in clients)


async def test_late_failure_of_an_old_connection_does_not_close_the_new_one():
    old, new = FakeClient(), FakeClient()
    p = provider_for(old)
    await p.read()
    old_conn = p._conn
    p._drop()  # connection replaced...
    p._factory = lambda: new
    await p.read()
    assert p._conn is not old_conn and not new.closed
    p._drop(old_conn)  # ...and then the abandoned thread of the old one fails late
    assert p._conn is not None and not new.closed
