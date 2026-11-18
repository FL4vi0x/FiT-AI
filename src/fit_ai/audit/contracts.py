"""Audit contract."""
from __future__ import annotations

from typing import Protocol

from fit_ai.audit.models import AuditEvent


class AuditWriteError(Exception):
    """An audit record could not be persisted. Never swallowed: the caller applies its audit policy."""


class AuditSink(Protocol):
    def record(self, event: AuditEvent) -> None:
        """Raise AuditWriteError when the event is not durably stored."""
        ...

    def list_events(self, request_id: str | None = None, limit: int = 100) -> list[AuditEvent]: ...
    def purge_expired(self) -> int: ...
    def close(self) -> None: ...
