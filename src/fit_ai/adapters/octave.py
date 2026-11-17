"""OCTAVE telemetry provider (read-only).

Talks to a local OCTAVE service through its official Python SDK (MIT, loaded in
place from the third-party checkout: nothing is copied). The SDK is blocking,
so every call runs in a worker thread and never blocks the event loop.

Nothing is ever written to the vehicle. The SDK client is only reachable through
`_ReadOnlyClient`, which allows a fixed list of property reads, the catalog's
`info` lookup and ONE state-changing call: registering this Core as a consumer of
the three PIDs it reports (`obdManager.setParameterDemand`, scope "read" in
OCTAVE's own API). Without that demand OCTAVE does not poll a PID nobody asked
for, and `paramStore` keeps serving its last (stale) value while the link is up.
"""
from __future__ import annotations

import asyncio
import importlib.util
import logging
import math
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from fit_ai.domain.telemetry import (
    MPH_TO_KMH,
    ProtocolIncompatible,
    ProviderError,
    ProviderStatus,
    ProviderTimeout,
    ProviderUnavailable,
    TelemetryError,
    VehicleLinkDown,
    VehicleTelemetry,
)

log = logging.getLogger(__name__)

SOURCE = "octave"
# Service protocol versions this adapter was written and tested against (OCTAVE v0.9.6 = 3).
SUPPORTED_PROTOCOLS = frozenset({3})
# The SDK is loaded in place from a checkout. Two SDKs are verified: the one of release v0.9.6
# (git archive v0.9.6 sdk/python) and the checkout's newer one (see docs/consolidation-review.md).

PID_RPM = "RPM"
PID_SPEED = "SPEED"
PID_COOLANT = "COOLANT_TEMP"
PIDS = (PID_RPM, PID_SPEED, PID_COOLANT)
DEMAND_CONSUMER = "fit-ai-core"

_READ_ALLOWLIST = frozenset(
    {
        ("paramStore", PID_RPM),
        ("paramStore", PID_SPEED),
        ("paramStore", PID_COOLANT),
        ("obdManager", "connected"),
        ("obdManager", "connectionStatus"),
        ("sim", "active"),
    }
)

_sdk_module: ModuleType | None = None
_sdk_lock = threading.Lock()


def load_sdk(sdk_path: Path) -> ModuleType:
    """Import `octave_client` from `sdk_path` without touching sys.path and without
    writing bytecode into the third-party tree."""
    global _sdk_module
    with _sdk_lock:
        if _sdk_module is not None:
            return _sdk_module
        init = Path(sdk_path) / "octave_client" / "__init__.py"
        if not init.is_file():
            raise ProviderError(f"OCTAVE SDK not found at {init.parent}")
        spec = importlib.util.spec_from_file_location(
            "octave_client", init, submodule_search_locations=[str(init.parent)]
        )
        module = importlib.util.module_from_spec(spec)
        previous = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            sys.modules["octave_client"] = module
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop("octave_client", None)
            raise
        finally:
            sys.dont_write_bytecode = previous
        _sdk_module = module
        return module


class _ReadOnlyClient:
    """The only door to the SDK client."""

    def __init__(self, client: Any):
        self._client = client

    @property
    def closed(self) -> bool:
        # `Client.closed` exists in newer SDKs only (not in the v0.9.6 release's): without it
        # a lost connection is detected by the next request failing, which also reconnects.
        return bool(getattr(self._client, "closed", False))

    @property
    def server(self) -> dict:
        return getattr(self._client, "server", None) or {}

    def get(self, obj: str, prop: str) -> Any:
        if (obj, prop) not in _READ_ALLOWLIST:
            raise PermissionError(f"read of {obj}.{prop} is not allowed")
        return self._client.get(obj, prop)

    def catalog_info(self, pid: str) -> dict:
        if pid not in (PID_RPM, PID_SPEED, PID_COOLANT):
            raise PermissionError(f"catalog lookup of {pid} is not allowed")
        return self._client.call("parameterCatalog", "info", pid) or {}

    def set_demand(self, pids: list[str]) -> None:
        """Ask OCTAVE to poll `pids` for us (empty list: stop). Only our three PIDs."""
        if not set(pids) <= set(PIDS):
            raise PermissionError("demand for this parameter is not allowed")
        self._client.call("obdManager", "setParameterDemand", DEMAND_CONSUMER, list(pids))

    def close(self) -> None:
        self._client.close()


