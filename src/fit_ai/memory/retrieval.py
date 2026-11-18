"""Contextual recall: what the assistant may be told from memory, under hard size limits.

Everything returned here is STORED INFORMATION (user statements and past conversation), never a sensor
reading. The rendered block says so explicitly and shows how old each item is, so stale memory cannot be
mistaken for the current state of the vehicle.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fit_ai.memory.contracts import MemoryStore
from fit_ai.memory.models import ConversationTurn, MemoryFact, MemoryHit, UserPreference


@dataclass(frozen=True)
class RecallLimits:
    max_preferences: int = 5
    max_facts: int = 4
    max_recent_turns: int = 2
    max_item_chars: int = 200
    max_total_chars: int = 900


@dataclass(frozen=True)
class MemoryContext:
    preferences: tuple[UserPreference, ...] = ()
    facts: tuple[MemoryFact | MemoryHit, ...] = ()
    recent_turns: tuple[ConversationTurn, ...] = ()
    truncated: bool = False
    rendered: str = field(default="", compare=False)

    @property
    def empty(self) -> bool:
        return not (self.preferences or self.facts or self.recent_turns)


def _age(then: datetime, now: datetime) -> str:
    s = max(0.0, (now - then).total_seconds())
    if s < 90:
        return "agora há pouco"
    if s < 5400:
        return f"há {round(s / 60)} min"
    if s < 172800:
        return f"há {round(s / 3600)} h"
    return f"há {round(s / 86400)} dias"


def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


class ContextRetriever:
    def __init__(self, store: MemoryStore, limits: RecallLimits = RecallLimits(),
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._store, self._limits, self._clock = store, limits, clock

    def recall(self, query: str, conversation_id: str | None = None, *,
               facts: Sequence[MemoryFact | MemoryHit] | None = None) -> MemoryContext:
        """Preferences + relevant facts + the last turns of THIS conversation, within the size limits.
        `facts`: already retrieved facts (for example by the audited `get_memory_facts` tool); when None, the
        store is searched. No relevant fact means no fact is injected (never "all memory")."""
        lim = self._limits
        prefs = tuple(self._store.list_preferences()[: lim.max_preferences])
        found = list(facts) if facts is not None else self._store.search(query, kinds=("fact",), limit=lim.max_facts)
        turns: tuple[ConversationTurn, ...] = ()
        if conversation_id is not None and lim.max_recent_turns:
            turns = tuple(self._store.recent_turns(conversation_id, lim.max_recent_turns))
        return self._render(MemoryContext(preferences=prefs, facts=tuple(found[: lim.max_facts]), recent_turns=turns))

    def _render(self, ctx: MemoryContext) -> MemoryContext:
        lim, now = self._limits, self._clock()
        lines: list[str] = []
        for p in ctx.preferences:
            lines.append(f"- preferência: {_clip(p.key, 40)} = {_clip(p.value, lim.max_item_chars)}")
        for f in ctx.facts:
            lines.append(f"- fato informado pelo usuário ({_age(f.created_at, now)}): {_clip(f.content, lim.max_item_chars)}")
        for t in ctx.recent_turns:
            who = "usuário" if t.role == "user" else "assistente"
            lines.append(f"- conversa anterior ({_age(t.created_at, now)}, {who}): {_clip(t.content, lim.max_item_chars)}")
        if not lines:
            return ctx
        header = "MEMÓRIA (informações guardadas; NÃO são leituras de sensores e podem estar desatualizadas):"
        out, used, truncated = [header], len(header), False
        for line in lines:
            if used + len(line) + 1 > lim.max_total_chars:
                truncated = True
                break
            out.append(line)
            used += len(line) + 1
        return MemoryContext(ctx.preferences, ctx.facts, ctx.recent_turns, truncated, "\n".join(out))
