"""Builders shared by the grounding tests and the adversarial corpus."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fit_ai.grounding import EvidenceBundle, StructuredAnswer, build_evidence
from fit_ai.grounding.response import Claim
from fit_ai.tools.contracts import ToolOutcome

NOW = datetime(2026, 11, 17, 15, 0, 0, tzinfo=UTC)


def telemetry_outcome(rpm=800, speed=0.0, temp=90.0, *, simulated=True, age_s=0.2, ok=True, error_code=None,
                      decision="allowed", name="get_vehicle_telemetry", run_id="run-1") -> ToolOutcome:
    if not ok:
        return ToolOutcome(run_id=run_id, requested_name=name, decision=decision, permission="READ", ok=False,
                           error_code=error_code or "vehicle_link_down", error_message="x", started_at=NOW)
    missing = [n for n, v in (("rpm", rpm), ("speed_kmh", speed), ("coolant_temp_c", temp)) if v is None]
    data = {"state": "ok" if not missing else "partial", "rpm": rpm, "speed_kmh": speed, "coolant_temp_c": temp,
            "missing": missing, "source": "fake", "simulated": simulated,
            "timestamp": (NOW - timedelta(seconds=age_s + 0.01)).isoformat()}
    return ToolOutcome(run_id=run_id, requested_name=name, decision="allowed", permission="READ", ok=True, data=data,
                       started_at=NOW, duration_s=0.01, simulated=simulated)


def status_outcome(state="connected", simulated=True) -> ToolOutcome:
    data = {"available": state in ("connected", "vehicle_link_down"), "state": state, "source": "fake",
            "simulated": simulated, "protocol_version": 3, "octave_version": "fake", "detail": None}
    return ToolOutcome(run_id="run-s", requested_name="get_vehicle_status", decision="allowed", permission="READ",
                       ok=True, data=data, started_at=NOW, duration_s=0.01, simulated=simulated)


def bundle(*outcomes: ToolOutcome, turn_id="turn-1", max_age_s=10.0) -> EvidenceBundle:
    return EvidenceBundle.of(turn_id, [build_evidence(o, turn_id) for o in outcomes], max_age_s)


def live(rpm=800, speed=0.0, temp=90.0, simulated=True, age_s=0.2, **kw) -> EvidenceBundle:
    return bundle(telemetry_outcome(rpm, speed, temp, simulated=simulated, age_s=age_s, **kw))


def ans(text: str, claims=(), unknown=()) -> StructuredAnswer:
    return StructuredAnswer(answer=text, claims=[Claim(field=f, value=v, unit=u) for f, v, u in claims],
                            unknown=list(unknown))
