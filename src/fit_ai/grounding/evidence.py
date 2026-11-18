"""Evidence: what the tools actually observed in THIS turn. The only source of truth for sensor values.

Rules enforced by code:
- only `get_vehicle_telemetry` produces sensor values; memory facts, user text and model output never do;
- every evidence item belongs to exactly one turn and a bundle refuses items from another turn;
- a reading older than `max_age_s` is stale and is not usable as a current value.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from fit_ai.tools.contracts import ToolOutcome

SENSOR_FIELDS = ("rpm", "speed_kmh", "coolant_temp_c")
CANONICAL_UNIT = {"rpm": "rpm", "speed_kmh": "km/h", "coolant_temp_c": "°C"}
FIELD_LABEL = {"rpm": "rotação", "speed_kmh": "velocidade", "coolant_temp_c": "temperatura do líquido de arrefecimento"}
TELEMETRY_TOOL = "get_vehicle_telemetry"
STATUS_TOOL = "get_vehicle_status"
DEFAULT_MAX_AGE_S = 10.0


class EvidenceError(Exception):
    """An attempt to build an inconsistent bundle (for example mixing readings of different turns)."""


@dataclass(frozen=True)
class Evidence:
    run_id: str
    turn_id: str
    tool: str
    read_at: datetime  # when the tool finished (our clock)
    state: Literal["ok", "partial", "error", "denied"]
    simulated: bool | None = None
    source: str | None = None
    age_s: float | None = None  # read_at - the provider's own timestamp (None: no timestamp)
    values: dict[str, float] = field(default_factory=dict)  # ONLY fields the source really provided
    missing: tuple[str, ...] = ()
    error_code: str | None = None
    link_state: str | None = None  # status tool: connected | vehicle_link_down | ...
    status_available: bool | None = None

    def is_stale(self, max_age_s: float) -> bool:
        return self.age_s is not None and self.age_s > max_age_s

    def usable(self, max_age_s: float) -> bool:
        return self.state in ("ok", "partial") and not self.is_stale(max_age_s)


def build_evidence(outcome: ToolOutcome, turn_id: str) -> Evidence | None:
    """Turn a tool outcome into evidence. Returns None for tools that are not evidence of the vehicle
    (memory facts are stored information, never measurements)."""
    if outcome.requested_name not in (TELEMETRY_TOOL, STATUS_TOOL):
        return None
    from datetime import timedelta
    read_at = outcome.started_at + timedelta(seconds=outcome.duration_s)
    common = dict(run_id=outcome.run_id, turn_id=turn_id, tool=outcome.requested_name, read_at=read_at,
                  simulated=outcome.simulated)
    if not outcome.ok or outcome.data is None:
        return Evidence(**common, state="denied" if outcome.decision == "denied" else "error",
                        error_code=outcome.error_code)
    d = outcome.data
    if outcome.requested_name == STATUS_TOOL:
        return Evidence(**common, state="ok", source=d.get("source"), link_state=d.get("state"),
                        status_available=d.get("available"))
    values = {f: float(d[f]) for f in SENSOR_FIELDS if d.get(f) is not None}
    missing = tuple(f for f in SENSOR_FIELDS if d.get(f) is None)
    age = None
    if d.get("timestamp"):
        ts = datetime.fromisoformat(str(d["timestamp"]).replace("Z", "+00:00"))
        age = max(0.0, (read_at - ts).total_seconds())
    return Evidence(**common, state="ok" if not missing else "partial", source=d.get("source"), age_s=age,
                    values=values, missing=missing)


class EvidenceBundle:
    def __init__(self, turn_id: str, max_age_s: float = DEFAULT_MAX_AGE_S):
        self.turn_id = turn_id
        self.max_age_s = max_age_s
        self._items: list[Evidence] = []

    def add(self, ev: Evidence | None) -> None:
        if ev is None:
            return
        if ev.turn_id != self.turn_id:
            raise EvidenceError("evidence from another turn cannot be mixed into this turn")
        self._items.append(ev)

    @classmethod
    def of(cls, turn_id: str, items: Iterable[Evidence | None], max_age_s: float = DEFAULT_MAX_AGE_S) -> "EvidenceBundle":
        b = cls(turn_id, max_age_s)
        for i in items:
            b.add(i)
        return b

    @property
    def items(self) -> tuple[Evidence, ...]:
        return tuple(self._items)

    @property
    def telemetry(self) -> tuple[Evidence, ...]:
        return tuple(e for e in self._items if e.tool == TELEMETRY_TOOL)

    @property
    def status(self) -> tuple[Evidence, ...]:
        return tuple(e for e in self._items if e.tool == STATUS_TOOL)

    def _latest_usable(self) -> Evidence | None:
        ok = [e for e in self.telemetry if e.usable(self.max_age_s)]
        return max(ok, key=lambda e: e.read_at) if ok else None

    def value(self, name: str) -> float | None:
        """The current value of a field, or None. The ONLY way answers may learn a sensor value."""
        ev = self._latest_usable()
        return None if ev is None else ev.values.get(name)

    @property
    def simulated(self) -> bool | None:
        ev = self._latest_usable() or (self.telemetry[-1] if self.telemetry else None)
        return None if ev is None else ev.simulated

    @property
    def has_usable_reading(self) -> bool:
        return self._latest_usable() is not None

    @property
    def stale(self) -> Evidence | None:
        """The newest successful but too-old telemetry evidence, when there is no usable one."""
        if self.has_usable_reading:
            return None
        old = [e for e in self.telemetry if e.state in ("ok", "partial") and e.is_stale(self.max_age_s)]
        return max(old, key=lambda e: e.read_at) if old else None

    @property
    def failure(self) -> Evidence | None:
        bad = [e for e in self.telemetry if e.state in ("error", "denied")]
        return bad[-1] if bad else None

    def missing_fields(self) -> tuple[str, ...]:
        ev = self._latest_usable()
        return ev.missing if ev else ()

    def link_down(self) -> bool:
        return any(e.link_state not in (None, "connected") for e in self.status)
