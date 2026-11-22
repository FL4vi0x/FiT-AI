"""The provider must work when it is used from more than one event loop (P7 stabilisation).

Found while investigating the `c01` timeout of the P7 adversarial benchmark: the harness created the provider on one
loop, called `health()` there, and then served each chat request from a new loop (Starlette's TestClient creates one per
request). httpx keeps the connection of the previous request alive, and a connection belongs to the loop that opened it:
reusing it from another loop made the first chat request stall until the 60 s model timeout (or fail at once with
"Event loop is closed"). It was a benchmark artefact, not slowness of the model: the server answered such requests in a
few seconds, or never saw work for them.

A real loopback HTTP server with persistent connections (like Ollama's) is used on purpose: httpx.MockTransport has no
connection pool, so it cannot show the problem.
"""
from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from ai_helpers import SETTINGS, chat_reply

from fit_ai.ai import ChatMessage, LLMSettings, OllamaProvider


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive, like Ollama

    def log_message(self, *args):  # silence
        pass

    def _send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/version":
            self._send({"version": "0.0-test"})
        else:
            self._send({"models": [{"name": SETTINGS.model, "digest": "sha256:test"}]})

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self._send(chat_reply("ok"))


@pytest.fixture()
def server_url():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


def _provider(url: str) -> OllamaProvider:
    return OllamaProvider(LLMSettings(ollama_url=url, timeout_s=10.0))


async def _chat(p: OllamaProvider):
    return await p.generate([ChatMessage.user("oi")], timeout_s=10.0)


def test_requests_on_successive_closed_loops_all_succeed(server_url):
    p = _provider(server_url)
    assert asyncio.run(p.health()).available  # loop A, closed afterwards
    for _ in range(4):  # a new loop per request, like a TestClient used without a context manager
        assert asyncio.run(_chat(p)).content == "ok"
    asyncio.run(p.aclose())  # must not raise even though the last client belonged to a closed loop


def test_health_on_a_live_loop_then_requests_from_worker_threads(server_url):
    """The benchmark's exact shape: health() on the main loop, each case served from a worker thread's own loop."""
    async def main():
        p = _provider(server_url)
        assert (await p.health()).available
        for _ in range(3):
            out = await asyncio.wait_for(asyncio.to_thread(lambda: asyncio.run(_chat(p))), timeout=30)
            assert out.content == "ok"
        await p.aclose()
    asyncio.run(main())


def test_the_same_loop_still_reuses_one_client(server_url):
    async def main():
        p = _provider(server_url)
        first = p._client
        for _ in range(3):
            assert (await _chat(p)).content == "ok"
        assert p._client is first  # no needless client churn on a single loop
        await p.aclose()
    asyncio.run(main())
