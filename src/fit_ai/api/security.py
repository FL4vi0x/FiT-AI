"""Request-level protection for a loopback-only API.

A web page in any browser on this machine can send requests to 127.0.0.1. With DNS
rebinding the page's own hostname (e.g. evil.example) is made to resolve to 127.0.0.1, so
the browser treats the API as same-origin and lets the page read the answers. What gives
it away is the `Host` header, which keeps the attacker's name. This guard refuses any
request whose Host is not exactly a local name.
"""
from __future__ import annotations

import json

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
