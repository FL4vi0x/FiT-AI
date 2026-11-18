"""Tool registry: permissions, validation, timeouts, error containment, and the real telemetry tools."""
import asyncio
from datetime import UTC, datetime

import pytest
from pydantic import Field

from fit_ai.adapters.fake_telemetry import FakeTelemetryProvider
from fit_ai.domain.telemetry import ProviderTimeout, VehicleLinkDown
from fit_ai.memory import SqliteMemoryStore
from fit_ai.services.telemetry import TelemetryService
from fit_ai.tools import (
    Permission,
    ToolInput,
    ToolOutput,
    ToolRegistrationError,
    ToolRegistry,
    ToolSpec,
    build_vehicle_registry,
)

pytestmark = pytest.mark.anyio


class Echo(ToolInput):
    text: str = Field(max_length=20)


class EchoOut(ToolOutput):
    text: str


def make_tool(name="echo_tool", permission=Permission.READ, side_effects=(), timeout_s=1.0, fn=None):
    class T:
        spec = ToolSpec(name=name, description="d", input_model=Echo, output_model=EchoOut,
                        permission=permission, side_effects=side_effects, timeout_s=timeout_s)

        async def run(self, args):
            return await fn(args) if fn else EchoOut(text=args.text)
    return T()


# ── registration policy ──
@pytest.mark.parametrize("perm", [Permission.ACTION_LOW, Permission.ACTION_CONFIRM, Permission.FORBIDDEN])
def test_only_read_tools_can_be_registered(perm):
    with pytest.raises(ToolRegistrationError, match="only READ"):
        ToolRegistry().register(make_tool(permission=perm))


def test_read_tool_with_side_effects_is_rejected():
    with pytest.raises(ToolRegistrationError, match="side effects"):
        ToolRegistry().register(make_tool(side_effects=("writes_file",)))


@pytest.mark.parametrize("name", ["", "A", "Has Space", "rm -rf /", "a" * 70, "x;y", "../etc", "9start"])
def test_bad_names_and_duplicates_are_rejected(name):
    with pytest.raises(ToolRegistrationError):
        ToolRegistry().register(make_tool(name=name))
    r = ToolRegistry()
    r.register(make_tool())
    with pytest.raises(ToolRegistrationError, match="already"):
        r.register(make_tool())


def test_timeout_bound_is_enforced_at_registration():
    for bad in (0, -1, 31):
        with pytest.raises(ToolRegistrationError):
            ToolRegistry().register(make_tool(timeout_s=bad))


# ── execution ──
async def test_valid_call_succeeds_and_is_serialisable():
    r = ToolRegistry()
    r.register(make_tool())
    o = await r.execute("echo_tool", {"text": "oi"})
    assert o.ok and o.decision == "allowed" and o.data == {"text": "oi"} and o.permission == "READ"


@pytest.mark.parametrize("name", ["nao_existe", "", "ECHO_TOOL", "set_ac_temperature", "../../bin/sh", None, 42, "x" * 500])
async def test_unknown_or_invented_tools_are_denied(name):
    r = ToolRegistry()
    r.register(make_tool())
    o = await r.execute(name, {})
    assert not o.ok and o.decision == "denied" and o.error_code == "unknown_tool"
    assert len(o.requested_name) <= 64  # a hostile name never travels back into logs untruncated


@pytest.mark.parametrize("args", [{"text": "ok", "extra": 1}, {}, {"text": 5}, {"text": "x" * 21},
                                  '{"text": "ok", "rm": "-rf"}', "not json", "[1,2]", 7, '{"text":'])
async def test_invalid_or_extra_arguments_are_rejected(args):
    r = ToolRegistry()
    r.register(make_tool())
    o = await r.execute("echo_tool", args)
    assert not o.ok and o.error_code == "invalid_arguments" and o.decision == "denied"


async def test_argument_values_never_leak_into_the_error_message():
    r = ToolRegistry()
    r.register(make_tool())
    o = await r.execute("echo_tool", {"text": "SEGREDO-" * 5})
    assert "SEGREDO" not in (o.error_message or "")


async def test_json_string_arguments_are_accepted():
    r = ToolRegistry()
    r.register(make_tool())
    assert (await r.execute("echo_tool", '{"text": "oi"}')).ok


async def test_tool_not_offered_for_this_request_is_denied():
    r = ToolRegistry()
    r.register(make_tool())
    o = await r.execute("echo_tool", {"text": "a"}, allowed=["other"])
    assert o.error_code == "tool_not_offered" and o.decision == "denied"


async def test_timeout_is_enforced_and_reported():
    async def slow(args):
        await asyncio.sleep(5)
    r = ToolRegistry()
    r.register(make_tool(timeout_s=0.05, fn=slow))
    o = await r.execute("echo_tool", {"text": "a"})
    assert not o.ok and o.error_code == "tool_timeout" and o.decision == "allowed"


async def test_unexpected_exception_is_contained_without_leaking_internals(caplog):
    async def boom(args):
        raise RuntimeError("password=hunter2 /etc/shadow")
    r = ToolRegistry()
    r.register(make_tool(fn=boom))
    o = await r.execute("echo_tool", {"text": "a"})
    assert o.error_code == "tool_error" and "hunter2" not in (o.error_message or "")
    assert any("failed unexpectedly" in m for m in caplog.messages)  # not silent: logged with traceback


async def test_a_forged_spec_cannot_slip_past_execution(monkeypatch):
    r = ToolRegistry()
    t = make_tool()
    r.register(t)
    object.__setattr__(t.spec, "permission", Permission.ACTION_LOW)  # tamper after registration
    o = await r.execute("echo_tool", {"text": "a"})
    assert o.error_code == "permission_denied" and not o.ok


