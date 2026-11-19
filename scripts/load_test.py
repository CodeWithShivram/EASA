"""Load and failure tests against the running demo stack (P8-M5, ADR-039).

Run from the repository root after scripts/demo.ps1:

    uv run --project apps/api python scripts/load_test.py            # load only
    uv run --project apps/api python scripts/load_test.py --failures # also stop services

Everything goes through the web app's backend for frontend, as a browser would.
The demo users' passwords are read from var/demo/credentials.txt and never
printed. Load: concurrent searches, a few grounded answers on the single CPU
model, and a sign-in burst (last, because it trips the sign-in limit for a
minute). Failures (--failures): the database, the chat model and the API are
stopped one at a time with `docker compose stop`, the responses are checked,
and each service is started again and must recover. A Markdown report goes to
var/loadtest/.
"""

import argparse
import statistics
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = [
    "How many days of annual leave do employees get?",
    "What is the hotel limit per night in capital cities?",
    "Within how many days must expense claims be submitted?",
    "How long are personal data records kept?",
    "Who approves remote work requests?",
    "What is the per diem for overnight trips?",
]


@dataclass
class Result:
    name: str
    statuses: Counter[str] = field(default_factory=Counter)
    latencies_ms: list[float] = field(default_factory=list)
    wall_s: float = 0.0
    notes: list[str] = field(default_factory=list)
    throughput: bool = True  # False for failure probes: one request each, no rate

    def row(self) -> str:
        n = sum(self.statuses.values())
        ordered = sorted(self.latencies_ms)
        p50 = statistics.median(ordered) if ordered else 0.0
        p95 = ordered[max(0, round(0.95 * len(ordered)) - 1)] if ordered else 0.0
        rate = f"{n / self.wall_s:.1f}" if self.throughput and self.wall_s else "-"
        statuses = ", ".join(f"{k} {v}" for k, v in sorted(self.statuses.items()))
        return (
            f"| {self.name} | {n} | {statuses} | {p50:.0f} | {p95:.0f} | "
            f"{max(ordered, default=0):.0f} | {rate} |"
        )


def credentials(path: Path) -> dict[str, tuple[str, str]]:
    users = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            users[parts[0]] = (parts[1], parts[2])
    return users


class Browser:
    """One signed-in browser session against the web app."""

    def __init__(self, web: str, username: str, password: str) -> None:
        self.web = web
        self.http = httpx.Client(base_url=web, timeout=360, trust_env=False)
        response = self.http.post(
            "/bff/session",
            headers={"Origin": web},
            json={"username": username, "password": password},
        )
        response.raise_for_status()
        # The session cookie is Secure in production. Browsers send it to
        # http://localhost; Python's cookie jar does not, so it is sent explicitly.
        token = response.cookies.get("easa_session")
        if not token:
            raise RuntimeError("sign-in returned no session cookie")
        self.http.cookies.clear()
        self.http.headers["Cookie"] = f"easa_session={token}"

    def post(self, path: str, body: dict[str, object]) -> httpx.Response:
        return self.http.post(f"/bff/api/v1{path}", headers={"Origin": self.web}, json=body)

    def get(self, path: str) -> httpx.Response:
        return self.http.get(f"/bff/api/v1{path}")


def code(response: httpx.Response) -> str:
    if response.status_code < 400:
        return str(response.status_code)
    try:
        return f"{response.status_code} {response.json()['error']['code']}"
    except ValueError, KeyError, TypeError:
        return str(response.status_code)


def timed(call: Callable[[], httpx.Response]) -> tuple[str, float]:
    started = time.perf_counter()
    try:
        response = call()
        status = code(response)
    except httpx.HTTPError as error:
        status = type(error).__name__
    return status, (time.perf_counter() - started) * 1000


def run_load(name: str, calls: list[Callable[[], httpx.Response]], workers: int) -> Result:
    result = Result(name)
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for status, ms in pool.map(timed, calls):
            result.statuses[status] += 1
            result.latencies_ms.append(ms)
    result.wall_s = time.perf_counter() - started
    return result


def compose(*args: str) -> None:
    subprocess.run(["docker", "compose", *args], cwd=ROOT, check=True, capture_output=True)  # noqa: S603, S607


