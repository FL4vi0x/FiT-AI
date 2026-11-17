import math

import pytest

from fit_ai.adapters.octave import _check_coolant_unit, _number, _speed_factor
from fit_ai.domain.telemetry import MPH_TO_KMH, ProtocolIncompatible, ProviderError, mph_to_kmh


@pytest.mark.parametrize(
    "mph, kmh",
    [(0, 0.0), (1, 1.609344), (60, 96.56064), (62.1371192237334, 100.0)],
)
def test_mph_to_kmh(mph, kmh):
    assert mph_to_kmh(mph) == pytest.approx(kmh, rel=1e-6, abs=1e-6)


def test_factor_constant_is_exact_international_mile():
    assert MPH_TO_KMH == 1.609344


@pytest.mark.parametrize("unit, factor", [("MPH", MPH_TO_KMH), ("mph", MPH_TO_KMH), ("km/h", 1.0), ("KPH", 1.0)])
def test_speed_factor_from_catalog_unit(unit, factor):
    assert _speed_factor(unit) == factor


@pytest.mark.parametrize("unit", [None, "", "knots", "m/s"])
def test_unknown_speed_unit_is_refused_not_guessed(unit):
    with pytest.raises(ProtocolIncompatible):
        _speed_factor(unit)


def test_coolant_unit_celsius_only():
    _check_coolant_unit("°C")
    _check_coolant_unit("C")
    for bad in (None, "", "°F", "K"):
        with pytest.raises(ProtocolIncompatible):
            _check_coolant_unit(bad)


def test_number_rules():
    assert _number(None, "x") is None
    assert _number(5, "x") == 5.0
    assert _number(49.1, "x") == 49.1
    assert _number(math.nan, "x") is None
    assert _number(math.inf, "x") is None
    for bad in ("800", True, [1], {"v": 1}):
        with pytest.raises(ProviderError):
            _number(bad, "x")
