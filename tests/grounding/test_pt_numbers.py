"""Portuguese number/unit extraction: digits, number words, Brazilian separators, units and context."""
import pytest

from fit_ai.grounding.numbers import extract_mentions, matches, normalise


def one(text):
    ms = extract_mentions(text)
    assert len(ms) == 1, [(m.value, m.text) for m in ms]
    return ms[0]


@pytest.mark.parametrize("text,value,unit,field", [
    ("O motor está a 800 RPM.", 800, "rpm", "rpm"),
    ("Rotação: 1.200 rpm", 1200, "rpm", "rpm"),
    ("rotação de 1200 rotações por minuto", 1200, "rpm", "rpm"),
    ("Velocidade de 12,5 km/h", 12.5, "kmh", "speed_kmh"),
    ("a 60 quilômetros por hora", 60, "kmh", "speed_kmh"),
    ("a 60 km por hora", 60, "kmh", "speed_kmh"),
    ("Temperatura 90°C", 90, "celsius", "coolant_temp_c"),
    ("90 ºC", 90, "celsius", "coolant_temp_c"),
    ("90 graus Celsius", 90, "celsius", "coolant_temp_c"),
    ("90 graus", 90, "celsius", "coolant_temp_c"),
    ("194 °F", 194, "fahrenheit", "coolant_temp_c"),
    ("75 mph", 75, "mph", "speed_kmh"),
    ("5 mil rpm", 5000, "rpm", "rpm"),
    ("1,2 mil rpm", 1200, "rpm", "rpm"),
    ("zero km/h", 0, "kmh", "speed_kmh"),
    ("a temperatura é de 88,5", 88.5, None, "coolant_temp_c"),  # unit-less: noun gives the field
    ("a rotação está em 3000", 3000, None, "rpm"),
])
def test_digit_mentions(text, value, unit, field):
    m = one(text)
    assert (m.value, m.unit, m.field) == (value, unit, field)


@pytest.mark.parametrize("text,value", [
    ("oitocentas rotações", 800), ("oitocentos rpm", 800), ("mil rpm", 1000), ("mil e duzentos rpm", 1200),
    ("dois mil e quinhentos rpm", 2500), ("cento e vinte km/h", 120), ("cem km/h", 100), ("vinte e dois graus", 22),
    ("noventa graus", 90), ("quinze km/h", 15), ("dezenove km/h", 19), ("trezentas rotações", 300),
    ("novecentos e noventa e nove rpm", 999), ("zero rpm", 0), ("duas mil rotações", 2000), ("seis mil rpm", 6000),
])
def test_number_words(text, value):
    assert one(text).value == value


def test_malformed_word_runs_fail_closed_as_separate_numbers():
    ms = extract_mentions("dois três rpm")  # not one number: two numbers, each gets checked later
    assert [m.value for m in ms] == [2, 3]


def test_article_um_is_not_a_number_but_um_with_a_unit_is():
    assert extract_mentions("uma rotação estável") == []
    assert extract_mentions("um motor bom") == []
    assert one("um quilômetro por hora").value == 1


@pytest.mark.parametrize("text,kind", [
    ("em 2 segundos", "benign"), ("há 3 minutos", "benign"), ("são 3 sensores", "benign"),
    ("2 leituras", "benign"), ("Honda Fit 2005", "year"), ("o Fit LX 2005", "year"),
])
def test_non_telemetry_numbers_are_recognised(text, kind):
    m = one(text)
    assert (m.benign if kind == "benign" else m.year_like) and m.field is None


def test_year_exemption_does_not_cover_a_bare_number():
    assert not one("Está em 2005.").year_like  # without a vehicle marker it is just a number
    ms = extract_mentions("O Fit 2005 está a 2000 rpm")
    assert [(m.value, m.year_like, m.field) for m in ms] == [(2005, True, None), (2000, False, "rpm")]


@pytest.mark.parametrize("text,unit", [("32 psi", "psi"), ("2 litros", "litros"), ("45 %", "porcento"),
                                       ("12 volts", "volts"), ("120 km", "km"), ("3 bar", "bar")])
def test_unsupported_units_are_flagged(text, unit):
    m = one(text)
    assert m.unsupported_unit == unit and m.field is None


def test_range_gives_each_number_the_shared_unit():
    ms = extract_mentions("entre 700 e 900 rpm")
    assert [(m.value, m.field) for m in ms] == [(700, "rpm"), (900, "rpm")]


def test_negative_numbers_and_ranges_with_a_hyphen():
    assert one("temperatura de -5 °C").value == -5
    assert [m.value for m in extract_mentions("700-900 rpm")] == [700, 900]  # a hyphen between digits is not a sign


def test_sentence_boundaries_stop_noun_association():
    ms = extract_mentions("A temperatura está estável. Depois contei 90 vezes.")
    assert ms[0].benign and ms[0].field is None  # "temperatura" is in the previous sentence and "vezes" is benign


def test_but_clause_stops_association():
    m = extract_mentions("A velocidade é alta, mas a conta deu 77")[-1]
    assert m.field is None  # "mas" starts a new clause: no noun in reach


@pytest.mark.parametrize("v,dec,obs,field,unit,ok", [
    (800, 0, 800.0, "rpm", None, True), (801, 0, 800.0, "rpm", None, False), (800, 1, 800.0, "rpm", None, True),
    (12, 0, 12.3, "speed_kmh", None, True),     # rounding to the displayed precision
    (13, 0, 12.5, "speed_kmh", None, True),     # half up
    (12, 0, 12.5, "speed_kmh", None, False),
    (12.3, 1, 12.3, "speed_kmh", None, True), (12.4, 1, 12.3, "speed_kmh", None, False),
    (90, 0, 90.0, "coolant_temp_c", "celsius", True), (91, 0, 90.0, "coolant_temp_c", "celsius", False),
    (194, 0, 90.0, "coolant_temp_c", "fahrenheit", True),   # 90 °C = 194 °F
    (195, 0, 90.0, "coolant_temp_c", "fahrenheit", False),
    (62, 0, 100.0, "speed_kmh", "mph", True),               # 100 km/h = 62.1 mph
    (63, 0, 100.0, "speed_kmh", "mph", False),
    (0, 0, 0.0, "speed_kmh", None, True), (1, 0, 0.0, "speed_kmh", None, False),
])
def test_matches_rules(v, dec, obs, field, unit, ok):
    assert matches(v, dec, obs, field, unit) is ok


def test_normalise_handles_accents_symbols_and_case():
    assert normalise("Rotação 90°C a 60 KM/H") == "rotacao 90 celsius  a 60  kmh "
