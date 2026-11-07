# EASA — Enterprise AI Support Agent

A learning and portfolio project. The goal is an enterprise-style AI support agent: authorized employees ask questions about company knowledge and get answers grounded in approved documents, with citations and server-side access control.

> **Status: Phase 1 (Foundation and Architecture), in progress.**
> The backend skeleton exists: configuration, logging, error handling and health endpoints. The frontend, database migrations and documentation are not built yet.
> This is not production software. All company documents and employee data used in this project are synthetic.

## Structure

```
easa/
  apps/api/   FastAPI backend (Python 3.14, uv)          [M1: skeleton]
  apps/web/   Next.js frontend (TypeScript, Tailwind)    [not yet created]
  docs/       Architecture, security and API documents   [not yet created]
  scripts/    Development and check scripts              [not yet created]
```

## Prerequisites

Verified on the development machine (Windows 11):

| Tool    | Version verified |
|---------|------------------|
| Git     | 2.55.0           |
| Node.js | 24.13.0          |
| npm     | 11.6.2           |
| Python  | 3.14.7 (`py -3.14`) |
| uv      | 0.12.9           |

Not required for Phase 1: PostgreSQL (SQLite is used initially), Ollama and Docker.

## Backend (apps/api)

All commands run from `apps/api`. uv creates `apps/api/.venv` with the system Python 3.14 and never downloads its own interpreter.

```powershell
cd apps/api
uv sync                      # install runtime and dev dependencies from uv.lock
uv run ruff format --check . # formatting
uv run ruff check .          # lint (includes security rules)
uv run pytest                # unit and integration tests
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

Endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/health` | Liveness. Always `200 {"status":"ok"}` while the process is up; never touches the database |
| `GET /api/v1/health/ready` | Readiness. Runs `SELECT 1`; `200 ready` or `503 not_ready` with `checks.database = "unavailable"` |
| `GET /docs` | OpenAPI UI (disabled when `EASA_ENVIRONMENT=production`) |

Every response carries a server-generated `X-Correlation-ID` header. That ID also appears in the JSON logs and in error bodies (`{"error": {"code", "message", "correlation_id"}}`).

Configuration uses `EASA_*` environment variables or `apps/api/.env`; see [apps/api/.env.example](apps/api/.env.example). Invalid values and unknown keys in `.env` stop the app at startup.

## Local data

Runtime data, including the SQLite database, is stored in `var/` directories. Git ignores these directories, as well as all `*.db` / `*.sqlite*` files and `.env` files.

## Project guide

See [CLAUDE_DEVELOPMENT_GUIDE.txt](CLAUDE_DEVELOPMENT_GUIDE.txt) for engineering standards and the phased roadmap.
