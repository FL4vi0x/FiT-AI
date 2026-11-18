"""Internal assistant orchestration (tools -> evidence -> LLM -> verification -> fallback -> audit).

No HTTP endpoint lives here: the public chat API is P7.
"""
from fit_ai.orchestration.config import AssistantSettings
from fit_ai.orchestration.intent import Intent, classify
from fit_ai.orchestration.turn import (
    AUDIT_REFUSAL,
    CONTROL_REFUSAL,
    HISTORY_PLACEHOLDER,
    AssistantOrchestrator,
    TurnRequest,
    TurnResult,
)

__all__ = [
    "AUDIT_REFUSAL", "AssistantOrchestrator", "AssistantSettings", "CONTROL_REFUSAL", "HISTORY_PLACEHOLDER",
    "Intent", "TurnRequest", "TurnResult", "classify",
]
