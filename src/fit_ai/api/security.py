"""Request-level protection for a loopback-only API.

A web page in any browser on this machine can send requests to 127.0.0.1. With DNS
rebinding the page's own hostname (e.g. evil.example) is made to resolve to 127.0.0.1, so
the browser treats the API as same-origin and lets the page read the answers. What gives
it away is the `Host` header, which keeps the attacker's name. This guard refuses any
request whose Host is not exactly a local name.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Collection

ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def host_name(raw: bytes) -> str | None:
    """The host part of a Host header value (port removed, IPv6 brackets removed, lower-case),
    or None when it is not a well-formed `host[:port]`."""
    try:
        value = raw.decode("ascii").strip().lower()
    except UnicodeDecodeError:
        return None
    if not value:
        return None
    if value.startswith("["):  # [::1] or [::1]:8000
        end = value.find("]")
        if end == -1:
            return None
        host, rest = value[1:end], value[end + 1 :]
        if rest and not (rest.startswith(":") and rest[1:].isdigit()):
            return None
        return host
    if value.count(":") > 1:  # bare IPv6 without brackets is not valid in a Host header
        return None
    host, sep, port = value.partition(":")
    if sep and not port.isdigit():
        return None
    return host


class HostGuard:
    """ASGI middleware: 400 unless there is exactly one Host header naming a local address."""

    def __init__(self, app, allowed: frozenset[str] = ALLOWED_HOSTS):
        self.app = app
        self.allowed = allowed

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        hosts = [v for k, v in scope.get("headers", []) if k == b"host"]
        name = host_name(hosts[0]) if len(hosts) == 1 else None
        if name in self.allowed:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        body = json.dumps({"error": {"code": "invalid_host", "message": "Host header not allowed"}}).encode()
        await send({"type": "http.response.start", "status": 400,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


# ───────────────────────── request identity ─────────────────────────
class RequestContext:
    """ASGI middleware: gives every HTTP request a fresh server-generated id (never taken from the client),
    available as `scope["state"]["request_id"]` and returned in the `X-Request-ID` response header."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), (b"x-request-id", request_id.encode())]}
            await send(message)

        await self.app(scope, receive, send_with_id)


# ───────────────────────── browser-originated requests ─────────────────────────
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class _BodyTooLarge(BaseException):
    """BaseException on purpose: FastAPI wraps any `Exception` raised while reading the body into a 400."""


async def _reply(send, status: int, code: str, message: str, request_id: str | None = None) -> None:
    payload: dict = {"error": {"code": code, "message": message}}
    if request_id:
        payload["request_id"] = request_id
    body = json.dumps(payload).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def _is_json_content_type(raw: bytes | None) -> bool:
    if raw is None:
        return False
    parts = [p.strip() for p in raw.decode("latin-1").lower().split(";")]
    if parts[0] != "application/json":
        return False
    return all(p in ("charset=utf-8", 'charset="utf-8"') for p in parts[1:])


class BrowserGuard:
    """Policy for requests that can change state (POST/PUT/PATCH/DELETE). Being on 127.0.0.1 is not protection:
    any web page open in a browser on this machine can send requests to it.

    - `Origin`: absent (a native client such as curl or PowerShell) is fine; present, it must be on the
      allow-list (empty by default). "null" and unknown origins are refused.
    - `Sec-Fetch-Site`: only `same-origin` and `none` pass, unless the Origin is allow-listed.
    - `Content-Type` must be exactly application/json (UTF-8): the "simple" types a page can send without a
      CORS preflight (text/plain, forms) are refused.
    - Body size is limited by Content-Length and again while streaming (chunked uploads).
    No CORS header is ever emitted and preflights are not answered, so a cross-origin JSON request never starts.
    """

    def __init__(self, app, allowed_origins: Collection[str] = (), max_body_bytes: int = 16 * 1024,
                 body_paths: Collection[str] = ("/api/v1/chat",)):
        self.app = app
        self.allowed_origins = frozenset(o.rstrip("/").lower() for o in allowed_origins)
        self.max_body_bytes = max_body_bytes
        self.body_paths = frozenset(body_paths)  # routes that take a JSON body: Content-Type and size are enforced

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in UNSAFE_METHODS:
            await self.app(scope, receive, send)
            return
        rid = scope.get("state", {}).get("request_id")
        headers: dict[bytes, list[bytes]] = {}
        for k, v in scope.get("headers", []):
            headers.setdefault(k, []).append(v)

        origins = headers.get(b"origin", [])
        origin_ok = False
        if origins:
            origin = origins[0].decode("latin-1").rstrip("/").lower() if len(origins) == 1 else None
            if origin is None or origin not in self.allowed_origins:
                await _reply(send, 403, "origin_not_allowed", "This origin is not allowed to call the API.", rid)
                return
            origin_ok = True
        fetch_site = headers.get(b"sec-fetch-site", [])
        if fetch_site and not origin_ok:
            if len(fetch_site) != 1 or fetch_site[0].decode("latin-1").lower() not in ("same-origin", "none"):
                await _reply(send, 403, "cross_site_request", "Cross-site requests are not allowed.", rid)
                return

        if scope["path"] not in self.body_paths or scope["method"] != "POST":
            # read-only routes, and other methods on the chat route: the router's own 405
            await self.app(scope, receive, send)
            return

        ctype = headers.get(b"content-type", [])
        if len(ctype) != 1 or not _is_json_content_type(ctype[0]):
            await _reply(send, 415, "unsupported_media_type", "Content-Type must be application/json (UTF-8).", rid)
            return
        lengths = headers.get(b"content-length", [])
        if lengths:
            try:
                declared = int(lengths[0])
            except ValueError:
                declared = -1
            if declared < 0 or len(lengths) != 1:
                await _reply(send, 400, "invalid_content_length", "Content-Length is not valid.", rid)
                return
            if declared > self.max_body_bytes:
                await _reply(send, 413, "payload_too_large", "The request body is too large.", rid)
                return

        received = 0
        started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise _BodyTooLarge
            return message

        async def tracking_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if not started:
                await _reply(send, 413, "payload_too_large", "The request body is too large.", rid)
