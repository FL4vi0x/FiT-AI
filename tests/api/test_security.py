"""Host validation (DNS rebinding), CORS and exposed surface."""
import pytest
from fastapi.testclient import TestClient

from fit_ai.api.security import host_name
from fit_ai.main import create_app
from test_http_api import FakeProvider

TELEMETRY = "/api/v1/vehicle/telemetry"


def get(path, host, provider=None, **headers):
    """GET with an exact Host header (`host=None` leaves the client's default)."""
    provider = provider or FakeProvider()
    client = TestClient(create_app(provider=provider), base_url="http://127.0.0.1:8000")
    h = dict(headers)
    if host is not None:
        h["Host"] = host
    return client.get(path, headers=h), provider


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "127.0.0.1:8000", "localhost", "localhost:8000", "LOCALHOST:8000", "[::1]", "[::1]:8000"],
)
def test_local_hosts_are_served(host):
    r, _ = get(TELEMETRY, host)
    assert r.status_code == 200


@pytest.mark.parametrize(
    "host",
    [
        "evil.example",                 # classic DNS rebinding: attacker's name -> 127.0.0.1
        "evil.example:8000",
        "127.0.0.1.evil.example",       # looks local, is not
        "localhost.evil.example",
        "127.0.0.1@evil.example",       # userinfo trick
        "evil.example#127.0.0.1",
        "localhost.",                   # trailing dot: a different name
        "0.0.0.0",
        "192.168.1.10:8000",
        "127.0.0.2",
        "[::1]x",
        "[::1",
        "::1",                          # bare IPv6 is not a valid Host header
        "localhost:abc",
        "localhost:",
        "local host",
    ],
)
def test_foreign_or_malformed_hosts_are_rejected_before_any_work(host):
    r, provider = get(TELEMETRY, host)
    assert r.status_code == 400
    assert r.json() == {"error": {"code": "invalid_host", "message": "Host header not allowed"}}
    assert provider.read_calls == 0  # the request never reached the service


def test_every_route_is_guarded_including_health_and_docs():
    for path in ("/health", "/api/v1/vehicle/status", TELEMETRY, "/docs", "/openapi.json", "/nonexistent"):
        r, _ = get(path, "evil.example")
        assert r.status_code == 400, path


def test_missing_host_header_is_rejected():
    from fit_ai.api.security import HostGuard

    sent = []

    async def app(scope, receive, send):  # pragma: no cover - must not be reached
        sent.append("reached")

    async def run():
        async def send(msg):
            sent.append(msg)

        await HostGuard(app)({"type": "http", "headers": []}, None, send)

    import asyncio

    asyncio.run(run())
    assert sent[0]["status"] == 400 and "reached" not in sent


def test_duplicate_host_headers_are_rejected():
    from fit_ai.api.security import HostGuard
    import asyncio

    out = []

    async def app(scope, receive, send):  # pragma: no cover
        out.append("reached")

    async def send(msg):
        out.append(msg)

    scope = {"type": "http", "headers": [(b"host", b"127.0.0.1"), (b"host", b"evil.example")]}
    asyncio.run(HostGuard(app)(scope, None, send))
    assert out[0]["status"] == 400 and "reached" not in out


def test_host_name_parsing():
    assert host_name(b"127.0.0.1:8000") == "127.0.0.1"
    assert host_name(b"[::1]:80") == "::1"
    assert host_name(b"LocalHost") == "localhost"
    assert host_name(b"") is None
    assert host_name("localhóst".encode()) is None


def test_no_cors_headers_are_ever_sent():
    """No CORS middleware: a page from another origin can send a simple GET but can never read the answer."""
    r, _ = get(TELEMETRY, "127.0.0.1:8000", Origin="https://evil.example")
    assert r.status_code == 200
    assert not [h for h in r.headers if h.lower().startswith("access-control-")]


def test_cors_preflight_is_not_answered():
    client = TestClient(create_app(provider=FakeProvider()), base_url="http://127.0.0.1:8000")
    r = client.options(TELEMETRY, headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert r.status_code == 405
    assert not [h for h in r.headers if h.lower().startswith("access-control-")]


def test_exposed_surface_is_exactly_the_reviewed_one():
    """Adding any route (especially admin or write ones) must be a conscious change to this list."""
    app = create_app(provider=FakeProvider())
    api = {(path, method.upper()) for path, ops in app.openapi()["paths"].items() for method in ops}
    assert api == {
        ("/health", "GET"),
        ("/api/v1/vehicle/telemetry", "GET"),
        ("/api/v1/vehicle/status", "GET"),
        ("/api/v1/chat", "POST"),  # P7: the only state-changing route; guarded by BrowserGuard + HostGuard
    }
    # framework-provided documentation routes (read-only, no data); anything else registered directly is a surprise
    direct = {r.path for r in app.routes if hasattr(r, "methods")}
    assert direct == {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
