"""Test doubles for the SDK client."""
from __future__ import annotations

from typing import Any, Callable

DEFAULT_VALUES: dict[tuple[str, str], Any] = {
    ("obdManager", "connected"): True,
    ("obdManager", "connectionStatus"): "Simulated · Connected",
    ("paramStore", "RPM"): 800,
    ("paramStore", "SPEED"): 0,
    ("paramStore", "COOLANT_TEMP"): 90,
    ("sim", "active"): True,
}


class FakeClient:
    """Records every operation. `set` exists only so a test can prove it is never called."""

    def __init__(
        self,
        values: dict | None = None,
        *,
        protocol: int = 3,
        speed_unit: str = "MPH",
        coolant_unit: str = "°C",
        on_get: Callable[[str, str], Any] | None = None,
    ):
        self.values = {**DEFAULT_VALUES, **(values or {})}
        self.server = {"protocolVersion": protocol, "app": {"version": "0.9.6", "headless": True}}
        self.units = {"SPEED": speed_unit, "COOLANT_TEMP": coolant_unit, "RPM": "RPM"}
        self.on_get = on_get
        self.closed = False
        self.ops: list[tuple] = []
        self.demand: dict[str, list] = {}

    def get(self, obj, prop=None):
        self.ops.append(("get", obj, prop))
        if self.on_get:
            self.on_get(obj, prop)
        return self.values.get((obj, prop))

    def call(self, obj, method, *args):
        self.ops.append(("call", obj, method, *args))
        if (obj, method) == ("obdManager", "setParameterDemand"):
            self.demand[args[0]] = list(args[1])
            return None
        assert (obj, method) == ("parameterCatalog", "info"), "only catalog lookups may be called"
        return {"unit": self.units.get(args[0])}

    def set(self, *args):  # pragma: no cover - must never run
        self.ops.append(("set", *args))

    def request(self, op, **kw):  # pragma: no cover - must never run
        self.ops.append(("request", op))

    def close(self):
        self.closed = True
