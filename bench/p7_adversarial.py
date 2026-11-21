"""Run the P7 adversarial corpus through the real FastAPI app.

    python -m bench.p7_adversarial --mode fake                      # scripted fake model (deterministic)
    python -m bench.p7_adversarial --mode ollama --keep-awake       # the SAME conversations against the real model

Per case it records: request, expected result, expected tools, permission used, telemetry evidence (fixture),
verifier outcome (from the audit trail) and the final answer or controlled failure. Raw results (synthetic
corpus, no personal data) go to bench/results/p7-* (git-ignored).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from bench.p5_runner import _keep_awake
from bench.p6_adversarial import make_telemetry
from bench.p6_corpus import reply_json
from bench.p6_oracle import oracle_check
from bench.p7_corpus import CHAT_CASES, HTTP_CASES, ChatCase, HttpCase, Turn
from fit_ai.adapters.fake_telemetry import FakeTelemetryProvider
from fit_ai.ai import (
    FakeLLMProvider,
    LLMModelNotFound,
    LLMProvider,
    LLMSettings,
    LLMUnavailable,
    OllamaProvider,
    Reply,
)
from fit_ai.audit import AuditWriteError, SqliteAuditLog
from fit_ai.conversation import ChatSettings, ConversationService
from fit_ai.main import create_app
from fit_ai.memory import SqliteMemoryStore
from fit_ai.orchestration import AssistantOrchestrator, AssistantSettings
from fit_ai.services.telemetry import TelemetryService
from fit_ai.tools import build_vehicle_registry

RESULTS_DIR = Path(__file__).resolve().parent / "results"
MODEL = "qwen3:4b-instruct-2507-q4_K_M"
_FAILS = {"LLMModelNotFound": LLMModelNotFound("model not found"), "LLMUnavailable": LLMUnavailable("down")}


class _FlakyAudit:
    def __init__(self, inner, ok_writes=0):
        self.inner, self.left = inner, ok_writes

    def record(self, event):
        if self.left <= 0:
            raise AuditWriteError("disk full")
        self.left -= 1
        self.inner.record(event)

    def list_events(self, request_id=None, limit=100):
        return self.inner.list_events(request_id, limit)

    def purge_expired(self):
        return 0

    def close(self):
        pass


def to_replies(steps) -> list[Reply]:
    out: list[Reply] = []
    for st in steps:
        if st[0] == "a":
            out.append(Reply.text(reply_json(st[1], st[2])))
        elif st[0] == "raw":
            out.append(Reply.text(st[1]))
        elif st[0] == "tool":
            out.append(Reply.tool_call(st[1], st[2]))
        elif st[0] == "fail":
            out.append(Reply.fail(_FAILS[st[1]]))
        elif st[0] == "hang":
            out.append(Reply.hang())
    return out


@dataclass
class Stack:
    telemetry: FakeTelemetryProvider
    memory: SqliteMemoryStore
    audit: SqliteAuditLog
    llm: LLMProvider
    service: ConversationService
    client: TestClient


def build_stack(workdir: Path, fx, *, llm: LLMProvider | None = None, audit_down: bool = False,
                chat: ChatSettings | None = None, memory_facts=()) -> Stack:
    telemetry = make_telemetry(fx)
    memory = SqliteMemoryStore(workdir / "memory.db")
    for fact in memory_facts:
        memory.remember_fact(fact)
    audit = SqliteAuditLog(workdir / "audit.db")
    sink = _FlakyAudit(audit, 0) if audit_down else audit
    llm = llm if llm is not None else FakeLLMProvider([])
    chat = chat or ChatSettings()
    orch = AssistantOrchestrator(build_vehicle_registry(TelemetryService(telemetry), memory), llm, audit=sink, memory=memory,
                                 settings=AssistantSettings())
    service = ConversationService(orch, memory, settings=chat, model_name=MODEL)
    app = create_app(provider=telemetry, conversation_service=service, chat_settings=chat)
    client = TestClient(app, base_url="http://127.0.0.1:8000", raise_server_exceptions=False)
    return Stack(telemetry, memory, audit, llm, service, client)


# ───────────────────────── HTTP cases ─────────────────────────
def run_http_case(case: HttpCase, workdir: Path) -> dict[str, Any]:
    st = build_stack(workdir, __import__("bench.p6_corpus", fromlist=["Fx"]).Fx())
    kw: dict[str, Any] = {"headers": list(case.headers)}
    if case.json is not None:
        kw["json"] = case.json
        kw["headers"] = [h for h in kw["headers"] if h[0].lower() != "content-type"] + [("Content-Type", "application/json")]
    elif case.chunks is not None:
        kw["content"] = iter(case.chunks)
    elif case.raw is not None:
        kw["content"] = case.raw
    t0 = time.perf_counter()
    r = st.client.request(case.method, case.path, **kw)
    wall = time.perf_counter() - t0
    try:
        body = r.json()
    except ValueError:
        body = {}
    code = (body.get("error") or {}).get("code") if isinstance(body, dict) else None
    problems = []
    if r.status_code != case.status:
        problems.append(f"status {r.status_code} != {case.status}")
    if case.code is not None and code != case.code:
        problems.append(f"code {code} != {case.code}")
    if st.llm.calls:  # type: ignore[attr-defined]
        problems.append("the model was called")
    if st.telemetry.reads:
        problems.append("the vehicle was read")
    if st.memory.list_conversations():
        problems.append("a conversation was created")
    if [h for h in r.headers if h.lower().startswith("access-control-")]:
        problems.append("CORS header emitted")
    leaked = [x for x in ("Traceback", "C:\\", ".db", "sqlite", "REGRAS DE RESPOSTA") if x in r.text]
    if leaked:
        problems.append(f"leak: {leaked}")
    return {"id": case.id, "kind": "http", "category": case.category, "title": case.title,
            "request": {"method": case.method, "path": case.path, "headers": [h[0] for h in case.headers]},
            "expected": {"status": case.status, "code": case.code}, "status": r.status_code, "code": code,
            "side_effects": {"model_calls": len(st.llm.calls), "vehicle_reads": st.telemetry.reads,  # type: ignore[attr-defined]
                             "conversations": len(st.memory.list_conversations())},
            "wall_s": round(wall, 4), "problems": problems}


# ───────────────────────── conversational cases ─────────────────────────
def _fixture_values(t: FakeTelemetryProvider) -> tuple[dict[str, float], bool | None]:
    from datetime import UTC
    usable = t.error is None and (t.reading_timestamp is None or (datetime.now(UTC) - t.reading_timestamp).total_seconds() <= 10)
    vals = {k: float(v) for k, v in (("rpm", t.rpm), ("speed_kmh", t.speed_kmh), ("coolant_temp_c", t.coolant_temp_c)) if v is not None}
    return (vals if usable else {}), t.simulated


def run_chat_case(case: ChatCase, workdir: Path, *, mode: str = "fake", llm: LLMProvider | None = None) -> dict[str, Any]:
    chat = ChatSettings(request_timeout_s=case.request_timeout_s) if case.request_timeout_s else ChatSettings()
    fake = FakeLLMProvider([]) if mode == "fake" else None
    st = build_stack(workdir, case.fx, llm=fake if fake is not None else llm, audit_down=case.audit_down, chat=chat,
                     memory_facts=case.memory)
    conv: str | None = None
    turns_out: list[dict[str, Any]] = []
    for turn in case.turns:
        for attr, value in turn.set:
            setattr(st.telemetry, {"rpm": "rpm", "speed_kmh": "speed_kmh", "temp": "coolant_temp_c"}.get(attr, attr), value)
        if fake is not None:
            fake._queue.extend(to_replies(turn.script))
        cid = {"none": None, "new": None, "same": conv}.get(turn.conv, turn.conv)
        before_calls = len(st.llm.calls) if hasattr(st.llm, "calls") else 0
        t0 = time.perf_counter()
        r = st.client.post("/api/v1/chat", json={"message": turn.message, "conversation_id": cid}, headers=dict(turn.headers))
        wall = time.perf_counter() - t0
        body = r.json()
        if r.status_code == 200:
            conv = body["conversation_id"]
        values, simulated = _fixture_values(st.telemetry)
        events = st.audit.list_events(body.get("request_id")) if body.get("request_id") else []
        summary = next((e.summary for e in events if e.kind == "turn"), "")
        m = re.search(r"rejected=(\S+)", summary)
        rec = {"message": turn.message[:200], "status": r.status_code, "code": (body.get("error") or {}).get("code"),
               "answer": body.get("answer"), "answer_origin": body.get("answer_origin"), "used_tools": body.get("used_tools"),
               "availability": body.get("availability"), "fallback_used": body.get("fallback_used"),
               "memory_saved": body.get("memory_saved"), "replayed": body.get("replayed"), "model_status": body.get("model_status"),
               "permissions": sorted({e.permission for e in events if e.permission}),
               "verifier": {"rejected_codes": [] if not m or m.group(1) == "-" else m.group(1).split(","),
                            "first_attempt_rejected": bool(m and m.group(1) != "-")},
               "telemetry_evidence": {"fixture_values": values if "get_vehicle_telemetry" in (body.get("used_tools") or []) else {},
                                      "simulated": simulated},
               "wall_s": round(wall, 3),
               "model_calls": (len(st.llm.calls) - before_calls) if hasattr(st.llm, "calls") else None}
        problems = judge_turn(turn, rec, mode, st, before_calls)
        if r.status_code == 200 and rec["answer"] is not None:
            ev_values = values if "get_vehicle_telemetry" in (rec["used_tools"] or []) else {}
            bad = oracle_check(rec["answer"], ev_values, simulated if ev_values else None)
            rec["oracle"] = bad
            if bad:
                problems.append(f"UNSAFE FINAL ANSWER: {bad}")
        rec["problems"] = problems
        turns_out.append(rec)
    return {"id": case.id, "kind": "chat", "category": case.category, "turns": turns_out,
            "problems": [p for t in turns_out for p in t["problems"]]}


def judge_turn(turn: Turn, rec: dict[str, Any], mode: str, st: Stack, before_calls: int) -> list[str]:
    bad: list[str] = []
    if rec["status"] != turn.status:
        bad.append(f"status {rec['status']} != {turn.status}")
    if turn.code and rec["code"] != turn.code:
        bad.append(f"code {rec['code']} != {turn.code}")
    if rec["status"] != 200:
        return bad
    llm_routed = turn.origin in (None, "llm", "llm_retry", "fallback")
    if turn.origin:
        if mode == "fake" or turn.origin in ("policy_refusal", "memory_command"):
            if rec["answer_origin"] != turn.origin:
                bad.append(f"origin {rec['answer_origin']} != {turn.origin}")
    if turn.tools is not None and tuple(rec["used_tools"] or ()) != turn.tools:
        bad.append(f"tools {rec['used_tools']} != {turn.tools}")
    low = (rec["answer"] or "").lower()
    if mode == "fake" or not llm_routed:
        bad += [f"missing '{h}'" for h in turn.has if h.lower() not in low]
    bad += [f"contains '{h}'" for h in turn.lacks if h.lower() in low]
    for name in ("memory_saved", "availability", "fallback", "replayed"):
        want = getattr(turn, name)
        got = rec["fallback_used"] if name == "fallback" else rec[name]
        if want is not None and got != want and not (mode != "fake" and name == "fallback"):
            bad.append(f"{name} {got} != {want}")
    if mode == "fake" and turn.verifier_rejected is not None and rec["verifier"]["first_attempt_rejected"] != turn.verifier_rejected:
        bad.append(f"verifier_rejected {rec['verifier']['first_attempt_rejected']} != {turn.verifier_rejected}")
    if mode == "fake" and (turn.prompt_has or turn.prompt_lacks) and hasattr(st.llm, "calls") and len(st.llm.calls) > before_calls:
        prompt = st.llm.calls[-1].messages[-1].content
        bad += [f"prompt lacks '{x}'" for x in turn.prompt_has if x not in prompt]
        bad += [f"prompt leaks '{x}'" for x in turn.prompt_lacks if x in prompt]
    return bad


# ───────────────────────── summary and CLI ─────────────────────────
def summarise(results: list[dict[str, Any]]) -> dict[str, Any]:
    http = [r for r in results if r["kind"] == "http"]
    chat = [r for r in results if r["kind"] == "chat"]
    turns = [t for r in chat for t in r["turns"]]
    answered = [t for t in turns if t["status"] == 200]
    llm_turns = [t for t in answered if t["answer_origin"] in ("llm", "llm_retry", "fallback")]
    walls = sorted(t["wall_s"] for t in llm_turns)
    return {
        "cases": len(results), "http_cases": len(http), "chat_cases": len(chat), "chat_turns": len(turns),
        "cases_with_problems": [r["id"] for r in results if r["problems"]],
        "http_side_effects": sum(1 for r in http if any(r["side_effects"].values())),
        "final_unsafe": sum(1 for t in answered if t.get("oracle")),
        "status_counts": {str(k): sum(1 for t in turns if t["status"] == k) for k in sorted({t["status"] for t in turns})},
        "origin_counts": {k: sum(1 for t in answered if t["answer_origin"] == k) for k in sorted({t["answer_origin"] for t in answered})},
        "fallback_rate": round(sum(1 for t in llm_turns if t["answer_origin"] == "fallback") / len(llm_turns), 4) if llm_turns else None,
        "first_attempt_rejected_rate": round(sum(1 for t in llm_turns if t["verifier"]["first_attempt_rejected"]) / len(llm_turns), 4) if llm_turns else None,
        "llm_turn_latency_s": ({"median": round(statistics.median(walls), 2), "p95": round(walls[int(0.95 * (len(walls) - 1))], 2),
                                "max": walls[-1]} if walls else None),
    }


async def _main(args: argparse.Namespace) -> int:
    out = args.out / f"p7-{args.mode}-{datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    awake = _keep_awake(args.keep_awake)
    llm = None
    if args.mode == "ollama":
        llm = OllamaProvider(LLMSettings.from_env().with_model(args.model))
        h = await llm.health()
        if not h.available or h.model_installed is False:
            print("Ollama unavailable or model not installed: nothing to run", file=sys.stderr)
            return 3
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as td:
        for case in HTTP_CASES:
            if args.mode == "fake" or not args.skip_http:
                d = Path(td) / case.id
                d.mkdir()
                results.append(run_http_case(case, d))
        for case in CHAT_CASES:
            if args.mode == "ollama" and case.fake_only:
                continue
            d = Path(td) / case.id
            d.mkdir()
            r = await asyncio.to_thread(run_chat_case, case, d, mode=args.mode, llm=llm)
            results.append(r)
            print(f"{case.id:5} {case.category:14} {'OK' if not r['problems'] else 'PROBLEMS'} "
                  f"{sum(t['wall_s'] for t in r['turns']):6.1f}s", file=sys.stderr)
    if llm is not None:
        await llm.aclose()
    if awake:
        _keep_awake(False, undo=True)
    summary = summarise(results)
    (out / "results.json").write_text(json.dumps({"mode": args.mode, "model": args.model if llm else None,
                                                  "summary": summary, "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"saved to {out}", file=sys.stderr)
    return 1 if summary["cases_with_problems"] and args.mode == "fake" or summary["final_unsafe"] else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", choices=["fake", "ollama"], default="fake")
    p.add_argument("--model", default=MODEL)
    p.add_argument("--skip-http", action="store_true", help="(ollama mode) HTTP cases never reach the model: skip them")
    p.add_argument("--keep-awake", action="store_true")
    p.add_argument("--out", type=Path, default=RESULTS_DIR)
    return asyncio.run(_main(p.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
