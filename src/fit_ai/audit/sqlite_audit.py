"""Local SQLite audit log. A separate database file from user memory, so deleting memory never erases
the audit trail (and the audit trail never holds conversation text)."""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fit_ai.audit.contracts import AuditWriteError
from fit_ai.audit.models import AuditEvent

log = logging.getLogger("fit_ai.audit")
_TS = "%Y-%m-%dT%H:%M:%S.%fZ"


def _fmt(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime(_TS)


def _parse(s: str) -> datetime:
    return datetime.strptime(s, _TS).replace(tzinfo=UTC)


class SqliteAuditLog:
    def __init__(self, path: str | Path, *, retention_days: float | None = 90,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        if retention_days is not None and retention_days <= 0:
            raise ValueError("retention_days must be positive or None")
        self.path = Path(path)
        self._retention = retention_days
        self._clock = clock
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            con = self._connect()
            try:
                con.executescript("""
                    CREATE TABLE IF NOT EXISTS audit_events(
                        event_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, turn_id TEXT, ts TEXT NOT NULL,
                        kind TEXT NOT NULL, tool TEXT, permission TEXT, decision TEXT NOT NULL, summary TEXT NOT NULL,
                        duration_ms INTEGER, error_code TEXT, simulated INTEGER);
                    CREATE INDEX IF NOT EXISTS audit_req ON audit_events(request_id, ts);
                    CREATE INDEX IF NOT EXISTS audit_ts ON audit_events(ts);
                """)
            finally:
                con.close()
        except (sqlite3.Error, OSError) as exc:
            raise AuditWriteError(f"cannot initialise the audit database: {type(exc).__name__}") from None

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=5000")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA secure_delete=ON")
        return con

    def record(self, event: AuditEvent) -> None:
        try:
            con = self._connect()
            try:
                con.execute(
                    "INSERT INTO audit_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (event.event_id, event.request_id, event.turn_id, _fmt(event.timestamp), event.kind, event.tool,
                     event.permission, event.decision, event.summary, event.duration_ms, event.error_code,
                     None if event.simulated is None else int(event.simulated)))
            finally:
                con.close()
        except (sqlite3.Error, OSError) as exc:
            # the message carries the exception TYPE only: SQL text or paths must not leak into error output
            log.error("audit write failed: %s", type(exc).__name__)
            raise AuditWriteError(f"audit write failed: {type(exc).__name__}") from None

    def list_events(self, request_id: str | None = None, limit: int = 100) -> list[AuditEvent]:
        try:
            con = self._connect()
            try:
                if request_id is None:
                    rows = con.execute("SELECT * FROM audit_events ORDER BY ts, rowid LIMIT ?",
                                       (max(1, min(limit, 1000)),)).fetchall()
                else:
                    rows = con.execute("SELECT * FROM audit_events WHERE request_id=? ORDER BY ts, rowid LIMIT ?",
                                       (request_id, max(1, min(limit, 1000)))).fetchall()
            finally:
                con.close()
        except (sqlite3.Error, OSError) as exc:
            raise AuditWriteError(f"audit read failed: {type(exc).__name__}") from None
        return [AuditEvent(event_id=r["event_id"], request_id=r["request_id"], turn_id=r["turn_id"],
                           timestamp=_parse(r["ts"]), kind=r["kind"], tool=r["tool"], permission=r["permission"],
                           decision=r["decision"], summary=r["summary"], duration_ms=r["duration_ms"],
                           error_code=r["error_code"],
                           simulated=None if r["simulated"] is None else bool(r["simulated"])) for r in rows]

    def purge_expired(self) -> int:
        if self._retention is None:
            return 0
        cutoff = _fmt(self._clock() - timedelta(days=self._retention))
        try:
            con = self._connect()
            try:
                n = con.execute("DELETE FROM audit_events WHERE ts<?", (cutoff,)).rowcount
                if n:
                    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                con.close()
        except (sqlite3.Error, OSError) as exc:
            raise AuditWriteError(f"audit purge failed: {type(exc).__name__}") from None
        return n

    def close(self) -> None:
        """Connections are per operation; nothing is held open."""
