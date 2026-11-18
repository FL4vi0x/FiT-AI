"""Benchmark harness for the AI Engine (PoC 03 / P4): sequential, reproducible, no parallel load.

    python -m bench.run_benchmark --models qwen3:4b-instruct-2507-q4_K_M --repeat 1
    python -m bench.run_benchmark --provider fake            # dry run, no Ollama needed

This is a FUNCTIONAL harness. Statistical model comparison (many samples) belongs to P5.
Timings are the provider's own (`total_s` is NOT time-to-first-token; TTFT is not measured: no streaming).
Results go to bench/results/<timestamp>/ (git-ignored) and contain metrics only, never prompts or answers
(unless --include-content is passed explicitly).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import platform
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from bench.scenarios import Scenario, build_scenarios
from fit_ai.ai import FakeLLMProvider, LLMError, LLMProvider, LLMSettings, OllamaProvider, Reply

RESULTS_DIR = Path(__file__).resolve().parent / "results"
DEFAULT_MODELS = ["qwen3:4b-instruct-2507-q4_K_M"]


async def run_scenario(provider: LLMProvider, sc: Scenario, settings: LLMSettings,
                       include_content: bool) -> dict[str, Any]:
    rec: dict[str, Any] = {"scenario": sc.id, "context": settings.context, "temperature": settings.temperature,
                           "seed": settings.seed, "max_tokens": sc.max_tokens or settings.max_tokens,
                           "think": settings.think if sc.think is None else sc.think}
    t0 = time.perf_counter()
    try:
        r = await provider.generate(sc.messages, tools=sc.tools, response_format=sc.response_format,
                                    max_tokens=sc.max_tokens, think=sc.think)
    except LLMError as exc:
        rec.update(ok=False, error=type(exc).__name__, error_detail=str(exc)[:200],
                   wall_s=round(time.perf_counter() - t0, 3))
        return rec
    rec["wall_s"] = round(time.perf_counter() - t0, 3)
    problem = sc.check(r)
    rec.update(ok=problem is None, check_failure=problem, finish_reason=r.finish_reason,
               prompt_tokens=r.usage.prompt_tokens, completion_tokens=r.usage.completion_tokens,
               load_s=r.timings.load_s, prompt_eval_s=r.timings.prompt_eval_s,
               generation_s=r.timings.generation_s, total_s=r.timings.total_s,
               prompt_tokens_per_s=r.prompt_tokens_per_s, generation_tokens_per_s=r.generation_tokens_per_s,
               tool_calls=[c.name for c in r.tool_calls], content_chars=len(r.content),
               thinking_chars=r.thinking_chars)
    if include_content:
        rec["content"] = r.content
    return rec


def _fake_provider(model: str) -> FakeLLMProvider:
    # Dry run only validates the harness plumbing: scenario checks that need JSON/tool output will FAIL here.
    return FakeLLMProvider(model=model, default=Reply.text("Resposta simulada.", completion_tokens=5))


async def run(args: argparse.Namespace) -> dict[str, Any]:
    scenarios = [s for s in build_scenarios() if not args.scenarios or s.id in args.scenarios]
    base = LLMSettings.from_env()
    report: dict[str, Any] = {"started": datetime.now().isoformat(timespec="seconds"), "provider": args.provider,
                              "python": platform.python_version(), "os": platform.platform(),
                              "repeat": args.repeat, "note": "functional run; not a statistical benchmark",
                              "models": []}
    for model in args.models:
        settings = base.with_model(model)
        provider: LLMProvider = _fake_provider(model) if args.provider == "fake" else OllamaProvider(settings)
        entry: dict[str, Any] = {"model": model, "runs": []}
        try:
            health = await provider.health()
            entry["health"] = health.model_dump()
            if not health.available or health.model_installed is False:
                entry["skipped"] = "server unavailable" if not health.available else "model not installed"
            else:
                for sc in scenarios:  # strictly sequential
                    for i in range(args.repeat):
                        rec = await run_scenario(provider, sc, settings, args.include_content)
                        rec["iteration"] = i + 1
                        entry["runs"].append(rec)
                        rate = rec.get("generation_tokens_per_s")
                        print(f"{model} {sc.id} #{i + 1}: {'ok' if rec['ok'] else 'FAIL'} "
                              f"{round(rate, 1) if rate else '-'} tok/s", file=sys.stderr)
        finally:
            if hasattr(provider, "aclose"):
                await provider.aclose()
        report["models"].append(entry)
    report["finished"] = datetime.now().isoformat(timespec="seconds")
    return report


def _cell(r: dict[str, Any], key: str, nd: int = 2) -> Any:
    v = r.get(key)
    if v is None:
        return ""
    return round(v, nd) if isinstance(v, float) else v


def summarize(report: dict[str, Any]) -> str:
    lines = ["# Benchmark funcional (P4)", "",
             f"Provider: `{report['provider']}` · repeat: {report['repeat']} · {report['started']}", "",
             "> Run funcional curto, não estatístico. `total_s` não é tempo até o primeiro token "
             "(TTFT não medido).", ""]
    for m in report["models"]:
        digest = (m.get("health") or {}).get("model_digest") or "n/d"
        lines += [f"## {m['model']}", f"digest: `{digest}`", ""]
        if "skipped" in m:
            lines += [f"**Ignorado:** {m['skipped']}", ""]
            continue
        lines += ["| cenário | ok | prompt tok | gerados | load s | total s | gen tok/s | erro |",
                  "|---|---|---|---|---|---|---|---|"]
        for r in m["runs"]:
            err = r.get("error") or r.get("check_failure") or ""
            lines.append(f"| {r['scenario']} | {'sim' if r['ok'] else 'NÃO'} | {_cell(r, 'prompt_tokens')} | "
                         f"{_cell(r, 'completion_tokens')} | {_cell(r, 'load_s')} | {_cell(r, 'total_s')} | "
                         f"{_cell(r, 'generation_tokens_per_s', 1)} | {err} |")
        rates = [r["generation_tokens_per_s"] for r in m["runs"] if r.get("generation_tokens_per_s")]
        if rates:
            lines += ["", f"Mediana de geração: {statistics.median(rates):.1f} tok/s (n={len(rates)})"]
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    p.add_argument("--provider", choices=["ollama", "fake"], default="ollama")
    p.add_argument("--scenarios", nargs="*", help="scenario ids (default: all)")
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--include-content", action="store_true", help="also store model answers (off by default)")
    p.add_argument("--out", type=Path, default=RESULTS_DIR)
    args = p.parse_args(argv)
    if not 1 <= args.repeat <= 10:
        p.error("--repeat must be 1..10 (P5 owns large samples)")
    report = asyncio.run(run(args))
    out = args.out / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md = summarize(report)
    (out / "summary.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"\nsaved to {out}", file=sys.stderr)
    failed = any(not r["ok"] for m in report["models"] for r in m["runs"])
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
