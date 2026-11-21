"""SqliteMemoryStore: CRUD, FTS5, isolation, retention, concurrency, injection, persistence."""
import re
import sqlite3
import threading
from datetime import UTC, datetime, timedelta

import pytest

from fit_ai.memory import (
    ContextRetriever,
    MemoryNotFound,
    MemoryPolicyError,
    RecallLimits,
    SqliteMemoryStore,
)
from fit_ai.memory.sqlite_store import fts_match_expression, query_tokens


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    return SqliteMemoryStore(tmp_path / "mem.db", clock=clock)


# ── conversations & turns ──
def test_conversation_turns_roundtrip_and_order(store):
    c = store.create_conversation("teste")
    store.add_turn(c.id, "user", "Olá, tudo bem?")
    store.add_turn(c.id, "assistant", "Tudo ótimo!")
    store.add_turn(c.id, "user", "Qual a rotação?")
    turns = store.recent_turns(c.id, limit=2)
    assert [t.content for t in turns] == ["Tudo ótimo!", "Qual a rotação?"]  # oldest first, limited
    assert store.get_conversation(c.id).title == "teste"
    assert store.list_conversations()[0].id == c.id


def test_turn_in_unknown_conversation_is_rejected(store):
    with pytest.raises(MemoryNotFound):
        store.add_turn("nope", "user", "x")


def test_conversations_are_isolated(store):
    a, b = store.create_conversation(), store.create_conversation()
    store.add_turn(a.id, "user", "segredo do azulejo")
    store.add_turn(b.id, "user", "outra conversa")
    assert [t.content for t in store.recent_turns(b.id)] == ["outra conversa"]
    assert store.search("azulejo", kinds=("turn",), conversation_id=b.id) == []
    assert len(store.search("azulejo", kinds=("turn",), conversation_id=a.id)) == 1
    with pytest.raises(ValueError):  # turns can't be searched without naming one conversation
        store.search("azulejo", kinds=("turn",))
    assert store.search("azulejo") == []  # default kinds never include turns


def test_turn_cap_drops_oldest(tmp_path, clock):
    s = SqliteMemoryStore(tmp_path / "m.db", max_turns_per_conversation=3, clock=clock)
    c = s.create_conversation()
    for i in range(6):
        clock.advance(seconds=1)
        s.add_turn(c.id, "user", f"mensagem {i}")
    assert [t.content for t in s.recent_turns(c.id, 10)] == ["mensagem 3", "mensagem 4", "mensagem 5"]
    assert s.search("mensagem 0", kinds=("turn",), conversation_id=c.id)[0].content != "mensagem 0"


def test_turn_validation(store):
    c = store.create_conversation()
    with pytest.raises(MemoryPolicyError):
        store.add_turn(c.id, "user", "x" * 9000)
    with pytest.raises(MemoryPolicyError):
        store.add_turn(c.id, "user", "a\x00b")


# ── facts & preferences ──
def test_fact_crud_and_unicode(store):
    f = store.remember_fact("Meu Fit tem pneus novos — troca feita em São Paulo ✔")
    assert store.get_fact(f.id).content.startswith("Meu Fit")
    u = store.update_fact(f.id, "Meu Fit está com óleo novo (ação concluída)")
    assert u.updated_at >= f.updated_at and u.id == f.id
    assert [x.id for x in store.list_facts()] == [f.id]
    assert store.search("oleo")[0].id == f.id  # diacritics-insensitive: óleo ~ oleo
    store.delete_fact(f.id)
    with pytest.raises(MemoryNotFound):
        store.get_fact(f.id)
    with pytest.raises(MemoryNotFound):
        store.delete_fact(f.id)


def test_preferences_upsert_keeps_identity(store):
    p1 = store.set_preference("Tratamento", "me chame de Valéria")
    p2 = store.set_preference("tratamento", "me chame de chefe")
    assert p1.id == p2.id and len(store.list_preferences()) == 1
    assert store.list_preferences()[0].value == "me chame de chefe"
    assert store.search("chefe", kinds=("preference",))[0].id == p1.id
    assert store.search("Valéria", kinds=("preference",)) == []  # the old value left the index
    store.delete_preference("tratamento")
    assert store.list_preferences() == []


@pytest.mark.parametrize("origin", ["telemetry", "tool", "model", "simulated", "octave", ""])
def test_only_explicit_user_facts_are_stored(store, origin):
    with pytest.raises(MemoryPolicyError):
        store.remember_fact("o carro está a 800 rpm", origin=origin)
    assert store.list_facts() == []


@pytest.mark.parametrize("text", ["rpm=800", "speed_kmh: 0", "coolant_temp_c = 90.5", "leitura RPM:  3200"])
def test_sensor_readings_cannot_become_facts_or_preferences(store, text):
    with pytest.raises(MemoryPolicyError):
        store.remember_fact(text)
    with pytest.raises(MemoryPolicyError):
        store.set_preference("ultima_leitura", text)
    assert store.list_facts() == [] and store.list_preferences() == []


