"""Latency of the P6 building blocks (no model): SQLite, FTS5, tools, verifier, audit, orchestration with a fake LLM.

    python -m bench.p6_perf            # writes bench/results/p6-perf-<stamp>.json

Single process, sequential, a few hundred repetitions per measurement. Numbers describe THIS development laptop
(i5-1235U, SSD), not the final in-car hardware.
"""
from __future__ import annotations

import asyncio
import json
import platform
import statistics
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from bench.p6_corpus import CASES
from fit_ai.adapters.fake_telemetry import FakeTelemetryProvider
from fit_ai.ai import FakeLLMProvider, Reply
from fit_ai.audit import AuditEvent, SqliteAuditLog
from fit_ai.grounding import EvidenceBundle, StructuredAnswer, build_evidence, render_fallback, verify
from fit_ai.memory import ContextRetriever, SqliteMemoryStore
from fit_ai.orchestration import AssistantOrchestrator, AssistantSettings, TurnRequest
from fit_ai.services.telemetry import TelemetryService
from fit_ai.tools import build_vehicle_registry

RESULTS_DIR = Path(__file__).resolve().parent / "results"
WORDS = "pneu óleo filtro vela correia pastilha freio rodízio alinhamento bateria revisão viagem estrada posto rota música".split()


def pct(xs: list[float], q: float) -> float:
    s = sorted(xs)
    k = (len(s) - 1) * q / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def stat(ms: list[float]) -> dict[str, float]:
    return {"n": len(ms), "median_ms": round(statistics.median(ms), 3), "p95_ms": round(pct(ms, 95), 3),
            "max_ms": round(max(ms), 3)}


def timeit(fn, n: int) -> list[float]:
    out = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t) * 1000)
    return out


async def atimeit(fn, n: int) -> list[float]:
    out = []
    for _ in range(n):
        t = time.perf_counter()
        await fn()
        out.append((time.perf_counter() - t) * 1000)
    return out


def fill(store: SqliteMemoryStore, n: int) -> None:
    for i in range(n):
        store.remember_fact(f"Nota {i}: {WORDS[i % len(WORDS)]} e {WORDS[(i * 7 + 3) % len(WORDS)]} do meu Fit, "
                            f"item {i} sobre {WORDS[(i * 3) % len(WORDS)]}")


