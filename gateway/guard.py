"""Protection for a gateway reached through a tunnel.

- A per-address token bucket for every /api and /mcp call (general), and a stricter one per address for
  calls that start a model trial (default 3 an hour for public visitors).
- A per-session limit on backtests (default 30 a minute).
- A cap on request size, enforced on the bytes actually received, and caps on spec and text lengths.
- A cap on live event streams, overall and per address.

The visitor's address is the tunnel's `CF-Connecting-IP` header when the request comes from this machine
(cloudflared connects from localhost), else the socket's peer address. Adapted from the Finstinct server.
"""
from __future__ import annotations

import ipaddress
import json
import os
import threading
import time

MAX_BODY_BYTES = int(os.environ.get("GATEWAY_MAX_BODY", 64 * 1024))
MAX_SIGNAL = 400
MAX_NOTES = 2000
MAX_CLAIM_TEXT = 2000
MAX_PARAMS = 40
MAX_STREAMS_TOTAL = 40
MAX_STREAMS_PER_IP = 4


def _env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


class RateLimiter:
    """Token buckets per key: `burst` tokens, refilled at `per_minute` per minute."""

    def __init__(self, per_minute: float, burst: float, max_keys: int = 20_000, clock=time.monotonic):
        self.rate, self.burst, self.max_keys, self.clock = per_minute / 60.0, float(burst), max_keys, clock
        self._b: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def take(self, key: str, cost: float = 1.0) -> float:
        """0 if allowed, else the seconds to wait."""
        now = self.clock()
        with self._lock:
            tokens, last = self._b.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if tokens >= cost:
                self._b[key] = (tokens - cost, now)
                if len(self._b) > self.max_keys:
                    self._prune(now)
                return 0.0
            self._b[key] = (tokens, now)
            return (cost - tokens) / self.rate if self.rate > 0 else 60.0

    def _prune(self, now: float) -> None:
        full = [k for k, (t, last) in self._b.items() if t + (now - last) * self.rate >= self.burst]
        for k in full:
            del self._b[k]
        if len(self._b) > self.max_keys:
            for k in sorted(self._b, key=lambda k: self._b[k][1])[: len(self._b) - self.max_keys]:
                del self._b[k]


class StreamSlots:
    """Leases on live event streams. A lease that is never given back expires."""

    def __init__(self, total: int = MAX_STREAMS_TOTAL, per_ip: int = MAX_STREAMS_PER_IP):
        self.total, self.per_ip = total, per_ip
        self._leases: dict[int, tuple[str, float]] = {}
        self._next = 0
        self._lock = threading.Lock()

    def acquire(self, ip: str, max_age: float = 3600.0) -> tuple[int | None, str | None]:
        now = time.monotonic()
        with self._lock:
            self._leases = {k: v for k, v in self._leases.items() if v[1] > now}
            if len(self._leases) >= self.total:
                return None, "Too many live streams are open right now. Try again in a minute."
            if sum(1 for a, _ in self._leases.values() if a == ip) >= self.per_ip:
                return None, "You already have the most live streams allowed at once."
            self._next += 1
            self._leases[self._next] = (ip, now + max_age)
            return self._next, None

    def release(self, lease: int | None) -> None:
        with self._lock:
            self._leases.pop(lease, None)


def _is_local(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def client_ip_from_scope(scope) -> str:
    peer = (scope.get("client") or ("unknown", 0))[0] or "unknown"
    if _is_local(peer):
        for name, value in scope.get("headers") or []:
            if name == b"cf-connecting-ip":
                v = value.decode("latin-1").strip()
                try:
                    return str(ipaddress.ip_address(v))
                except ValueError:
                    break
    return peer


def client_ip(request) -> str:
    return client_ip_from_scope(request.scope)


def is_public(ip: str) -> bool:
    """A visitor through the tunnel (or any non-loopback address), as opposed to a client on this machine."""
    return not _is_local(ip)


class Limits:
    """The limiters one app shares."""

    def __init__(self, *, general: RateLimiter | None = None, backtests_per_minute: float = 30,
                 trials_per_hour: float = 3, local_exempt: bool = True):
        self.general = general or RateLimiter(_env("GATEWAY_RATE_GENERAL", 300), _env("GATEWAY_BURST_GENERAL", 100))
        self.backtests = RateLimiter(backtests_per_minute, backtests_per_minute)
        self.trials = RateLimiter(trials_per_hour / 60.0, trials_per_hour)
        self.streams = StreamSlots()
        self.local_exempt = local_exempt

    def backtest_wait(self, session_id: str) -> float:
        return self.backtests.take(session_id)

    def trial_wait(self, ip: str) -> float:
        if self.local_exempt and not is_public(ip):
            return 0.0
        return self.trials.take(ip)


def check_lengths(spec: dict, claim: dict | None = None) -> str | None:
    """A plain message if a text field is too long, else None."""
    if not isinstance(spec, dict):
        return "spec must be a JSON object."
    if len(str(spec.get("signal", ""))) > MAX_SIGNAL:
        return f"signal is longer than {MAX_SIGNAL} characters."
    if len(str(spec.get("notes", ""))) > MAX_NOTES:
        return f"notes are longer than {MAX_NOTES} characters."
    if len(spec.get("params") or {}) > MAX_PARAMS:
        return f"params has more than {MAX_PARAMS} entries."
    if claim and len(str(claim.get("text", ""))) > MAX_CLAIM_TEXT:
        return f"claim text is longer than {MAX_CLAIM_TEXT} characters."
    return None


class Guard:
    """Pure ASGI middleware: size limit and general rate limit for /api and /mcp."""

    def __init__(self, app, general: RateLimiter, max_body: int = MAX_BODY_BYTES):
        self.app, self.general, self.max_body = app, general, max_body

    async def _reply(self, send, status: int, detail: str, retry: float | None = None):
        body = json.dumps({"detail": detail}).encode()
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
        if retry is not None:
            headers.append((b"retry-after", str(max(1, int(retry + 0.999))).encode()))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if path.startswith("/api/") or path == "/mcp":
            wait = self.general.take(client_ip_from_scope(scope))
            if wait:
                return await self._reply(send, 429, "Too many requests. Slow down a little.", wait)
        if scope.get("method") in ("POST", "PUT", "PATCH"):
            for name, value in scope.get("headers") or []:
                if name == b"content-length":
                    try:
                        if int(value) > self.max_body:
                            return await self._reply(send, 413, f"The request is larger than {self.max_body} bytes.")
                    except ValueError:
                        return await self._reply(send, 400, "Bad Content-Length.")
            chunks, size = [], 0
            while True:
                msg = await receive()
                if msg["type"] == "http.disconnect":
                    return
                b = msg.get("body", b"")
                size += len(b)
                if size > self.max_body:
                    return await self._reply(send, 413, f"The request is larger than {self.max_body} bytes.")
                chunks.append(b)
                if not msg.get("more_body"):
                    break
            body = b"".join(chunks)
            sent = False

            async def replay():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            return await self.app(scope, replay, send)
        return await self.app(scope, receive, send)