@dataclass
class _Connection:
    client: _ReadOnlyClient
    protocol: int
    octave_version: str | None
    speed_factor: float  # native speed unit -> km/h


def _speed_factor(unit: str | None) -> float:
    u = (unit or "").strip().lower()
    if u == "mph":
        return MPH_TO_KMH
    if u in ("km/h", "kph", "kmh"):
        return 1.0
    raise ProtocolIncompatible(f"unexpected speed unit {unit!r}")


def _check_coolant_unit(unit: str | None) -> None:
    if not (unit or "").strip().upper().endswith("C"):
        raise ProtocolIncompatible(f"unexpected coolant temperature unit {unit!r}")


def _number(value: Any, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderError(f"OCTAVE returned a non-numeric {name}")
    if not math.isfinite(value):
        return None
    return float(value)


def _translate(exc: BaseException) -> TelemetryError:
    if isinstance(exc, TelemetryError):
        return exc
    sdk = _sdk_module
    # OctaveConnectError (an OSError) exists in newer SDKs; the v0.9.6 release raises a plain OSError.
    connect_error = getattr(sdk, "OctaveConnectError", None)
    if connect_error is not None and isinstance(exc, connect_error):
        return ProviderUnavailable("OCTAVE is not reachable")
    if isinstance(exc, TimeoutError):
        return ProviderTimeout("OCTAVE did not answer in time")
    if sdk is not None and isinstance(exc, sdk.OctaveError):
        message = str(exc)
        code = getattr(exc, "code", None)
        if "no reply within" in message:
            return ProviderTimeout("OCTAVE did not answer in time")
        if code in ("unauthorised", "forbidden", "rateLimited"):
            return ProviderError(f"OCTAVE refused the request ({code})")
        if code == "closed" or message.startswith(("connection closed", "connection lost")):
            return ProviderUnavailable("connection to OCTAVE was lost")
        return ProviderError("OCTAVE returned an error")
    if isinstance(exc, OSError):
        return ProviderUnavailable("OCTAVE is not reachable")
    return ProviderError("unexpected error talking to OCTAVE")


class OctaveProvider:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9876,
        timeout_s: float = 2.0,
        sdk_path: Path | None = None,
        client_factory: Callable[[], Any] | None = None,
        clock: Callable[[], datetime] | None = None,
        demand_settle_s: float = 1.0,
    ):
        self._timeout_s = timeout_s
        self._demand_settle_s = demand_settle_s
        self._deadline_s = timeout_s * 2 + 1
        self._clock = clock or (lambda: datetime.now().astimezone())
        if client_factory is None:
            if sdk_path is None:
                raise ValueError("sdk_path is required without a client_factory")
            sdk = load_sdk(sdk_path)
            client_factory = lambda: sdk.Client(host, port, timeout=timeout_s, check_version=False)  # noqa: E731
        self._factory = client_factory
        self._conn: _Connection | None = None
        self._conn_lock = threading.Lock()
        self._async_lock = asyncio.Lock()

    # ── public, async ─────────────────────────────────────────────────────

    async def read(self) -> VehicleTelemetry:
        return await self._run(self._read_sync)

    async def status(self) -> ProviderStatus:
        try:
            return await self._run(self._status_sync)
        except TelemetryError as exc:
            return ProviderStatus(state=exc.code, source=SOURCE, detail=str(exc))

    async def aclose(self) -> None:
        await asyncio.to_thread(self._drop, None, True)

    # ── internals ─────────────────────────────────────────────────────────

    async def _run(self, fn: Callable[[], Any]) -> Any:
        async with self._async_lock:
            try:
                return await asyncio.wait_for(asyncio.to_thread(fn), timeout=self._deadline_s)
            except asyncio.TimeoutError:
                raise ProviderTimeout("OCTAVE did not answer in time") from None

    def _connection(self) -> _Connection:
        with self._conn_lock:
            if self._conn is not None and not self._conn.client.closed:
                return self._conn
            self._conn = None
            try:
                self._conn = self._open()
            except Exception as exc:
                raise _translate(exc) from exc
            return self._conn

    def _open(self) -> _Connection:
        try:
            raw = self._factory()
        except OSError as exc:
            # Could not connect at all (refused, unreachable, or a connect timeout: on Windows a
            # closed loopback port can run out the timeout). Nothing is serving; not a slow answer.
            raise ProviderUnavailable("OCTAVE is not reachable") from exc
        client = _ReadOnlyClient(raw)
        try:
            protocol = client.server.get("protocolVersion")
            if protocol not in SUPPORTED_PROTOCOLS:
                raise ProtocolIncompatible(
                    f"OCTAVE speaks protocol {protocol}; supported: {sorted(SUPPORTED_PROTOCOLS)}"
                )
            speed_factor = _speed_factor(client.catalog_info(PID_SPEED).get("unit"))
            _check_coolant_unit(client.catalog_info(PID_COOLANT).get("unit"))
            version = (client.server.get("app") or {}).get("version")
            # Make OCTAVE poll our PIDs, then give the first poll a moment: values it
            # held from before the demand existed may be stale.
            client.set_demand(list(PIDS))
            if self._demand_settle_s:
                time.sleep(self._demand_settle_s)
            return _Connection(client, protocol, version, speed_factor)
        except BaseException:
            client.close()
            raise

    def _drop(self, only: _Connection | None = None, release_demand: bool = False) -> None:
        """Forget and close the current connection. With `only`, do nothing unless it is
        still the current one (a late failure must not kill a newer healthy connection)."""
        with self._conn_lock:
            if only is not None and self._conn is not only:
                conn = only
                is_current = False
            else:
                conn, self._conn = self._conn, None
                is_current = True
        if conn is not None:
            try:
                if release_demand and is_current:
                    conn.client.set_demand([])
            except Exception:
                pass
            try:
                conn.client.close()
            except Exception:  # closing must never raise
                pass

    def _simulated(self, client: _ReadOnlyClient) -> bool | None:
        try:
            value = client.get("sim", "active")
        except Exception:
            return None
        return value if isinstance(value, bool) else None

    def _read_sync(self) -> VehicleTelemetry:
        conn = self._connection()
        client = conn.client
        try:
            if client.get("obdManager", "connected") is not True:
                raise VehicleLinkDown("OCTAVE is running but has no vehicle link")
            rpm = _number(client.get("paramStore", PID_RPM), "RPM")
            speed = _number(client.get("paramStore", PID_SPEED), "speed")
            coolant = _number(client.get("paramStore", PID_COOLANT), "coolant temperature")
            simulated = self._simulated(client)
        except VehicleLinkDown:
            raise
        except Exception as exc:
            translated = _translate(exc)
            log.warning("OCTAVE read failed: %s", translated.code)
            if not isinstance(translated, ProviderError):  # connection-level failure: reconnect next time
                self._drop(conn)
            raise translated from exc
        return VehicleTelemetry(
            rpm=None if rpm is None else int(round(rpm)),
            speed_kmh=None if speed is None else round(speed * conn.speed_factor, 1),
            coolant_temp_c=None if coolant is None else round(coolant, 1),
            source=SOURCE,
            simulated=simulated,
            timestamp=self._clock(),
        )

    def _status_sync(self) -> ProviderStatus:
        conn = self._connection()
        client = conn.client
        try:
            linked = client.get("obdManager", "connected") is True
            detail = client.get("obdManager", "connectionStatus")
            simulated = self._simulated(client)
        except Exception as exc:
            translated = _translate(exc)
            self._drop(conn)
            raise translated from exc
        return ProviderStatus(
            state="connected" if linked else VehicleLinkDown.code,
            source=SOURCE,
            simulated=simulated,
            protocol_version=conn.protocol,
            octave_version=conn.octave_version,
            detail=detail if isinstance(detail, str) else None,
        )
