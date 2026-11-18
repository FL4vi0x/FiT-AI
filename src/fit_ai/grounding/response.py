"""The structured answer contract between the LLM and the verifier."""
from __future__ import annotations

import json
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from fit_ai.grounding.evidence import SENSOR_FIELDS

MAX_ANSWER_CHARS = 800


class ResponseFormatError(Exception):
    """The model output is not a valid StructuredAnswer. `code` is stable (used in retry hints and metrics)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field: Literal["rpm", "speed_kmh", "coolant_temp_c"]  # no other telemetry field exists
    value: float
    unit: str = Field(min_length=1, max_length=12)

    @field_validator("value")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("value must be finite")
        return v


class StructuredAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    answer: str = Field(min_length=1, max_length=MAX_ANSWER_CHARS)
    claims: list[Claim] = Field(default_factory=list, max_length=6)
    unknown: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("answer")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("answer must not be blank")
        return v

    @field_validator("unknown")
    @classmethod
    def _short(cls, v: list[str]) -> list[str]:
        if any(len(x) > 40 for x in v):
            raise ValueError("unknown entries must be short names")
        return v


# Hand-written flat schema (the local runtime's grammar-constrained decoding handles flat schemas best).
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "claims": {"type": "array", "items": {
            "type": "object",
            "properties": {"field": {"type": "string", "enum": list(SENSOR_FIELDS)},
                           "value": {"type": "number"}, "unit": {"type": "string"}},
            "required": ["field", "value", "unit"], "additionalProperties": False}},
        "unknown": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "claims", "unknown"],
    "additionalProperties": False,
}


def parse_structured(raw: str) -> StructuredAnswer:
    """Strict parse: JSON object only (no code fences, no prose around it), no unknown keys."""
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError, RecursionError):
        raise ResponseFormatError("invalid_json") from None
    if not isinstance(obj, dict):
        raise ResponseFormatError("not_an_object")
    try:
        return StructuredAnswer.model_validate(obj)
    except ValidationError as exc:
        e = exc.errors()[0]
        kind = "unknown_field" if e["type"] == "extra_forbidden" else "schema_violation"
        where = ".".join(str(p) for p in e["loc"])[:60]
        raise ResponseFormatError(kind, where) from None
