"""SQLite memory store with FTS5 lexical search, retention and best-effort secure deletion.

Design notes
- One short-lived connection per operation (thread-safe, no shared state), `BEGIN IMMEDIATE` write
  transactions, WAL + busy_timeout for concurrent writers.
- `secure_delete=ON` on every connection, and after every deletion `_scrub()` runs an FTS5 `optimize`
  (rewrites the index so removed terms leave no stale segment) and `wal_checkpoint(TRUNCATE)`.
  `compact()`/`delete_all()` also VACUUM. This is best effort: see docs/poc-03-p6-grounding-memory.md for
  what it cannot guarantee (SSD wear levelling, filesystem journals, backups, copies).
- The FTS table is maintained by hand in the same transaction as its base row (no external-content
  triggers), so a deleted row can never be returned by search.
- If FTS5 is not compiled into SQLite, search falls back to parametrised LIKE queries.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from fit_ai.memory.contracts import MemoryNotFound, MemoryPolicyError, MemoryStorageError
from fit_ai.memory.models import (
    MAX_PREF_KEY_CHARS,
    Conversation,
    ConversationTurn,
    MemoryFact,
    MemoryHit,
    MemoryKind,
    TurnRole,
    UserPreference,
)

log = logging.getLogger("fit_ai.memory")

_TS = "%Y-%m-%dT%H:%M:%S.%fZ"  # fixed width, so string comparison orders correctly
_STOPWORDS = frozenset("a o e é de da do das dos em no na nos nas um uma uns umas que para com por os as se ao à "
                       "ou mas me meu minha eu você voce lembra lembre sobre qual quais".split())
# Output of our own evidence renderer / tool results: never allowed to be saved as a permanent "fact".
_TELEMETRY_RECORD = re.compile(r"\b(?:rpm|speed_kmh|coolant_temp_c)\s*[=:]\s*-?\d", re.I)
MAX_QUERY_TOKENS = 10


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _fmt(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime(_TS)


def _parse(s: str) -> datetime:
    return datetime.strptime(s, _TS).replace(tzinfo=UTC)


def _new_id() -> str:
    return uuid.uuid4().hex


def query_tokens(query: str) -> list[str]:
    """Words of a free-text query, lower-cased, stop-words removed, at most MAX_QUERY_TOKENS. Anything that is
    not a letter/digit (quotes, operators, `col:` filters, `*`, `--`) is discarded, so no FTS5 syntax or SQL
    can be smuggled through the query."""
    words = re.findall(r"\w+", query.lower())
    kept = [w for w in words if w not in _STOPWORDS and len(w) >= 2]
    return list(dict.fromkeys(kept))[:MAX_QUERY_TOKENS]


def fts_match_expression(tokens: Sequence[str]) -> str:
    parts = []
    for t in tokens:
        q = '"' + t.replace('"', '""') + '"'
        parts.append(q + "*" if len(t) >= 4 else q)  # prefix match tolerates plurals / conjugations
    return " OR ".join(parts)


def _like_escape(token: str) -> str:
    return token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class SqliteMemoryStore:
    def __init__(
        self,
        path: str | Path,
        *,
        turn_retention_days: float | None = 30,
        max_turns_per_conversation: int = 200,
        use_fts: bool = True,
        clock: Callable[[], datetime] = _utcnow,
    ):
        if turn_retention_days is not None and turn_retention_days <= 0:
            raise ValueError("turn_retention_days must be positive or None")
        if max_turns_per_conversation < 2:
            raise ValueError("max_turns_per_conversation must be >= 2")
        self.path = Path(path)
        self._retention = turn_retention_days
        self._max_turns = max_turns_per_conversation
        self._clock = clock
        self.fts_enabled = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema(use_fts)

    # ───────────────────────── infrastructure ─────────────────────────
    def _connect(self) -> sqlite3.Connection:
        try:
            con = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA busy_timeout=5000")
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=NORMAL")
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("PRAGMA secure_delete=ON")
            return con
        except sqlite3.Error as exc:
            raise MemoryStorageError(f"cannot open the memory database: {exc}") from None

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                yield con
            except BaseException:
                con.execute("ROLLBACK")
                raise
            con.execute("COMMIT")
        except sqlite3.Error as exc:
            raise MemoryStorageError(f"memory database error: {exc}") from None
        finally:
            con.close()

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        con = self._connect()
        try:
            yield con
        except sqlite3.Error as exc:
            raise MemoryStorageError(f"memory database error: {exc}") from None
        finally:
            con.close()

    def _init_schema(self, want_fts: bool) -> None:
        con = self._connect()
        try:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS conversations(
                    id TEXT PRIMARY KEY, title TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS turns(
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                    content TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT);
                CREATE INDEX IF NOT EXISTS turns_conv ON turns(conversation_id, created_at);
                CREATE TABLE IF NOT EXISTS facts(
                    id TEXT PRIMARY KEY, content TEXT NOT NULL, origin TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT);
                CREATE TABLE IF NOT EXISTS preferences(
                    id TEXT PRIMARY KEY, key TEXT NOT NULL UNIQUE, value TEXT NOT NULL, origin TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            """)
            exists = con.execute("SELECT 1 FROM sqlite_master WHERE name='memory_fts'").fetchone() is not None
            if want_fts and not exists:
                try:
                    con.execute("CREATE VIRTUAL TABLE memory_fts USING fts5("
                                "content, kind UNINDEXED, ref_id UNINDEXED, conv UNINDEXED, "
                                "tokenize='unicode61 remove_diacritics 2')")
                    exists = True
                except sqlite3.OperationalError as exc:
                    log.warning("FTS5 unavailable, memory search falls back to LIKE: %s", exc)
            self.fts_enabled = want_fts and exists
        except sqlite3.Error as exc:
            raise MemoryStorageError(f"cannot initialise the memory database: {exc}") from None
        finally:
            con.close()

    def _now(self) -> datetime:
        return self._clock()

    # FTS maintenance (always inside the caller's transaction) --------------------------------------
    def _fts_put(self, con: sqlite3.Connection, kind: str, ref_id: str, content: str, conv: str | None = None) -> None:
        if self.fts_enabled:
            con.execute("INSERT INTO memory_fts(content, kind, ref_id, conv) VALUES (?,?,?,?)",
                        (content, kind, ref_id, conv or ""))

    def _fts_drop(self, con: sqlite3.Connection, kind: str, ref_id: str) -> None:
        if self.fts_enabled:
            con.execute("DELETE FROM memory_fts WHERE kind=? AND ref_id=?", (kind, ref_id))

    # ───────────────────────── conversations ─────────────────────────
    def create_conversation(self, title: str | None = None) -> Conversation:
        if title is not None and len(title) > 200:
            raise MemoryPolicyError("title too long")
        now = self._now()
        c = Conversation(id=_new_id(), title=title, created_at=now, updated_at=now)
        with self._tx() as con:
            con.execute("INSERT INTO conversations VALUES (?,?,?,?)", (c.id, title, _fmt(now), _fmt(now)))
        return c

    def get_conversation(self, conversation_id: str) -> Conversation:
        with self._read() as con:
            r = con.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if r is None:
            raise MemoryNotFound("conversation not found")
        return Conversation(id=r["id"], title=r["title"], created_at=_parse(r["created_at"]),
                            updated_at=_parse(r["updated_at"]))

    def list_conversations(self, limit: int = 50) -> list[Conversation]:
        with self._read() as con:
            rows = con.execute("SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?",
                               (max(1, min(limit, 500)),)).fetchall()
        return [Conversation(id=r["id"], title=r["title"], created_at=_parse(r["created_at"]),
                             updated_at=_parse(r["updated_at"])) for r in rows]

    def add_turn(self, conversation_id: str, role: TurnRole, content: str) -> ConversationTurn:
        now = self._now()
        expires = now + timedelta(days=self._retention) if self._retention else None
        try:
            t = ConversationTurn(id=_new_id(), conversation_id=conversation_id, role=role, content=content,
                                 created_at=now, expires_at=expires)
        except ValidationError as exc:
            raise MemoryPolicyError(f"invalid turn: {exc.errors()[0]['msg']}") from None
        if "\x00" in content:
            raise MemoryPolicyError("content must not contain NUL characters")
        dropped = 0
        with self._tx() as con:
            if con.execute("SELECT 1 FROM conversations WHERE id=?", (conversation_id,)).fetchone() is None:
                raise MemoryNotFound("conversation not found")
            con.execute("INSERT INTO turns VALUES (?,?,?,?,?,?)",
                        (t.id, conversation_id, role, content, _fmt(now), _fmt(expires) if expires else None))
            self._fts_put(con, "turn", t.id, content, conversation_id)
            con.execute("UPDATE conversations SET updated_at=? WHERE id=?", (_fmt(now), conversation_id))
            dropped = self._trim_conversation(con, conversation_id)
        if dropped:
            self._scrub()
        return t

    def _trim_conversation(self, con: sqlite3.Connection, conversation_id: str) -> int:
        """Drop the oldest turns beyond the per-conversation cap (inside the caller's transaction)."""
        old = con.execute("SELECT id FROM turns WHERE conversation_id=? ORDER BY created_at DESC, rowid DESC "
                          "LIMIT -1 OFFSET ?", (conversation_id, self._max_turns)).fetchall()
        for (tid,) in old:
            con.execute("DELETE FROM turns WHERE id=?", (tid,))
            self._fts_drop(con, "turn", tid)
        return len(old)

    def record_exchange(self, conversation_id: str | None, user_content: str,
                        assistant_content: str) -> tuple[Conversation, ConversationTurn, ConversationTurn]:
        """Persist ONE user/assistant exchange atomically: both turns or neither. With `conversation_id=None`
        the conversation is created in the same transaction, so a failure never leaves an empty conversation
        or a user turn without its answer."""
        now = self._now()
        expires = now + timedelta(days=self._retention) if self._retention else None
        cid = conversation_id or _new_id()
        try:
            turns = [ConversationTurn(id=_new_id(), conversation_id=cid, role=role, content=text, created_at=now,
                                      expires_at=expires)
                     for role, text in (("user", user_content), ("assistant", assistant_content))]
        except ValidationError as exc:
            raise MemoryPolicyError(f"invalid turn: {exc.errors()[0]['msg']}") from None
        if "\x00" in user_content or "\x00" in assistant_content:
            raise MemoryPolicyError("content must not contain NUL characters")
        dropped = 0
        with self._tx() as con:
            exists = con.execute("SELECT created_at FROM conversations WHERE id=?", (cid,)).fetchone()
            if conversation_id is None:
                con.execute("INSERT INTO conversations VALUES (?,?,?,?)", (cid, None, _fmt(now), _fmt(now)))
                created = now
            elif exists is None:
                raise MemoryNotFound("conversation not found")
            else:
                created = _parse(exists["created_at"])
            for t in turns:
                con.execute("INSERT INTO turns VALUES (?,?,?,?,?,?)",
                            (t.id, cid, t.role, t.content, _fmt(now), _fmt(expires) if expires else None))
                self._fts_put(con, "turn", t.id, t.content, cid)
            con.execute("UPDATE conversations SET updated_at=? WHERE id=?", (_fmt(now), cid))
            dropped = self._trim_conversation(con, cid)
        if dropped:
            self._scrub()
        return Conversation(id=cid, title=None, created_at=created, updated_at=now), turns[0], turns[1]

    def recent_turns(self, conversation_id: str, limit: int = 6) -> list[ConversationTurn]:
        """Oldest-first, only this conversation, expired turns invisible."""
        with self._read() as con:
            rows = con.execute(
                "SELECT * FROM turns WHERE conversation_id=? AND (expires_at IS NULL OR expires_at>?) "
                "ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (conversation_id, _fmt(self._now()), max(1, min(limit, 200)))).fetchall()
        return [self._turn(r) for r in reversed(rows)]

    @staticmethod
    def _turn(r: sqlite3.Row) -> ConversationTurn:
        return ConversationTurn(id=r["id"], conversation_id=r["conversation_id"], role=r["role"],
                                content=r["content"], created_at=_parse(r["created_at"]),
                                expires_at=_parse(r["expires_at"]) if r["expires_at"] else None)

    # ───────────────────────── preferences ─────────────────────────
    def set_preference(self, key: str, value: str) -> UserPreference:
        key = key.strip().lower()
        if len(key) > MAX_PREF_KEY_CHARS:
            raise MemoryPolicyError("preference key too long")
        now = self._now()
        try:
            probe = UserPreference(id="x", key=key, value=value, created_at=now, updated_at=now)
        except ValidationError as exc:
            raise MemoryPolicyError(f"invalid preference: {exc.errors()[0]['msg']}") from None
        if "\x00" in value or _TELEMETRY_RECORD.search(value):
            raise MemoryPolicyError("a preference cannot hold NUL characters or sensor readings")
        with self._tx() as con:
            r = con.execute("SELECT id, created_at FROM preferences WHERE key=?", (key,)).fetchone()
            if r is None:
                pid, created = _new_id(), now
                con.execute("INSERT INTO preferences VALUES (?,?,?,?,?,?)",
                            (pid, key, value, "user_explicit", _fmt(now), _fmt(now)))
            else:
                pid, created = r["id"], _parse(r["created_at"])
                con.execute("UPDATE preferences SET value=?, updated_at=? WHERE id=?", (value, _fmt(now), pid))
                self._fts_drop(con, "preference", pid)
            self._fts_put(con, "preference", pid, f"{key} {value}")
        if r is not None:
            self._scrub()  # the previous value is a deletion
        return probe.model_copy(update={"id": pid, "created_at": created})

    def list_preferences(self) -> list[UserPreference]:
        with self._read() as con:
            rows = con.execute("SELECT * FROM preferences ORDER BY key").fetchall()
        return [self._pref(r) for r in rows]

    @staticmethod
    def _pref(r: sqlite3.Row) -> UserPreference:
        return UserPreference(id=r["id"], key=r["key"], value=r["value"], origin=r["origin"],
                              created_at=_parse(r["created_at"]), updated_at=_parse(r["updated_at"]))

    # ───────────────────────── facts ─────────────────────────
    def remember_fact(self, content: str, *, ttl_days: float | None = None,
                      origin: str = "user_explicit") -> MemoryFact:
        if origin != "user_explicit":
            raise MemoryPolicyError("only facts the user explicitly asked to remember can be stored "
                                    "(telemetry, tool output and model output are never permanent facts)")
        if ttl_days is not None and ttl_days <= 0:
            raise MemoryPolicyError("ttl_days must be positive")
        if "\x00" in content:
            raise MemoryPolicyError("content must not contain NUL characters")
        if _TELEMETRY_RECORD.search(content):
            raise MemoryPolicyError("sensor readings are temporary telemetry, not permanent facts")
        now = self._now()
        expires = now + timedelta(days=ttl_days) if ttl_days else None
        try:
            f = MemoryFact(id=_new_id(), content=content, created_at=now, updated_at=now, expires_at=expires)
        except ValidationError as exc:
            raise MemoryPolicyError(f"invalid fact: {exc.errors()[0]['msg']}") from None
        with self._tx() as con:
            con.execute("INSERT INTO facts VALUES (?,?,?,?,?,?)",
                        (f.id, content, f.origin, _fmt(now), _fmt(now), _fmt(expires) if expires else None))
            self._fts_put(con, "fact", f.id, content)
        return f

    def update_fact(self, fact_id: str, content: str) -> MemoryFact:
        if "\x00" in content or _TELEMETRY_RECORD.search(content):
            raise MemoryPolicyError("sensor readings are temporary telemetry, not permanent facts")
        now = self._now()
        with self._tx() as con:
            r = con.execute("SELECT * FROM facts WHERE id=? AND (expires_at IS NULL OR expires_at>?)",
                            (fact_id, _fmt(now))).fetchone()
            if r is None:
                raise MemoryNotFound("fact not found")
            try:
                f = MemoryFact(id=fact_id, content=content, created_at=_parse(r["created_at"]), updated_at=now,
                               expires_at=_parse(r["expires_at"]) if r["expires_at"] else None)
            except ValidationError as exc:
                raise MemoryPolicyError(f"invalid fact: {exc.errors()[0]['msg']}") from None
            con.execute("UPDATE facts SET content=?, updated_at=? WHERE id=?", (content, _fmt(now), fact_id))
            self._fts_drop(con, "fact", fact_id)
            self._fts_put(con, "fact", fact_id, content)
        self._scrub()
        return f

    def get_fact(self, fact_id: str) -> MemoryFact:
        with self._read() as con:
            r = con.execute("SELECT * FROM facts WHERE id=? AND (expires_at IS NULL OR expires_at>?)",
                            (fact_id, _fmt(self._now()))).fetchone()
        if r is None:
            raise MemoryNotFound("fact not found")
        return self._fact(r)

    def list_facts(self, limit: int = 100) -> list[MemoryFact]:
        with self._read() as con:
            rows = con.execute("SELECT * FROM facts WHERE expires_at IS NULL OR expires_at>? "
                               "ORDER BY created_at DESC, rowid DESC LIMIT ?",
                               (_fmt(self._now()), max(1, min(limit, 500)))).fetchall()
        return [self._fact(r) for r in rows]

    @staticmethod
    def _fact(r: sqlite3.Row) -> MemoryFact:
        return MemoryFact(id=r["id"], content=r["content"], origin=r["origin"], created_at=_parse(r["created_at"]),
                          updated_at=_parse(r["updated_at"]),
                          expires_at=_parse(r["expires_at"]) if r["expires_at"] else None)

    # ───────────────────────── search ─────────────────────────
    def search(self, query: str, *, kinds: Sequence[MemoryKind] = ("fact", "preference"),
               conversation_id: str | None = None, limit: int = 5) -> list[MemoryHit]:
        """Lexical search. Turns are only searchable inside ONE conversation (`conversation_id` required)."""
        kinds = tuple(dict.fromkeys(kinds))
        if "turn" in kinds and conversation_id is None:
            raise ValueError("searching turns requires a conversation_id (conversations are isolated)")
        tokens = query_tokens(query)
        if not tokens or not kinds:
            return []
        limit = max(1, min(limit, 50))
        hits = self._search_fts(tokens, kinds, conversation_id, limit) if self.fts_enabled \
            else self._search_like(tokens, kinds, conversation_id, limit)
        return hits

    def _hydrate(self, con: sqlite3.Connection, kind: str, ref_id: str, now: str) -> tuple[str, datetime] | None:
        if kind == "fact":
            r = con.execute("SELECT content, created_at FROM facts WHERE id=? AND (expires_at IS NULL OR expires_at>?)",
                            (ref_id, now)).fetchone()
        elif kind == "preference":
            r = con.execute("SELECT key||': '||value AS content, created_at FROM preferences WHERE id=?",
                            (ref_id,)).fetchone()
        else:
            r = con.execute("SELECT content, created_at FROM turns WHERE id=? AND (expires_at IS NULL OR expires_at>?)",
                            (ref_id, now)).fetchone()
        return None if r is None else (r["content"], _parse(r["created_at"]))

    def _search_fts(self, tokens: list[str], kinds: tuple[str, ...], conv: str | None, limit: int) -> list[MemoryHit]:
        marks = ",".join("?" * len(kinds))
        sql = (f"SELECT kind, ref_id, conv, bm25(memory_fts) AS score FROM memory_fts "
               f"WHERE memory_fts MATCH ? AND kind IN ({marks})")
        args: list[object] = [fts_match_expression(tokens), *kinds]
        if conv is not None:
            sql += " AND (kind<>'turn' OR conv=?)"
            args.append(conv)
        else:
            sql += " AND kind<>'turn'"
        sql += " ORDER BY score LIMIT ?"
        args.append(limit * 4)  # over-fetch: expired rows are dropped below
        now = _fmt(self._now())
        out: list[MemoryHit] = []
        with self._read() as con:
            try:
                rows = con.execute(sql, args).fetchall()
            except sqlite3.OperationalError as exc:  # a malformed MATCH can never come from query_tokens
                log.error("FTS query failed: %s", exc)
                return []
            for r in rows:
                h = self._hydrate(con, r["kind"], r["ref_id"], now)
                if h is not None:
                    out.append(MemoryHit(kind=r["kind"], id=r["ref_id"], content=h[0], created_at=h[1],
                                         conversation_id=r["conv"] or None, score=float(r["score"])))
        out.sort(key=lambda h: (h.score, -h.created_at.timestamp()))
        return out[:limit]

    def _search_like(self, tokens: list[str], kinds: tuple[str, ...], conv: str | None, limit: int) -> list[MemoryHit]:
        now = _fmt(self._now())
        specs = {"fact": ("facts", "content", "id", None, "(expires_at IS NULL OR expires_at>?)"),
                 "preference": ("preferences", "key||' '||value", "id", None, "1=1"),
                 "turn": ("turns", "content", "id", "conversation_id", "(expires_at IS NULL OR expires_at>?)")}
        scored: dict[tuple[str, str], MemoryHit] = {}
        with self._read() as con:
            for kind in kinds:
                table, col, idc, convc, live = specs[kind]
                for tok in tokens:
                    sql = f"SELECT {idc} AS ref_id, {col} AS content, created_at FROM {table} WHERE {live}"
                    args: list[object] = [now] if "?" in live else []
                    sql += f" AND lower({col}) LIKE ? ESCAPE '\\'"
                    args.append(f"%{_like_escape(tok)}%")
                    if convc:
                        sql += f" AND {convc}=?"
                        args.append(conv)
                    for r in con.execute(sql, args).fetchall():
                        key = (kind, r["ref_id"])
                        prev = scored.get(key)
                        score = (prev.score if prev else 0.0) - 1.0  # more matched tokens -> lower (better)
                        scored[key] = MemoryHit(kind=kind, id=r["ref_id"], content=r["content"],
                                                created_at=_parse(r["created_at"]), score=score,
                                                conversation_id=conv if kind == "turn" else None)
        return sorted(scored.values(), key=lambda h: (h.score, -h.created_at.timestamp()))[:limit]

    # ───────────────────────── deletion & retention ─────────────────────────
    def delete_fact(self, fact_id: str) -> None:
        with self._tx() as con:
            if con.execute("DELETE FROM facts WHERE id=?", (fact_id,)).rowcount == 0:
                raise MemoryNotFound("fact not found")
            self._fts_drop(con, "fact", fact_id)
        self._scrub()

    def delete_preference(self, key_or_id: str) -> None:
        with self._tx() as con:
            r = con.execute("SELECT id FROM preferences WHERE key=? OR id=?",
                            (key_or_id.strip().lower(), key_or_id)).fetchone()
            if r is None:
                raise MemoryNotFound("preference not found")
            con.execute("DELETE FROM preferences WHERE id=?", (r["id"],))
            self._fts_drop(con, "preference", r["id"])
        self._scrub()

    def delete_turn(self, turn_id: str) -> None:
        with self._tx() as con:
            if con.execute("DELETE FROM turns WHERE id=?", (turn_id,)).rowcount == 0:
                raise MemoryNotFound("turn not found")
            self._fts_drop(con, "turn", turn_id)
        self._scrub()

    def delete_conversation(self, conversation_id: str) -> None:
        with self._tx() as con:
            if con.execute("SELECT 1 FROM conversations WHERE id=?", (conversation_id,)).fetchone() is None:
                raise MemoryNotFound("conversation not found")
            if self.fts_enabled:
                con.execute("DELETE FROM memory_fts WHERE kind='turn' AND conv=?", (conversation_id,))
            con.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))  # turns cascade
        self._scrub()

    def delete_all(self) -> None:
        with self._tx() as con:
            for table in ("turns", "conversations", "facts", "preferences"):
                con.execute(f"DELETE FROM {table}")
            if self.fts_enabled:
                con.execute("DELETE FROM memory_fts")
        self.compact()

    def purge_expired(self) -> int:
        """Physically remove expired turns and facts (reads already hide them)."""
        now = _fmt(self._now())
        n = 0
        with self._tx() as con:
            for kind, table in (("turn", "turns"), ("fact", "facts")):
                ids = [r["id"] for r in con.execute(
                    f"SELECT id FROM {table} WHERE expires_at IS NOT NULL AND expires_at<=?", (now,))]
                for i in ids:
                    con.execute(f"DELETE FROM {table} WHERE id=?", (i,))
                    self._fts_drop(con, kind, i)
                n += len(ids)
        if n:
            self._scrub()
        return n

    def _scrub(self) -> None:
        """Rewrite the FTS index (drops removed terms from old segments) and truncate the WAL."""
        con = self._connect()
        try:
            if self.fts_enabled:
                con.execute("INSERT INTO memory_fts(memory_fts) VALUES('optimize')")
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error as exc:
            raise MemoryStorageError(f"memory maintenance failed: {exc}") from None
        finally:
            con.close()

    def compact(self) -> None:
        self._scrub()
        con = self._connect()
        try:
            con.execute("VACUUM")
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error as exc:
            raise MemoryStorageError(f"memory compaction failed: {exc}") from None
        finally:
            con.close()

    def close(self) -> None:
        """No connection outlives an operation; kept for contract symmetry (and a final checkpoint)."""
        try:
            self._scrub()
        except Exception:  # noqa: BLE001 - closing must not raise
            log.exception("final memory checkpoint failed")