# ── FTS5 search ──
def test_search_ranks_and_limits(store):
    for t in ["Gosto de música sertaneja nas viagens", "Prefiro rotas sem pedágio", "Música clássica de manhã"]:
        store.remember_fact(t)
    hits = store.search("música", limit=5)
    assert {h.content.split()[0] for h in hits} == {"Gosto", "Música"}
    assert len(store.search("música", limit=1)) == 1
    assert all(h.kind == "fact" for h in hits)


def test_empty_and_stopword_queries_return_nothing(store):
    store.remember_fact("alguma coisa")
    for q in ["", "   ", "de a o", "!!! ---", "\x00"]:
        assert store.search(q) == []


@pytest.mark.parametrize("evil", [
    '" OR 1=1 --', "'; DROP TABLE facts; --", 'content:segredo', "kind:fact", "NEAR(a b)", "* OR *",
    "segredo*", '"unterminated', "a AND NOT b", "{col}:x", "(((", "\\", "%", "_",
])
def test_hostile_queries_are_neutralised(store, evil):
    store.remember_fact("o segredo do cofre é azul")
    store.search(evil)  # never raises
    assert store.list_facts()  # tables intact
    expr = fts_match_expression(query_tokens(evil))
    parts = [p for p in expr.split(" OR ") if p]
    assert all(re.fullmatch(r'"\w+"\*?', p) for p in parts)  # only quoted words: no operator or column filter


def test_hostile_query_does_not_widen_results(store):
    store.remember_fact("alpha confidencial")
    store.remember_fact("beta publico")
    assert [h.content for h in store.search('beta" OR "alpha')] != []
    # a query made only of operators/column filters matches nothing, it does not match everything
    assert store.search('kind:fact OR content:"*"') == []


def test_like_fallback_when_fts_is_off(tmp_path, clock):
    s = SqliteMemoryStore(tmp_path / "nofts.db", use_fts=False, clock=clock)
    assert not s.fts_enabled
    s.remember_fact("100% de desconto na troca de óleo")
    s.remember_fact("preço normal")
    assert [h.content for h in s.search("desconto")] == ["100% de desconto na troca de óleo"]
    assert s.search("%") == [] and s.search("_") == []  # LIKE wildcards are data, not patterns
    c = s.create_conversation()
    s.add_turn(c.id, "user", "tema isolado")
    assert s.search("isolado", kinds=("turn",), conversation_id=c.id)
    assert s.search("isolado", kinds=("turn",), conversation_id="other") == []


def test_deleted_rows_never_appear_in_search(store):
    f = store.remember_fact("palavra-chave única zebra")
    assert store.search("zebra")
    store.delete_fact(f.id)
    assert store.search("zebra") == []


# ── retention ──
def test_expired_items_are_invisible_then_purged(store, clock):
    f = store.remember_fact("lembrete temporário girafa", ttl_days=1)
    c = store.create_conversation()
    store.add_turn(c.id, "user", "conversa antiga hipopótamo")
    assert store.search("girafa") and store.recent_turns(c.id)
    clock.advance(days=2)  # fact (1 d) expired; turn (30 d default) not yet
    assert store.search("girafa") == [] and store.list_facts() == []
    with pytest.raises(MemoryNotFound):
        store.get_fact(f.id)
    assert len(store.recent_turns(c.id)) == 1
    clock.advance(days=40)
    assert store.recent_turns(c.id) == []
    assert store.purge_expired() == 2
    assert store.purge_expired() == 0


def test_retention_is_configurable(tmp_path, clock):
    s = SqliteMemoryStore(tmp_path / "r.db", turn_retention_days=0.5, clock=clock)
    c = s.create_conversation()
    s.add_turn(c.id, "user", "curta duração")
    clock.advance(hours=13)
    assert s.recent_turns(c.id) == []
    with pytest.raises(ValueError):
        SqliteMemoryStore(tmp_path / "bad.db", turn_retention_days=0)


# ── persistence, transactions, concurrency ──
def test_data_survives_a_restart(tmp_path):
    p = tmp_path / "persist.db"
    s1 = SqliteMemoryStore(p)
    c = s1.create_conversation("persistente")
    s1.add_turn(c.id, "user", "oi depois do reinício")
    f = s1.remember_fact("gosto de café sem açúcar")
    s1.set_preference("idioma", "português")
    s1.close()
    s2 = SqliteMemoryStore(p)
    assert s2.recent_turns(c.id)[0].content == "oi depois do reinício"
    assert s2.get_fact(f.id).content == "gosto de café sem açúcar"
    assert s2.search("cafe")[0].id == f.id  # FTS index persisted as well
    assert s2.list_preferences()[0].value == "português"


