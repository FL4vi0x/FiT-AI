"""Production wiring of the chat: telemetry service + memory + audit + Ollama + orchestrator -> ConversationService.

Everything that can fail at start-up (settings, unwritable data directory) makes chat UNAVAILABLE instead of
raising: the Core must keep serving telemetry. Ollama being switched off is not a start-up error at all (the
provider connects on first use).
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fit_ai.ai import LLMSettings, OllamaProvider
from fit_ai.audit import AuditWriteError, SqliteAuditLog
from fit_ai.config import ConfigError
from fit_ai.conversation.config import ChatSettings
from fit_ai.conversation.service import ConversationService
from fit_ai.memory import MemoryStorageError, SqliteMemoryStore
from fit_ai.orchestration import AssistantOrchestrator, AssistantSettings
from fit_ai.services.telemetry import TelemetryService
from fit_ai.tools import build_vehicle_registry

log = logging.getLogger("fit_ai.conversation")


@dataclass
class ChatRuntime:
    service: ConversationService
    close: Callable[[], Awaitable[None]]


def build_chat_runtime(telemetry: TelemetryService, chat_settings: ChatSettings, *,
                       assistant_settings: AssistantSettings | None = None,
                       llm_settings: LLMSettings | None = None) -> ChatRuntime | None:
    """None (chat disabled, logged) when anything needed cannot be set up."""
    try:
        assistant = assistant_settings or AssistantSettings.from_env()
        llm_cfg = llm_settings or LLMSettings.from_env()
        memory = SqliteMemoryStore(assistant.memory_db, turn_retention_days=assistant.turn_retention_days)
        audit = SqliteAuditLog(assistant.audit_db, retention_days=assistant.audit_retention_days)
        llm = OllamaProvider(llm_cfg)
    except (ConfigError, MemoryStorageError, AuditWriteError, OSError) as exc:
        log.error("chat disabled: %s: %s", type(exc).__name__, exc if isinstance(exc, ConfigError) else "setup failed")
        return None
    try:  # housekeeping, never fatal
        memory.purge_expired()
        audit.purge_expired()
    except (MemoryStorageError, AuditWriteError):
        log.exception("start-up retention purge failed")
    orchestrator = AssistantOrchestrator(build_vehicle_registry(telemetry, memory), llm, audit=audit, memory=memory,
                                         settings=assistant)
    service = ConversationService(orchestrator, memory, settings=chat_settings, model_name=llm_cfg.model)

    async def close() -> None:
        await llm.aclose()
        memory.close()
        audit.close()

    return ChatRuntime(service, close)
