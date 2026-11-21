"""Structured answer parsing, evidence rules and the deterministic fallback (which must always verify)."""
import itertools
import json

import pytest
from grounding_helpers import ans, bundle, live, status_outcome, telemetry_outcome

from fit_ai.grounding import (
    RESPONSE_SCHEMA,
    EvidenceBundle,
    ResponseFormatError,
    format_number,
    parse_structured,
    render_fallback,
    render_unavailable_info,
    verify,
)


# ───────── strict parsing ─────────
def test_valid_answer_parses():
    a = parse_structured(json.dumps({"answer": "Simulado: 800 rpm.", "claims": [
        {"field": "rpm", "value": 800, "unit": "rpm"}], "unknown": ["pressao_pneu"]}))
    assert a.claims[0].field == "rpm" and a.unknown == ["pressao_pneu"]


@pytest.mark.parametrize("raw,code", [
    ("not json", "invalid_json"), ("", "invalid_json"), ("```json\n{}\n```", "invalid_json"),
    ('{"answer": "x"} trailing', "invalid_json"), ("[1]", "not_an_object"), ('"texto"', "not_an_object"),
    ("null", "not_an_object"),
    ('{"answer": "x", "claims": [], "unknown": [], "extra": 1}', "unknown_field"),
    ('{"answer": "x", "claims": [{"field": "pressao_pneu", "value": 30, "unit": "psi"}], "unknown": []}', "schema_violation"),
    ('{"answer": "x", "claims": [{"field": "rpm", "value": 800, "unit": "rpm", "x": 1}], "unknown": []}', "unknown_field"),
    ('{"answer": "", "claims": [], "unknown": []}', "schema_violation"),
    ('{"answer": "   ", "claims": [], "unknown": []}', "schema_violation"),
    ('{"claims": [], "unknown": []}', "schema_violation"),
    ('{"answer": 5, "claims": [], "unknown": []}', "schema_violation"),
    ('{"answer": "x", "claims": [{"field": "rpm", "value": "alto", "unit": "rpm"}], "unknown": []}', "schema_violation"),
    ('{"answer": "x", "claims": [{"field": "rpm", "value": NaN, "unit": "rpm"}], "unknown": []}', "schema_violation"),
    ('{"answer": "x", "claims": [{"field": "rpm", "value": Infinity, "unit": "rpm"}], "unknown": []}', "schema_violation"),
    ('{"answer": "' + "a" * 801 + '", "claims": [], "unknown": []}', "schema_violation"),
    ('{"answer": "x", "claims": [' + ",".join(['{"field":"rpm","value":1,"unit":"rpm"}'] * 7) + '], "unknown": []}', "schema_violation"),
])
def test_invalid_model_output_is_rejected_with_a_stable_code(raw, code):
    with pytest.raises(ResponseFormatError) as e:
        parse_structured(raw)
    assert e.value.code == code


def test_deeply_nested_garbage_does_not_crash():
    with pytest.raises(ResponseFormatError):
        parse_structured("[" * 5000)


def test_schema_only_allows_the_three_sensor_fields():
    enum = RESPONSE_SCHEMA["properties"]["claims"]["items"]["properties"]["field"]["enum"]
    assert enum == ["rpm", "speed_kmh", "coolant_temp_c"]
    assert RESPONSE_SCHEMA["additionalProperties"] is False


# ───────── formatting ─────────
@pytest.mark.parametrize("v,f,txt", [(800.0, "rpm", "800"), (0.0, "speed_kmh", "0"), (90.0, "coolant_temp_c", "90"),
                                     (12.5, "speed_kmh", "12,5"), (88.55, "coolant_temp_c", "88,6"), (104.25, "coolant_temp_c", "104,3"), (0.04, "speed_kmh", "0"),
                                     (-4.0, "coolant_temp_c", "-4")])
def test_number_formatting_uses_the_brazilian_decimal_comma(v, f, txt):
    assert format_number(v, f) == txt


# ───────── the fallback always passes the verifier ─────────
VALUES = [0, 800, 3250]
SPEEDS = [0.0, 12.5, 100.0, 87.34]
TEMPS = [-5.0, 90.0, 104.25]


