"""P5 investigation: why does a ~1.3k-token prompt cost 50-100 s on this CPU, and does `num_thread` change it?

Talks to the local Ollama directly (this probe is isolated from the public LLMProvider contract on purpose:
`num_thread` is a server-side tuning knob, not part of the Fit AI contract). Loopback only, no downloads,
strictly sequential, configurations interleaved per round so drift hits all of them equally.

    python -m bench.p5_prompt_cost --model qwen3:4b-instruct-2507-q4_K_M --threads 0 4 8 12 --rounds 3

`--threads 0` means "do not send num_thread" (the Ollama default; the server log shows n_threads = 6).
Each call uses a unique nonce at the start of the user turn so the user turn is never cached, and asks for 8
tokens, so the time is almost purely prompt processing. Output: bench/results/p5-promptcost-<stamp>.json.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from bench.p5_scenarios import _FILLER
from fit_ai.ai import LLMSettings, load_system_prompt
from fit_ai.ai.config import validate_loopback_url

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def chat(base: str, model: str, nonce: str, filler_reps: int, num_thread: int, ctx: int, seed: int) -> dict:
    user = f"[{nonce}] " + _FILLER * filler_reps + "\n\nCom base no texto acima, cite um item de manutenção preventiva."
    options = {"num_ctx": ctx, "num_predict": 8, "temperature": 0.2, "seed": seed}
    if num_thread:
        options["num_thread"] = num_thread
    body = {"model": model, "stream": False, "think": False, "options": options,
            "messages": [{"role": "system", "content": load_system_prompt().text}, {"role": "user", "content": user}]}
    req = urllib.request.Request(base + "/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=300) as r:  # base validated as loopback by the caller
        d = json.loads(r.read())
    ns = lambda k: (d.get(k) or 0) / 1e9  # noqa: E731
    new = d.get("prompt_eval_count")
    return {"num_thread": num_thread, "wall_s": round(time.perf_counter() - t0, 2), "prompt_eval_count": new,
            "prompt_eval_s": round(ns("prompt_eval_duration"), 2), "load_s": round(ns("load_duration"), 2),
            "total_s": round(ns("total_duration"), 2),
            "prompt_tps": round(new / ns("prompt_eval_duration"), 1) if new and ns("prompt_eval_duration") else None}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default="qwen3:4b-instruct-2507-q4_K_M")
    p.add_argument("--threads", type=int, nargs="+", default=[0, 4, 8, 12])
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--filler", type=int, default=20, help="~1.3k tokens at 20")
    p.add_argument("--context", type=int, default=4096)
    a = p.parse_args()
    base = validate_loopback_url(LLMSettings.from_env().ollama_url)
    rows = []
    for rnd in range(1, a.rounds + 1):
        for th in a.threads:
            r = chat(base, a.model, f"r{rnd}t{th}", a.filler, th, a.context, 42 + rnd)
            r["round"] = rnd
            rows.append(r)
            print(f"round {rnd} num_thread={th or 'default'}: prompt {r['prompt_eval_count']} tok in "
                  f"{r['prompt_eval_s']}s = {r['prompt_tps']} tok/s (load {r['load_s']}s)", file=sys.stderr)
    summary = {}
    for th in a.threads:
        v = [r["prompt_tps"] for r in rows if r["num_thread"] == th and r["prompt_tps"]]
        summary[str(th or "default")] = {"n": len(v), "median_prompt_tps": round(statistics.median(v), 1) if v else None,
                                         "min": min(v, default=None), "max": max(v, default=None)}
    out = RESULTS_DIR / f"p5-promptcost-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"model": a.model, "context": a.context, "filler_reps": a.filler,
                               "summary": summary, "rows": rows}, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"saved to {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