def test_failed_write_rolls_back_everything(store, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("index failure")
    monkeypatch.setattr(store, "_fts_put", boom)
    with pytest.raises(RuntimeError):
        store.remember_fact("não deve ficar pela metade")
    monkeypatch.undo()
    assert store.list_facts() == []  # base row rolled back together with the failed index write


def test_concurrent_writers_do_not_lose_or_corrupt(tmp_path):
    s = SqliteMemoryStore(tmp_path / "conc.db")
    c = s.create_conversation()
    errors: list[BaseException] = []

    def work(i: int):
        try:
            for j in range(10):
                s.add_turn(c.id, "user", f"thread {i} msg {j}")
                s.remember_fact(f"fato {i}-{j}")
        except BaseException as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(exc)

    ts = [threading.Thread(target=work, args=(i,)) for i in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errors == []
    assert len(s.recent_turns(c.id, 200)) == 80 and len(s.list_facts(500)) == 80
    con = sqlite3.connect(s.path)
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert con.execute("SELECT count(*) FROM memory_fts").fetchone()[0] == 160


def test_unwritable_location_is_a_typed_error(tmp_path):
    from fit_ai.memory import MemoryStorageError
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises((MemoryStorageError, OSError)):
        SqliteMemoryStore(blocker / "sub" / "m.db")


# ── contextual recall ──
def test_recall_is_bounded_and_labels_memory_as_not_telemetry(store, clock):
    store.set_preference("tratamento", "me chame de Valéria")
    for i in range(10):
        store.remember_fact(f"nota {i} sobre pneus e rodízio " + "x" * 400)
    c = store.create_conversation()
    store.add_turn(c.id, "user", "pergunta antiga sobre pneus")
    clock.advance(days=3)
    ctx = ContextRetriever(store, RecallLimits(max_facts=3, max_total_chars=500), clock=clock).recall("pneus", c.id)
    assert len(ctx.facts) == 3 and len(ctx.rendered) <= 500
    assert "NÃO são leituras de sensores" in ctx.rendered and "há 3 dias" in ctx.rendered


def test_recall_with_nothing_relevant_injects_no_facts(store):
    store.remember_fact("gosto de jazz")
    ctx = ContextRetriever(store).recall("qual a rotação do motor?")
    assert ctx.facts == () and ctx.empty


# ───────── atomic exchange (P7) ─────────
def test_record_exchange_creates_conversation_and_both_turns_together(store):
    conv, u, a = store.record_exchange(None, "Qual a rotação?", "[resposta]")
    assert conv.id == u.conversation_id == a.conversation_id
    assert [(t.role, t.content) for t in store.recent_turns(conv.id, 10)] == [("user", "Qual a rotação?"), ("assistant", "[resposta]")]
    conv2, _, _ = store.record_exchange(conv.id, "E agora?", "ok")
    assert conv2.id == conv.id and len(store.recent_turns(conv.id, 10)) == 4  # order kept: user, assistant, user, assistant
    assert [t.role for t in store.recent_turns(conv.id, 10)] == ["user", "assistant", "user", "assistant"]


def test_record_exchange_is_all_or_nothing(store, monkeypatch):
    c = store.create_conversation()
    calls = {"n": 0}
    real = store._fts_put

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:  # the assistant turn's index write fails after the user turn was inserted
            raise RuntimeError("index failure")
        return real(*a, **k)
    monkeypatch.setattr(store, "_fts_put", flaky)
    with pytest.raises(RuntimeError):
        store.record_exchange(c.id, "pergunta", "resposta")
    monkeypatch.undo()
    assert store.recent_turns(c.id, 10) == []  # no half exchange


def test_record_exchange_new_conversation_leaves_no_empty_conversation_on_failure(store, monkeypatch):
    monkeypatch.setattr(store, "_fts_put", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        store.record_exchange(None, "pergunta", "resposta")
    monkeypatch.undo()
    assert store.list_conversations() == []


def test_record_exchange_validation_and_unknown_conversation(store):
    with pytest.raises(MemoryNotFound):
        store.record_exchange("nope", "a", "b")
    with pytest.raises(MemoryPolicyError):
        store.record_exchange(None, "a" * 9000, "b")
    with pytest.raises(MemoryPolicyError):
        store.record_exchange(None, "a", "b" + chr(0))
    assert store.list_conversations() == []


def test_record_exchange_respects_the_turn_cap(tmp_path):
    s = SqliteMemoryStore(tmp_path / "cap.db", max_turns_per_conversation=4)
    conv, _, _ = s.record_exchange(None, "u0", "a0")
    for i in range(1, 4):
        s.record_exchange(conv.id, f"u{i}", f"a{i}")
    assert [t.content for t in s.recent_turns(conv.id, 10)] == ["u2", "a2", "u3", "a3"]
