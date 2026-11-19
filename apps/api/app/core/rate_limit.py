"""In-process rate limits (P8-M1, ADR-035).

A sliding window per key: at most ``limit`` events in ``window`` seconds.
State lives in this process only, so the limits hold for a single API
instance (documented); several instances would need a shared store.

Keys: sign-in attempts per client address (``client_address``), model calls
(answers, conversation questions, the agent) per signed-in user. Behind the
web app's backend for frontend every browser request arrives from the web
server's address, so a per-user key is the reliable one for model calls.
"""

import ipaddress
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from http import HTTPStatus

from fastapi import Request

from app.core.errors import AppError

# Bounds memory when many distinct keys appear (e.g. a scan from many addresses).
MAX_KEYS = 10_000


class RateLimiter:
    def __init__(
        self, limit: int, window: float = 60.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.limit = limit
        self.window = window
        self._clock = clock
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> float | None:
        """Record an event; None if allowed, otherwise the seconds until it would be."""
        if self.limit <= 0:  # 0 disables the limit
            return None
        now = self._clock()
        with self._lock:
            events = self._events.get(key)
            if events is None:
                if len(self._events) >= MAX_KEYS:
                    self._evict(now)
                events = self._events[key] = deque()
            while events and now - events[0] >= self.window:
                events.popleft()
            if len(events) >= self.limit:
                return max(0.0, self.window - (now - events[0]))
            events.append(now)
            return None

    def _evict(self, now: float) -> None:
        """Drop keys without recent events; if none, the oldest key."""
        stale = [k for k, e in self._events.items() if not e or now - e[-1] >= self.window]
        for key in stale:
            del self._events[key]
        if len(self._events) >= MAX_KEYS:
            oldest = min(self._events, key=lambda k: self._events[k][-1])
            del self._events[oldest]


def too_many_requests(retry_after: float) -> AppError:
    seconds = max(1, int(retry_after + 0.999))
    return AppError(
        "Too many requests. Try again later.",
        code="rate_limited",
        status_code=HTTPStatus.TOO_MANY_REQUESTS,
        headers={"Retry-After": str(seconds)},
    )


def client_address(request: Request, trusted_proxies: Sequence[str]) -> str:
    """The client's address: the TCP peer, or the forwarded client of a trusted proxy.

    ``X-Forwarded-For`` is read only when the peer is a trusted proxy, and then
    from the right: the first address that is not itself a trusted proxy. A
    browser can put anything into the header, so it is only as reliable as the
    proxy that sets it (see ADR-035).
    """
    peer = request.client.host if request.client else "unknown"
    if peer not in trusted_proxies:
        return peer
    forwarded = [a.strip() for a in request.headers.get("x-forwarded-for", "").split(",")]
    for address in reversed([a for a in forwarded if a]):
        if address in trusted_proxies:
            continue
        try:
            return str(ipaddress.ip_address(address))
        except ValueError:
            return peer  # malformed: fall back to the proxy itself
    return peer
