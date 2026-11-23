import pytest

from fit_ai.adapters.octave import load_sdk
from fit_ai.config import Settings


@pytest.fixture
def anyio_backend():
    return "asyncio"


def sdk_available() -> bool:
    """The OCTAVE SDK lives OUTSIDE this repository (FIT/runtime/octave-sdk-0.9.6, extracted from the OCTAVE project, whose licence
    decision is still open), so a clean clone, or CI, does not have it. Tests that really need it are skipped, visibly."""
    return (Settings.from_env().octave_sdk_path / "octave_client" / "__init__.py").is_file()


NEEDS_SDK_REASON = "the OCTAVE SDK is not installed (FIT/runtime/octave-sdk-0.9.6 or OCTAVE_SDK_PATH): it is not part of this repository"


def pytest_collection_modifyitems(config, items):
    if sdk_available():
        return
    skip = pytest.mark.skip(reason=NEEDS_SDK_REASON)
    for item in items:
        if "needs_sdk" in item.keywords or "sdk" in getattr(item, "fixturenames", ()):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def sdk():
    """The official OCTAVE SDK, loaded in place (only for its exception classes in unit tests)."""
    return load_sdk(Settings.from_env().octave_sdk_path)


# ───────────────────────── P7: shared rig for conversation / chat API tests ─────────────────────────
import json  # noqa: E402

from fit_ai.adapters.fake_telemetry import FakeTelemetryProvider  # noqa: E402
from fit_ai.ai import FakeLLMProvider, Reply  # noqa: E402
from fit_ai.audit import AuditWriteError, SqliteAuditLog  # noqa: E402
from fit_ai.conversation import ChatSettings, ConversationService  # noqa: E402
from fit_ai.main import create_app  # noqa: E402
from fit_ai.memory import SqliteMemoryStore  # noqa: E402
from fit_ai.orchestration import AssistantOrchestrator, AssistantSettings  # noqa: E402
from fit_ai.services.telemetry import TelemetryService  # noqa: E402
from fit_ai.tools import build_vehicle_registry  # noqa: E402

MODEL = "qwen3:4b-instruct-2507-q4_K_M"


def llm_json(answer: str, claims=()) -> Reply:
    """A scripted model reply in the structured-answer format."""
    return Reply.text(json.dumps({"answer": answer, "claims": [{"field": f, "value": v, "unit": u} for f, v, u in claims],
                                  "unknown": []}, ensure_ascii=False))


GOOD_RPM = "No simulador, o motor está a 800 RPM."


class FlakyAudit:
    """An audit sink that accepts `ok_writes` records and then fails (disk full, locked file...)."""

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


class ChatRig:
    """ConversationService wired exactly like production, but with fakes and temporary SQLite databases."""

    def __init__(self, tmp_path, script=(), *, telemetry=None, with_llm=True, chat=None, audit_ok_writes=None,
                 audit_policy="fail_closed"):
        self.telemetry = telemetry or FakeTelemetryProvider(800, 0.0, 90.0, simulated=True, source="fake-octave")
        self.memory = SqliteMemoryStore(tmp_path / "memory.db")
        self.audit_db = SqliteAuditLog(tmp_path / "audit.db")
        self.audit = self.audit_db if audit_ok_writes is None else FlakyAudit(self.audit_db, audit_ok_writes)
        self.llm = FakeLLMProvider(list(script)) if with_llm else None
        self.chat_settings = chat or ChatSettings()
        orch = AssistantOrchestrator(build_vehicle_registry(TelemetryService(self.telemetry), self.memory), self.llm,
                                     audit=self.audit, memory=self.memory,
                                     settings=AssistantSettings(audit_policy=audit_policy))
        self.service = ConversationService(orch, self.memory, settings=self.chat_settings, model_name=MODEL)

    def app(self):
        return create_app(provider=self.telemetry, conversation_service=self.service, chat_settings=self.chat_settings)

    def client(self, **kw):
        from fastapi.testclient import TestClient
        kw.setdefault("raise_server_exceptions", False)
        return TestClient(self.app(), base_url="http://127.0.0.1:8000", **kw)

    async def ask(self, message, conversation_id=None, **kw):
        return await self.service.chat(message, conversation_id, request_id=kw.pop("request_id", "req-test"), **kw)


@pytest.fixture
def chat_rig(tmp_path):
    def make(script=(), **kw):
        return ChatRig(tmp_path, script, **kw)
    return make
