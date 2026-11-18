"""P5 comparative benchmark runner (PoC 03). Sequential only; models are INTERLEAVED per round so slow drift
(thermal state, background load) hits both models equally, and scenario order is the same shuffled order
for both models within a round.

    python -m bench.p5_runner --rounds 5 --context 4096
    python -m bench.p5_runner --rounds 5 --context 8192 --scenarios LATENCY_long_cold LATENCY_long_warm TOOL_rpm
    python -m bench.p5_runner --analyze bench/results/p5-<stamp>

Raw data: bench/results/p5-<stamp>/raw.jsonl (git-ignored; metrics only, never prompts or answers).
Safety: aborts on a sustained throughput collapse (thermal / contention suspicion), repeated timeouts or the
--max-minutes budget. CPU temperature is NOT readable without admin rights, so stability is judged by
throughput drift, not by temperature.
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import dataclasses
import json
import math
import platform
import random
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from bench.p5_scenarios import P5Scenario, build_p5_scenarios
from fit_ai.ai import ChatMessage, LLMError, LLMSettings, LLMTimeout, OllamaProvider, load_system_prompt

RESULTS_DIR = Path(__file__).resolve().parent / "results"
OLLAMA_EXE = Path(__file__).resolve().parents[2] / "runtime" / "ollama" / "ollama.exe"
MODELS = ["qwen3:4b-instruct-2507-q4_K_M", "qwen3:8b-q4_K_M"]
CALL_TIMEOUT_S = 300.0
SUSPEND_SLACK_S = 30.0  # a call that overran its own timeout by more than this => the machine was suspended
DROP_RATIO = 0.6  # a round whose median gen tok/s falls below 60% of that model's round-1 median is "collapsed"


# ───────────────────────── measurement helpers ─────────────────────────
def percentile(values: list[float], q: float) -> float | None:
    """Linear-interpolation percentile (q in 0..100). With n=5, p95 is within 20% of the max: report n."""
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * q / 100
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def sample_system(base_url: str = "http://127.0.0.1:11434") -> dict[str, float | None]:
    """Inference-process RAM (MB), system free RAM (MB), CPU clock (MHz), Ollama's own model size (MB).
    The model runs in a `llama-server` child of the portable Ollama, so every process whose executable lives
    under runtime/ollama is summed. One PowerShell call, outside the timed region. Failure -> Nones."""
    root = str(OLLAMA_EXE.parent)
    ps = (f"$p=Get-Process -EA SilentlyContinue|?{{$_.Path -and $_.Path.StartsWith('{root}')}};"
          "$ws=($p|Measure-Object WorkingSet64 -Sum).Sum;$pv=($p|Measure-Object PrivateMemorySize64 -Sum).Sum;"
          "$o=Get-CimInstance Win32_OperatingSystem;$c=Get-CimInstance Win32_Processor;"
          "\"$ws,$pv,$($o.FreePhysicalMemory),$($c.CurrentClockSpeed)\"")
    out: dict[str, float | None] = {"infer_ws_mb": None, "infer_private_mb": None, "sys_free_mb": None,
                                    "cpu_mhz": None, "ps_size_mb": None}
    try:
        txt = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             timeout=30).stdout.strip()
        ws, pv, free_kb, mhz = (float(x) if x else None for x in txt.split(","))
        out.update(infer_ws_mb=ws and round(ws / 2**20), infer_private_mb=pv and round(pv / 2**20),
                   sys_free_mb=free_kb and round(free_kb / 1024), cpu_mhz=mhz)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    try:
        with urllib.request.urlopen(base_url + "/api/ps", timeout=5) as r:  # loopback only (constant above)
            models = json.loads(r.read()).get("models", [])
        out["ps_size_mb"] = round(sum(m.get("size", 0) for m in models) / 2**20) if models else None
    except (OSError, ValueError):
        pass
    return out


async def one_call(provider: OllamaProvider, sc: P5Scenario, nonce: str) -> dict[str, Any]:
    rec: dict[str, Any] = {"scenario": sc.id, "category": sc.category, "nonce": nonce}
    t0 = time.perf_counter()
    try:
        r = await provider.generate(sc.build(nonce), tools=sc.tools, response_format=sc.response_format,
                                    max_tokens=sc.max_tokens, think=False, timeout_s=CALL_TIMEOUT_S)
    except LLMError as exc:
        wall = time.perf_counter() - t0
        rec.update(ok=False, reason=f"error:{type(exc).__name__}", error=type(exc).__name__, wall_s=round(wall, 3))
        if isinstance(exc, LLMTimeout) and wall > CALL_TIMEOUT_S + SUSPEND_SLACK_S:
            rec.update(invalid=True, reason="suspend_suspected")  # event loop was frozen: not a model result
        return rec
    rec["wall_s"] = round(time.perf_counter() - t0, 3)
    ok, reason = sc.score(r)
    # prompt_tokens counts the whole prompt INCLUDING the cached prefix; only the new tokens cost time
    new_tokens = None if r.usage.prompt_tokens is None else r.usage.prompt_tokens - (r.usage.cached_prompt_tokens or 0)
    new_tps = (new_tokens / r.timings.prompt_eval_s) if new_tokens and r.timings.prompt_eval_s else None
    rec.update(prompt_new_tokens=new_tokens, prompt_new_tps=new_tps, ok=ok, reason=reason, finish_reason=r.finish_reason, prompt_tokens=r.usage.prompt_tokens,
               cached_prompt_tokens=r.usage.cached_prompt_tokens, completion_tokens=r.usage.completion_tokens,
               load_s=r.timings.load_s, prompt_eval_s=r.timings.prompt_eval_s, generation_s=r.timings.generation_s,
               total_s=r.timings.total_s, gen_tps=r.generation_tokens_per_s,
               tool_calls=[c.name for c in r.tool_calls], content_chars=len(r.content),
               thinking_chars=r.thinking_chars)
    return rec


async def warmup(provider: OllamaProvider) -> dict[str, Any]:
    """Discarded call: loads the model and primes the shared system-prompt prefix (identical for both models)."""
    t0 = time.perf_counter()
    try:
        r = await provider.generate([load_system_prompt().as_message(), ChatMessage.user("Diga olá.")],
                                    max_tokens=8, think=False, timeout_s=CALL_TIMEOUT_S)
        return {"warmup": True, "load_s": r.timings.load_s, "wall_s": round(time.perf_counter() - t0, 3)}
    except LLMError as exc:
        wall = time.perf_counter() - t0
        return {"warmup": True, "error": type(exc).__name__, "wall_s": round(wall, 3),
                "invalid": isinstance(exc, LLMTimeout) and wall > CALL_TIMEOUT_S + SUSPEND_SLACK_S}


def _keep_awake(enable: bool, undo: bool = False) -> bool:
    """Ask Windows not to suspend while THIS process lives (SetThreadExecutionState; per process, reverts on exit,
    no system setting is changed). The display may still turn off."""
    if not (enable or undo) or sys.platform != "win32":
        return False
    es_continuous, es_system_required = 0x80000000, 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(es_continuous if undo else es_continuous | es_system_required)
    return not undo


# ───────────────────────── run ─────────────────────────
async def run(args: argparse.Namespace) -> int:
    scenarios = [s for s in build_p5_scenarios() if not args.scenarios or s.id in args.scenarios]
    body = [s for s in scenarios if s.cold_pair is None and s.id != "LATENCY_long_cold"]
    pair = [s for s in scenarios if s.id in ("LATENCY_long_cold", "LATENCY_long_warm")]  # kept adjacent, last
    out = args.out / f"p5-{datetime.now():%Y%m%d-%H%M%S}-ctx{args.context}"
    out.mkdir(parents=True, exist_ok=True)
    base = LLMSettings.from_env()
    meta = {"started": datetime.now().isoformat(timespec="seconds"), "python": platform.python_version(),
            "os": platform.platform(), "models": args.models, "rounds": args.rounds, "context": args.context,
            "think": False, "temperature": base.temperature, "base_seed": base.seed, "call_timeout_s": CALL_TIMEOUT_S,
            "scenarios": [s.id for s in scenarios], "cooldown_s": args.cooldown,
            "ollama_env": "NUM_PARALLEL=1 MAX_LOADED_MODELS=1 KEEP_ALIVE=10m (runtime/tools/ollama-serve.ps1)",
            "boot_sample": sample_system()}
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    raw = (out / "raw.jsonl").open("a", encoding="utf-8")
    baseline: dict[str, float] = {}
    collapsed: dict[str, int] = {m: 0 for m in args.models}
    consecutive_timeouts = 0
    deadline = time.monotonic() + args.max_minutes * 60
    abort: str | None = None
    invalid_calls = 0
    awake = _keep_awake(args.keep_awake)

    for rnd in range(1, args.rounds + 1):
        order = body[:]
        random.Random(1000 + rnd).shuffle(order)  # same order for every model in this round
        order += pair
        nonce = f"r{rnd}"
        for model in args.models:
            settings = dataclasses.replace(base.with_model(model), context=args.context, seed=base.seed + rnd)
            settings.validate()
            provider = OllamaProvider(settings)
            tps: list[float] = []
            try:
                for _attempt in (1, 2):
                    w = await warmup(provider)
                    raw.write(json.dumps({"round": rnd, "model": model, "context": args.context, **w,
                                          **sample_system()}) + "\n")
                    if not w.get("invalid"):
                        break
                    invalid_calls += 1
                for sc in order:
                    if time.monotonic() > deadline:
                        abort = f"time budget of {args.max_minutes} min reached"
                        break
                    rec = await one_call(provider, sc, nonce)
                    rec.update(round=rnd, model=model, context=args.context, seed=settings.seed, **sample_system())
                    raw.write(json.dumps(rec) + "\n")
                    raw.flush()
                    if rec.get("invalid"):  # suspension artifact: row kept, excluded from stats, run again once
                        invalid_calls += 1
                        rec = await one_call(provider, sc, nonce)
                        rec.update(round=rnd, model=model, context=args.context, seed=settings.seed, retry=True,
                                   **sample_system())
                        raw.write(json.dumps(rec) + "\n")
                        raw.flush()
                    print(f"r{rnd} {model[:12]:12} {sc.id:24} {'ok  ' if rec['ok'] else 'FAIL'} "
                          f"{rec.get('total_s') and round(rec['total_s'], 1)}s", file=sys.stderr)
                    consecutive_timeouts = consecutive_timeouts + 1 if rec.get("error") == "LLMTimeout" else 0
                    if consecutive_timeouts >= 3:
                        abort = "3 consecutive timeouts"
                        break
                    if rec.get("gen_tps") and (rec.get("completion_tokens") or 0) >= 10:
                        tps.append(rec["gen_tps"])
            finally:
                await provider.aclose()
            if abort:
                break
            if tps:
                med = statistics.median(tps)
                baseline.setdefault(model, med)
                collapsed[model] = collapsed[model] + 1 if med < DROP_RATIO * baseline[model] else 0
                if collapsed[model] >= 2:
                    abort = (f"sustained throughput collapse on {model}: round median {med:.1f} tok/s < "
                             f"{DROP_RATIO:.0%} of baseline {baseline[model]:.1f} (thermal/contention suspected)")
                    break
        if abort:
            break
        if rnd < args.rounds:
            await asyncio.sleep(args.cooldown)

    raw.close()
    if awake:
        _keep_awake(False, undo=True)
    meta.update(finished=datetime.now().isoformat(timespec="seconds"), aborted=abort, invalid_calls=invalid_calls,
                keep_awake=args.keep_awake,
                end_sample=sample_system(), round_baseline_tps=baseline)
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    analyze(out)
    print(f"saved to {out}" + (f"  ABORTED: {abort}" if abort else ""), file=sys.stderr)
    return 2 if abort else 0


# ───────────────────────── analysis ─────────────────────────
def _stat(xs: list[float | None], nd: int = 2) -> dict[str, float | None]:
    v = [x for x in xs if x is not None]
    if not v:
        return {"n": 0, "median": None, "p95": None, "max": None}
    r = lambda x: None if x is None else round(x, nd)  # noqa: E731
    return {"n": len(v), "median": r(statistics.median(v)), "p95": r(percentile(v, 95)), "max": r(max(v))}


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    calls = [r for r in rows if "scenario" in r and not r.get("invalid")]  # suspension artifacts excluded
    out: dict[str, Any] = {"models": {}, "invalid_excluded": sum(1 for r in rows if r.get("invalid"))}
    for model in sorted({r["model"] for r in calls}):
        mrows = [r for r in calls if r["model"] == model]
        ent: dict[str, Any] = {"scenarios": {}, "categories": {}}
        for sid in sorted({r["scenario"] for r in mrows}):
            s = [r for r in mrows if r["scenario"] == sid]
            ent["scenarios"][sid] = {
                "category": s[0]["category"], "n": len(s), "passed": sum(1 for r in s if r["ok"]),
                "errors": sum(1 for r in s if r.get("error")),
                "fail_reasons": sorted({r["reason"] for r in s if not r["ok"]}),
                "total_s": _stat([r.get("total_s") for r in s]),
                "steady_s": _stat([None if r.get("total_s") is None else r["total_s"] - (r.get("load_s") or 0) for r in s]),
                "prompt_eval_s": _stat([r.get("prompt_eval_s") for r in s]),
                "prompt_tokens": _stat([r.get("prompt_tokens") for r in s], 0),
                "cached_prompt_tokens": _stat([r.get("cached_prompt_tokens") for r in s], 0),
                "prompt_new_tokens": _stat([r.get("prompt_new_tokens") for r in s], 0),
                "prompt_new_tps": _stat([r.get("prompt_new_tps") for r in s], 1),
                "gen_tps": _stat([r.get("gen_tps") for r in s if (r.get("completion_tokens") or 0) >= 10], 1),
                "completion_tokens": _stat([r.get("completion_tokens") for r in s], 0)}
        for cat in sorted({r["category"] for r in mrows}):
            c = [r for r in mrows if r["category"] == cat]
            ent["categories"][cat] = {"n": len(c), "passed": sum(1 for r in c if r["ok"])}
        ent["ram"] = {"infer_ws_mb": _stat([r.get("infer_ws_mb") for r in mrows], 0),
                      "infer_private_mb": _stat([r.get("infer_private_mb") for r in mrows], 0),
                      "ollama_ps_size_mb": _stat([r.get("ps_size_mb") for r in mrows], 0),
                      "sys_free_mb_min": min((r["sys_free_mb"] for r in mrows if r.get("sys_free_mb")), default=None)}
        ent["gen_tps_all"] = _stat([r.get("gen_tps") for r in mrows if (r.get("completion_tokens") or 0) >= 10], 1)
        out["models"][model] = ent
    return out


def analyze(out: Path) -> None:
    rows = [json.loads(line) for line in (out / "raw.jsonl").read_text(encoding="utf-8").splitlines() if line]
    agg = aggregate(rows)
    (out / "stats.json").write_text(json.dumps(agg, indent=2), encoding="utf-8")
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    L = [f"# P5 stats — ctx {meta['context']} · rounds {meta['rounds']} · {meta['started']}", ""]
    if meta.get("aborted"):
        L += [f"**ABORTED:** {meta['aborted']}", ""]
    if agg["invalid_excluded"]:
        L += [f"**{agg['invalid_excluded']} chamada(s) inválida(s) por suspensão do sistema, excluídas.**", ""]
    for model, ent in agg["models"].items():
        L += [f"## {model}", "", "Qualidade por categoria: " + ", ".join(
            f"{c} {v['passed']}/{v['n']}" for c, v in ent["categories"].items()), "",
            "| cenário | ok | total s med/p95 | steady s med | prompt tok (cache) | tokens novos | prompt s med | novos tok/s | gen tok/s med/p95 |",
            "|---|---|---|---|---|---|---|---|---|"]
        for sid, s in ent["scenarios"].items():
            L.append(f"| {sid} | {s['passed']}/{s['n']} | {s['total_s']['median']}/{s['total_s']['p95']} | "
                     f"{s['steady_s']['median']} | {s['prompt_tokens']['median']} (cache {s['cached_prompt_tokens']['median']}) | "
                     f"{s['prompt_new_tokens']['median']} | {s['prompt_eval_s']['median']} | {s['prompt_new_tps']['median']} | "
                     f"{s['gen_tps']['median']}/{s['gen_tps']['p95']} |")
        L += ["", f"RAM processos de inferência (WS MB): {ent['ram']['infer_ws_mb']}; privada MB: {ent['ram']['infer_private_mb']}; "
              f"tamanho segundo /api/ps MB: {ent['ram']['ollama_ps_size_mb']}; "
              f"RAM livre mínima do sistema: {ent['ram']['sys_free_mb_min']} MB", ""]
    (out / "stats.md").write_text("\n".join(L), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--models", nargs="+", default=MODELS)
    p.add_argument("--rounds", type=int, default=5)
    p.add_argument("--context", type=int, default=4096)
    p.add_argument("--scenarios", nargs="*")
    p.add_argument("--cooldown", type=float, default=20.0, help="seconds between rounds")
    p.add_argument("--max-minutes", type=float, default=90.0)
    p.add_argument("--keep-awake", action="store_true", help="prevent system suspend while this process runs")
    p.add_argument("--out", type=Path, default=RESULTS_DIR)
    p.add_argument("--analyze", type=Path, help="re-aggregate an existing results directory and exit")
    a = p.parse_args(argv)
    if a.analyze:
        analyze(a.analyze)
        return 0
    if not 1 <= a.rounds <= 20:
        p.error("--rounds must be 1..20")
    return asyncio.run(run(a))


if __name__ == "__main__":
    raise SystemExit(main())
