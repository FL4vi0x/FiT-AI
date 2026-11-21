"""Latency of the chat path, stage by stage.

    python -m bench.p7_perf --mode fake  --n 40      # everything except the model (HTTP, service, memory, tools, verify, persist)
    python -m bench.p7_perf --mode ollama --n 6      # the same with the real local model (slow: CPU inference)

Per request it measures: HTTP round trip (in-process ASGI client), the service's own latency, and the stages
the orchestrator reports (tools, memory recall, model, verifier) plus the time to persist the exchange.
Median / p95 / max. Numbers describe THIS development laptop, not the in-car hardware.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import platform
import statistics
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from bench.p5_runner import _keep_awake
from bench.p6_corpus import Fx
from bench.p7_adversarial import MODEL, build_stack, to_replies
from fit_ai.ai import LLMSettings, OllamaProvider, Reply
from fit_ai.conversation import ChatSettings

RESULTS_DIR = Path(__file__).resolve().parent / "results"
GOOD = ("a", "No simulador, o motor está a 800 RPM.", ())
GENERAL = ("a", "Troca de óleo é a renovação do lubrificante do motor, que protege as peças.", ())


def pct(xs: list[float], q: float) -> float:
    s = sorted(xs)
    k = (len(s) - 1) * q / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def stat(xs: list[float]) -> dict[str, float]:
    return {"n": len(xs), "median": round(statistics.median(xs), 2), "p95": round(pct(xs, 95), 2), "max": round(max(xs), 2)}


SCENARIOS = {
    "telemetry_complete": dict(fx=Fx(), facts=0, message="Qual é a rotação atual?", fake_reply=GOOD),
    "telemetry_partial": dict(fx=Fx(speed=None, temp=None), facts=0, message="Qual é a rotação atual?", fake_reply=GOOD),
    "general_no_relevant_memory": dict(fx=Fx(), facts=0, message="Explique o que é troca de óleo.", fake_reply=GENERAL),
    "general_with_1000_memories": dict(fx=Fx(), facts=1000, message="Explique o que é troca de óleo.", fake_reply=GENERAL),
    "memory_question_1000_memories": dict(fx=Fx(), facts=1000, message="Você lembra da minha nota sobre pneu e revisão?",
                                          fake_reply=("a", "Encontrei notas suas sobre pneus e revisão.", ())),
    "octave_unavailable": dict(fx=Fx(fail="vehicle_link_down"), facts=0, message="Qual é a rotação atual?",
                               fake_reply=("a", "Não consigo ler os dados do veículo agora; a conexão está interrompida.", ())),
}
WORDS = "pneu óleo filtro vela correia pastilha freio rodízio alinhamento bateria revisão".split()


def run_scenario(name: str, spec: dict[str, Any], mode: str, n: int, llm) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as td:
        facts = [f"Nota {i}: {WORDS[i % 11]} e {WORDS[(i * 7 + 3) % 11]} do meu Fit, item {i}" for i in range(spec["facts"])]
        st = build_stack(Path(td), spec["fx"], llm=llm if mode == "ollama" else None, chat=ChatSettings(request_timeout_s=300),
                         memory_facts=facts)
        stages: list[dict[str, float]] = []
        persist: list[float] = []
        orch = st.service._orch
        real_run = orch.run

        async def run(req):
            res = await real_run(req)
            stages.append(res.timings_ms)
            return res
        orch.run = run  # type: ignore[method-assign]
        real_rec = st.memory.record_exchange

        def rec(*a, **k):
            t = time.perf_counter()
            out = real_rec(*a, **k)
            persist.append((time.perf_counter() - t) * 1000)
            return out
        st.memory.record_exchange = rec  # type: ignore[method-assign]

        http, service, sources = [], [], []
        total = n + (1 if mode == "ollama" else 0)  # one warm-up call (model load + system-prompt prefix) in real mode
        for i in range(total):
            if mode == "fake":
                st.llm._queue.extend(to_replies([spec["fake_reply"]]))  # type: ignore[attr-defined]
            t0 = time.perf_counter()
            r = st.client.post("/api/v1/chat", json={"message": spec["message"]})
            dt = (time.perf_counter() - t0) * 1000
            if mode == "ollama" and i == 0:
                stages.clear(), persist.clear()
                continue
            body = r.json()
            http.append(dt)
            if r.status_code == 200:
                service.append(body["latency_ms"])
                sources.append(body["answer_origin"])
        out: dict[str, Any] = {"http_ms": stat(http), "service_ms": stat(service) if service else None,
                               "persist_ms": stat(persist) if persist else None,
                               "origins": {k: sources.count(k) for k in sorted(set(sources))}}
        for stage in ("tools_ms", "memory_ms", "llm_ms", "verify_ms"):
            vals = [s[stage] for s in stages if stage in s]
            out[stage] = stat(vals) if vals else None
        return out


async def amain(args: argparse.Namespace) -> dict[str, Any]:
    llm = None
    if args.mode == "ollama":
        llm = OllamaProvider(LLMSettings.from_env().with_model(args.model))
        h = await llm.health()
        if not h.available or h.model_installed is False:
            raise SystemExit("Ollama unavailable or model not installed")
    res: dict[str, Any] = {"mode": args.mode, "model": args.model if llm else None, "n": args.n, "python": platform.python_version(),
                           "os": platform.platform(), "started": datetime.now().isoformat(timespec="seconds"), "scenarios": {}}
    names = args.scenarios or list(SCENARIOS)
    for name in names:
        res["scenarios"][name] = await asyncio.to_thread(run_scenario, name, SCENARIOS[name], args.mode, args.n, llm)
        print(f"{name}: http median {res['scenarios'][name]['http_ms']['median']} ms", file=sys.stderr)
    if llm is not None:
        await llm.aclose()
    return res


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", choices=["fake", "ollama"], default="fake")
    p.add_argument("--model", default=MODEL)
    p.add_argument("--n", type=int, default=30)
    p.add_argument("--scenarios", nargs="*", choices=list(SCENARIOS))
    p.add_argument("--keep-awake", action="store_true")
    p.add_argument("--out", type=Path, default=RESULTS_DIR)
    a = p.parse_args(argv)
    awake = _keep_awake(a.keep_awake)
    out = asyncio.run(amain(a))
    if awake:
        _keep_awake(False, undo=True)
    a.out.mkdir(parents=True, exist_ok=True)
    path = a.out / f"p7-perf-{a.mode}-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out["scenarios"], indent=1, ensure_ascii=False))
    print(f"saved to {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