@pytest.mark.parametrize("rpm,speed,temp,sim", list(itertools.product(VALUES, SPEEDS, TEMPS, [True, False, None])))
def test_fallback_from_full_readings_is_verified(rpm, speed, temp, sim):
    b = live(rpm, speed, temp, simulated=sim)
    text = render_fallback(b)
    v = verify(ans(text), b)
    assert v.passed, (text, v.violations)
    if sim is True:
        assert "simulad" in text.lower()


@pytest.mark.parametrize("rpm,speed,temp", [(None, 0.0, 90.0), (800, None, 90.0), (800, 0.0, None), (800, None, None),
                                            (None, None, 90.0), (None, 5.5, None)])
@pytest.mark.parametrize("requested", [(), ("rpm",), ("speed_kmh",), ("coolant_temp_c",), ("rpm", "speed_kmh")])
def test_fallback_with_partial_data_never_invents_and_verifies(rpm, speed, temp, requested):
    b = live(rpm, speed, temp)
    text = render_fallback(b, requested)
    assert verify(ans(text), b).passed, text
    wanted = [f for f in ("rpm", "speed_kmh", "coolant_temp_c") if not requested or f in requested]
    present = {"rpm": rpm, "speed_kmh": speed, "coolant_temp_c": temp}
    if all(present[f] is None for f in wanted):
        assert "Indisponível" in text and not any(ch.isdigit() for ch in text.split("Indisponível")[0].split(":")[-1])


def test_fallback_requested_subset_only_shows_the_requested_field():
    t = render_fallback(live(800, 0.0, 90.0), ("rpm",))
    assert "rotação 800 rpm" in t and "velocidade" not in t and "temperatura" not in t


@pytest.mark.parametrize("outcome,needle", [
    (telemetry_outcome(ok=False, error_code="vehicle_link_down"), "interrompida"),
    (telemetry_outcome(ok=False, error_code="octave_unavailable"), "não está disponível"),
    (telemetry_outcome(ok=False, error_code="octave_timeout"), "a tempo"),
    (telemetry_outcome(ok=False, error_code="no_data"), "nenhum valor"),
    (telemetry_outcome(ok=False, error_code="algo_novo"), "falha"),
])
def test_fallback_on_failures_states_the_reason_and_gives_no_numbers(outcome, needle):
    b = bundle(outcome)
    t = render_fallback(b)
    assert needle in t and "Não vou estimar" in t and not any(ch.isdigit() for ch in t)
    assert verify(ans(t), b).passed


def test_fallback_on_stale_reading():
    b = live(age_s=45)
    t = render_fallback(b)
    assert "desatualizada" in t and "800" not in t
    assert verify(ans(t), b).passed


def test_fallback_without_any_evidence():
    b = EvidenceBundle("turn-1")
    t = render_fallback(b)
    assert t == render_unavailable_info() and "não está disponível" in t
    assert verify(ans(t), b).passed


def test_fallback_with_only_status_evidence_does_not_pretend_to_have_values():
    t = render_fallback(bundle(status_outcome()))
    assert not any(ch.isdigit() for ch in t)


def test_a_stale_and_a_fresh_reading_in_one_turn_use_the_fresh_one():
    b = bundle(telemetry_outcome(900, age_s=60, run_id="old"), telemetry_outcome(800, age_s=0.2, run_id="new"))
    assert b.value("rpm") == 800 and "800" in render_fallback(b) and "900" not in render_fallback(b)


# ───────── status-only turns ─────────
@pytest.mark.parametrize("state", ["connected", "vehicle_link_down"])
@pytest.mark.parametrize("sim", [True, False, None])
def test_status_fallback_is_verified_and_never_claims_a_real_car_for_a_simulator(state, sim):
    b = bundle(status_outcome(state=state, simulated=sim))
    t = render_fallback(b)
    assert verify(ans(t), b).passed, t
    if sim is True and state == "connected":
        assert "simulado" in t and "carro real" not in t
    if state == "vehicle_link_down":
        assert "interrompida" in t


def test_status_fallback_when_the_status_tool_itself_failed():
    b = bundle(telemetry_outcome(ok=False, error_code="octave_unavailable", name="get_vehicle_status"))
    t = render_fallback(b)
    assert "Não consegui consultar" in t and verify(ans(t), b).passed
