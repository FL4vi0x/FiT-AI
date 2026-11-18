"""Local persistent memory (SQLite + FTS5). Independent of FastAPI, OCTAVE and the LLM."""
from fit_ai.memory.contracts import (
    MemoryError_,
    MemoryNotFound,
    MemoryPolicyError,
    MemoryStorageError,
    MemoryStore,
)
from fit_ai.memory.models import (
    Conversation,
    ConversationTurn,
    MemoryFact,
    MemoryHit,
    UserPreference,
)
from fit_ai.memory.retrieval import ContextRetriever, MemoryContext, RecallLimits
from fit_ai.memory.sqlite_store import SqliteMemoryStore

__all__ = [
    "ContextRetriever", "Conversation", "ConversationTurn", "MemoryContext", "MemoryError_", "MemoryFact",
    "MemoryHit", "MemoryNotFound", "MemoryPolicyError", "MemoryStorageError", "MemoryStore", "RecallLimits",
    "SqliteMemoryStore", "UserPreference",
]
