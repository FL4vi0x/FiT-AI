"""GET /api/v1/llm/status: read-only availability of the local language-model server (P8.3)."""
import asyncio
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from fit_ai.adapters.fake_telemetry import FakeTelemetryProvider
from fit_ai.ai import LLMSettings, OllamaProvider, ProviderHealth
from fit_ai.main import create_app
from fit_ai.services.llm_status import LLMStatusService, classify

pytestmark = pytest.mark.anyio

MODEL = "qwen3:4b-instruct-2507-q4_K_M"
FIELDS = {"state", "model", "checked_at"}


def health(**kw) -> ProviderHealth:
    base = dict(available=True, backend="ollama", model=MODEL, model_installed=True, model_digest="sha256:secret-digest",
                server_version="0.40.16", detail=None)
    base.update(kw)
    return ProviderHealth(**base)


# ───────────── the mapping: only a refusal to connect means "unavailable" ─────────────
@pytest.mark.parametrize("kw,state", [
    (dict(), "available"),
    (dict(model_installed=False, detail="llm_model_not_found"), "model_not_installed"),
    (dict(available=False, model_installed=None, detail="llm_unavailable"), "unavailable"),
    (dict(available=False, model_installed=None, detail="llm_timeout"), "unverified"),
    (dict(available=False, model_installed=None, detail="llm_transport_error"), "unverified"),
    (dict(available=False, model_installed=None, detail="llm_invalid_response"), "unverified"),
    (dict(available=False, model_installed=None, detail=None), "unverified"),
])
def test_classification(kw, state):
    assert classify(health(**kw)) == state


# ───────────── the service ─────────────
class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def service(fn, **kw):
    return LLMStatusService(fn, model=MODEL, now=lambda: datetime(2026, 11, 23, tzinfo=UTC), **kw)


async def test_not_configured_has_no_model_and_asks_nothing():
    st = await LLMStatusService(None).get_status()
    assert st.state == "not_configured" and st.model is None


async def test_a_timeout_is_unverified_not_unavailable():
    async def slow():
        await asyncio.sleep(5)
        return health()
    st = await service(slow, timeout_s=0.05).get_status()
    assert st.state == "unverified"


async def test_an_unexpected_error_is_unverified_and_never_raised():
    async def boom():
        raise RuntimeError("secret detail that must not leak")
    st = await service(boom).get_status()
    assert st.state == "unverified" and "secret" not in repr(st)


async def test_results_are_cached_briefly_and_refreshed_after_the_ttl():
    calls, clock = [], Clock()

    async def h():
        calls.append(1)
        return health()
    s = service(h, clock=clock, ttl_s=5.0)
    await s.get_status()
    await s.get_status()
    assert len(calls) == 1
    clock.t = 5.1
    await s.get_status()
    assert len(calls) == 2


async def test_concurrent_callers_share_one_check():
    calls = []

    async def h():
        calls.append(1)
        await asyncio.sleep(0.05)
        return health()
    s = service(h)
    await asyncio.gather(*(s.get_status() for _ in range(8)))
    assert len(calls) == 1


# ───────────── the route ─────────────
def app_with(svc):
    app = create_app(provider=FakeTelemetryProvider())
    if svc is not None:
        app.state.llm_status_service = svc
    return TestClient(app, base_url="http://127.0.0.1:8000")  # a local Host, as in the other API tests


def test_without_a_language_model_the_route_says_not_configured():
    r = app_with(None).get("/api/v1/llm/status")
    assert r.status_code == 200 and r.json()["state"] == "not_configured" and r.json()["model"] is None


def test_response_has_exactly_three_fields_and_leaks_nothing():
    async def h():
        return health()
    r = app_with(service(h)).get("/api/v1/llm/status")
    body = r.json()
    assert r.status_code == 200 and set(body) == FIELDS and body["state"] == "available" and body["model"] == MODEL
    text = r.text
    for secret in ("sha256", "digest", "0.40.16", "127.0.0.1", "11434", "http"):
        assert secret not in text


def test_the_client_cannot_steer_the_check():
    seen = []

    async def h():
        seen.append(1)
        return health()
    c = app_with(service(h))
    r = c.get("/api/v1/llm/status", params={"url": "http://evil.example:11434", "model": "other:tag", "host": "evil"})
    assert r.status_code == 200 and r.json()["model"] == MODEL and len(seen) == 1


def test_it_is_read_only():
    c = app_with(service(lambda: None))
    for method in ("post", "put", "patch", "delete"):
        assert getattr(c, method)("/api/v1/llm/status").status_code in (405, 403, 400)


def test_host_header_protection_still_applies():
    async def h():
        return health()
    c = app_with(service(h))
    assert c.get("/api/v1/llm/status", headers={"Host": "evil.example"}).status_code == 400
    assert c.get("/api/v1/llm/status", headers={"Host": "localhost:8000"}).status_code == 200


# ───────────── end to end with the REAL provider over a mocked transport ─────────────
def provider_for(handler):
    transport = httpx.MockTransport(handler)
    return OllamaProvider(LLMSettings(model=MODEL), client=httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:11434"))


async def test_the_check_only_reads_version_and_tags_and_never_loads_a_model():
    requests = []

    def handler(request: httpx.Request):
        requests.append((request.method, request.url.path))
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.40.16"})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": MODEL, "digest": "sha256:abc"}]})
        return httpx.Response(500)
    p = provider_for(handler)
    st = await LLMStatusService(p.health, model=MODEL).get_status()
    assert st.state == "available"
    assert sorted(requests) == [("GET", "/api/tags"), ("GET", "/api/version")]  # no /api/chat, no /api/generate, no /api/pull


async def test_model_not_installed_is_reported():
    def handler(request):
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.40.16"})
        return httpx.Response(200, json={"models": [{"name": "another:model", "digest": "x"}]})
    st = await LLMStatusService(provider_for(handler).health, model=MODEL).get_status()
    assert st.state == "model_not_installed"


async def test_a_switched_off_server_is_unavailable():
    def handler(request):
        raise httpx.ConnectError("refused")
    st = await LLMStatusService(provider_for(handler).health, model=MODEL).get_status()
    assert st.state == "unavailable"


async def test_a_server_that_does_not_answer_in_time_is_unverified():
    def handler(request):
        raise httpx.ReadTimeout("slow")
    st = await LLMStatusService(provider_for(handler).health, model=MODEL).get_status()
    assert st.state == "unverified"
