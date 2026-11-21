"""Conversation errors. Independent of HTTP: each has a stable machine-readable `code` and a SAFE message
(no prompts, paths, stack traces, SQL or model internals). The HTTP layer maps `code` to a status."""
from __future__ import annotations


class ConversationError(Exception):
    code = "conversation_error"
    safe_message = "The conversation could not be processed."

    def __init__(self, message: str | None = None):
        super().__init__(message or self.safe_message)
        self.safe_message = message or type(self).safe_message


class InvalidMessage(ConversationError):
    code = "invalid_message"
    safe_message = "The message is not acceptable."


class InvalidConversationId(ConversationError):
    code = "invalid_conversation_id"
    safe_message = "conversation_id is not a valid conversation identifier."


class InvalidIdempotencyKey(ConversationError):
    code = "invalid_idempotency_key"
    safe_message = "Idempotency-Key must be 8-64 characters: letters, digits, '-' or '_'."


class ConversationNotFound(ConversationError):
    code = "conversation_not_found"
    safe_message = "There is no conversation with this identifier."


class IdempotencyConflict(ConversationError):
    code = "idempotency_key_reuse"
    safe_message = "This Idempotency-Key was already used for a different request."


class RequestInProgress(ConversationError):
    code = "request_in_progress"
    safe_message = "A request with this Idempotency-Key is still being processed."


class ServiceBusy(ConversationError):
    """All generation slots are taken and the waiting room is full (or the wait ran out)."""

    code = "service_busy"
    safe_message = "The assistant is busy with another request. Try again shortly."

    def __init__(self, message: str | None = None, retry_after_s: int = 10):
        super().__init__(message)
        self.retry_after_s = retry_after_s


class RequestTimeout(ConversationError):
    code = "request_timeout"
    safe_message = "The assistant did not finish within the time limit."


class ModelUnavailable(ConversationError):
    """The language model could not answer and there is no data the assistant can answer from without it."""

    code = "model_unavailable"
    safe_message = "The language model is not available right now."

    def __init__(self, kind: str = "unavailable"):
        # kind: unavailable | timeout | not_found | error  (no provider text is ever carried)
        self.kind = kind
        self.code = {"timeout": "model_timeout", "not_found": "model_not_found"}.get(kind, "model_unavailable")
        super().__init__({"timeout": "The language model did not answer in time.",
                          "not_found": "The configured language model is not installed."}.get(kind))


class AuditUnavailable(ConversationError):
    code = "audit_unavailable"
    safe_message = "The audit log is unavailable, so the request was not processed."


class StorageUnavailable(ConversationError):
    code = "storage_unavailable"
    safe_message = "The conversation store is unavailable. Nothing was saved; the request can be retried."


class ChatUnavailable(ConversationError):
    code = "chat_unavailable"
    safe_message = "The chat service is not available (it is not configured or failed to start)."
