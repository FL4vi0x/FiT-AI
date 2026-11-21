"""ConversationService: one chat turn from a typed request to a typed, verified answer. Independent of HTTP.

Responsibilities (everything else is reused from P6, nothing is duplicated):
  validation -> admission control (bounded queue) -> [explicit memory command | P6 orchestrator: READ tools,
  evidence, LLM, deterministic verifier, fallback, audit] -> atomic persistence -> safe response.

Policies, all tested:
- The verifier/fallback of P6 have the last word on telemetry: this layer never returns raw model text.
- Persistence is ATOMIC and happens only for an answer that was verified (or built by code): the user turn and
  the answer are stored together or not at all. A new conversation is created in that same transaction, so a
  failed request never leaves an empty conversation, a half exchange, or a user turn without an answer.
  If persistence fails the answer is discarded (503) and the request can be retried without duplicates.
- Idempotency-Key (optional): a retry of a completed request returns the stored response (no second model
  call, no duplicate turns); a different payload with the same key is refused; the same key in flight is 409.
- Memory is written only by an explicit imperative command parsed by code ("Fit, lembre que ..."), never by
  the model and never from a question. Sensor readings and secrets are refused. "Anotado" is said only after
  the fact was really persisted.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fit_ai.audit import redact
from fit_ai.conversation.config import ChatSettings
from fit_ai.conversation.errors import (
    AuditUnavailable,
    ConversationNotFound,
    IdempotencyConflict,
    InvalidConversationId,
    InvalidIdempotencyKey,
    InvalidMessage,
    ModelUnavailable,
    RequestInProgress,
    RequestTimeout,
    ServiceBusy,
    StorageUnavailable,
)
from fit_ai.conversation.models import ChatResponse
from fit_ai.grounding.evidence import EvidenceBundle
from fit_ai.grounding.numbers import extract_mentions
from fit_ai.memory import MemoryError_, MemoryNotFound, MemoryPolicyError, MemoryStore
from fit_ai.orchestration import AssistantOrchestrator, TurnRequest, TurnResult, history_text

log = logging.getLogger("fit_ai.conversation")

_ID = re.compile(r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$")
_KEY = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
# Imperative, explicit requests only. "lembre/memorize" may omit "que"; "guarde/anote/registre" need a connector.
_REMEMBER = re.compile(
    r"^\s*(?:fit\s*[,:;\-]?\s*)?(?:por favor[,\s]+)?"
    r"(?:(?:lembre(?:-se)?|memorize)\s+(?:(?:de|que|disso:?|isto:?)\s+)?|(?:guarde|anote|registre)\s+(?:que|isto:?|isso:?|disso:?)\s+)"
    r"(?P<content>\S.*)$", re.IGNORECASE | re.DOTALL)

# Credentials and personal identifiers are refused by WORD (any phrasing, "minha senha é ...") and by SHAPE
# (CPF, card-like digit runs), on top of the audit redactor (e-mails, phones, key=value secrets, tokens).
_SENSITIVE_WORDS = re.compile(
    r"\b(?:senhas?|password|passwd|tokens?|api[ _-]?key|segredos?|pin|cvv|cpf|rg|cnh|"
    r"chave\s+(?:de\s+|da\s+)?(?:api|acesso|privada|secreta|pix)|cart[aã]o\s+de\s+(?:cr[eé]dito|d[eé]bito)|"
    r"conta\s+banc[aá]ria|ag[eê]ncia\s+banc[aá]ria)\b", re.IGNORECASE)
_SENSITIVE_NUMBER = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b|\b(?:\d[ -]?){13,19}\b")

_MODEL_STATUS = {"LLMUnavailable": "unavailable", "LLMTimeout": "timeout", "LLMModelNotFound": "not_found",
                 "LLMModelUnavailable": "not_found"}
_PERSISTED_SOURCES = ("llm", "llm_retry", "fallback", "deterministic", "policy_refusal")


@dataclass
class _Idem:
    fingerprint: str
    expires: float
    response: ChatResponse | None = None  # None while the request is in flight


class ConversationService:
    def __init__(self, orchestrator: AssistantOrchestrator, memory: MemoryStore, *,
                 settings: ChatSettings | None = None, model_name: str | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self._orch, self._memory = orchestrator, memory
        self._s = settings or ChatSettings()
        self._model_name = model_name
        self._clock = clock
        self._sem = asyncio.Semaphore(self._s.max_concurrent)
        self._waiting = 0
        self._idem: OrderedDict[str, _Idem] = OrderedDict()

    # ───────────────────────── public ─────────────────────────
    async def chat(self, message: str, conversation_id: str | None = None, *, request_id: str,
                   idempotency_key: str | None = None) -> ChatResponse:
        t0 = time.perf_counter()
        text = (message or "").strip()
        if not text:
            raise InvalidMessage("The message is empty.")
        if len(text) > self._s.max_message_chars:
            raise InvalidMessage(f"The message exceeds the limit of {self._s.max_message_chars} characters.")
        cid = self._parse_conversation_id(conversation_id)
        if idempotency_key is not None and not _KEY.fullmatch(idempotency_key):
            raise InvalidIdempotencyKey()

        replay = self._idem_begin(idempotency_key, cid, text)
        if replay is not None:
            return replay.model_copy(update={"replayed": True, "request_id": request_id})
        try:
            if cid is not None:
                await self._require_conversation(cid)
            command = _parse_remember(text)
            if command is not None:
                resp = await self._remember(command, cid, text, request_id, t0)
            else:
                async with self._admission():
                    resp = await self._answer(text, cid, request_id, t0)
        except BaseException:
            self._idem_abort(idempotency_key)  # nothing was persisted: a retry is allowed (and cancel is clean)
            raise
        self._idem_done(idempotency_key, resp)
        return resp

    async def aclose(self) -> None:
        """Nothing is held open besides what the caller owns (provider, stores)."""

    # ───────────────────────── the model path ─────────────────────────
    async def _answer(self, text: str, cid: str | None, request_id: str, t0: float) -> ChatResponse:
        try:
            async with asyncio.timeout(self._s.request_timeout_s):
                res = await self._orch.run(TurnRequest(text, conversation_id=cid, persist=False, request_id=request_id))
                if res.source == "audit_refusal":
                    raise AuditUnavailable()
                kind = _MODEL_STATUS.get(res.llm_error or "", "error" if res.llm_error else None)
                if kind and not (res.evidence.telemetry or res.evidence.status):
                    raise ModelUnavailable(kind)  # nothing the assistant can answer from without the model
                if res.source not in _PERSISTED_SOURCES:  # defensive: never persist an unknown kind of answer
                    raise StorageUnavailable()
                conv_id = await self._persist(cid, text, history_text(res.answer, res.evidence))
        except TimeoutError:
            raise RequestTimeout() from None
        return self._response(res, conv_id, request_id, t0)

    def _response(self, res: TurnResult, conv_id: str, request_id: str, t0: float) -> ChatResponse:
        b = res.evidence
        status = _MODEL_STATUS.get(res.llm_error or "", "error" if res.llm_error else None)
        return ChatResponse(
            conversation_id=conv_id, request_id=request_id, answer=res.answer,
            model=self._model_name if res.llm_calls > 0 else None, answer_origin=res.source,  # type: ignore[arg-type]
            used_tools=list(dict.fromkeys(res.tools)), fallback_used=res.source in ("fallback", "deterministic"),
            data_source=_data_source(b), simulated=_simulated(b), availability=_availability(b),
            model_status=status or ("ok" if res.llm_calls > 0 else "not_used"),  # type: ignore[arg-type]
            memory_saved=False, history_saved=True, latency_ms=int((time.perf_counter() - t0) * 1000))

    # ───────────────────────── explicit memory command ─────────────────────────
    async def _remember(self, content: str, cid: str | None, text: str, request_id: str, t0: float) -> ChatResponse:
        refusal = _memory_refusal(content)
        saved_id: str | None = None
        if refusal is None:
            try:
                fact = await asyncio.to_thread(self._memory.remember_fact, content)
                saved_id = fact.id
            except MemoryError_ as exc:
                log.warning("memory command refused or failed: %s", type(exc).__name__)
                if isinstance(exc, MemoryPolicyError):
                    refusal = "Não consegui guardar isso: o conteúdo não é aceito como memória."
                else:
                    raise StorageUnavailable() from None
        answer = (refusal if saved_id is None else
                  f"Anotado: “{content}”. Vou tratar isso como algo que você me pediu para lembrar "
                  "(não é uma leitura do veículo).")
        try:
            conv_id = await self._persist(cid, text, answer)
        except BaseException:
            if saved_id is not None:  # keep the state consistent: no fact without its exchange
                try:
                    await asyncio.to_thread(self._memory.delete_fact, saved_id)
                except MemoryError_:
                    log.exception("could not roll back a memory fact after a failed exchange")
            raise
        return ChatResponse(
            conversation_id=conv_id, request_id=request_id, answer=answer, model=None, answer_origin="memory_command",
            used_tools=[], fallback_used=False, data_source=None, simulated=None, availability="not_requested",
            model_status="not_used", memory_saved=saved_id is not None, history_saved=True,
            latency_ms=int((time.perf_counter() - t0) * 1000))

    # ───────────────────────── persistence / lookup ─────────────────────────
    async def _persist(self, cid: str | None, user_text: str, assistant_text: str) -> str:
        try:
            conv, _, _ = await asyncio.to_thread(self._memory.record_exchange, cid, user_text, assistant_text)
            return conv.id
        except MemoryNotFound:
            raise ConversationNotFound() from None
        except MemoryError_ as exc:
            log.error("could not persist the exchange: %s", type(exc).__name__)
            raise StorageUnavailable() from None

    async def _require_conversation(self, cid: str) -> None:
        try:
            await asyncio.to_thread(self._memory.get_conversation, cid)
        except MemoryNotFound:
            raise ConversationNotFound() from None
        except MemoryError_ as exc:
            log.error("conversation lookup failed: %s", type(exc).__name__)
            raise StorageUnavailable() from None

    @staticmethod
    def _parse_conversation_id(raw: str | None) -> str | None:
        if raw is None:
            return None
        raw = raw.strip()
        if not _ID.fullmatch(raw):
            raise InvalidConversationId()
        return uuid.UUID(raw).hex  # the store's own form

    # ───────────────────────── admission control ─────────────────────────
    @asynccontextmanager
    async def _admission(self) -> AsyncIterator[None]:
        """At most `max_concurrent` generations; at most `max_waiting` requests wait, for at most
        `queue_timeout_s`; everything else is refused at once. Nothing waits without a bound."""
        if self._sem.locked() and self._waiting >= self._s.max_waiting:
            raise ServiceBusy(retry_after_s=max(1, int(self._s.request_timeout_s // 18)))
        self._waiting += 1
        try:
            await asyncio.wait_for(self._sem.acquire(), self._s.queue_timeout_s)
        except TimeoutError:
            raise ServiceBusy(retry_after_s=max(1, int(self._s.request_timeout_s // 18))) from None
        finally:
            self._waiting -= 1
        try:
            yield
        finally:
            self._sem.release()

    # ───────────────────────── idempotency ─────────────────────────
    def _idem_begin(self, key: str | None, cid: str | None, text: str) -> ChatResponse | None:
        if key is None:
            return None
        now = self._clock()
        for k in [k for k, v in self._idem.items() if v.expires <= now and v.response is not None]:
            del self._idem[k]
        fp = hashlib.sha256(f"{cid or ''}\x00{text}".encode()).hexdigest()
        entry = self._idem.get(key)
        if entry is not None:
            if entry.fingerprint != fp:
                raise IdempotencyConflict()
            if entry.response is None:
                raise RequestInProgress()
            return entry.response
        while len(self._idem) >= self._s.idempotency_max_entries:  # bounded: drop the oldest completed entry
            victim = next((k for k, v in self._idem.items() if v.response is not None), None)
            if victim is None:
                raise ServiceBusy(retry_after_s=5)
            del self._idem[victim]
        self._idem[key] = _Idem(fp, now + self._s.idempotency_ttl_s)
        return None

    def _idem_done(self, key: str | None, resp: ChatResponse) -> None:
        if key is not None and key in self._idem:
            self._idem[key].response = resp
            self._idem[key].expires = self._clock() + self._s.idempotency_ttl_s

    def _idem_abort(self, key: str | None) -> None:
        if key is not None:
            entry = self._idem.get(key)
            if entry is not None and entry.response is None:
                del self._idem[key]


# ───────────────────────── pure helpers ─────────────────────────
def _parse_remember(text: str) -> str | None:
    """The content of an explicit, imperative memory request, or None (a question is never a command)."""
    if text.rstrip().endswith("?"):
        return None
    m = _REMEMBER.match(text)
    if not m:
        return None
    content = m.group("content").strip()
    if content.lower().strip(" :.,;!") in ("que", "de", "disso", "isto", "isso"):  # just a connector: no content
        return None
    return content


def _memory_refusal(content: str) -> str | None:
    if len(content) < 3:
        return "Não entendi o que devo lembrar. Diga, por exemplo: “lembre que prefiro respostas curtas”."
    if any(m.field is not None for m in extract_mentions(content)):
        return ("Não guardo leituras de sensores (rotação, velocidade ou temperatura) como memória permanente: "
                "são valores temporários do veículo. Nada foi guardado.")
    if (redact(content, limit=len(content) + 16) != " ".join(content.split()) or _SENSITIVE_WORDS.search(content)
            or _SENSITIVE_NUMBER.search(content)):
        return "Não guardo senhas, chaves, e-mails, telefones ou outros dados sensíveis. Nada foi guardado."
    if len(content) > 900:
        return "O texto é longo demais para guardar. Resuma e peça de novo. Nada foi guardado."
    return None


def _availability(b: EvidenceBundle) -> str:
    if not b.telemetry and not b.status:
        return "not_requested"
    if b.telemetry:
        if b.has_usable_reading:
            return "partial" if b.missing_fields() else "ok"
        return "stale" if b.stale is not None else "unavailable"
    return "ok" if any(e.state == "ok" for e in b.status) else "unavailable"


def _data_source(b: EvidenceBundle) -> str | None:
    for e in (*b.telemetry, *b.status):
        if e.state in ("ok", "partial") and e.source:
            return e.source
    return None


def _simulated(b: EvidenceBundle) -> bool | None:
    if b.telemetry:
        return b.simulated
    for e in b.status:
        if e.state == "ok":
            return e.simulated
    return None


__all__ = ["ConversationService"]
