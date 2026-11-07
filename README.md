# EASA — Enterprise AI Support Agent

A learning and portfolio project. The goal is an enterprise-style AI support agent: authorized employees ask questions about company knowledge and get answers grounded in approved documents, with citations and server-side access control.

> **Status: Phase 1 (Foundation and Architecture), in progress.**
> The backend skeleton exists: configuration, logging, error handling, health endpoints, database sessions and Alembic migrations. There are no domain tables yet. The frontend and architecture documentation are not built yet.
> This is not production software. All company documents and employee data used in this project are synthetic.

## Structure

```
easa/
  apps/api/   FastAPI backend (Python 3.14, uv)          [M1–M2]       
  apps/web/   Next.js frontend (TypeScript, Tailwind)    [not yet created]
  docs/       Progress tracking (architecture docs: M4)  [PROGRESS.md]
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

### Database migrations

The database URL comes from the same validated settings as the app (`EASA_DATABASE_URL`, defaulting to the git-ignored `apps/api/var/easa.db`). `alembic.ini` contains no URL.

```powershell
uv run alembic upgrade head      # apply migrations (currently only the empty baseline)
uv run alembic current           # show the applied revision
uv run alembic check             # fail if ORM models and migrations have drifted
uv run alembic downgrade base    # revert all migrations
uv run alembic upgrade head --sql  # print SQL without connecting
```

Configuration uses `EASA_*` environment variables or `apps/api/.env`; see [apps/api/.env.example](apps/api/.env.example). Invalid values and unknown keys in `.env` stop the app at startup.

## Local data

Runtime data, including the SQLite database, is stored in `var/` directories. Git ignores these directories, as well as all `*.db` / `*.sqlite*` files and `.env` files.

## Progress

Milestone status, verification results and commit hashes are tracked in [docs/PROGRESS.md](docs/PROGRESS.md).

## Project guide

See [CLAUDE_DEVELOPMENT_GUIDE.txt](CLAUDE_DEVELOPMENT_GUIDE.txt) for engineering standards and the phased roadmap.
