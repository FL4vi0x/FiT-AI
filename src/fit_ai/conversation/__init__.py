"""Conversation layer (P7): a verified chat turn, independent of HTTP."""
from fit_ai.conversation.config import ChatSettings
from fit_ai.conversation.errors import (
    AuditUnavailable,
    ChatUnavailable,
    ConversationError,
    ConversationNotFound,
    IdempotencyConflict,
    InvalidConversationId,
    InvalidIdempotencyKey,
    InvalidMessage,
    ModelUnavailable,
    RequestInProgress,
    RequestTimeout,
    ServiceBusy,
    StorageUnavailable,
)
from fit_ai.conversation.models import ChatRequest, ChatResponse
from fit_ai.conversation.service import ConversationService

__all__ = [
    "AuditUnavailable", "ChatRequest", "ChatResponse", "ChatSettings", "ChatUnavailable", "ConversationError",
    "ConversationNotFound", "ConversationService", "IdempotencyConflict", "InvalidConversationId",
    "InvalidIdempotencyKey", "InvalidMessage", "ModelUnavailable", "RequestInProgress", "RequestTimeout",
    "ServiceBusy", "StorageUnavailable",
]
