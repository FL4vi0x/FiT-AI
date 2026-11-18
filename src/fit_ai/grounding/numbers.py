"""Deterministic analysis of Brazilian-Portuguese answer text: which numbers does it state and about what?

This module only EXTRACTS and CLASSIFIES; deciding whether a statement is allowed is the verifier's job.

Documented limits (the verifier is fail-closed because of them):
- Numbers: digits ("800", "1.200", "1,5", "5 mil") and Portuguese number words up to the thousands
  ("oitocentas", "dois mil e quinhentos"). Fractions ("meio"), ordinals, Roman numerals, scientific notation,
  dates and clock times are NOT understood: any such digits are simply reported as unattached numbers.
- "1.500" is read the Brazilian way (thousand separator = 1500); "1.5" and "1,5" are decimals.
- A bare "um"/"uma" is an article, not a number, unless a telemetry unit follows it.
- "graus" without a scale is read as Celsius.
- Unit/noun association is positional (a unit within 4 tokens after the number, a telemetry noun within 6 tokens
  before it, same clause). A sentence can defeat this heuristic; the verifier then still rejects any number
  it cannot tie to evidence, rather than guessing it is harmless.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

MPH_TO_KMH = 1.609344

# ───────────────────────── normalisation ─────────────────────────
_SYMBOLS = [
    (re.compile(r"[°º]\s*c\b"), " celsius "),
    (re.compile(r"[°º]\s*f\b"), " fahrenheit "),
    (re.compile(r"(?<=\d)\s*[°º]"), " graus "),
    (re.compile(r"\bkm\s*/\s*h\b"), " kmh "),
    (re.compile(r"\bkm\s+por\s+hora\b"), " kmh "),
    (re.compile(r"\bm\s*/\s*s\b"), " ms "),
    (re.compile(r"\br\.p\.m\b\.?"), " rpm "),
    (re.compile(r"\bmi\s*/\s*h\b"), " mph "),
    (re.compile(r"%"), " porcento "),
]


def normalise(text: str) -> str:
    t = text.lower().replace("−", "-").replace("–", "-")
    for rx, rep in _SYMBOLS:
        t = rx.sub(rep, t)
    t = unicodedata.normalize("NFKD", t)
    return "".join(c for c in t if not unicodedata.combining(c))


# ───────────────────────── tokens ─────────────────────────
_TOKEN = re.compile(
    r"(?P<num>\d{1,3}(?:\.\d{3})+(?:,\d+)?(?!\d)|\d+(?:[.,]\d+)?)"
    r"|(?P<word>[a-z]+)"
    r"|(?P<stop>[.!?;\n]+)")
_CLAUSE_WORDS = frozenset({"mas", "porem", "entretanto", "contudo", "todavia"})


@dataclass(frozen=True)
class Tok:
    kind: str  # num | word | stop
    text: str
    start: int
    sentence: int  # clause index: increments on . ! ? ; newline and on "mas/porém/..."


def tokenize(norm: str) -> list[Tok]:
    out: list[Tok] = []
    sent = 0
    for m in _TOKEN.finditer(norm):
        kind = m.lastgroup or "word"
        if kind == "stop":
            sent += 1
            out.append(Tok("stop", m.group(), m.start(), sent))
            continue
        if kind == "word" and m.group() in _CLAUSE_WORDS:
            sent += 1
        out.append(Tok(kind, m.group(), m.start(), sent))
    return out


# ───────────────────────── Portuguese number words ─────────────────────────
_UNITS = {"zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6,
          "sete": 7, "oito": 8, "nove": 9}
_TEENS = {"dez": 10, "onze": 11, "doze": 12, "treze": 13, "catorze": 14, "quatorze": 14, "quinze": 15,
          "dezesseis": 16, "dezeseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19}
_TENS = {"vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60, "setenta": 70,
         "oitenta": 80, "noventa": 90}
_HUNDREDS = {"cem": 100, "cento": 100, "duzentos": 200, "duzentas": 200, "trezentos": 300, "trezentas": 300,
             "quatrocentos": 400, "quatrocentas": 400, "quinhentos": 500, "quinhentas": 500, "seiscentos": 600,
             "seiscentas": 600, "setecentos": 700, "setecentas": 700, "oitocentos": 800, "oitocentas": 800,
             "novecentos": 900, "novecentas": 900}
NUMBER_WORDS = {**_UNITS, **_TEENS, **_TENS, **_HUNDREDS, "mil": 1000}


def _words_value(words: list[str]) -> int | None:
    """Value of a run of number words, or None when the run is not a well-formed number."""
    total = cur = 0
    last = None
    for w in words:
        v = NUMBER_WORDS[w]
        if w == "mil":
            if last == "mil":
                return None
            total += (cur or 1) * 1000
            cur, last = 0, "mil"
        elif v >= 100:
            if last in ("h", "t", "u", "d"):
                return None
            cur, last = cur + v, "h"
        elif v >= 20:
            if last in ("t", "u", "d"):
                return None
            cur, last = cur + v, "t"
        elif v >= 10:
            if last in ("t", "u", "d"):
                return None
            cur, last = cur + v, "d"
        else:
            if last in ("u", "d") or (v == 0 and len(words) > 1):
                return None
            cur, last = cur + v, "u"
    return total + cur


# ───────────────────────── units and nouns ─────────────────────────
# unit key -> (kind, field). kind: sensor | unsupported | benign
_COMPOUND = [  # (token sequence, unit)
    (("quilometros", "por", "hora"), "kmh"), (("quilometro", "por", "hora"), "kmh"),
    (("km", "por", "hora"), "kmh"), (("milhas", "por", "hora"), "mph"), (("milha", "por", "hora"), "mph"),
    (("rotacoes", "por", "minuto"), "rpm"), (("rotacao", "por", "minuto"), "rpm"),
    (("graus", "celsius"), "celsius"), (("grau", "celsius"), "celsius"),
    (("graus", "fahrenheit"), "fahrenheit"), (("grau", "fahrenheit"), "fahrenheit"),
]
_SINGLE = {"rpm": "rpm", "rotacoes": "rpm", "giros": "rpm",
           "kmh": "kmh", "mph": "mph",
           "celsius": "celsius", "graus": "celsius", "grau": "celsius", "fahrenheit": "fahrenheit"}
UNIT_FIELD = {"rpm": "rpm", "kmh": "speed_kmh", "mph": "speed_kmh", "celsius": "coolant_temp_c",
              "fahrenheit": "coolant_temp_c"}
_UNSUPPORTED = frozenset({
    "psi", "bar", "kpa", "pa", "porcento", "litro", "litros", "l", "ml", "volt", "volts", "v", "ampere", "amperes",
    "km", "quilometro", "quilometros", "metro", "metros", "m", "ms", "kg", "nm", "cv", "hp", "watts", "ohms",
    "milha", "milhas", "galoes", "galao", "kwh"})
_BENIGN = frozenset({
    "segundo", "segundos", "s", "minuto", "minutos", "hora", "horas", "dia", "dias", "semana", "semanas", "mes",
    "meses", "ano", "anos", "vez", "vezes", "leitura", "leituras", "sensor", "sensores", "campo", "campos",
    "item", "itens", "valor", "valores", "tentativa", "tentativas", "passo", "passos", "opcao", "opcoes",
    "frase", "frases", "linha", "linhas", "exemplo", "exemplos", "dado", "dados", "parametro", "parametros"})
_CONNECTORS = frozenset({"e", "a", "ate", "ou", "de", "do", "da", "em"})
NOUN_FIELD = {"rpm": "rpm", "rotacao": "rpm", "rotacoes": "rpm", "giro": "rpm", "giros": "rpm",
              "velocidade": "speed_kmh", "temperatura": "coolant_temp_c", "arrefecimento": "coolant_temp_c"}
_YEAR_MARKERS = frozenset({"fit", "lx", "ano", "modelo", "honda"})
_NEGATORS = frozenset({"nao", "nunca", "jamais", "nem", "sem"})


@dataclass(frozen=True)
class Mention:
    """A number stated in the text."""

    value: float
    decimals: int
    sentence: int
    index: int  # token index
    text: str
    unit: str | None  # rpm|kmh|mph|celsius|fahrenheit (sensor) | None
    field: str | None  # sensor field the number is about (from its unit or a nearby noun), or None
    unsupported_unit: str | None = None  # e.g. "psi", "litros": a measurement we have no sensor for
    benign: bool = False  # followed by a time/count unit ("2 segundos", "3 sensores")
    year_like: bool = False
    negated: bool = False  # "nao"/"nunca"/... within 3 tokens before: the text denies this value


def _digit_value(tok: str) -> tuple[float, int]:
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", tok):  # Brazilian thousands: 1.200 / 1.200,5
        tok = tok.replace(".", "")
    tok = tok.replace(",", ".")
    dec = len(tok.split(".")[1]) if "." in tok else 0
    return float(tok), dec


def _find_unit(toks: list[Tok], i: int) -> tuple[str | None, str | None, bool]:
    """(sensor unit, unsupported unit word, benign) for the first unit within 4 tokens after index i."""
    steps = 0
    j = i
    while j < len(toks) and steps < 5:
        t = toks[j]
        if t.kind == "stop":
            break
        if t.kind == "num" or (t.kind == "word" and t.text in NUMBER_WORDS):
            j += 1
            steps += 1
            continue
        if t.kind == "word":
            words = tuple(x.text for x in toks[j:j + 3] if x.kind == "word")
            for seq, unit in _COMPOUND:
                if words[:len(seq)] == seq:
                    return unit, None, False
            if t.text in _SINGLE:
                return _SINGLE[t.text], None, False
            if t.text in _UNSUPPORTED:
                return None, t.text, False
            if t.text in _BENIGN:
                return None, None, True
            if t.text in _CONNECTORS:
                j += 1
                steps += 1
                continue
        break
    return None, None, False


def _noun_field(toks: list[Tok], i: int) -> str | None:
    """Telemetry noun within 6 tokens BEFORE index i, same clause."""
    sent = toks[i].sentence
    for k in range(i - 1, max(-1, i - 7), -1):
        t = toks[k]
        if t.sentence != sent or t.kind == "stop":
            break
        if t.kind == "word" and t.text in NOUN_FIELD:
            return NOUN_FIELD[t.text]
    return None


def extract_mentions(text: str) -> list[Mention]:
    norm = normalise(text)
    toks = tokenize(norm)
    out: list[Mention] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.kind == "num":
            value, dec = _digit_value(t.text)
            neg = t.start >= 1 and norm[t.start - 1] == "-" and (t.start == 1 or norm[t.start - 2] in " (\n")
            if neg:
                value = -value
            end = i + 1
            if end < len(toks) and toks[end].kind == "word" and toks[end].text == "mil":
                value, dec, end = value * 1000, max(0, dec - 3), end + 1
            out.append(_make(toks, i, end, value, dec, t.text, norm))
            i = end
            continue
        if t.kind == "word" and t.text in NUMBER_WORDS:
            run, j = [t.text], i + 1
            while j < len(toks):
                nxt = toks[j]
                if nxt.kind == "word" and nxt.text in NUMBER_WORDS:
                    run.append(nxt.text)
                    j += 1
                elif (nxt.kind == "word" and nxt.text == "e" and j + 1 < len(toks)
                      and toks[j + 1].kind == "word" and toks[j + 1].text in NUMBER_WORDS):
                    j += 1  # "e" joins number words ("vinte e dois"); it is not part of the value
                else:
                    break
            val = _words_value(run)
            if val is not None:
                parts = [(run, i, j)]
            else:  # not a well-formed number: every word counts as its own number (fail-closed)
                parts = [([w], i + n, i + n + 1) for n, w in enumerate(w for w in run)]
            for words, a, b in parts:
                v = _words_value(words)
                if v is None:
                    continue
                if words in (["um"], ["uma"]):
                    unit, _, _ = _find_unit(toks, b)
                    if unit is None:
                        continue  # an article
                out.append(_make(toks, a, b, float(v), 0, " ".join(words), norm))
            i = j
            continue
        i += 1
    return out


def _make(toks: list[Tok], a: int, b: int, value: float, dec: int, text: str, norm: str) -> Mention:
    unit, unsupported, benign = _find_unit(toks, b)
    field = UNIT_FIELD.get(unit) if unit else None
    if field is None and unsupported is None and not benign:
        field = _noun_field(toks, a)
    prev = [x.text for x in toks[max(0, a - 2):a] if x.kind == "word"]
    year = (field is None and unit is None and unsupported is None and not benign and value == int(value)
            and 1980 <= value <= 2040 and any(p in _YEAR_MARKERS for p in prev))
    neg = any(x.kind == "word" and x.text in _NEGATORS and x.sentence == toks[a].sentence
              for x in toks[max(0, a - 3):a])
    return Mention(value=value, decimals=dec, sentence=toks[a].sentence, index=a, text=text, unit=unit, field=field,
                   unsupported_unit=unsupported, benign=benign, year_like=year, negated=neg)


# ───────────────────────── value comparison ─────────────────────────
def to_unit(value_in_canonical: float, field: str, unit: str | None) -> float:
    """Express a canonical-unit value (rpm, km/h, °C) in the unit the text used."""
    if unit == "mph":
        return value_in_canonical / MPH_TO_KMH
    if unit == "fahrenheit":
        return value_in_canonical * 9 / 5 + 32
    return value_in_canonical


def matches(mention_value: float, decimals: int, observed: float, field: str, unit: str | None) -> bool:
    """True when the text value equals the observed one, expressed in the text's unit and rounded (half up)
    to the precision the text displays. No other tolerance exists: 801 is not 800."""
    expected = to_unit(observed, field, unit)
    q = Decimal(1).scaleb(-decimals)
    shown = Decimal(repr(expected)).quantize(q, rounding=ROUND_HALF_UP)
    return shown == Decimal(repr(mention_value)).quantize(q, rounding=ROUND_HALF_UP)


# ───────────────────────── clause-level lexicons ─────────────────────────
def clauses(text: str) -> list[tuple[int, list[Tok], str]]:
    """The normalised clauses of a text: (clause id, tokens, joined text). Ids match `Mention.sentence`."""
    toks = tokenize(normalise(text))
    by: dict[int, list[Tok]] = {}
    for t in toks:
        if t.kind != "stop":
            by.setdefault(t.sentence, []).append(t)
    return [(sid, ts, " ".join(x.text for x in ts)) for sid, ts in sorted(by.items())]


_STRICT_UNITS = frozenset({"rpm", "kmh", "mph", "celsius", "fahrenheit"})


def orphan_units(text: str) -> list[str]:
    """Strict telemetry units (rpm, km/h, mph, Celsius, Fahrenheit) with NO recognised number within the three
    tokens before them, in the same clause. A unit with an unrecognised number ("five thousand rpm", "DCCC rpm",
    "quinientas rpm") is a measurement claim this module cannot read: the verifier rejects it (fail-closed)."""
    toks = tokenize(normalise(text))
    out: list[str] = []
    for i, t in enumerate(toks):
        if t.kind != "word" or t.text not in _STRICT_UNITS:
            continue
        # a number just before ("800 rpm") or just after ("o RPM é 800") ties the word to a readable number
        near = [x for x in toks[max(0, i - 3):i + 4] if x.sentence == t.sentence]
        if not any(x.kind == "num" or (x.kind == "word" and x.text in NUMBER_WORDS) for x in near):
            out.append(t.text)
    return out

