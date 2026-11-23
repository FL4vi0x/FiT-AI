"""Internal turn orchestrator (P6). NOT an HTTP endpoint: P7 will wrap it.

Flow of one turn:
  1. classify the request deterministically (control requests are refused without calling the model);
  2. execute ONLY the READ tools that intent needs (at most one round, never model-chosen);
  3. turn tool outcomes into per-turn evidence;
  4. ask the LLM once for a structured answer (compact prompt, stable prefix);
  5. verify it with code; if rejected, ONE corrective retry; if still rejected, a deterministic answer
     built from the evidence alone. The LLM is never the last authority on a sensor value;
  6. persist the (telemetry-free) turn, audit every decision.
Every tool the model asks for is refused and audited: tools are executed by this layer, not by the model.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Literal

from fit_ai.ai import ChatMessage, LLMError, LLMIncompleteResponse, LLMInvalidResponse, LLMProvider
from fit_ai.audit import AuditEvent, AuditSink, AuditWriteError
from fit_ai.grounding import (
    RESPONSE_SCHEMA,
    EvidenceBundle,
    ResponseFormatError,
    StructuredAnswer,
    build_evidence,
    parse_structured,
    render_fallback,
    render_unavailable_info,
    verify,
)
from fit_ai.grounding.evidence import TELEMETRY_TOOL
from fit_ai.memory import ContextRetriever, MemoryError_, MemoryStore
from fit_ai.memory.models import MemoryHit
from fit_ai.orchestration.config import AssistantSettings
from fit_ai.orchestration.intent import MEMORY_TOOL, Intent, classify
from fit_ai.orchestration.prompt import correction_message, leaks_prompt, system_message, user_message
from fit_ai.tools import ToolOutcome, ToolRegistry

log = logging.getLogger("fit_ai.orchestration")

Source = Literal["llm", "llm_retry", "fallback", "deterministic", "policy_refusal", "audit_refusal"]

CONTROL_REFUSAL = ("Eu só leio dados do veículo e converso: não executo ações nem controlo o carro. "
                   "Posso informar uma leitura de rotação, velocidade ou temperatura.")
AUDIT_REFUSAL = "Não posso responder agora porque o registro de auditoria está indisponível."
HISTORY_PLACEHOLDER = "[resposta com leitura de telemetria — os valores não são guardados no histórico]"
MAX_REQUEST_CHARS = 2000


@dataclass(frozen=True)
class TurnRequest:
    text: str
    conversation_id: str | None = None  # an EXISTING conversation: used to recall its recent turns
    persist: bool = True  # False: the caller (ConversationService) persists the exchange itself
    request_id: str | None = None  # the caller's (server-generated) id, so audit records match the HTTP response


@dataclass(frozen=True)
class TurnResult:
    request_id: str
    turn_id: str
    answer: str
    source: Source
    intent: str
    tools: tuple[str, ...]
    tool_outcomes: tuple[ToolOutcome, ...]
    evidence: EvidenceBundle
    llm_calls: int = 0
    first_attempt_ok: bool | None = None  # None: the LLM was not asked / failed
    first_attempt_codes: tuple[str, ...] = ()
    final_codes: tuple[str, ...] = ()  # why the last LLM attempt was rejected (empty when accepted)
    llm_error: str | None = None
    injection_suspected: bool = False
    audit_degraded: bool = False
    memory_error: bool = False
    timings_ms: dict[str, float] = field(default_factory=dict)
    first_raw: str | None = field(default=None, repr=False, compare=False)  # first model answer text (evaluation only)


def history_text(answer: str, bundle: EvidenceBundle) -> str:
    """What an assistant answer looks like in the stored history: a turn that used telemetry never keeps its
    values (they are temporary, and old readings must not be mistaken for the current state)."""
    return HISTORY_PLACEHOLDER if bundle.telemetry or bundle.status else answer


class _AuditBlocked(Exception):
    """Fail-closed policy: an audit record could not be written."""


class AssistantOrchestrator:
    def __init__(
        self,
        registry: ToolRegistry,
        llm: LLMProvider | None,
        *,
        audit: AuditSink,
        memory: MemoryStore | None = None,
        settings: AssistantSettings | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._registry, self._llm, self._audit, self._memory = registry, llm, audit, memory
        self._settings = settings or AssistantSettings()
        self._clock = clock
        self._retriever = ContextRetriever(memory, clock=clock) if memory is not None else None

    # ───────────────────────── public ─────────────────────────
    async def run(self, request: TurnRequest) -> TurnResult:
        t0 = time.perf_counter()
        request_id, turn_id = request.request_id or uuid.uuid4().hex, uuid.uuid4().hex
        text = request.text.strip()[:MAX_REQUEST_CHARS]
        intent = classify(text)
        bundle = EvidenceBundle(turn_id, self._settings.telemetry_max_age_s)
        ctx = _Ctx(request_id, turn_id, bundle)
        try:
            return await self._run(request, text, intent, ctx, t0)
        except _AuditBlocked:
            log.error("audit unavailable: the turn was refused (fail_closed policy)")
            return self._result(ctx, AUDIT_REFUSAL, "audit_refusal", intent, t0)

    # ───────────────────────── the turn ─────────────────────────
    async def _run(self, request: TurnRequest, text: str, intent: Intent, ctx: "_Ctx", t0: float) -> TurnResult:
        if intent.injection:
            self._emit(ctx, "policy", "ok", summary="possible instruction-override attempt (flagged, handled normally)")
        if intent.control:
            self._emit(ctx, "policy", "refused", error_code="control_request",
                       summary="request to act on the vehicle refused without calling the model")
            res = self._result(ctx, CONTROL_REFUSAL, "policy_refusal", intent, t0, intent_obj=intent)
            self._finish(ctx, res)
            return res

        # 2 — READ tools needed by the intent (registered ones only)
        wanted = tuple(n for n in intent.tools if n in self._registry.names)
        tools_t = time.perf_counter()
        memory_facts: list[MemoryHit] | None = None
        for name in wanted:
            self._emit(ctx, "tool_authorization", "allowed", tool=name, permission="READ")
            args = {"query": text[:200], "limit": 3} if name == MEMORY_TOOL else {}
            outcome = await self._registry.execute(name, args, allowed=wanted, run_id=uuid.uuid4().hex)
            ctx.outcomes.append(outcome)
            self._emit(ctx, "tool_result", "ok" if outcome.ok else ("denied" if outcome.decision == "denied" else "error"),
                       tool=name, permission=outcome.permission, duration_ms=int(outcome.duration_s * 1000),
                       error_code=outcome.error_code, simulated=outcome.simulated, summary=_summarise(outcome))
            ev = build_evidence(outcome, ctx.turn_id)
            ctx.bundle.add(ev)
            if name == MEMORY_TOOL and outcome.ok and outcome.data:
                memory_facts = [MemoryHit(kind="fact", id=f["id"], content=f["content"],
                                          created_at=datetime.fromisoformat(f["created_at"].replace("Z", "+00:00")))
                                for f in outcome.data.get("facts", [])]
        ctx.timings["tools_ms"] = (time.perf_counter() - tools_t) * 1000

        # 4/5 — LLM + verification
        if self._llm is None:
            answer = self._safe_fallback(ctx, intent)
            source: Source = "deterministic"
            res = self._result(ctx, answer, source, intent, t0, intent_obj=intent)
        else:
            res = await self._with_llm(request, text, intent, ctx, memory_facts, t0)

        # 6 — persistence and the turn audit record
        res = self._persist(request, text, res, ctx)
        self._finish(ctx, res)
        return res

    async def _with_llm(self, request: TurnRequest, text: str, intent: Intent, ctx: "_Ctx",
                        memory_facts: list[MemoryHit] | None, t0: float) -> TurnResult:
        mem_t = time.perf_counter()
        memory_block = ""
        if self._retriever is not None:
            try:
                memory_block = await asyncio.to_thread(
                    lambda: self._retriever.recall(text, request.conversation_id, facts=memory_facts).rendered)
            except MemoryError_:
                log.exception("memory recall failed")
                ctx.memory_error = True
        ctx.timings["memory_ms"] = (time.perf_counter() - mem_t) * 1000

        base = [system_message(), user_message(text, ctx.bundle, memory_block)]
        has_readings = bool(ctx.bundle.telemetry or ctx.bundle.status)
        verify_ms = llm_ms = 0.0
        attempts: list[tuple[bool, tuple[str, ...]]] = []
        messages = list(base)
        accepted: StructuredAnswer | None = None
        for attempt in (1, 2):
            t_l = time.perf_counter()
            try:
                resp = await self._llm.generate(messages, response_format=RESPONSE_SCHEMA, think=False,
                                                max_tokens=self._settings.llm_max_tokens,
                                                timeout_s=self._settings.llm_timeout_s)
            except (LLMInvalidResponse, LLMIncompleteResponse) as exc:
                # the provider contract already rejected the output (invalid JSON, undeclared tool call, cut off):
                # that is an invalid structured answer, so it gets the same single corrective retry
                llm_ms += (time.perf_counter() - t_l) * 1000
                ctx.llm_calls += 1
                code = "llm_invalid_response" if isinstance(exc, LLMInvalidResponse) else "llm_incomplete_response"
                self._emit(ctx, "policy", "error", error_code=code,
                           summary="the model output was rejected by the provider contract (invalid or undeclared tool call)")
                attempts.append((False, (code,)))
                if attempt == 1:
                    messages = [*base, correction_message((code,), with_readings=has_readings)]
                    continue
                break
            except LLMError as exc:  # timeout, unavailable, transport...: retrying would not help
                llm_ms += (time.perf_counter() - t_l) * 1000
                ctx.llm_calls += 1
                ctx.llm_error = type(exc).__name__
                break
            llm_ms += (time.perf_counter() - t_l) * 1000
            ctx.llm_calls += 1

            for call in resp.tool_calls:  # the model may NOT run tools: refuse + audit each request
                refused = await self._registry.execute(call.name, call.arguments, allowed=frozenset(),
                                                       run_id=uuid.uuid4().hex)
                self._emit(ctx, "tool_authorization", "denied", tool=refused.requested_name,
                           permission=refused.permission, error_code=refused.error_code,
                           summary="tool call requested by the model was refused")

            t_v = time.perf_counter()
            codes: tuple[str, ...]
            parsed: StructuredAnswer | None = None
            if resp.tool_calls:
                codes = ("unexpected_tool_call",)
            else:
                try:
                    parsed = parse_structured(resp.content)
                    verdict = verify(parsed, ctx.bundle)
                    codes = verdict.codes
                    if not codes and leaks_prompt(parsed.answer):  # reciting the internal instructions
                        codes = ("prompt_leak",)
                except ResponseFormatError as exc:
                    codes = (exc.code,)
            verify_ms += (time.perf_counter() - t_v) * 1000
            if attempt == 1:
                ctx.first_raw = parsed.answer if parsed is not None else resp.content[:400]
            attempts.append((not codes, codes))
            if not codes:
                accepted = parsed
                break
            if attempt == 1:  # one corrective retry, with the rejected output and the reason
                messages = [*base]
                if resp.content.strip():
                    messages.append(ChatMessage.assistant(resp.content[:600]))
                messages.append(correction_message(codes, with_readings=has_readings))

        ctx.timings["llm_ms"], ctx.timings["verify_ms"] = llm_ms, verify_ms
        first_ok = attempts[0][0] if attempts else None
        first_codes = attempts[0][1] if attempts else ()
        if accepted is not None:
            source: Source = "llm" if len(attempts) == 1 else "llm_retry"
            return self._result(ctx, accepted.answer, source, intent, t0, intent_obj=intent, first_ok=first_ok,
                                first_codes=first_codes)
        final_codes = attempts[-1][1] if attempts else ()
        answer = self._safe_fallback(ctx, intent)
        return self._result(ctx, answer, "fallback", intent, t0, intent_obj=intent, first_ok=first_ok,
                            first_codes=first_codes, final_codes=final_codes)

    # ───────────────────────── helpers ─────────────────────────
    def _safe_fallback(self, ctx: "_Ctx", intent: Intent) -> str:
        text = render_fallback(ctx.bundle, intent.fields)
        check = verify(StructuredAnswer(answer=text), ctx.bundle)
        if not check.passed:  # a bug in the fallback must not become a wrong answer
            log.error("deterministic fallback failed verification: %s", check.codes)
            return render_unavailable_info()
        return text

    def _persist(self, request: TurnRequest, text: str, res: TurnResult, ctx: "_Ctx") -> TurnResult:
        if self._memory is None or request.conversation_id is None or not request.persist:
            return res
        stored = history_text(res.answer, ctx.bundle)
        try:
            self._memory.record_exchange(request.conversation_id, text, stored)  # atomic: both turns or none
        except MemoryError_:
            log.exception("could not persist the turn")
            return replace(res, memory_error=True)
        return res

    def _result(self, ctx: "_Ctx", answer: str, source: Source, intent: Intent | None, t0: float, *,
                intent_obj: Intent | None = None, first_ok: bool | None = None, first_codes: tuple[str, ...] = (),
                final_codes: tuple[str, ...] = ()) -> TurnResult:
        i = intent_obj or intent
        ctx.timings["total_ms"] = (time.perf_counter() - t0) * 1000
        return TurnResult(
            request_id=ctx.request_id, turn_id=ctx.turn_id, answer=answer, source=source,
            intent=i.kind if i else "general", tools=tuple(o.requested_name for o in ctx.outcomes),
            tool_outcomes=tuple(ctx.outcomes), evidence=ctx.bundle, llm_calls=ctx.llm_calls, first_attempt_ok=first_ok,
            first_attempt_codes=first_codes, final_codes=final_codes, llm_error=ctx.llm_error,
            injection_suspected=bool(i and i.injection), audit_degraded=ctx.audit_degraded,
            memory_error=ctx.memory_error, timings_ms={k: round(v, 2) for k, v in ctx.timings.items()},
            first_raw=ctx.first_raw)

    def _finish(self, ctx: "_Ctx", res: TurnResult) -> None:
        self._emit(ctx, "turn", "ok", error_code=res.llm_error, duration_ms=int(ctx.timings.get("total_ms", 0)),
                   simulated=ctx.bundle.simulated,
                   summary=(f"source={res.source} intent={res.intent} tools={len(res.tools)} llm_calls={res.llm_calls} "
                            f"rejected={','.join(res.final_codes or res.first_attempt_codes) or '-'}"))

    def _emit(self, ctx: "_Ctx", kind: str, decision: str, *, tool: str | None = None, permission: str | None = None,
              duration_ms: int | None = None, error_code: str | None = None, simulated: bool | None = None,
              summary: str = "") -> None:
        ev = AuditEvent(event_id=uuid.uuid4().hex, request_id=ctx.request_id, turn_id=ctx.turn_id,
                        timestamp=self._clock(), kind=kind, tool=tool, permission=permission, decision=decision,
                        summary=summary, duration_ms=duration_ms, error_code=error_code, simulated=simulated)
        try:
            self._audit.record(ev)
        except AuditWriteError:
            if self._settings.audit_policy == "fail_closed":
                raise _AuditBlocked from None
            # degrade_read_only: justified because every executable tool is READ (no side effect goes untraced)
            ctx.audit_degraded = True
            log.error("audit write failed; continuing under policy degrade_read_only")


@dataclass
class _Ctx:
    request_id: str
    turn_id: str
    bundle: EvidenceBundle
    outcomes: list[ToolOutcome] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    llm_calls: int = 0
    llm_error: str | None = None
    audit_degraded: bool = False
    memory_error: bool = False
    first_raw: str | None = None


def _summarise(o: ToolOutcome) -> str:
    if not o.ok:
        return f"{o.requested_name} -> {o.error_code}"
    d = o.data or {}
    if o.requested_name == TELEMETRY_TOOL:
        return (f"rpm={d.get('rpm')} speed_kmh={d.get('speed_kmh')} coolant_temp_c={d.get('coolant_temp_c')} "
                f"state={d.get('state')} missing={','.join(d.get('missing', [])) or '-'}")
    if o.requested_name == MEMORY_TOOL:
        return f"facts={len(d.get('facts', []))}"
    return f"state={d.get('state')} available={d.get('available')}"
