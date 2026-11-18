"""Deletion evidence (isolated tmp databases only, never the user's files).

Method: write a unique canary, prove it is stored AND searchable, delete it, then scan the raw bytes of the
.db, -wal and -shm files for the canary (as written and lower-cased, which is how FTS5 stores tokens).
This proves best-effort removal from the SQLite files. It does NOT prove physical erasure from the storage
medium (SSD wear levelling, filesystem journal, shadow copies, backups, OS caches): see the P6 report.
"""
import uuid
from pathlib import Path

import pytest

from fit_ai.memory import SqliteMemoryStore


def canary() -> str:
    return "CANARIO" + uuid.uuid4().hex[:16].upper()


def raw_bytes(db: Path) -> bytes:
    """Everything SQLite may have left on disk for this database."""
    blob = b""
    for suffix in ("", "-wal", "-shm", "-journal"):
        p = Path(str(db) + suffix)
        if p.exists():
            blob += p.read_bytes()
    return blob


def present(db: Path, word: str) -> bool:
    blob = raw_bytes(db)
    return word.encode() in blob or word.lower().encode() in blob


@pytest.fixture
def db(tmp_path):
    return tmp_path / "canary.db"


def test_sanity_the_scanner_finds_a_stored_canary(db):
    s, c = SqliteMemoryStore(db), canary()
    s.remember_fact(f"fato com {c}")
    assert s.search(c)  # retrievable
    assert present(db, c)  # and visible to the byte scan (the scan is not blind)


def test_deleted_fact_is_gone_from_api_search_and_bytes(db):
    s, c = SqliteMemoryStore(db), canary()
    f = s.remember_fact(f"anotação privada {c}")
    s.remember_fact("outra memória que deve permanecer")
    assert s.search(c) and s.get_fact(f.id)
    s.delete_fact(f.id)
    assert all(x.id != f.id for x in s.list_facts())
    assert s.search(c) == []
    s.close()  # no connection stays open: every operation closes its own
    assert not present(db, c)
    assert s.search("permanecer")  # unrelated data survived


def test_deleted_preference_and_overwritten_value_leave_no_bytes(db):
    s, c1, c2 = SqliteMemoryStore(db), canary(), canary()
    s.set_preference("apelido", f"valor antigo {c1}")
    s.set_preference("apelido", f"valor novo {c2}")  # overwrite = deletion of the old value
    s.close()
    assert not present(db, c1) and present(db, c2)
    s.delete_preference("apelido")
    s.close()
    assert not present(db, c2)


def test_deleted_conversation_removes_turns_and_index(db):
    s, c = SqliteMemoryStore(db), canary()
    conv = s.create_conversation(f"titulo {c}")
    s.add_turn(conv.id, "user", f"mensagem com {c}")
    s.add_turn(conv.id, "assistant", "resposta qualquer")
    assert s.search(c, kinds=("turn",), conversation_id=conv.id)
    s.delete_conversation(conv.id)
    assert s.search(c, kinds=("turn",), conversation_id=conv.id) == []
    s.close()
    assert not present(db, c.replace("CANARIO", "CANARIO"))  # turn text
    # NOTE the conversation TITLE was in the canary too and is removed with the row
    assert s.list_conversations() == []


def test_delete_all_then_compact_leaves_no_canary(db):
    s = SqliteMemoryStore(db)
    cs = [canary() for _ in range(5)]
    conv = s.create_conversation()
    for i, c in enumerate(cs):
        s.remember_fact(f"fato {i} {c}")
        s.set_preference(f"chave{i}", f"valor {c}")
        s.add_turn(conv.id, "user", f"turno {c}")
    assert all(s.search(c) or s.search(c, kinds=("turn",), conversation_id=conv.id) for c in cs)
    s.delete_all()
    s.close()
    assert s.list_facts() == [] and s.list_preferences() == [] and s.list_conversations() == []
    assert all(not present(db, c) for c in cs)


def test_expired_purge_removes_bytes(db):
    from datetime import UTC, datetime, timedelta
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    s, c = SqliteMemoryStore(db, clock=lambda: now[0]), canary()
    s.remember_fact(f"temporário {c}", ttl_days=1)
    now[0] += timedelta(days=2)
    assert s.search(c) == []  # hidden by expiry even before the purge...
    assert s.purge_expired() == 1
    s.close()
    assert not present(db, c)  # ...and physically removed by it


def test_wal_is_truncated_after_maintenance(db):
    s, c = SqliteMemoryStore(db), canary()
    f = s.remember_fact(f"no wal {c}")
    s.delete_fact(f.id)
    wal = Path(str(db) + "-wal")
    assert (not wal.exists()) or wal.stat().st_size == 0
