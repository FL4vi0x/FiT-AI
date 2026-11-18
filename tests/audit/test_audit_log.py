"""Audit log: events, redaction, retention, isolation and failure behaviour."""
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from fit_ai.audit import AuditEvent, AuditWriteError, SqliteAuditLog, redact

T0 = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


def ev(i=1, request_id="r1", **kw):
    base = dict(event_id=f"e{i}", request_id=request_id, timestamp=T0, kind="tool_result", decision="ok",
                tool="get_vehicle_telemetry", permission="READ", summary="rpm=800", duration_ms=12, simulated=True)
    base.update(kw)
    return AuditEvent(**base)


def test_event_roundtrip_with_all_required_fields(tmp_path):
    log = SqliteAuditLog(tmp_path / "a.db")
    log.record(ev(1, error_code=None))
    log.record(ev(2, kind="tool_authorization", decision="denied", tool="set_ac", error_code="unknown_tool",
                  simulated=None, duration_ms=None))
    got = log.list_events("r1")
    assert [e.event_id for e in got] == ["e1", "e2"]
    first = got[0]
    assert (first.request_id, first.kind, first.tool, first.permission, first.decision, first.duration_ms,
            first.simulated) == ("r1", "tool_result", "get_vehicle_telemetry", "READ", "ok", 12, True)
    assert first.timestamp == T0  # UTC timestamp preserved
    assert got[1].decision == "denied" and got[1].error_code == "unknown_tool" and got[1].simulated is None


def test_events_are_isolated_by_request(tmp_path):
    log = SqliteAuditLog(tmp_path / "a.db")
    log.record(ev(1, "reqA"))
    log.record(ev(2, "reqB"))
    assert [e.event_id for e in log.list_events("reqA")] == ["e1"]
    assert len(log.list_events()) == 2


@pytest.mark.parametrize("secret", [
    "Bearer abcdef0123456789abcdef", "api_key=sk-live-1234567890abcdef", "password: hunter2",
    "token=ghp_abcdefghijklmnopqrstuvwx", "senha=minhaSenha123", "sk-abcdefghijklmnopqrstuvwx",
    "authorization: Basic dXNlcjpwYXNzd29yZA==",
])
def test_credentials_are_redacted(tmp_path, secret):
    log = SqliteAuditLog(tmp_path / "a.db")
    log.record(ev(1, summary=f"falha ao chamar {secret} fim"))
    stored = log.list_events("r1")[0].summary
    assert "hunter2" not in stored and "minhaSenha123" not in stored and "abcdefghij" not in stored
    assert "[redacted" in stored
    raw = (tmp_path / "a.db").read_bytes() + (tmp_path / "a.db-wal").read_bytes() if (tmp_path / "a.db-wal").exists() \
        else (tmp_path / "a.db").read_bytes()
    assert b"hunter2" not in raw and b"minhaSenha123" not in raw


def test_personal_data_and_paths_are_redacted():
    t = redact("erro em C:\\Users\\Usuario\\Desktop\\x.db contato fulano@exemplo.com tel (11) 91234-5678")
    assert "Usuario" not in t and "fulano@" not in t and "91234" not in t
    assert "C:\\Users\\<user>" in t


def test_summary_is_truncated_and_whitespace_collapsed():
    e = ev(summary="a   b\n\nc " + "x" * 1000)
    assert len(e.summary) <= 240 and "\n" not in e.summary


def test_tool_name_and_error_code_are_sanitised():
    e = ev(tool="x" * 200 + "@mail.com", error_code="Bearer abcdef0123456789abcdef")
    assert len(e.tool) <= 64 and "abcdef0123456789abcdef" not in e.error_code


def test_unknown_fields_and_bad_kinds_are_rejected():
    with pytest.raises(Exception):
        AuditEvent(event_id="e", request_id="r", timestamp=T0, kind="conversation", decision="ok")
    with pytest.raises(Exception):
        AuditEvent(event_id="e", request_id="r", timestamp=T0, kind="turn", decision="ok", prompt="segredo")


def test_retention_purges_old_events(tmp_path):
    now = [T0]
    log = SqliteAuditLog(tmp_path / "a.db", retention_days=30, clock=lambda: now[0])
    log.record(ev(1, timestamp=T0 - timedelta(days=40)))
    log.record(ev(2, timestamp=T0 - timedelta(days=5)))
    assert log.purge_expired() == 1
    assert [e.event_id for e in log.list_events()] == ["e2"]
    now[0] += timedelta(days=60)
    assert log.purge_expired() == 1 and log.list_events() == []
    assert SqliteAuditLog(tmp_path / "b.db", retention_days=None).purge_expired() == 0
    with pytest.raises(ValueError):
        SqliteAuditLog(tmp_path / "c.db", retention_days=0)


def test_duplicate_event_ids_fail_loudly_not_silently(tmp_path):
    log = SqliteAuditLog(tmp_path / "a.db")
    log.record(ev(1))
    with pytest.raises(AuditWriteError):
        log.record(ev(1))


def test_write_failure_is_a_typed_error_without_leaking_internals(tmp_path):
    log = SqliteAuditLog(tmp_path / "a.db")
    con = sqlite3.connect(tmp_path / "a.db")
    con.execute("DROP TABLE audit_events")
    con.commit()
    con.close()
    with pytest.raises(AuditWriteError) as e:
        log.record(ev(1, summary="conteúdo sensível"))
    assert "audit_events" not in str(e.value) and "sensível" not in str(e.value) and str(tmp_path) not in str(e.value)


def test_unwritable_location_fails_at_construction(tmp_path):
    blocker = tmp_path / "f"
    blocker.write_text("x")
    with pytest.raises(AuditWriteError):
        SqliteAuditLog(blocker / "sub" / "a.db")


def test_audit_and_memory_databases_are_independent(tmp_path):
    from fit_ai.memory import SqliteMemoryStore
    mem = SqliteMemoryStore(tmp_path / "memory.db")
    log = SqliteAuditLog(tmp_path / "audit.db")
    mem.remember_fact("algo privado")
    log.record(ev(1))
    mem.delete_all()
    assert len(log.list_events()) == 1  # erasing memory never erases the audit trail
    con = sqlite3.connect(tmp_path / "audit.db")
    assert {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")} == {"audit_events"}
