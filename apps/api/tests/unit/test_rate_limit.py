import pytest
from pydantic import ValidationError
from starlette.requests import Request

from app.core import rate_limit
from app.core.config import Settings
from app.core.rate_limit import RateLimiter, client_address


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_sliding_window_allows_the_limit_then_reports_the_wait() -> None:
    clock = Clock()
    limiter = RateLimiter(3, window=60, clock=clock)

    assert [limiter.check("k") for _ in range(3)] == [None, None, None]
    clock.now += 20
    assert limiter.check("k") == pytest.approx(40)  # the first event expires in 40 s
    assert limiter.check("other") is None  # keys are independent
    clock.now += 40
    assert limiter.check("k") is None


def test_a_zero_limit_disables_the_check() -> None:
    limiter = RateLimiter(0)

    assert all(limiter.check("k") is None for _ in range(1000))


def test_memory_stays_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rate_limit, "MAX_KEYS", 3)
    clock = Clock()
    limiter = RateLimiter(1, window=60, clock=clock)

    for i in range(10):
        clock.now += 1
        limiter.check(f"k{i}")

    assert len(limiter._events) <= 3


def request(peer: str, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded is not None else []
    return Request(
        {"type": "http", "client": (peer, 1234), "headers": headers, "method": "GET", "path": "/"}
    )


@pytest.mark.parametrize(
    ("peer", "forwarded", "trusted", "expected"),
    [
        ("203.0.113.5", None, [], "203.0.113.5"),
        # An untrusted peer cannot choose its address with the header.
        ("203.0.113.5", "198.51.100.1", [], "203.0.113.5"),
        # A trusted proxy: the first address from the right that is not a proxy.
        ("10.0.0.2", "198.51.100.1", ["10.0.0.2"], "198.51.100.1"),
        ("10.0.0.2", "6.6.6.6, 198.51.100.1, 10.0.0.3", ["10.0.0.2", "10.0.0.3"], "198.51.100.1"),
        ("10.0.0.2", "not-an-ip", ["10.0.0.2"], "10.0.0.2"),
        ("10.0.0.2", "", ["10.0.0.2"], "10.0.0.2"),
    ],
)
def test_client_address(
    peer: str, forwarded: str | None, trusted: list[str], expected: str
) -> None:
    assert client_address(request(peer, forwarded), trusted) == expected


def test_trusted_proxies_must_be_ip_addresses() -> None:
    assert Settings(_env_file=None, trusted_proxies=[" 10.0.0.2 ", "::1"]).trusted_proxies == [
        "10.0.0.2",
        "::1",
    ]  # type: ignore[call-arg]
    with pytest.raises(ValidationError, match="IP addresses"):
        Settings(_env_file=None, trusted_proxies=["proxy.local"])  # type: ignore[call-arg]
