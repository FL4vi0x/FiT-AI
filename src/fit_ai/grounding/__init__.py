"""Grounding: evidence per turn, strict structured answers, a deterministic verifier and safe fallbacks."""
from fit_ai.grounding.evidence import (
    CANONICAL_UNIT,
    DEFAULT_MAX_AGE_S,
    FIELD_LABEL,
    SENSOR_FIELDS,
    Evidence,
    EvidenceBundle,
    EvidenceError,
    build_evidence,
)
from fit_ai.grounding.fallback import format_number, render_fallback, render_unavailable_info
from fit_ai.grounding.response import (
    RESPONSE_SCHEMA,
    Claim,
    ResponseFormatError,
    StructuredAnswer,
    parse_structured,
)
from fit_ai.grounding.verifier import Verdict, Verifier, Violation, verify

__all__ = [
    "CANONICAL_UNIT", "Claim", "DEFAULT_MAX_AGE_S", "Evidence", "EvidenceBundle", "EvidenceError", "FIELD_LABEL",
    "RESPONSE_SCHEMA", "ResponseFormatError", "SENSOR_FIELDS", "StructuredAnswer", "Verdict", "Verifier",
    "Violation", "build_evidence", "format_number", "parse_structured", "render_fallback",
    "render_unavailable_info", "verify",
]