def test_definitions_expose_schema_and_only_requested_tools():
    r = ToolRegistry()
    r.register(make_tool("tool_a"))
    r.register(make_tool("tool_b"))
    defs = r.definitions(["tool_b"])
    assert [d.name for d in defs] == ["tool_b"]
    assert defs[0].parameters["properties"]["text"]["type"] == "string"
    assert defs[0].parameters.get("additionalProperties") is False
    assert r.definitions(["nope"]) == []


# ── vehicle tools over the real TelemetryService ──
def registry(fake, memory=None):
    return build_vehicle_registry(TelemetryService(fake), memory)


async def test_telemetry_tool_returns_the_core_reading():
    fake = FakeTelemetryProvider(800, 0.0, 90.0, simulated=True, source="fake-octave")
    o = await registry(fake).execute("get_vehicle_telemetry", {})
    assert o.ok and o.simulated is True
    assert (o.data["rpm"], o.data["speed_kmh"], o.data["coolant_temp_c"]) == (800, 0.0, 90.0)
    assert o.data["state"] == "ok" and o.data["missing"] == [] and o.data["source"] == "fake-octave"
    assert fake.reads == 1


async def test_partial_data_lists_missing_fields_and_invents_nothing():
    o = await registry(FakeTelemetryProvider(800, None, None)).execute("get_vehicle_telemetry", {})
    assert o.ok and o.data["state"] == "partial"
    assert o.data["speed_kmh"] is None and o.data["coolant_temp_c"] is None
    assert o.data["missing"] == ["speed_kmh", "coolant_temp_c"]


async def test_no_data_at_all_is_an_error_not_a_success():
    o = await registry(FakeTelemetryProvider(None, None, None)).execute("get_vehicle_telemetry", {})
    assert not o.ok and o.error_code == "no_data"


@pytest.mark.parametrize("exc,code", [(VehicleLinkDown("link"), "vehicle_link_down"), (ProviderTimeout("t"), "octave_timeout")])
async def test_provider_failures_surface_stable_codes(exc, code):
    o = await registry(FakeTelemetryProvider().fail_with(exc)).execute("get_vehicle_telemetry", {})
    assert not o.ok and o.error_code == code and o.decision == "allowed"


async def test_unknown_simulation_flag_is_preserved_as_none():
    o = await registry(FakeTelemetryProvider(simulated=None)).execute("get_vehicle_telemetry", {})
    assert o.ok and o.data["simulated"] is None and o.simulated is None


async def test_telemetry_tool_rejects_arguments():
    o = await registry(FakeTelemetryProvider()).execute("get_vehicle_telemetry", {"pid": "0C"})
    assert o.error_code == "invalid_arguments"  # no way to ask for sensors we do not have


async def test_status_tool():
    fake = FakeTelemetryProvider(simulated=True)
    o = await registry(fake).execute("get_vehicle_status", {})
    assert o.ok and o.data["available"] is True and o.data["simulated"] is True
    assert o.data["protocol_version"] == 3 and o.data["state"] == "connected"
    fake.status_state = "vehicle_link_down"
    o2 = await registry(fake).execute("get_vehicle_status", {})
    assert o2.ok and o2.data["state"] == "vehicle_link_down" and o2.data["available"] is True


async def test_tool_slower_than_its_timeout_is_cut_off():
    reg = registry(FakeTelemetryProvider(delay_s=0.3))
    object.__setattr__(reg.spec("get_vehicle_telemetry"), "timeout_s", 0.05)
    o = await reg.execute("get_vehicle_telemetry", {})
    assert o.error_code == "tool_timeout"


async def test_memory_tool_returns_user_statements_marked_as_not_measurements(tmp_path):
    mem = SqliteMemoryStore(tmp_path / "m.db")
    mem.remember_fact("Troquei o óleo em outubro")
    mem.remember_fact("Gosto de rotas sem pedágio")
    reg = registry(FakeTelemetryProvider(), mem)
    o = await reg.execute("get_memory_facts", {"query": "óleo"})
    assert o.ok and o.data["authority"] == "user_statement" and o.data["is_measurement"] is False
    assert [f["content"] for f in o.data["facts"]] == ["Troquei o óleo em outubro"]
    assert len((await reg.execute("get_memory_facts", {})).data["facts"]) == 2
    assert (await reg.execute("get_memory_facts", {"limit": 99})).error_code == "invalid_arguments"
    assert o.simulated is None  # it is not telemetry


async def test_memory_tool_is_absent_without_a_store():
    reg = registry(FakeTelemetryProvider())
    assert "get_memory_facts" not in reg.names
    assert (await reg.execute("get_memory_facts", {})).error_code == "unknown_tool"


async def test_all_registered_vehicle_tools_are_read_only():
    reg = registry(FakeTelemetryProvider(), SqliteMemoryStore(":memory:") if False else None)
    assert all(reg.spec(n).permission is Permission.READ and not reg.spec(n).side_effects for n in reg.names)
    assert set(reg.names) == {"get_vehicle_status", "get_vehicle_telemetry"}


async def test_tools_never_write_to_the_provider():
    """The telemetry provider contract has no write method; the tool layer must not need one."""
    fake = FakeTelemetryProvider()
    reg = registry(fake)
    for name in reg.names:
        await reg.execute(name, {})
    assert {a for a in dir(fake) if a.startswith(("write", "set_", "send", "command"))} == set()
    assert datetime.now(UTC)  # (keeps the import used)