def wait_for(check: Callable[[], bool], seconds: float = 180) -> float:
    started = time.perf_counter()
    while time.perf_counter() - started < seconds:
        try:
            if check():
                return time.perf_counter() - started
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise RuntimeError("did not recover in time")


def failure(
    name: str,
    service: str,
    probes: dict[str, Callable[[], httpx.Response]],
    recovered: Callable[[], bool],
) -> Result:
    result = Result(name, throughput=False)
    compose("stop", service)
    try:
        for label, probe in probes.items():
            status, ms = timed(probe)
            result.statuses[f"{label}: {status}"] += 1
            result.latencies_ms.append(ms)
    finally:
        compose("start", service)
        result.wall_s = wait_for(recovered)
        result.notes.append(f"{service} serving again {result.wall_s:.0f} s after its restart")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--web", default="http://localhost:3000")
    parser.add_argument(
        "--credentials", type=Path, default=ROOT / "var" / "demo" / "credentials.txt"
    )
    parser.add_argument("--searches", type=int, default=200)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--answers", type=int, default=3)
    parser.add_argument("--failures", action="store_true")
    args = parser.parse_args()

    users = credentials(args.credentials)
    sessions = [
        Browser(args.web, *users[role]) for role in ("employee", "manager", "administrator")
    ]
    results: list[Result] = []
    questions = [QUESTIONS[i % len(QUESTIONS)] for i in range(max(args.searches, args.answers))]

    searches = [
        (
            lambda s=sessions[i % 3], q=questions[i]: s.post(
                "/search", {"query": q, "mode": "hybrid", "top_k": 5}
            )
        )
        for i in range(args.searches)
    ]
    results.append(run_load(f"Search, {args.workers} at a time", searches, args.workers))
    answers = [
        (lambda s=sessions[i % 3], q=questions[i]: s.post("/answers", {"question": q}))
        for i in range(args.answers)
    ]
    results.append(
        run_load(f"Grounded answers, {args.answers} at once (one CPU model)", answers, args.answers)
    )
    results.append(
        run_load(
            "Pages: dashboard, 50 requests",
            [lambda s=sessions[0]: s.http.get("/")] * 50,
            args.workers,
        )
    )

    if args.failures:
        employee = sessions[0]
        results.append(
            failure(
                "Database stopped",
                "postgres",
                {
                    "readiness": lambda: employee.get("/health/ready"),
                    "search": lambda: employee.post("/search", {"query": QUESTIONS[0]}),
                    "documents": lambda: employee.get("/documents"),
                },
                lambda: employee.post("/search", {"query": QUESTIONS[0]}).status_code == 200,
            )
        )
        results.append(
            failure(
                "Chat model stopped",
                "llm",
                {
                    "answer": lambda: employee.post("/answers", {"question": QUESTIONS[0]}),
                    "search": lambda: employee.post("/search", {"query": QUESTIONS[0]}),
                },
                lambda: employee.get("/health/ready").status_code == 200,
            )
        )
        results.append(
            failure(
                "API stopped",
                "api",
                {
                    "health": lambda: employee.get("/health"),
                    "login page": lambda: httpx.get(
                        f"{args.web}/login", timeout=10, trust_env=False
                    ),
                },
                lambda: employee.get("/documents").status_code == 200,
            )
        )

    # Last: a burst of sign-ins from one browser address trips the sign-in limit.
    username, password = users["employee"]
    sign_ins = [
        lambda: httpx.post(
            f"{args.web}/bff/session",
            headers={"Origin": args.web},
            json={"username": username, "password": password},
            timeout=60,
            trust_env=False,
        )
    ] * 30
    burst = run_load("Sign-in burst, 30 through the web app", sign_ins, 5)
    burst.notes.append(
        "the web server is one client address for the API: 20 sign-ins per minute (ADR-035)"
    )
    results.append(burst)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "# Load and failure test",
        "",
        f"{datetime.now(UTC).isoformat(timespec='seconds')} against {args.web}.",
        "",
        "| Scenario | Requests | Responses | p50 ms | p95 ms | Max ms | Per second |",
        "|---|---|---|---|---|---|---|",
        *(r.row() for r in results),
        "",
        *(f"- {r.name}: {note}" for r in results for note in r.notes),
    ]
    out = ROOT / "var" / "loadtest" / f"{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sys.stdout.write("\n".join(lines) + f"\n\nReport: {out.relative_to(ROOT)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