async def main() -> dict:
    res: dict = {"python": platform.python_version(), "os": platform.platform(),
                 "started": datetime.now(UTC).isoformat(timespec="seconds"), "memory": {}, "other": {}}
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        # ── SQLite / FTS5 vs memory size ──
        for size in (0, 100, 1000, 5000):
            store = SqliteMemoryStore(td / f"m{size}.db")
            conv = store.create_conversation()
            fill(store, size)
            entry: dict = {}
            entry["insert_fact"] = stat(timeit(lambda: store.remember_fact(f"nova nota sobre {WORDS[size % 15]} e revisão"), 60))
            entry["add_turn"] = stat(timeit(lambda: store.add_turn(conv.id, "user", "pergunta de teste sobre o carro"), 60))
            entry["recent_turns"] = stat(timeit(lambda: store.recent_turns(conv.id, 6), 200))
            entry["list_preferences"] = stat(timeit(store.list_preferences, 200))
            entry["fts_search_relevant"] = stat(timeit(lambda: store.search("pneu revisão", limit=5), 200))
            entry["fts_search_no_match"] = stat(timeit(lambda: store.search("xylofone zumbido", limit=5), 200))
            retr = ContextRetriever(store)
            entry["recall_context"] = stat(timeit(lambda: retr.recall("quando troquei o óleo e o filtro?", conv.id), 200))
            entry["recall_no_relevant"] = stat(timeit(lambda: retr.recall("qual a capital da França", conv.id), 200))
            victim = store.remember_fact("fato a ser apagado XYZCANARIO")
            t = time.perf_counter()
            store.delete_fact(victim.id)  # includes FTS optimize + WAL truncate
            entry["delete_with_secure_scrub_ms"] = round((time.perf_counter() - t) * 1000, 2)
            t = time.perf_counter()
            store.compact()
            entry["compact_ms"] = round((time.perf_counter() - t) * 1000, 2)
            entry["db_size_kb"] = round(Path(store.path).stat().st_size / 1024, 1)
            res["memory"][str(size)] = entry

        # ── audit ──
        audit = SqliteAuditLog(td / "audit.db")
        n = [0]

        def write():
            n[0] += 1
            audit.record(AuditEvent(event_id=f"e{n[0]}", request_id="r", timestamp=datetime.now(UTC), kind="tool_result",
                                    decision="ok", tool="get_vehicle_telemetry", permission="READ", summary="rpm=800"))
        res["other"]["audit_write"] = stat(timeit(write, 200))

        # ── tool execution + grounding ──
        fake = FakeTelemetryProvider(800, 0.0, 90.0)
        mem = SqliteMemoryStore(td / "tools.db")
        reg = build_vehicle_registry(TelemetryService(fake), mem)
        res["other"]["tool_telemetry_complete"] = stat(await atimeit(lambda: reg.execute("get_vehicle_telemetry", {}), 300))
        fake_partial = FakeTelemetryProvider(800, None, None)
        reg_p = build_vehicle_registry(TelemetryService(fake_partial), mem)
        res["other"]["tool_telemetry_partial"] = stat(await atimeit(lambda: reg_p.execute("get_vehicle_telemetry", {}), 300))
        res["other"]["tool_status"] = stat(await atimeit(lambda: reg.execute("get_vehicle_status", {}), 300))
        outcome = await reg.execute("get_vehicle_telemetry", {})
        bundle = EvidenceBundle.of("t", [build_evidence(outcome, "t")])
        ok = StructuredAnswer(answer="No simulador, o motor está a 800 RPM, a velocidade é 0 km/h e a temperatura 90 °C.")
        bad = StructuredAnswer(answer="Seu motor está a cinco mil RPM e a temperatura está normal, mas a pressão dos pneus está boa.")
        res["other"]["verify_accepting"] = stat(timeit(lambda: verify(ok, bundle), 500))
        res["other"]["verify_rejecting"] = stat(timeit(lambda: verify(bad, bundle), 500))
        res["other"]["render_fallback"] = stat(timeit(lambda: render_fallback(bundle), 500))

        # ── whole orchestration with a fake LLM (everything except model inference) ──
        good = Reply.text(json.dumps({"answer": "No simulador, o motor está a 800 RPM.", "claims": [], "unknown": []},
                                     ensure_ascii=False))

        async def turn(telemetry, store, question, replies):
            audit2 = SqliteAuditLog(td / f"a{time.perf_counter_ns()}.db")
            orch = AssistantOrchestrator(build_vehicle_registry(TelemetryService(telemetry), store),
                                         FakeLLMProvider(list(replies)), audit=audit2, memory=store,
                                         settings=AssistantSettings())
            t = time.perf_counter()
            r = await orch.run(TurnRequest(question))
            return (time.perf_counter() - t) * 1000, r

        scen = {
            "orchestrate_complete_data_empty_memory": (FakeTelemetryProvider(800, 0.0, 90.0), SqliteMemoryStore(td / "e.db"),
                                                       "Qual a rotação?", [good]),
            "orchestrate_partial_data": (FakeTelemetryProvider(800, None, None), SqliteMemoryStore(td / "p.db"),
                                         "Qual a rotação?", [good]),
            "orchestrate_no_relevant_memory": (FakeTelemetryProvider(800, 0.0, 90.0), None, "Qual a rotação?", [good]),
        }
        big = SqliteMemoryStore(td / "big.db")
        fill(big, 1000)
        scen["orchestrate_1000_memories_memory_question"] = (
            FakeTelemetryProvider(800, 0.0, 90.0), big, "Você lembra da minha nota sobre pneu e revisão? Qual a rotação?", [good])
        scen["orchestrate_with_one_retry"] = (FakeTelemetryProvider(800, 0.0, 90.0), SqliteMemoryStore(td / "r.db"), "Qual a rotação?",
                                              [Reply.text(json.dumps({"answer": "5000 rpm", "claims": [], "unknown": []})), good])
        for name, (tel, store, q, replies) in scen.items():
            ms, last = [], None
            for _ in range(40):
                t_ms, last = await turn(tel, store, q, replies)
                ms.append(t_ms)
            res["other"][name] = {**stat(ms), "last_source": last.source,
                                  "stages_ms": last.timings_ms}

    # ── corpus replay cost ──
    from bench.p6_adversarial import run_case
    with tempfile.TemporaryDirectory() as td2:
        ms = []
        for c in CASES:
            d = Path(td2) / c.id
            d.mkdir()
            r = await run_case(c, d)
            ms.append(r["wall_s"] * 1000)
    res["other"]["corpus_case_with_fake_llm"] = stat(ms)
    return res


if __name__ == "__main__":
    out = asyncio.run(main())
    path = RESULTS_DIR / f"p6-perf-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"memory": {k: {kk: v["median_ms"] if isinstance(v, dict) and "median_ms" in v else v
                                      for kk, v in e.items()} for k, e in out["memory"].items()},
                      "other": {k: v.get("median_ms") for k, v in out["other"].items()}}, indent=1, ensure_ascii=False))
    print(f"saved to {path}", file=sys.stderr)
